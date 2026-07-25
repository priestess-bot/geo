"""Append-only Workflow C Report Snapshot lifecycle and Customer-safe reads."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
import hashlib
import json
from typing import Any, Literal, cast
from uuid import UUID

from geo_core.project_scope import set_project_scope
from geo_core.workflow_c_reports.postgres_contracts import (
    AdvanceWorkflowCReportSnapshot,
    CreateWorkflowCReportSnapshot,
    WorkflowCReportApprovalError,
    WorkflowCReportConflict,
    WorkflowCReportNotFound,
    WorkflowCReportSnapshotStatus,
    WorkflowCReportSnapshotVersion,
    _TERMINAL_STATUSES,
    _require_aware,
)
from geo_core.workflow_c_reports.postgres_receipts import (
    command_scope,
    create_input_hash,
    find_command_receipt,
    idempotency_key_hash,
    insert_command_receipt,
    lock_command_receipt,
    replay_command_receipt,
    report_version_hash,
    same_draft,
    transition_input_hash,
)
from geo_core.workflow_c_reports.customer_projection import (
    WorkflowCCustomerApprovedReport,
    WorkflowCCustomerProjectionError,
    WorkflowCCustomerReportPayload,
)


class PostgresWorkflowCApprovedReportSnapshots:
    """Project-scoped append-only lifecycle writer and latest-approved reader."""

    persistence: Literal["durable"] = "durable"

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def create_draft(
        self, command: CreateWorkflowCReportSnapshot
    ) -> WorkflowCReportSnapshotVersion:
        connection = self._connect()
        try:
            set_project_scope(connection, command.project_id)
            command_scope = "create"
            key_hash = idempotency_key_hash(command.idempotency_key)
            input_hash = create_input_hash(command)
            lock_command_receipt(connection, command.project_id, command_scope, key_hash)
            receipt = find_command_receipt(
                connection, command.project_id, command_scope, key_hash
            )
            if receipt is not None:
                result = replay_command_receipt(
                    connection,
                    project_id=command.project_id,
                    receipt=receipt,
                    report_id=command.report_id,
                    input_hash=input_hash,
                    load_version=self._version_at,
                )
                connection.commit()
                return result
            source = self._source(connection, command)
            _assert_source_lineage(source, command)
            payload_hash = _canonical_hash(command.approved_safe_payload)
            version_hash = report_version_hash(
                report_id=command.report_id,
                version=1,
                status="draft",
                command=command,
                payload_hash=payload_hash,
                actor_id=command.actor_id,
                reason=None,
                occurred_at=command.occurred_at,
            )
            connection.execute(
                """INSERT INTO workflow_c_report_snapshot_versions(
                       project_id, report_id, version, status, campaign_id,
                       monitoring_report_id, monitoring_report_hash, semantic_snapshot_hash,
                       source_kind, approved_safe_payload, approved_safe_payload_hash,
                       version_hash, actor_id, reason, occurred_at
                   ) VALUES (
                       %s, %s, 1, 'draft', %s, %s, %s, %s, %s, %s::jsonb, %s,
                       %s, %s, NULL, %s
                   ) ON CONFLICT (project_id, report_id, version) DO NOTHING""",
                (
                    command.project_id,
                    command.report_id,
                    command.campaign_id,
                    command.monitoring_report_id,
                    command.monitoring_report_hash,
                    command.semantic_snapshot_hash,
                    command.source_kind,
                    _json(command.approved_safe_payload),
                    payload_hash,
                    version_hash,
                    command.actor_id,
                    command.occurred_at,
                ),
            )
            row = self._current(connection, command.project_id, command.report_id)
            result = _version(row)
            if not same_draft(result, command, payload_hash):
                raise WorkflowCReportConflict("Workflow C report draft identity was reused")
            insert_command_receipt(
                connection,
                project_id=command.project_id,
                report_id=command.report_id,
                command_scope=command_scope,
                key_hash=key_hash,
                input_hash=input_hash,
                result=result,
                occurred_at=command.occurred_at,
            )
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def advance(
        self, command: AdvanceWorkflowCReportSnapshot
    ) -> WorkflowCReportSnapshotVersion:
        connection = self._connect()
        try:
            set_project_scope(connection, command.project_id)
            command_scope_for_status = command_scope(command.status)
            key_hash = idempotency_key_hash(command.idempotency_key)
            input_hash = transition_input_hash(command)
            lock_command_receipt(
                connection, command.project_id, command_scope_for_status, key_hash
            )
            receipt = find_command_receipt(
                connection, command.project_id, command_scope_for_status, key_hash
            )
            if receipt is not None:
                result = replay_command_receipt(
                    connection,
                    project_id=command.project_id,
                    receipt=receipt,
                    report_id=command.report_id,
                    input_hash=input_hash,
                    load_version=self._version_at,
                )
                connection.commit()
                return result
            self._lock_lifecycle(connection, command.project_id, command.report_id)
            predecessor = _version(self._current(connection, command.project_id, command.report_id))
            if predecessor.version != command.expected_version:
                raise WorkflowCReportConflict("Workflow C report version is stale")
            _assert_application_transition(predecessor.status, command.status)
            if command.status == "approved":
                draft_actor = self._draft_actor(
                    connection, command.project_id, command.report_id
                )
                if draft_actor == command.actor_id:
                    raise WorkflowCReportApprovalError(
                        "Workflow C report maker cannot approve the same report"
                    )
                source = self._source_for_version(connection, predecessor)
                _assert_approvable_source(source, predecessor)
            version = predecessor.version + 1
            version_hash = report_version_hash(
                report_id=predecessor.report_id,
                version=version,
                status=command.status,
                command=predecessor,
                payload_hash=predecessor.approved_safe_payload_hash,
                actor_id=command.actor_id,
                reason=command.reason,
                occurred_at=command.occurred_at,
            )
            connection.execute(
                """INSERT INTO workflow_c_report_snapshot_versions(
                       project_id, report_id, version, status, campaign_id,
                       monitoring_report_id, monitoring_report_hash, semantic_snapshot_hash,
                       source_kind, approved_safe_payload, approved_safe_payload_hash,
                       version_hash, actor_id, reason, occurred_at
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s,
                       %s, %s, %s, %s
                   )""",
                (
                    predecessor.project_id,
                    predecessor.report_id,
                    version,
                    command.status,
                    predecessor.campaign_id,
                    predecessor.monitoring_report_id,
                    predecessor.monitoring_report_hash,
                    predecessor.semantic_snapshot_hash,
                    predecessor.source_kind,
                    _json(predecessor.approved_safe_payload),
                    predecessor.approved_safe_payload_hash,
                    version_hash,
                    command.actor_id,
                    command.reason,
                    command.occurred_at,
                ),
            )
            result = _version(self._current(connection, command.project_id, command.report_id))
            if result.version != version or result.version_hash != version_hash:
                raise WorkflowCReportApprovalError("Workflow C report transition was not persisted")
            insert_command_receipt(
                connection,
                project_id=command.project_id,
                report_id=command.report_id,
                command_scope=command_scope_for_status,
                key_hash=key_hash,
                input_hash=input_hash,
                result=result,
                occurred_at=command.occurred_at,
            )
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(
        self, *, project_id: UUID, report_id: UUID
    ) -> WorkflowCReportSnapshotVersion:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            result = _version(self._current(connection, project_id, report_id))
            connection.rollback()
            return result
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list(self, *, project_id: UUID) -> tuple[WorkflowCReportSnapshotVersion, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT DISTINCT ON (report_id)
                          project_id, report_id, version, status, campaign_id,
                          monitoring_report_id, monitoring_report_hash,
                          semantic_snapshot_hash, source_kind, approved_safe_payload,
                          approved_safe_payload_hash, version_hash, actor_id, reason, occurred_at
                     FROM workflow_c_report_snapshot_versions
                    WHERE project_id = %s
                    ORDER BY report_id, version DESC""",
                (project_id,),
            ).fetchall()
            connection.rollback()
            return tuple(_version(_mapping(row)) for row in rows)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_approved_reports(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[WorkflowCCustomerApprovedReport, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """WITH latest AS (
                       SELECT DISTINCT ON (report_id)
                              project_id, report_id, version, status, campaign_id,
                              monitoring_report_id, monitoring_report_hash,
                              semantic_snapshot_hash, source_kind,
                              approved_safe_payload, approved_safe_payload_hash,
                              occurred_at
                         FROM workflow_c_report_snapshot_versions
                        WHERE project_id = %s AND campaign_id = %s
                        ORDER BY report_id, version DESC
                   )
                   SELECT latest.report_id AS id, latest.project_id, latest.campaign_id,
                          latest.semantic_snapshot_hash,
                          latest.monitoring_report_hash,
                          latest.source_kind, latest.approved_safe_payload,
                          latest.approved_safe_payload_hash,
                          latest.occurred_at AS approved_at
                     FROM latest
                     JOIN monitoring_reports AS report
                       ON report.project_id = latest.project_id
                      AND report.id = latest.monitoring_report_id
                     JOIN workflow_c_semantic_metric_snapshots AS metric
                       ON metric.project_id = latest.project_id
                      AND metric.snapshot_hash = latest.semantic_snapshot_hash
                    WHERE latest.status = 'approved'
                      AND report.report_hash = latest.monitoring_report_hash
                      AND metric.evidence_status = 'complete'
                      AND metric.approved_at IS NOT NULL
                      AND NOT metric.test_only AND NOT metric.synthetic
                      AND metric.capture_method = latest.source_kind
                      AND latest.source_kind IN (
                          'provider_api', 'proxy_grounded_api', 'automated_ui'
                      )
                    ORDER BY latest.occurred_at DESC, latest.report_id DESC""",
                (project_id, campaign_id),
            ).fetchall()
            connection.rollback()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return tuple(_approved_report(_mapping(value)) for value in rows)

    def _source(
        self, connection: Any, command: CreateWorkflowCReportSnapshot
    ) -> Mapping[str, object] | None:
        return _row(
            connection.execute(
                """SELECT report.project_id, report.campaign_id, report.report_hash,
                          metric.evidence_status, metric.test_only, metric.synthetic,
                          metric.approved_at AS metric_approved_at, metric.capture_method
                     FROM monitoring_reports AS report
                     JOIN workflow_c_semantic_metric_snapshots AS metric
                       ON metric.project_id = report.project_id
                      AND metric.snapshot_hash = %s
                    WHERE report.project_id = %s AND report.campaign_id = %s
                      AND report.id = %s""",
                (
                    command.semantic_snapshot_hash,
                    command.project_id,
                    command.campaign_id,
                    command.monitoring_report_id,
                ),
            )
        )

    def _source_for_version(
        self, connection: Any, version: WorkflowCReportSnapshotVersion
    ) -> Mapping[str, object] | None:
        return self._source(
            connection,
            CreateWorkflowCReportSnapshot(
                report_id=version.report_id,
                project_id=version.project_id,
                campaign_id=version.campaign_id,
                monitoring_report_id=version.monitoring_report_id,
                monitoring_report_hash=version.monitoring_report_hash,
                semantic_snapshot_hash=version.semantic_snapshot_hash,
                source_kind=version.source_kind,
                approved_safe_payload=version.approved_safe_payload,
                actor_id=version.actor_id,
                occurred_at=version.occurred_at,
                idempotency_key="source-revalidation",
            ),
        )

    @staticmethod
    def _lock_lifecycle(connection: Any, project_id: UUID, report_id: UUID) -> None:
        """Serialize append-only transitions without granting UPDATE to the App role."""

        connection.execute(
            """SELECT pg_advisory_xact_lock(
                   hashtextextended(%s::text || ':' || %s::text, 0)
               )""",
            (project_id, report_id),
        )

    @staticmethod
    def _version_at(
        connection: Any, project_id: UUID, report_id: UUID, version: int
    ) -> WorkflowCReportSnapshotVersion:
        row = _row(
            connection.execute(
                """SELECT project_id, report_id, version, status, campaign_id,
                          monitoring_report_id, monitoring_report_hash,
                          semantic_snapshot_hash, source_kind, approved_safe_payload,
                          approved_safe_payload_hash, version_hash, actor_id, reason, occurred_at
                     FROM workflow_c_report_snapshot_versions
                    WHERE project_id = %s AND report_id = %s AND version = %s""",
                (project_id, report_id, version),
            )
        )
        return _version(row)

    @staticmethod
    def _draft_actor(connection: Any, project_id: UUID, report_id: UUID) -> UUID:
        row = _row(
            connection.execute(
                """SELECT actor_id FROM workflow_c_report_snapshot_versions
                    WHERE project_id = %s AND report_id = %s AND version = 1""",
                (project_id, report_id),
            )
        )
        if row is None:
            raise WorkflowCReportApprovalError("Workflow C report draft disappeared")
        return _uuid(row, "actor_id")

    @staticmethod
    def _current(connection: Any, project_id: UUID, report_id: UUID) -> Mapping[str, object] | None:
        return _row(
            connection.execute(
                """SELECT project_id, report_id, version, status, campaign_id,
                          monitoring_report_id, monitoring_report_hash,
                          semantic_snapshot_hash, source_kind, approved_safe_payload,
                          approved_safe_payload_hash, version_hash, actor_id, reason, occurred_at
                     FROM workflow_c_report_snapshot_versions
                    WHERE project_id = %s AND report_id = %s
                    ORDER BY version DESC LIMIT 1""",
                (project_id, report_id),
            )
        )


def _assert_source_lineage(
    source: Mapping[str, object] | None, command: CreateWorkflowCReportSnapshot
) -> None:
    if source is None:
        raise WorkflowCReportApprovalError("Workflow C report source does not exist")
    if source.get("project_id") != command.project_id or source.get("campaign_id") != command.campaign_id:
        raise WorkflowCReportApprovalError("Workflow C report source crosses project or campaign")
    if source.get("report_hash") != command.monitoring_report_hash:
        raise WorkflowCReportApprovalError("Workflow C report source hash differs from draft")
    if source.get("capture_method") != command.source_kind:
        raise WorkflowCReportApprovalError("Workflow C report source kind differs from semantic snapshot")


def _assert_approvable_source(
    source: Mapping[str, object] | None, version: WorkflowCReportSnapshotVersion
) -> None:
    command = CreateWorkflowCReportSnapshot(
        report_id=version.report_id,
        project_id=version.project_id,
        campaign_id=version.campaign_id,
        monitoring_report_id=version.monitoring_report_id,
        monitoring_report_hash=version.monitoring_report_hash,
        semantic_snapshot_hash=version.semantic_snapshot_hash,
        source_kind=version.source_kind,
        approved_safe_payload=version.approved_safe_payload,
        actor_id=version.actor_id,
        occurred_at=version.occurred_at,
        idempotency_key="source-revalidation",
    )
    _assert_source_lineage(source, command)
    if source is None:
        raise WorkflowCReportApprovalError("Workflow C report source disappeared")
    if source.get("evidence_status") != "complete":
        raise WorkflowCReportApprovalError("insufficient-evidence snapshot cannot reach Customer")
    if source.get("test_only") is not False or source.get("synthetic") is not False:
        raise WorkflowCReportApprovalError("test or synthetic snapshot cannot reach Customer")
    if source.get("metric_approved_at") is None:
        raise WorkflowCReportApprovalError("semantic snapshot must be independently approved")


def _assert_application_transition(
    previous: WorkflowCReportSnapshotStatus, target: str
) -> None:
    allowed = {
        "draft": frozenset({"in_review"}),
        "in_review": frozenset({"approved", "revoked"}),
        "approved": _TERMINAL_STATUSES,
        "stale": frozenset(),
        "superseded": frozenset(),
        "revoked": frozenset(),
    }
    if target not in allowed[previous]:
        raise WorkflowCReportApprovalError("Workflow C report status transition is invalid")


def _approved_report(row: Mapping[str, object]) -> WorkflowCCustomerApprovedReport:
    try:
        payload = row["approved_safe_payload"]
        if not isinstance(payload, Mapping):
            raise TypeError("payload is invalid")
        if _canonical_hash(payload) != _hash(row, "approved_safe_payload_hash"):
            raise ValueError("payload hash is invalid")
        return WorkflowCCustomerApprovedReport(
            id=_uuid(row, "id"),
            project_id=_uuid(row, "project_id"),
            campaign_id=_uuid(row, "campaign_id"),
            semantic_snapshot_hash=_hash(row, "semantic_snapshot_hash"),
            report_hash=_hash(row, "monitoring_report_hash"),
            source_kind=_source_kind(row["source_kind"]),
            approved_safe_payload=WorkflowCCustomerReportPayload.from_mapping(payload),
            approved_at=_timestamp(row, "approved_at"),
        )
    except (KeyError, TypeError, ValueError, WorkflowCCustomerProjectionError) as error:
        raise WorkflowCReportApprovalError("Workflow C Customer report row is invalid") from error


def _version(row: Mapping[str, object] | None) -> WorkflowCReportSnapshotVersion:
    if row is None:
        raise WorkflowCReportNotFound("Workflow C report snapshot does not exist")
    try:
        payload = row["approved_safe_payload"]
        if not isinstance(payload, Mapping):
            raise TypeError("payload is invalid")
        status = row["status"]
        if status not in {"draft", "in_review", "approved", "stale", "superseded", "revoked"}:
            raise ValueError("status is invalid")
        return WorkflowCReportSnapshotVersion(
            report_id=_uuid(row, "report_id"),
            project_id=_uuid(row, "project_id"),
            version=_positive_int(row, "version"),
            status=cast(WorkflowCReportSnapshotStatus, status),
            campaign_id=_uuid(row, "campaign_id"),
            monitoring_report_id=_uuid(row, "monitoring_report_id"),
            monitoring_report_hash=_hash(row, "monitoring_report_hash"),
            semantic_snapshot_hash=_hash(row, "semantic_snapshot_hash"),
            source_kind=_source_kind(row["source_kind"]),
            approved_safe_payload=WorkflowCCustomerReportPayload.from_mapping(payload),
            approved_safe_payload_hash=_hash(row, "approved_safe_payload_hash"),
            version_hash=_hash(row, "version_hash"),
            actor_id=_uuid(row, "actor_id"),
            reason=_reason(row.get("reason")),
            occurred_at=_timestamp(row, "occurred_at"),
        )
    except (KeyError, TypeError, ValueError, WorkflowCCustomerProjectionError) as error:
        raise WorkflowCReportApprovalError("Workflow C report snapshot row is invalid") from error


def _row(cursor: Any) -> Mapping[str, object] | None:
    value = cursor.fetchone()
    return _mapping(value) if value is not None else None


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WorkflowCReportApprovalError("Workflow C report query must use mapping rows")
    return dict(value)


def _uuid(row: Mapping[str, object], field: str) -> UUID:
    value = row[field]
    if not isinstance(value, UUID):
        raise TypeError(f"{field} is not a UUID")
    return value


def _positive_int(row: Mapping[str, object], field: str) -> int:
    value = row[field]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise TypeError(f"{field} is not a positive integer")
    return value


def _hash(row: Mapping[str, object], field: str) -> str:
    value = row[field]
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise TypeError(f"{field} is not a SHA-256 hash")
    return value


def _source_kind(value: object) -> Literal["provider_api", "proxy_grounded_api", "automated_ui"]:
    if value in {"provider_api", "proxy_grounded_api", "automated_ui"}:
        return cast(Literal["provider_api", "proxy_grounded_api", "automated_ui"], value)
    raise ValueError("source kind is invalid")


def _reason(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("reason is invalid")
    return value


def _timestamp(row: Mapping[str, object], field: str) -> datetime:
    value = row[field]
    _require_aware(value, field)
    return cast(datetime, value)


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    if isinstance(value, WorkflowCCustomerReportPayload):
        value = value.to_dict()
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = [
    "AdvanceWorkflowCReportSnapshot", "CreateWorkflowCReportSnapshot",
    "PostgresWorkflowCApprovedReportSnapshots",
    "WorkflowCReportApprovalError",
    "WorkflowCReportSnapshotStatus",
    "WorkflowCReportSnapshotVersion",
]
