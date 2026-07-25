"""Persistent command receipt and identity helpers for Workflow C reports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
import hashlib
import json
from typing import Any
from uuid import UUID

from geo_core.workflow_c_reports.postgres_contracts import (
    AdvanceWorkflowCReportSnapshot,
    CreateWorkflowCReportSnapshot,
    WorkflowCReportApprovalError,
    WorkflowCReportConflict,
    WorkflowCReportSnapshotStatus,
    WorkflowCReportSnapshotVersion,
)


VersionLoader = Callable[
    [Any, UUID, UUID, int], WorkflowCReportSnapshotVersion
]


def lock_command_receipt(
    connection: Any, project_id: UUID, command_scope: str, key_hash: str
) -> None:
    connection.execute(
        """SELECT pg_advisory_xact_lock(
               hashtextextended(%s::text || ':' || %s || ':' || %s, 0)
           )""",
        (project_id, command_scope, key_hash),
    )


def find_command_receipt(
    connection: Any, project_id: UUID, command_scope: str, key_hash: str
) -> Mapping[str, object] | None:
    row = connection.execute(
        """SELECT report_id, input_hash, result_version, result_version_hash
             FROM workflow_c_report_command_receipts
            WHERE project_id = %s AND command_scope = %s
              AND idempotency_key_hash = %s""",
        (project_id, command_scope, key_hash),
    ).fetchone()
    if row is None:
        return None
    if not isinstance(row, Mapping):
        raise WorkflowCReportApprovalError(
            "Workflow C report command receipt query must use mapping rows"
        )
    return dict(row)


def replay_command_receipt(
    connection: Any,
    *,
    project_id: UUID,
    receipt: Mapping[str, object],
    report_id: UUID,
    input_hash: str,
    load_version: VersionLoader,
) -> WorkflowCReportSnapshotVersion:
    receipt_report_id = _uuid(receipt, "report_id")
    if receipt_report_id != report_id or _hash(receipt, "input_hash") != input_hash:
        raise WorkflowCReportConflict(
            "Workflow C report Idempotency-Key was reused with different input or resource"
        )
    result = load_version(
        connection,
        project_id,
        receipt_report_id,
        _positive_int(receipt, "result_version"),
    )
    if result.version_hash != _hash(receipt, "result_version_hash"):
        raise WorkflowCReportApprovalError("Workflow C report command receipt is invalid")
    return result


def insert_command_receipt(
    connection: Any,
    *,
    project_id: UUID,
    report_id: UUID,
    command_scope: str,
    key_hash: str,
    input_hash: str,
    result: WorkflowCReportSnapshotVersion,
    occurred_at: datetime,
) -> None:
    connection.execute(
        """INSERT INTO workflow_c_report_command_receipts(
               project_id, report_id, command_scope, idempotency_key_hash,
               input_hash, result_version, result_version_hash, created_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            project_id,
            report_id,
            command_scope,
            key_hash,
            input_hash,
            result.version,
            result.version_hash,
            occurred_at,
        ),
    )


def command_scope(status: WorkflowCReportSnapshotStatus) -> str:
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


def idempotency_key_hash(value: str) -> str:
    return canonical_hash(value)


def create_input_hash(command: CreateWorkflowCReportSnapshot) -> str:
    return canonical_hash(
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


def transition_input_hash(command: AdvanceWorkflowCReportSnapshot) -> str:
    return canonical_hash(
        {
            "project_id": str(command.project_id),
            "report_id": str(command.report_id),
            "expected_version": command.expected_version,
            "status": command.status,
            "actor_id": str(command.actor_id),
            "reason": command.reason,
        }
    )


def same_draft(
    result: WorkflowCReportSnapshotVersion,
    command: CreateWorkflowCReportSnapshot,
    payload_hash: str,
) -> bool:
    return (
        result.version == 1
        and result.status == "draft"
        and result.project_id == command.project_id
        and result.campaign_id == command.campaign_id
        and result.monitoring_report_id == command.monitoring_report_id
        and result.monitoring_report_hash == command.monitoring_report_hash
        and result.semantic_snapshot_hash == command.semantic_snapshot_hash
        and result.source_kind == command.source_kind
        and dict(result.approved_safe_payload) == dict(command.approved_safe_payload)
        and result.approved_safe_payload_hash == payload_hash
        and result.actor_id == command.actor_id
    )


def report_version_hash(
    *,
    report_id: UUID,
    version: int,
    status: str,
    command: CreateWorkflowCReportSnapshot | WorkflowCReportSnapshotVersion,
    payload_hash: str,
    actor_id: UUID,
    reason: str | None,
    occurred_at: datetime,
) -> str:
    return canonical_hash(
        {
            "report_id": str(report_id),
            "version": version,
            "status": status,
            "campaign_id": str(command.campaign_id),
            "monitoring_report_id": str(command.monitoring_report_id),
            "monitoring_report_hash": command.monitoring_report_hash,
            "semantic_snapshot_hash": command.semantic_snapshot_hash,
            "source_kind": command.source_kind,
            "approved_safe_payload_hash": payload_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "occurred_at": occurred_at.isoformat(),
        }
    )


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _uuid(row: Mapping[str, object], field: str) -> UUID:
    value = row[field]
    if not isinstance(value, UUID):
        raise WorkflowCReportApprovalError(f"Workflow C report receipt {field} is invalid")
    return value


def _hash(row: Mapping[str, object], field: str) -> str:
    value = row[field]
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise WorkflowCReportApprovalError(f"Workflow C report receipt {field} is invalid")
    return value


def _positive_int(row: Mapping[str, object], field: str) -> int:
    value = row[field]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkflowCReportApprovalError(f"Workflow C report receipt {field} is invalid")
    return value


__all__ = [
    "canonical_hash",
    "command_scope",
    "create_input_hash",
    "find_command_receipt",
    "idempotency_key_hash",
    "insert_command_receipt",
    "lock_command_receipt",
    "replay_command_receipt",
    "report_version_hash",
    "same_draft",
    "transition_input_hash",
]
