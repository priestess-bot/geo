"""Internal report-publication runtime with memory and durable adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid5

from geo_api.workflow_c_report_contracts import CreateWorkflowCReportRequest
from geo_core.workflow_c_reports import (
    AdvanceWorkflowCReportSnapshot,
    CreateWorkflowCReportSnapshot,
    PostgresWorkflowCApprovedReportSnapshots,
    WorkflowCReportApprovalError,
    WorkflowCReportConflict,
    WorkflowCReportNotFound,
    WorkflowCReportSnapshotStatus,
    WorkflowCReportSnapshotVersion,
    WorkflowCCustomerReportPayload,
)


WORKFLOW_C_REPORT_NAMESPACE = UUID("39b65090-a966-52b6-b28c-c3e62efb6365")


@dataclass(frozen=True)
class _MemoryReportReceipt:
    report_id: UUID
    input_hash: str
    result_version: int
    result_version_hash: str


class WorkflowCReportPort(Protocol):
    persistence: str

    def create_draft(
        self,
        *,
        project_id: UUID,
        payload: CreateWorkflowCReportRequest,
        actor_id: UUID,
        idempotency_key: str,
    ) -> WorkflowCReportSnapshotVersion: ...

    def transition(
        self,
        *,
        project_id: UUID,
        report_id: UUID,
        expected_version: int,
        target_status: WorkflowCReportSnapshotStatus,
        actor_id: UUID,
        reason: str | None,
        idempotency_key: str,
    ) -> WorkflowCReportSnapshotVersion: ...

    def get(
        self, *, project_id: UUID, report_id: UUID
    ) -> WorkflowCReportSnapshotVersion: ...

    def list(self, *, project_id: UUID) -> tuple[WorkflowCReportSnapshotVersion, ...]: ...


class WorkflowCReportRuntime:
    """Test-only append-only report lifecycle with production-equivalent rules."""

    persistence = "memory_test_only"

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._lock = RLock()
        self._reports: dict[tuple[UUID, UUID], tuple[WorkflowCReportSnapshotVersion, ...]] = {}
        self._receipts: dict[tuple[UUID, str, str], _MemoryReportReceipt] = {}

    def create_draft(
        self,
        *,
        project_id: UUID,
        payload: CreateWorkflowCReportRequest,
        actor_id: UUID,
        idempotency_key: str,
    ) -> WorkflowCReportSnapshotVersion:
        report_id = _report_id(project_id, idempotency_key)
        occurred_at = self._clock()
        command = CreateWorkflowCReportSnapshot(
            report_id=report_id,
            project_id=project_id,
            campaign_id=payload.campaign_id,
            monitoring_report_id=payload.monitoring_report_id,
            monitoring_report_hash=payload.monitoring_report_hash,
            semantic_snapshot_hash=payload.semantic_snapshot_hash,
            source_kind=payload.source_kind,
            approved_safe_payload=payload.approved_safe_payload.to_domain(),
            actor_id=actor_id,
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
        )
        payload_hash = _hash(command.approved_safe_payload)
        result = WorkflowCReportSnapshotVersion(
            report_id=report_id,
            project_id=project_id,
            version=1,
            status="draft",
            campaign_id=command.campaign_id,
            monitoring_report_id=command.monitoring_report_id,
            monitoring_report_hash=command.monitoring_report_hash,
            semantic_snapshot_hash=command.semantic_snapshot_hash,
            source_kind=command.source_kind,
            approved_safe_payload=command.approved_safe_payload,
            approved_safe_payload_hash=payload_hash,
            version_hash=_version_hash(command, version=1, status="draft", reason=None),
            actor_id=actor_id,
            reason=None,
            occurred_at=occurred_at,
        )
        with self._lock:
            key = (project_id, report_id)
            receipt_key = (project_id, "create", _hash(command.idempotency_key))
            input_hash = _create_input_hash(command)
            receipt = self._receipts.get(receipt_key)
            if receipt is not None:
                return self._replay_receipt(
                    project_id=project_id,
                    receipt=receipt,
                    report_id=report_id,
                    input_hash=input_hash,
                )
            prior = self._reports.get(key)
            if prior is not None:
                if prior[0] != result:
                    raise WorkflowCReportConflict("Workflow C report draft identity was reused")
                self._receipts[receipt_key] = _memory_receipt(prior[0], input_hash)
                return prior[0]
            self._reports[key] = (result,)
            self._receipts[receipt_key] = _memory_receipt(result, input_hash)
        return result

    def transition(
        self,
        *,
        project_id: UUID,
        report_id: UUID,
        expected_version: int,
        target_status: WorkflowCReportSnapshotStatus,
        actor_id: UUID,
        reason: str | None,
        idempotency_key: str,
    ) -> WorkflowCReportSnapshotVersion:
        with self._lock:
            occurred_at = self._clock()
            command = AdvanceWorkflowCReportSnapshot(
                report_id=report_id,
                project_id=project_id,
                expected_version=expected_version,
                status=target_status,  # type: ignore[arg-type]
                actor_id=actor_id,
                occurred_at=occurred_at,
                idempotency_key=idempotency_key,
                reason=reason,
            )
            receipt_key = (
                project_id,
                _command_scope(target_status),
                _hash(command.idempotency_key),
            )
            input_hash = _transition_input_hash(command)
            receipt = self._receipts.get(receipt_key)
            if receipt is not None:
                return self._replay_receipt(
                    project_id=project_id,
                    receipt=receipt,
                    report_id=report_id,
                    input_hash=input_hash,
                )
            versions = self._reports.get((project_id, report_id))
            if not versions:
                raise WorkflowCReportNotFound("Workflow C report snapshot does not exist")
            current = versions[-1]
            if current.version != expected_version:
                raise WorkflowCReportConflict("Workflow C report version is stale")
            _allowed(current.status, target_status)
            if target_status == "approved" and versions[0].actor_id == actor_id:
                raise WorkflowCReportApprovalError(
                    "Workflow C report maker cannot approve the same report"
                )
            result = WorkflowCReportSnapshotVersion(
                report_id=report_id,
                project_id=project_id,
                version=current.version + 1,
                status=target_status,
                campaign_id=current.campaign_id,
                monitoring_report_id=current.monitoring_report_id,
                monitoring_report_hash=current.monitoring_report_hash,
                semantic_snapshot_hash=current.semantic_snapshot_hash,
                source_kind=current.source_kind,
                approved_safe_payload=current.approved_safe_payload,
                approved_safe_payload_hash=current.approved_safe_payload_hash,
                version_hash=_version_hash(
                    current,
                    version=current.version + 1,
                    status=target_status,
                    actor_id=actor_id,
                    occurred_at=occurred_at,
                    reason=reason,
                ),
                actor_id=actor_id,
                reason=command.reason,
                occurred_at=occurred_at,
            )
            self._reports[(project_id, report_id)] = (*versions, result)
            self._receipts[receipt_key] = _memory_receipt(result, input_hash)
            return result

    def get(
        self, *, project_id: UUID, report_id: UUID
    ) -> WorkflowCReportSnapshotVersion:
        with self._lock:
            versions = self._reports.get((project_id, report_id))
        if not versions:
            raise WorkflowCReportNotFound("Workflow C report snapshot does not exist")
        return versions[-1]

    def list(self, *, project_id: UUID) -> tuple[WorkflowCReportSnapshotVersion, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        versions[-1]
                        for (item_project, _), versions in self._reports.items()
                        if item_project == project_id
                    ),
                    key=lambda item: (item.occurred_at, str(item.report_id)),
                    reverse=True,
                )
            )

    def _replay_receipt(
        self,
        *,
        project_id: UUID,
        receipt: _MemoryReportReceipt,
        report_id: UUID,
        input_hash: str,
    ) -> WorkflowCReportSnapshotVersion:
        if receipt.report_id != report_id or receipt.input_hash != input_hash:
            raise WorkflowCReportConflict(
                "Workflow C report Idempotency-Key was reused with different input or resource"
            )
        versions = self._reports.get((project_id, report_id), ())
        result = next(
            (item for item in versions if item.version == receipt.result_version),
            None,
        )
        if result is None or result.version_hash != receipt.result_version_hash:
            raise WorkflowCReportApprovalError("Workflow C report command receipt is invalid")
        return result


class PostgresWorkflowCReportControl:
    persistence = "durable"

    def __init__(
        self,
        *,
        repository: PostgresWorkflowCApprovedReportSnapshots,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._clock = clock

    def create_draft(
        self,
        *,
        project_id: UUID,
        payload: CreateWorkflowCReportRequest,
        actor_id: UUID,
        idempotency_key: str,
    ) -> WorkflowCReportSnapshotVersion:
        return self._repository.create_draft(
            CreateWorkflowCReportSnapshot(
                report_id=_report_id(project_id, idempotency_key),
                project_id=project_id,
                campaign_id=payload.campaign_id,
                monitoring_report_id=payload.monitoring_report_id,
                monitoring_report_hash=payload.monitoring_report_hash,
                semantic_snapshot_hash=payload.semantic_snapshot_hash,
                source_kind=payload.source_kind,
                approved_safe_payload=payload.approved_safe_payload.to_domain(),
                actor_id=actor_id,
                occurred_at=self._clock(),
                idempotency_key=idempotency_key,
            )
        )

    def transition(
        self,
        *,
        project_id: UUID,
        report_id: UUID,
        expected_version: int,
        target_status: WorkflowCReportSnapshotStatus,
        actor_id: UUID,
        reason: str | None,
        idempotency_key: str,
    ) -> WorkflowCReportSnapshotVersion:
        return self._repository.advance(
            AdvanceWorkflowCReportSnapshot(
                report_id=report_id,
                project_id=project_id,
                expected_version=expected_version,
                status=target_status,  # type: ignore[arg-type]
                actor_id=actor_id,
                occurred_at=self._clock(),
                idempotency_key=idempotency_key,
                reason=reason,
            )
        )

    def get(
        self, *, project_id: UUID, report_id: UUID
    ) -> WorkflowCReportSnapshotVersion:
        return self._repository.get(project_id=project_id, report_id=report_id)

    def list(self, *, project_id: UUID) -> tuple[WorkflowCReportSnapshotVersion, ...]:
        return self._repository.list(project_id=project_id)


def _report_id(project_id: UUID, idempotency_key: str) -> UUID:
    key = idempotency_key.strip()
    if not key or len(key) > 200:
        raise WorkflowCReportApprovalError("Workflow C report Idempotency-Key is invalid")
    return uuid5(WORKFLOW_C_REPORT_NAMESPACE, f"{project_id}:{key}")


def _allowed(previous: str, target: str) -> None:
    allowed = {
        "draft": {"in_review"},
        "in_review": {"approved", "revoked"},
        "approved": {"stale", "superseded", "revoked"},
        "stale": set(),
        "superseded": set(),
        "revoked": set(),
    }
    if target not in allowed[previous]:
        raise WorkflowCReportApprovalError("Workflow C report status transition is invalid")


def _command_scope(status: WorkflowCReportSnapshotStatus) -> str:
    scopes = {
        "in_review": "submit",
        "approved": "approve",
        "stale": "stale",
        "superseded": "supersede",
        "revoked": "revoke",
    }
    try:
        return scopes[status]
    except KeyError as error:
        raise WorkflowCReportApprovalError(
            "Workflow C report command scope is invalid"
        ) from error


def _create_input_hash(command: CreateWorkflowCReportSnapshot) -> str:
    return _hash(
        {
            "project_id": str(command.project_id),
            "report_id": str(command.report_id),
            "campaign_id": str(command.campaign_id),
            "monitoring_report_id": str(command.monitoring_report_id),
            "monitoring_report_hash": command.monitoring_report_hash,
            "semantic_snapshot_hash": command.semantic_snapshot_hash,
            "source_kind": command.source_kind,
            "approved_safe_payload": command.approved_safe_payload.to_dict(),
            "actor_id": str(command.actor_id),
        }
    )


def _transition_input_hash(command: AdvanceWorkflowCReportSnapshot) -> str:
    return _hash(
        {
            "project_id": str(command.project_id),
            "report_id": str(command.report_id),
            "expected_version": command.expected_version,
            "status": command.status,
            "actor_id": str(command.actor_id),
            "reason": command.reason,
        }
    )


def _memory_receipt(
    result: WorkflowCReportSnapshotVersion, input_hash: str
) -> _MemoryReportReceipt:
    return _MemoryReportReceipt(
        report_id=result.report_id,
        input_hash=input_hash,
        result_version=result.version,
        result_version_hash=result.version_hash,
    )


def _version_hash(
    source: CreateWorkflowCReportSnapshot | WorkflowCReportSnapshotVersion,
    *,
    version: int,
    status: str,
    actor_id: UUID | None = None,
    occurred_at: datetime | None = None,
    reason: str | None,
) -> str:
    actor = actor_id or source.actor_id
    at = occurred_at or source.occurred_at
    payload_hash = (
        source.approved_safe_payload_hash
        if isinstance(source, WorkflowCReportSnapshotVersion)
        else _hash(source.approved_safe_payload)
    )
    return _hash(
        {
            "report_id": str(source.report_id),
            "version": version,
            "status": status,
            "campaign_id": str(source.campaign_id),
            "monitoring_report_id": str(source.monitoring_report_id),
            "monitoring_report_hash": source.monitoring_report_hash,
            "semantic_snapshot_hash": source.semantic_snapshot_hash,
            "source_kind": source.source_kind,
            "approved_safe_payload_hash": payload_hash,
            "actor_id": str(actor),
            "reason": reason,
            "occurred_at": at.isoformat(),
        }
    )


def _hash(value: object) -> str:
    if isinstance(value, WorkflowCCustomerReportPayload):
        value = value.to_dict()
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "PostgresWorkflowCReportControl",
    "WORKFLOW_C_REPORT_NAMESPACE",
    "WorkflowCReportPort",
    "WorkflowCReportRuntime",
]
