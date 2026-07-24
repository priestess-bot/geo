"""PostgreSQL persistence for the Sampling admission maker-checker boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.project_scope import set_project_scope
from geo_core.sampling.admission import (
    AdmissionPolicyStatus,
    AuthorizationState,
    SamplingAdmissionPolicyRecord,
)
from geo_core.sampling.contracts import (
    CaptureMethod,
    LocationControl,
    SamplingConflict,
    SamplingNotFound,
)


class PostgresSamplingAdmissionError(SamplingConflict):
    """PostgreSQL rejected a project-scoped Sampling admission command."""


@dataclass(frozen=True)
class PersistentSamplingAdmissionRuntimeOption:
    option_key: str
    option_hash: str
    display_name: str
    platform: str
    capture_method: CaptureMethod
    adapter_release: str
    location_control: LocationControl
    location_evidence_hash: str
    authorization_reference: str
    allowed_purposes: tuple[str, ...]


class PostgresSamplingAdmissionRepository:
    """Read and mutate policies only through the fenced database procedures."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock

    def create(
        self,
        record: SamplingAdmissionPolicyRecord,
        *,
        idempotency_key: str,
        runtime_option: PersistentSamplingAdmissionRuntimeOption,
    ) -> SamplingAdmissionPolicyRecord:
        created_at = record.created_at
        payload = {
            "schema_version": 1,
            "runtime_authorization_option_key": runtime_option.option_key,
            "runtime_authorization_option_hash": runtime_option.option_hash,
        }
        input_hash = _command_hash(
            {
                "operation": "create",
                "policy_id": str(record.id),
                "actor_id": record.created_by,
                "definition_hash": record.definition_hash,
                "runtime_option_hash": runtime_option.option_hash,
            }
        )
        return self._call(
            project_id=record.project_id,
            statement="""SELECT * FROM geo_create_workflow_c_sampling_admission_policy(
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                       )""",
            parameters=(
                record.project_id,
                record.id,
                _idempotency_hash(idempotency_key),
                input_hash,
                record.supersedes_policy_id,
                record.definition_hash,
                record.policy_version,
                record.platform,
                record.capture_method.value,
                record.adapter_release,
                record.location_control.value,
                record.location_evidence_hash,
                record.authorization_reference,
                Jsonb(list(record.authorized_purposes)),
                record.valid_until,
                record.quota_remaining,
                record.daily_task_limit,
                record.minimum_request_interval_seconds,
                record.max_concurrency,
                record.created_by,
                created_at,
                Jsonb(payload),
            ),
        )

    def transition(
        self,
        *,
        project_id: UUID,
        policy_id: UUID,
        expected_version: int,
        operation: str,
        actor_id: str,
        idempotency_key: str,
        reason: str | None,
        occurred_at: datetime | None = None,
    ) -> SamplingAdmissionPolicyRecord:
        at = occurred_at or self._clock()
        input_hash = _command_hash(
            {
                "operation": operation,
                "policy_id": str(policy_id),
                "expected_version": expected_version,
                "actor_id": actor_id,
                "reason": reason,
            }
        )
        return self._call(
            project_id=project_id,
            statement="""SELECT * FROM geo_transition_workflow_c_sampling_admission_policy(
                           %s, %s, %s, %s, %s, %s, %s, %s, %s
                       )""",
            parameters=(
                project_id,
                policy_id,
                expected_version,
                _idempotency_hash(idempotency_key),
                input_hash,
                operation,
                actor_id,
                reason,
                at,
            ),
        )

    def get(self, *, project_id: UUID, policy_id: UUID) -> SamplingAdmissionPolicyRecord:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT * FROM workflow_c_sampling_admission_policies
                   WHERE project_id = %s AND id = %s""",
                (project_id, policy_id),
            ).fetchone()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingAdmissionError(
                "Sampling admission policy could not be read"
            ) from error
        finally:
            connection.close()
        if row is None:
            raise SamplingNotFound("Sampling admission policy does not exist")
        return _record(_mapping(row), at=self._clock())

    def list(self, *, project_id: UUID) -> tuple[SamplingAdmissionPolicyRecord, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT * FROM workflow_c_sampling_admission_policies
                   WHERE project_id = %s
                   ORDER BY created_at DESC, id DESC""",
                (project_id,),
            ).fetchall()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingAdmissionError(
                "Sampling admission policies could not be listed"
            ) from error
        finally:
            connection.close()
        return tuple(_record(_mapping(row), at=self._clock()) for row in rows)

    def runtime_option(
        self, *, project_id: UUID, option_key: str
    ) -> PersistentSamplingAdmissionRuntimeOption:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT option_key, option_hash, display_name, platform, capture_method,
                          adapter_release, location_control, location_evidence_hash,
                          authorization_reference, allowed_purposes
                   FROM workflow_c_sampling_runtime_options
                   WHERE project_id = %s AND option_key = %s AND status = 'approved'""",
                (project_id, option_key),
            ).fetchone()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingAdmissionError(
                "Sampling admission runtime option could not be read"
            ) from error
        finally:
            connection.close()
        if row is None:
            raise SamplingNotFound("approved Sampling runtime authorization option does not exist")
        return _runtime_option(_mapping(row))

    def list_runtime_options(
        self, *, project_id: UUID
    ) -> tuple[PersistentSamplingAdmissionRuntimeOption, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT option_key, option_hash, display_name, platform, capture_method,
                          adapter_release, location_control, location_evidence_hash,
                          authorization_reference, allowed_purposes
                   FROM workflow_c_sampling_runtime_options
                   WHERE project_id = %s AND status = 'approved'
                   ORDER BY display_name, option_key""",
                (project_id,),
            ).fetchall()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingAdmissionError(
                "Sampling admission runtime options could not be listed"
            ) from error
        finally:
            connection.close()
        return tuple(_runtime_option(_mapping(row)) for row in rows)

    def _call(
        self,
        *,
        project_id: UUID,
        statement: str,
        parameters: tuple[object, ...],
    ) -> SamplingAdmissionPolicyRecord:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(statement, parameters).fetchone()
            if row is None:
                raise PostgresSamplingAdmissionError(
                    "Sampling admission command did not return a policy"
                )
            record = _record(_mapping(row), at=self._clock())
            connection.commit()
            return record
        except PostgresSamplingAdmissionError:
            connection.rollback()
            raise
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingAdmissionError(
                "PostgreSQL rejected the Sampling admission command"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _record(
    row: Mapping[str, object], *, at: datetime | None = None
) -> SamplingAdmissionPolicyRecord:
    payload = _mapping(row.get("payload"))
    expected_payload = {
        "runtime_authorization_option_key",
        "runtime_authorization_option_hash",
        "schema_version",
    }
    if set(payload) != expected_payload or payload.get("schema_version") != 1:
        raise PostgresSamplingAdmissionError("Sampling admission payload schema is invalid")
    record = SamplingAdmissionPolicyRecord(
        id=_uuid(row, "id"),
        project_id=_uuid(row, "project_id"),
        revision=_integer(row, "revision"),
        supersedes_policy_id=_optional_uuid(row, "supersedes_policy_id"),
        platform=_text(row, "platform"),
        capture_method=CaptureMethod(_text(row, "capture_method")),
        adapter_release=_text(row, "adapter_release"),
        location_control=LocationControl(_text(row, "location_control")),
        location_evidence_hash=_text(row, "location_evidence_hash"),
        authorization_reference=_text(row, "authorization_reference"),
        authorized_purposes=_text_tuple(row, "authorized_purposes"),
        valid_until=_datetime(row, "valid_until"),
        quota_remaining=_integer(row, "quota_remaining"),
        daily_task_limit=_integer(row, "daily_task_limit"),
        minimum_request_interval_seconds=_integer(row, "minimum_request_interval_seconds"),
        max_concurrency=_integer(row, "max_concurrency"),
        next_allowed_at=_datetime(row, "next_allowed_at"),
        created_by=_text(row, "created_by"),
        created_at=_datetime(row, "created_at"),
        status=AdmissionPolicyStatus(_text(row, "status")),
        submitted_by=_optional_text(row, "submitted_by"),
        submitted_at=_optional_datetime(row, "submitted_at"),
        decided_by=_optional_text(row, "decided_by"),
        decided_at=_optional_datetime(row, "decided_at"),
        decision_reason=_optional_text(row, "decision_reason"),
        revoked_by=_optional_text(row, "revoked_by"),
        revoked_at=_optional_datetime(row, "revoked_at"),
        revocation_reason=_optional_text(row, "revocation_reason"),
        aggregate_version=_integer(row, "aggregate_version"),
    )
    if record.definition_hash != _text(row, "definition_hash"):
        raise PostgresSamplingAdmissionError("Sampling admission definition hash is corrupt")
    if record.policy_version != _text(row, "policy_version"):
        raise PostgresSamplingAdmissionError("Sampling admission policy version is corrupt")
    _assert_effective_state(record, row, at=at)
    return record


def _assert_effective_state(
    record: SamplingAdmissionPolicyRecord,
    row: Mapping[str, object],
    *,
    at: datetime | None,
) -> None:
    stored = AuthorizationState(_text(row, "effective_authorization_state"))
    expected = record.effective_authorization_state(at=at or datetime.now(UTC))
    if expected is AuthorizationState.EXPIRED:
        if stored is not AuthorizationState.APPROVED:
            raise PostgresSamplingAdmissionError("Sampling admission expiry state is corrupt")
        return
    if stored is not expected:
        raise PostgresSamplingAdmissionError("Sampling admission lifecycle state is corrupt")


def _runtime_option(row: Mapping[str, object]) -> PersistentSamplingAdmissionRuntimeOption:
    return PersistentSamplingAdmissionRuntimeOption(
        option_key=_text(row, "option_key"),
        option_hash=_text(row, "option_hash"),
        display_name=_text(row, "display_name"),
        platform=_text(row, "platform"),
        capture_method=CaptureMethod(_text(row, "capture_method")),
        adapter_release=_text(row, "adapter_release"),
        location_control=LocationControl(_text(row, "location_control")),
        location_evidence_hash=_text(row, "location_evidence_hash"),
        authorization_reference=_text(row, "authorization_reference"),
        allowed_purposes=_text_tuple(row, "allowed_purposes"),
    )


def _idempotency_hash(value: str) -> str:
    key = value.strip()
    if not key or len(key) > 200:
        raise SamplingConflict("Sampling idempotency key must contain 1 to 200 characters")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _command_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mapping(value: object | None) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise PostgresSamplingAdmissionError("Sampling admission row is malformed")


def _uuid(row: Mapping[str, object], field: str) -> UUID:
    value = row.get(field)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresSamplingAdmissionError(f"Sampling admission {field} is malformed") from error


def _optional_uuid(row: Mapping[str, object], field: str) -> UUID | None:
    value = row.get(field)
    return None if value is None else _uuid(row, field)


def _integer(row: Mapping[str, object], field: str) -> int:
    value = row.get(field)
    if isinstance(value, bool):
        raise PostgresSamplingAdmissionError(f"Sampling admission {field} is malformed")
    if not isinstance(value, (int, str)):
        raise PostgresSamplingAdmissionError(f"Sampling admission {field} is malformed")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise PostgresSamplingAdmissionError(f"Sampling admission {field} is malformed") from error


def _datetime(row: Mapping[str, object], field: str) -> datetime:
    value = row.get(field)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PostgresSamplingAdmissionError(f"Sampling admission {field} is malformed")
    return value


def _optional_datetime(row: Mapping[str, object], field: str) -> datetime | None:
    value = row.get(field)
    return None if value is None else _datetime(row, field)


def _text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PostgresSamplingAdmissionError(f"Sampling admission {field} is malformed")
    return value


def _optional_text(row: Mapping[str, object], field: str) -> str | None:
    value = row.get(field)
    return None if value is None else _text(row, field)


def _text_tuple(row: Mapping[str, object], field: str) -> tuple[str, ...]:
    value = row.get(field)
    if not isinstance(value, list) or not value:
        raise PostgresSamplingAdmissionError(f"Sampling admission {field} is malformed")
    values = tuple(sorted({_text({"value": item}, "value") for item in value}))
    if len(values) != len(value):
        raise PostgresSamplingAdmissionError(f"Sampling admission {field} is not canonical")
    return values


__all__ = [
    "PersistentSamplingAdmissionRuntimeOption",
    "PostgresSamplingAdmissionError",
    "PostgresSamplingAdmissionRepository",
]
