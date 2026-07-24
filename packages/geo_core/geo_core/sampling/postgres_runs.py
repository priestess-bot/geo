"""Atomic PostgreSQL reservation and materialization for Sampling Runs."""

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
from geo_core.sampling.admission import SamplingAdmissionGrant
from geo_core.sampling.contracts import (
    SamplingConflict,
    SamplingNotFound,
    SamplingRun,
    SamplingRunStatus,
    SamplingSuite,
    SamplingTask,
    SamplingTaskIdentity,
    SamplingTaskStatus,
    sampling_task_id,
)
from geo_core.sampling.lifecycle import materialize_sampling_run


class PostgresSamplingRunError(SamplingConflict):
    """PostgreSQL rejected a Sampling Run reservation command."""


@dataclass(frozen=True)
class PersistentSamplingRunReservation:
    """The durable quota counters associated with one immutable Run."""

    run_id: UUID
    reserved_task_count: int
    consumed_task_count: int
    released_task_count: int

    def __post_init__(self) -> None:
        if self.reserved_task_count < 1 or min(
            self.consumed_task_count, self.released_task_count
        ) < 0:
            raise PostgresSamplingRunError("Sampling Run reservation counts are invalid")
        if self.consumed_task_count + self.released_task_count > self.reserved_task_count:
            raise PostgresSamplingRunError("Sampling Run reservation balance is invalid")

    @property
    def unused_task_count(self) -> int:
        return self.reserved_task_count - self.consumed_task_count - self.released_task_count


class PostgresSamplingRunRepository:
    """Persist a complete Run denominator through the fenced 0041 RPC."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def create_run(
        self,
        *,
        suite: SamplingSuite,
        grant: SamplingAdmissionGrant,
        run_id: UUID,
        idempotency_key: str,
        created_at: datetime,
    ) -> tuple[SamplingRun, tuple[SamplingTask, ...]]:
        run, tasks = materialize_sampling_run(
            suite, grant=grant, run_id=run_id, created_at=created_at
        )
        run_payload = {
            "schema_version": 1,
            "planned_task_keys": list(run.planned_task_keys),
            "authorization_reference": run.authorization_reference,
            "admission_policy_version": run.admission_policy_version,
        }
        task_payload = [_task_payload(task) for task in tasks]
        input_hash = _hash(
            {
                "operation": "create",
                "run_id": str(run.id),
                "suite_hash": run.suite_hash,
                "grant_hash": run.admission_grant_hash,
                "purpose": run.purpose,
                "admitted_not_before": run.admitted_not_before.isoformat(),
                "run_payload": run_payload,
                "tasks": task_payload,
            }
        )
        row = self._call(
            project_id=run.project_id,
            statement="""SELECT * FROM geo_create_workflow_c_sampling_run(
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s::jsonb, %s::jsonb, %s
                       )""",
            parameters=(
                run.project_id,
                run.id,
                _idempotency_hash(idempotency_key),
                input_hash,
                run.suite_id,
                run.suite_hash,
                run.admission_policy_hash,
                run.admission_grant_hash,
                run.purpose,
                run.authorization_reference,
                run.admission_policy_version,
                run.admitted_not_before,
                run.authorization_valid_until,
                Jsonb(run_payload),
                Jsonb(task_payload),
                run.created_at,
            ),
        )
        persisted = _run(_mapping(row))
        if persisted != run:
            raise PostgresSamplingRunError("Sampling Run replay differs from frozen input")
        stored_tasks = self.list_tasks(
            project_id=run.project_id,
            run_id=run.id,
            suite=suite,
        )
        if stored_tasks != tuple(sorted(tasks, key=lambda item: item.identity.task_key)):
            raise PostgresSamplingRunError("Sampling Run Task inventory is corrupt")
        return persisted, stored_tasks

    def get_run(self, *, project_id: UUID, run_id: UUID) -> SamplingRun:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT * FROM workflow_c_sampling_runs
                   WHERE project_id = %s AND id = %s""",
                (project_id, run_id),
            ).fetchone()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingRunError("Sampling Run could not be read") from error
        finally:
            connection.close()
        if row is None:
            raise SamplingNotFound("Sampling Run does not exist")
        return _run(_mapping(row))

    def list_runs(self, *, project_id: UUID) -> tuple[SamplingRun, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT * FROM workflow_c_sampling_runs
                   WHERE project_id = %s ORDER BY created_at DESC, id DESC""",
                (project_id,),
            ).fetchall()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingRunError("Sampling Runs could not be listed") from error
        finally:
            connection.close()
        return tuple(_run(_mapping(row)) for row in rows)

    def list_tasks(
        self, *, project_id: UUID, run_id: UUID, suite: SamplingSuite
    ) -> tuple[SamplingTask, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT * FROM workflow_c_sampling_tasks
                   WHERE project_id = %s AND run_id = %s
                   ORDER BY task_key""",
                (project_id, run_id),
            ).fetchall()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingRunError("Sampling Run Tasks could not be read") from error
        finally:
            connection.close()
        return tuple(_task(_mapping(row), suite=suite) for row in rows)

    def reservation(
        self, *, project_id: UUID, run_id: UUID
    ) -> PersistentSamplingRunReservation:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT id, reserved_task_count, consumed_task_count, released_task_count
                   FROM workflow_c_sampling_runs
                   WHERE project_id = %s AND id = %s""",
                (project_id, run_id),
            ).fetchone()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingRunError("Sampling Run reservation could not be read") from error
        finally:
            connection.close()
        if row is None:
            raise SamplingNotFound("Sampling Run does not exist")
        values = _mapping(row)
        return PersistentSamplingRunReservation(
            run_id=_uuid(values, "id"),
            reserved_task_count=_integer(values, "reserved_task_count"),
            consumed_task_count=_integer(values, "consumed_task_count"),
            released_task_count=_integer(values, "released_task_count"),
        )

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
                raise PostgresSamplingRunError("Sampling Run command did not return a Run")
            result = _mapping(row)
            connection.commit()
            return result
        except PostgresSamplingRunError:
            connection.rollback()
            raise
        except psycopg.Error as error:
            connection.rollback()
            detail = getattr(error.diag, "message_primary", "") or ""
            if detail.startswith("Sampling "):
                raise PostgresSamplingRunError(detail) from error
            raise PostgresSamplingRunError("PostgreSQL rejected the Sampling Run command") from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _task_payload(task: SamplingTask) -> dict[str, object]:
    identity = task.identity
    return {
        "id": str(task.id),
        "task_key": identity.task_key,
        "source_stratum_hash": identity.source_stratum_hash,
        "capture_method": identity.capture_method.value,
        "question_id": identity.question_id,
        "question_version": identity.question_version,
        "repetition": identity.repetition,
    }


def _run(row: Mapping[str, object]) -> SamplingRun:
    payload = _mapping(row.get("payload"))
    keys = payload.get("planned_task_keys")
    if set(payload) != {
        "schema_version",
        "planned_task_keys",
        "authorization_reference",
        "admission_policy_version",
    } or payload.get("schema_version") != 1 or not isinstance(keys, list) or not all(
        isinstance(item, str) for item in keys
    ):
        raise PostgresSamplingRunError("Sampling Run payload is invalid")
    reservation = PersistentSamplingRunReservation(
        run_id=_uuid(row, "id"),
        reserved_task_count=_integer(row, "reserved_task_count"),
        consumed_task_count=_integer(row, "consumed_task_count"),
        released_task_count=_integer(row, "released_task_count"),
    )
    if reservation.reserved_task_count != len(keys):
        raise PostgresSamplingRunError("Sampling Run denominator is corrupt")
    return SamplingRun(
        id=reservation.run_id,
        project_id=_uuid(row, "project_id"),
        suite_id=_uuid(row, "suite_id"),
        suite_hash=_text(row, "suite_hash"),
        admission_policy_id=_uuid(row, "admission_policy_id"),
        admission_policy_hash=_text(row, "admission_policy_hash"),
        admission_grant_hash=_text(row, "admission_grant_hash"),
        purpose=_text(row, "purpose"),
        authorization_reference=_text(payload, "authorization_reference"),
        authorization_valid_until=_datetime(row, "authorization_valid_until"),
        admission_policy_version=_text(payload, "admission_policy_version"),
        reserved_task_count=reservation.reserved_task_count,
        planned_task_keys=tuple(sorted(keys)),
        status=SamplingRunStatus(_text(row, "status")),
        admitted_not_before=_datetime(row, "admitted_not_before"),
        created_at=_datetime(row, "created_at"),
        version=_integer(row, "version"),
    )


def _task(row: Mapping[str, object], *, suite: SamplingSuite) -> SamplingTask:
    if _uuid(row, "suite_id") != suite.id:
        raise PostgresSamplingRunError("Sampling Task references a different Suite")
    source = suite.source_stratum
    if _text(row, "source_stratum_hash") != source.stratum_hash or _text(
        row, "capture_method"
    ) != source.capture_method.value:
        raise PostgresSamplingRunError("Sampling Task source lineage is corrupt")
    identity = SamplingTaskIdentity(
        suite_id=suite.id,
        suite_hash=suite.suite_hash,
        platform=source.platform,
        question_id=_text(row, "question_id"),
        question_version=_text(row, "question_version"),
        repetition=_integer(row, "repetition"),
        region=source.region,
        language=source.language,
        capture_method=source.capture_method,
        adapter_release=source.adapter_release,
        account_cohort=source.account_cohort,
        egress_policy_category=source.egress_policy_category,
        location_control=source.location_control,
        location_evidence_hash=source.location_evidence_hash,
        requested_country=source.requested_country,
        requested_region=source.requested_region,
        requested_locale=source.requested_locale,
        requested_language=source.requested_language,
        effective_country=source.effective_country,
        effective_region=source.effective_region,
        effective_locale=source.effective_locale,
        effective_language=source.effective_language,
        source_stratum_hash=source.stratum_hash,
    )
    stored_task_id = _uuid(row, "id")
    run_id = _uuid(row, "run_id")
    if identity.task_key != _text(row, "task_key") or stored_task_id not in {
        sampling_task_id(run_id, identity.task_key),
        identity.task_id,
    }:
        raise PostgresSamplingRunError("Sampling Task deterministic identity is corrupt")
    return SamplingTask(
        id=stored_task_id,
        project_id=_uuid(row, "project_id"),
        run_id=run_id,
        identity=identity,
        status=SamplingTaskStatus(_text(row, "status")),
        version=_integer(row, "version"),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresSamplingRunError("Sampling Run row mapping is invalid")
    return value


def _uuid(row: Mapping[str, object], key: str) -> UUID:
    value = row.get(key)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresSamplingRunError(f"Sampling Run {key} is invalid") from error


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PostgresSamplingRunError(f"Sampling Run {key} is invalid")
    return value


def _integer(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresSamplingRunError(f"Sampling Run {key} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise PostgresSamplingRunError(f"Sampling Run {key} is invalid") from error
    if result < 0:
        raise PostgresSamplingRunError(f"Sampling Run {key} is invalid")
    return result


def _datetime(row: Mapping[str, object], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PostgresSamplingRunError(f"Sampling Run {key} is invalid")
    return value.astimezone(UTC)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _idempotency_hash(value: str) -> str:
    key = value.strip()
    if not key:
        raise PostgresSamplingRunError("Idempotency-Key is required")
    return _hash({"idempotency_key": key})


__all__ = [
    "PersistentSamplingRunReservation",
    "PostgresSamplingRunError",
    "PostgresSamplingRunRepository",
]
