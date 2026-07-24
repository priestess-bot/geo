"""Atomic PostgreSQL admission for a frozen batch of Provider Sampling attempts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.model_gateway import canonical_json_hash
from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import SamplingConflict
from geo_core.sampling.postgres_attempts import PersistentProviderSamplingAttempt
from geo_core.sampling.postgres_worker_contracts import (
    ProviderSamplingWorkerSpec,
    WorkflowCSamplingSpecError,
    parse_provider_sampling_spec,
)


class PostgresProviderSamplingBulkAttemptError(SamplingConflict):
    """PostgreSQL rejected a bulk Provider Sampling admission."""


@dataclass(frozen=True)
class ProviderSamplingBulkAttemptItem:
    """One server-built immutable Provider Worker spec within a bulk command."""

    task_id: UUID
    attempt_id: UUID
    expected_task_version: int
    spec_payload: Mapping[str, object]
    spec_hash: str = field(init=False)
    spec: ProviderSamplingWorkerSpec = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.expected_task_version < 1:
            raise PostgresProviderSamplingBulkAttemptError(
                "Sampling Task version must be positive"
            )
        payload = MappingProxyType(dict(self.spec_payload))
        try:
            spec = parse_provider_sampling_spec(payload)
        except WorkflowCSamplingSpecError as error:
            raise PostgresProviderSamplingBulkAttemptError(
                "Provider Sampling bulk spec is invalid"
            ) from error
        if (
            spec.task_id != self.task_id
            or spec.attempt_id != self.attempt_id
            or spec.task_version != self.expected_task_version + 1
            or spec.attempt_version != 1
        ):
            raise PostgresProviderSamplingBulkAttemptError(
                "Provider Sampling bulk spec has inconsistent lineage"
            )
        object.__setattr__(self, "spec_payload", payload)
        object.__setattr__(self, "spec", spec)
        object.__setattr__(self, "spec_hash", canonical_json_hash(payload))

    def payload(self, *, project_id: UUID) -> dict[str, object]:
        return {
            "task_id": str(self.task_id),
            "attempt_id": str(self.attempt_id),
            "expected_task_version": self.expected_task_version,
            "spec_hash": self.spec_hash,
            "spec_payload": dict(self.spec_payload),
            "job_idempotency_key": (
                f"sampling.provider:{project_id}:{self.attempt_id}"
            ),
        }


@dataclass(frozen=True)
class ProviderSamplingBulkAttemptAdmission:
    """The complete, secret-free immutable input for one bulk enqueue command."""

    project_id: UUID
    run_id: UUID
    requested_not_before: datetime
    authorization_checked_at: datetime
    max_tasks: int
    items: tuple[ProviderSamplingBulkAttemptItem, ...]

    def __post_init__(self) -> None:
        if not 1 <= self.max_tasks <= 100_000:
            raise PostgresProviderSamplingBulkAttemptError(
                "bulk Sampling enqueue limit is invalid"
            )
        for timestamp, label in (
            (self.requested_not_before, "Sampling requested-not-before time"),
            (self.authorization_checked_at, "Sampling authorization time"),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise PostgresProviderSamplingBulkAttemptError(f"{label} must be timezone-aware")
        if len(self.items) > self.max_tasks:
            raise PostgresProviderSamplingBulkAttemptError(
                "bulk Sampling items exceed the requested limit"
            )
        if len({item.task_id for item in self.items}) != len(self.items):
            raise PostgresProviderSamplingBulkAttemptError("bulk Sampling Tasks are duplicated")
        if len({item.attempt_id for item in self.items}) != len(self.items):
            raise PostgresProviderSamplingBulkAttemptError("bulk Sampling Attempts are duplicated")
        if any(item.spec.run_id != self.run_id for item in self.items):
            raise PostgresProviderSamplingBulkAttemptError(
                "Provider Sampling bulk spec references a different Run"
            )

    def input_payload(self) -> dict[str, object]:
        """Return the caller-controlled command identity, never the ready slice.

        PostgreSQL freezes the server-resolved Task slice and Worker specs in its
        command result.  Including that slice here would make a valid retry look
        different after the first commit changes Tasks from ``planned`` to
        ``queued``.
        """
        return {
            "schema_version": 1,
            "run_id": str(self.run_id),
            "requested_not_before": self.requested_not_before.isoformat(),
            "max_tasks": self.max_tasks,
        }


@dataclass(frozen=True)
class PersistentProviderSamplingBulkAttempt:
    """Durable result for a whole bulk admission, including no-op replays."""

    run_id: UUID
    planned_task_count: int
    enqueued_count: int
    skipped_count: int
    attempts: tuple[PersistentProviderSamplingAttempt, ...]
    scheduled_at: tuple[datetime, ...]
    replayed: bool

    def __post_init__(self) -> None:
        if min(self.planned_task_count, self.enqueued_count, self.skipped_count) < 0:
            raise PostgresProviderSamplingBulkAttemptError("bulk Sampling counts are invalid")
        if self.enqueued_count != len(self.attempts) or len(self.attempts) != len(
            self.scheduled_at
        ):
            raise PostgresProviderSamplingBulkAttemptError("bulk Sampling result is incomplete")
        if self.planned_task_count != self.enqueued_count + self.skipped_count:
            raise PostgresProviderSamplingBulkAttemptError("bulk Sampling counts do not balance")
        if any(value.tzinfo is None or value.utcoffset() is None for value in self.scheduled_at):
            raise PostgresProviderSamplingBulkAttemptError("bulk Sampling schedule is invalid")


class PostgresProviderSamplingBulkAttemptRepository:
    """Call the fenced 0055 RPC; PostgreSQL commits every item or none of them."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def enqueue_ready(
        self,
        admission: ProviderSamplingBulkAttemptAdmission,
        *,
        idempotency_key: str,
    ) -> PersistentProviderSamplingBulkAttempt:
        input_hash = canonical_json_hash(admission.input_payload())
        connection = self._connect()
        try:
            set_project_scope(connection, admission.project_id)
            row = connection.execute(
                """SELECT geo_enqueue_ready_workflow_c_provider_sampling_attempts(
                       %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                   ) AS result""",
                (
                    admission.project_id,
                    admission.run_id,
                    _idempotency_hash(idempotency_key),
                    input_hash,
                    admission.requested_not_before,
                    admission.authorization_checked_at,
                    admission.max_tasks,
                    Jsonb(
                        [item.payload(project_id=admission.project_id) for item in admission.items]
                    ),
                ),
            ).fetchone()
            if row is None:
                raise PostgresProviderSamplingBulkAttemptError(
                    "bulk Sampling command did not return"
                )
            result = _result(_mapping(row).get("result"), admission=admission)
            connection.commit()
            return result
        except PostgresProviderSamplingBulkAttemptError:
            connection.rollback()
            raise
        except psycopg.Error as error:
            connection.rollback()
            detail = getattr(error.diag, "message_primary", "") or ""
            if detail.startswith(("Sampling ", "Provider Sampling ", "bulk Sampling ")):
                raise PostgresProviderSamplingBulkAttemptError(detail) from error
            raise PostgresProviderSamplingBulkAttemptError(
                "PostgreSQL rejected the bulk Provider Sampling command"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _result(
    value: object, *, admission: ProviderSamplingBulkAttemptAdmission
) -> PersistentProviderSamplingBulkAttempt:
    payload = _mapping(value)
    expected = {
        "schema_version",
        "run_id",
        "planned_task_count",
        "enqueued_count",
        "skipped_count",
        "attempts",
        "replayed",
    }
    if set(payload) != expected or payload.get("schema_version") != 1:
        raise PostgresProviderSamplingBulkAttemptError("bulk Sampling result schema is invalid")
    if _uuid(payload.get("run_id"), "Run ID") != admission.run_id:
        raise PostgresProviderSamplingBulkAttemptError("bulk Sampling result references another Run")
    attempts_value = payload.get("attempts")
    if not isinstance(attempts_value, list):
        raise PostgresProviderSamplingBulkAttemptError("bulk Sampling attempt result is invalid")
    attempts: list[PersistentProviderSamplingAttempt] = []
    scheduled: list[datetime] = []
    replayed = _boolean(payload.get("replayed"), "replayed")
    expected_items = {item.attempt_id: item for item in admission.items}
    for value in attempts_value:
        item = _mapping(value)
        if set(item) != {
            "attempt_id",
            "durable_job_id",
            "task_version",
            "attempt_version",
            "run_version",
            "scheduled_at",
        }:
            raise PostgresProviderSamplingBulkAttemptError(
                "bulk Sampling attempt result schema is invalid"
            )
        attempt_id = _uuid(item.get("attempt_id"), "Attempt ID")
        if not replayed and attempt_id not in expected_items:
            raise PostgresProviderSamplingBulkAttemptError(
                "bulk Sampling result includes an unrequested Attempt"
            )
        attempts.append(
            PersistentProviderSamplingAttempt(
                attempt_id=attempt_id,
                durable_job_id=_uuid(item.get("durable_job_id"), "durable Job ID"),
                task_version=_positive(item.get("task_version"), "task version"),
                attempt_version=_positive(item.get("attempt_version"), "attempt version"),
                run_version=_positive(item.get("run_version"), "Run version"),
                replayed=replayed,
            )
        )
        scheduled.append(_datetime(item.get("scheduled_at"), "schedule"))
    if not replayed and {item.attempt_id for item in attempts} != set(expected_items):
        raise PostgresProviderSamplingBulkAttemptError("bulk Sampling result Attempts differ")
    if len({item.attempt_id for item in attempts}) != len(attempts):
        raise PostgresProviderSamplingBulkAttemptError("bulk Sampling result Attempts are duplicated")
    return PersistentProviderSamplingBulkAttempt(
        run_id=admission.run_id,
        planned_task_count=_nonnegative(payload.get("planned_task_count"), "planned task count"),
        enqueued_count=_nonnegative(payload.get("enqueued_count"), "enqueued count"),
        skipped_count=_nonnegative(payload.get("skipped_count"), "skipped count"),
        attempts=tuple(attempts),
        scheduled_at=tuple(scheduled),
        replayed=replayed,
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresProviderSamplingBulkAttemptError("bulk Sampling result is invalid")
    return value


def _uuid(value: object, label: str) -> UUID:
    try:
        result = UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresProviderSamplingBulkAttemptError(
            f"bulk Sampling {label} is invalid"
        ) from error
    if result.int == 0:
        raise PostgresProviderSamplingBulkAttemptError(f"bulk Sampling {label} is invalid")
    return result


def _positive(value: object, label: str) -> int:
    result = _nonnegative(value, label)
    if result < 1:
        raise PostgresProviderSamplingBulkAttemptError(f"bulk Sampling {label} is invalid")
    return result


def _nonnegative(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresProviderSamplingBulkAttemptError(f"bulk Sampling {label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise PostgresProviderSamplingBulkAttemptError(
            f"bulk Sampling {label} is invalid"
        ) from error
    if result < 0:
        raise PostgresProviderSamplingBulkAttemptError(f"bulk Sampling {label} is invalid")
    return result


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise PostgresProviderSamplingBulkAttemptError(f"bulk Sampling {label} is invalid")
    return value


def _datetime(value: object, label: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PostgresProviderSamplingBulkAttemptError(
                f"bulk Sampling {label} is invalid"
            ) from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PostgresProviderSamplingBulkAttemptError(f"bulk Sampling {label} is invalid")
    return value


def _idempotency_hash(value: str) -> str:
    key = value.strip()
    if not key:
        raise PostgresProviderSamplingBulkAttemptError("Idempotency-Key is required")
    return canonical_json_hash({"idempotency_key": key})


__all__ = [
    "PersistentProviderSamplingBulkAttempt",
    "PostgresProviderSamplingBulkAttemptError",
    "PostgresProviderSamplingBulkAttemptRepository",
    "ProviderSamplingBulkAttemptAdmission",
    "ProviderSamplingBulkAttemptItem",
]
