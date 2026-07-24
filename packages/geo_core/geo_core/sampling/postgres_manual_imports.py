"""Durable maker-checker control for governed manual Sampling evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.model_gateway import canonical_json_hash
from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import SamplingConflict, SamplingNotFound
from geo_core.sampling.manual_import import (
    ManualCaptureDevice,
    ManualEvidenceImport,
    ManualEvidenceKind,
    ManualEvidenceStatus,
)
from geo_core.sampling.postgres_worker_contracts import parse_manual_sampling_spec


class PostgresManualEvidenceError(SamplingConflict):
    """PostgreSQL rejected a governed manual-evidence command."""


class PostgresManualEvidenceRepository:
    """Submit and decide manual evidence only through the fenced 0047 RPCs."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def submit(
        self,
        item: ManualEvidenceImport,
        *,
        source_content_hash: str,
        content_type: str,
        governance_policy_option_key: str,
        pre_redacted_attestation: bool,
        idempotency_key: str,
    ) -> ManualEvidenceImport:
        payload = _submission_payload(
            item,
            source_content_hash=source_content_hash,
            content_type=content_type,
            governance_policy_option_key=governance_policy_option_key,
            pre_redacted_attestation=pre_redacted_attestation,
        )
        input_hash = canonical_json_hash(
            {
                "operation": "submit",
                "manual_import_id": str(item.id),
                "attempt_id": str(item.attempt_id),
                "run_id": str(item.run_id),
                "task_id": str(item.task_id),
                "expected_task_version": item.expected_task_version,
                "artifact_manifest_id": str(item.artifact_manifest_id),
                "artifact_manifest_hash": item.artifact_manifest_hash,
                "artifact_content_hash": item.artifact_content_hash,
                "governance_policy_hash": item.governance_policy_hash,
                "capture_session_id": str(item.capture_session_id),
                "payload": payload,
                "submitted_by": item.submitted_by,
                "submitted_at": item.submitted_at.isoformat(),
            }
        )
        self._call(
            project_id=item.project_id,
            statement="""SELECT * FROM geo_submit_workflow_c_manual_sampling_evidence(
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s::jsonb, %s, %s
                       )""",
            parameters=(
                item.project_id,
                item.id,
                item.attempt_id,
                _idempotency_hash(idempotency_key),
                input_hash,
                item.run_id,
                item.task_id,
                item.expected_task_version,
                item.artifact_manifest_id,
                item.artifact_manifest_hash,
                item.artifact_content_hash,
                item.governance_policy_hash,
                item.capture_session_id,
                Jsonb(payload),
                item.submitted_by,
                item.submitted_at,
            ),
        )
        return self.get(project_id=item.project_id, import_id=item.id)

    def replay_submission(
        self,
        *,
        project_id: UUID,
        import_id: UUID,
        run_id: UUID,
        task_id: UUID,
        expected_task_version: int,
        submitted_by: str,
        source_content_hash: str,
        evidence_kind: str,
        device: str,
        locale: str,
        captured_at: datetime,
        content_type: str,
        governance_policy_option_key: str,
        pre_redacted_attestation: bool,
    ) -> ManualEvidenceImport | None:
        row = self._read_one(
            project_id=project_id,
            statement="""SELECT * FROM workflow_c_sampling_manual_imports
                         WHERE project_id = %s AND id = %s""",
            parameters=(project_id, import_id),
        )
        if row is None:
            return None
        payload = _mapping(row.get("payload"))
        expected = {
            "run_id": str(run_id),
            "task_id": str(task_id),
            "expected_task_version": expected_task_version,
            "submitted_by": submitted_by.strip(),
            "source_content_hash": source_content_hash,
            "evidence_kind": evidence_kind,
            "device": device,
            "locale": locale,
            "captured_at": captured_at.isoformat(),
            "content_type": content_type,
            "governance_policy_option_key": governance_policy_option_key,
            "pre_redacted_attestation": pre_redacted_attestation,
        }
        actual = {
            "run_id": str(row.get("run_id")),
            "task_id": str(row.get("task_id")),
            "expected_task_version": payload.get("expected_task_version"),
            "submitted_by": row.get("submitted_by"),
            "source_content_hash": payload.get("source_content_hash"),
            "evidence_kind": payload.get("evidence_kind"),
            "device": payload.get("device"),
            "locale": payload.get("locale"),
            "captured_at": payload.get("captured_at"),
            "content_type": payload.get("content_type"),
            "governance_policy_option_key": payload.get("governance_policy_option_key"),
            "pre_redacted_attestation": payload.get("pre_redacted_attestation"),
        }
        if actual != expected:
            raise PostgresManualEvidenceError(
                "manual evidence Idempotency-Key was reused with different input"
            )
        return _manual_import(row)

    def review(
        self,
        *,
        project_id: UUID,
        import_id: UUID,
        expected_version: int,
        reviewer_id: str,
        reason: str,
        approved: bool,
        reviewed_at: datetime,
        idempotency_key: str,
    ) -> ManualEvidenceImport:
        item = self.get(project_id=project_id, import_id=import_id)
        spec_payload: dict[str, object] | None = None
        spec_hash: str | None = None
        job_key: str | None = None
        if approved:
            spec_payload = _approved_spec(item)
            # The strict Worker parser is an application-side second fence.
            parse_manual_sampling_spec(MappingProxyType(spec_payload))
            spec_hash = canonical_json_hash(spec_payload)
            job_key = f"sampling.manual:{project_id}:{item.attempt_id}"
        input_hash = canonical_json_hash(
            {
                "operation": "review",
                "manual_import_id": str(import_id),
                "expected_version": expected_version,
                "reviewer_id": reviewer_id,
                "reason": reason,
                "approved": approved,
                "reviewed_at": reviewed_at.isoformat(),
                "spec_hash": spec_hash,
                "job_idempotency_key": job_key,
            }
        )
        self._call(
            project_id=project_id,
            statement="""SELECT * FROM geo_review_workflow_c_manual_sampling_evidence(
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s::jsonb, %s
                       )""",
            parameters=(
                project_id,
                import_id,
                _idempotency_hash(idempotency_key),
                input_hash,
                expected_version,
                reviewer_id,
                reason,
                approved,
                reviewed_at,
                spec_hash,
                Jsonb(spec_payload) if spec_payload is not None else None,
                job_key,
            ),
        )
        return self.get(project_id=project_id, import_id=import_id)

    def get(self, *, project_id: UUID, import_id: UUID) -> ManualEvidenceImport:
        row = self._read_one(
            project_id=project_id,
            statement="""SELECT * FROM workflow_c_sampling_manual_imports
                         WHERE project_id = %s AND id = %s""",
            parameters=(project_id, import_id),
        )
        if row is None:
            raise SamplingNotFound("manual evidence import does not exist")
        return _manual_import(row)

    def list(self, *, project_id: UUID) -> tuple[ManualEvidenceImport, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT * FROM workflow_c_sampling_manual_imports
                   WHERE project_id = %s ORDER BY submitted_at DESC, id DESC""",
                (project_id,),
            ).fetchall()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresManualEvidenceError("manual evidence imports could not be listed") from error
        finally:
            connection.close()
        return tuple(_manual_import(_mapping(row)) for row in rows)

    def for_attempt(self, *, project_id: UUID, attempt_id: UUID) -> ManualEvidenceImport:
        row = self._read_one(
            project_id=project_id,
            statement="""SELECT * FROM workflow_c_sampling_manual_imports
                         WHERE project_id = %s AND attempt_id = %s
                           AND status IN ('approved', 'committed')""",
            parameters=(project_id, attempt_id),
        )
        if row is None:
            raise SamplingNotFound("approved manual evidence does not exist for Attempt")
        return _manual_import(row)

    def _read_one(
        self,
        *,
        project_id: UUID,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object] | None:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(statement, parameters).fetchone()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresManualEvidenceError("manual evidence import could not be read") from error
        finally:
            connection.close()
        return _mapping(row) if row is not None else None

    def _call(
        self,
        *,
        project_id: UUID,
        statement: str,
        parameters: tuple[object, ...],
    ) -> Mapping[str, object]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(statement, parameters).fetchone()
            if row is None:
                raise PostgresManualEvidenceError("manual evidence command did not return")
            result = _mapping(row)
            connection.commit()
            return result
        except PostgresManualEvidenceError:
            connection.rollback()
            raise
        except psycopg.Error as error:
            connection.rollback()
            detail = getattr(error.diag, "message_primary", "") or ""
            if detail.startswith(("Manual Sampling ", "Sampling policy ")):
                raise PostgresManualEvidenceError(detail) from error
            raise PostgresManualEvidenceError(
                "PostgreSQL rejected the Manual Sampling evidence command"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _submission_payload(
    item: ManualEvidenceImport,
    *,
    source_content_hash: str,
    content_type: str,
    governance_policy_option_key: str,
    pre_redacted_attestation: bool,
) -> dict[str, object]:
    if (
        len(source_content_hash) != 64
        or not content_type.strip()
        or not governance_policy_option_key.strip()
    ):
        raise PostgresManualEvidenceError("manual evidence source content hash is invalid")
    return {
        "schema_version": 1,
        "task_key": item.task_key,
        "expected_task_version": item.expected_task_version,
        "evidence_kind": item.evidence_kind.value,
        "device": item.device.value,
        "locale": item.locale,
        "captured_at": item.captured_at.isoformat(),
        "source_content_hash": source_content_hash,
        "content_type": content_type,
        "governance_policy_option_key": governance_policy_option_key,
        "pre_redacted_attestation": pre_redacted_attestation,
    }


def _approved_spec(item: ManualEvidenceImport) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "sampling.manual_import",
        "manual_import_id": str(item.id),
        "run_id": str(item.run_id),
        "task_id": str(item.task_id),
        "attempt_id": str(item.attempt_id),
        "artifact_manifest_id": str(item.artifact_manifest_id),
        "artifact_manifest_hash": item.artifact_manifest_hash,
        "artifact_content_hash": item.artifact_content_hash,
        "governance_policy_hash": item.governance_policy_hash,
        "capture_session_id": str(item.capture_session_id),
        "task_version": item.expected_task_version + 1,
        "attempt_version": 1,
    }


def _manual_import(row: Mapping[str, object]) -> ManualEvidenceImport:
    payload = _mapping(row.get("payload"))
    status = _status(row.get("status"))
    return ManualEvidenceImport(
        id=_uuid(row, "id"),
        project_id=_uuid(row, "project_id"),
        run_id=_uuid(row, "run_id"),
        task_id=_uuid(row, "task_id"),
        task_key=_hash(payload, "task_key"),
        attempt_id=_uuid(row, "attempt_id"),
        expected_task_version=_positive(payload, "expected_task_version"),
        artifact_manifest_id=_uuid(row, "artifact_manifest_id"),
        artifact_manifest_hash=_hash(row, "artifact_manifest_hash"),
        artifact_content_hash=_hash(row, "artifact_content_hash"),
        governance_policy_hash=_hash(row, "governance_policy_hash"),
        capture_session_id=_uuid(row, "capture_session_id"),
        evidence_kind=ManualEvidenceKind(_text(payload, "evidence_kind")),
        device=ManualCaptureDevice(_text(payload, "device")),
        locale=_text(payload, "locale"),
        captured_at=_timestamp(payload, "captured_at"),
        submitted_by=_text(row, "submitted_by"),
        submitted_at=_timestamp(row, "submitted_at"),
        status=status,
        reviewed_by=_optional_text(row, "reviewed_by"),
        reviewed_at=_optional_timestamp(row, "reviewed_at"),
        review_reason=_optional_text(row, "review_reason"),
        committed_at=_optional_timestamp(row, "committed_at"),
        aggregate_version=_positive(row, "aggregate_version"),
    )


def _status(value: object) -> ManualEvidenceStatus:
    mapped = {"submitted": "pending_review", "approved": "approved", "rejected": "rejected", "committed": "committed"}
    try:
        return ManualEvidenceStatus(mapped[str(value)])
    except (KeyError, TypeError, ValueError) as error:
        raise PostgresManualEvidenceError("manual evidence status is invalid") from error


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresManualEvidenceError("manual evidence row is invalid")
    return value


def _uuid(row: Mapping[str, object], key: str) -> UUID:
    try:
        return UUID(str(row.get(key)))
    except (TypeError, ValueError) as error:
        raise PostgresManualEvidenceError(f"manual evidence {key} is invalid") from error


def _positive(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresManualEvidenceError(f"manual evidence {key} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise PostgresManualEvidenceError(f"manual evidence {key} is invalid") from error
    if result < 1:
        raise PostgresManualEvidenceError(f"manual evidence {key} is invalid")
    return result


def _hash(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or len(value) != 64:
        raise PostgresManualEvidenceError(f"manual evidence {key} is invalid")
    return value


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PostgresManualEvidenceError(f"manual evidence {key} is invalid")
    return value.strip()


def _optional_text(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    return _text(row, key)


def _timestamp(row: Mapping[str, object], key: str) -> datetime:
    value = row.get(key)
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PostgresManualEvidenceError(f"manual evidence {key} is invalid") from error
    else:
        raise PostgresManualEvidenceError(f"manual evidence {key} is invalid")
    if result.tzinfo is None or result.utcoffset() is None:
        raise PostgresManualEvidenceError(f"manual evidence {key} is invalid")
    return result


def _optional_timestamp(row: Mapping[str, object], key: str) -> datetime | None:
    return None if row.get(key) is None else _timestamp(row, key)


def _idempotency_hash(value: str) -> str:
    key = value.strip()
    if not key:
        raise PostgresManualEvidenceError("Idempotency-Key is required")
    return canonical_json_hash({"idempotency_key": key})


__all__ = [
    "PostgresManualEvidenceError",
    "PostgresManualEvidenceRepository",
]
