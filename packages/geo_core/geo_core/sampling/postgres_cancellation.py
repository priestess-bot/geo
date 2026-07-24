"""Typed PostgreSQL cancellation commands for durable Sampling execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import SamplingConflict


class PostgresSamplingCancellationError(SamplingConflict):
    """PostgreSQL rejected a fenced Sampling cancellation command."""


@dataclass(frozen=True)
class PersistentSamplingAttemptCancellation:
    run_id: UUID
    task_id: UUID
    attempt_id: UUID
    task_version: int
    attempt_version: int
    run_status: str
    cancellation_requested: bool
    replayed: bool

    def __post_init__(self) -> None:
        if min(self.task_version, self.attempt_version) < 1:
            raise PostgresSamplingCancellationError("Sampling cancellation versions are invalid")
        if self.run_status not in {"planned", "running", "cancel_requested", "cancelled"}:
            raise PostgresSamplingCancellationError("Sampling cancellation Run status is invalid")


@dataclass(frozen=True)
class PersistentSamplingRunCancellation:
    run_id: UUID
    run_status: str
    released_task_count: int
    cancellation_requested_count: int
    attempt_ids: tuple[UUID, ...]
    replayed: bool

    def __post_init__(self) -> None:
        if self.released_task_count < 0 or self.cancellation_requested_count < 0:
            raise PostgresSamplingCancellationError("Sampling cancellation counts are invalid")
        if self.run_status not in {"cancel_requested", "cancelled"}:
            raise PostgresSamplingCancellationError("Sampling cancellation Run status is invalid")


class PostgresSamplingCancellationRepository:
    """Call the fenced 0044 cancellation procedures under the project RLS scope."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def cancel_attempt(
        self,
        *,
        project_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        idempotency_key: str,
        cancelled_at: datetime,
    ) -> PersistentSamplingAttemptCancellation:
        if min(expected_task_version, expected_attempt_version) < 1:
            raise PostgresSamplingCancellationError("Sampling cancellation versions are invalid")
        _aware(cancelled_at)
        return _call(
            connect=self._connect,
            project_id=project_id,
            statement="""SELECT * FROM geo_cancel_workflow_c_sampling_attempt(
                             %s, %s, %s, %s, %s, %s, %s
                         )""",
            parameters=(
                project_id,
                attempt_id,
                expected_task_version,
                expected_attempt_version,
                _idempotency_hash(idempotency_key),
                _hash(
                    {
                        "operation": "cancel_attempt",
                        "attempt_id": str(attempt_id),
                        "expected_task_version": expected_task_version,
                        "expected_attempt_version": expected_attempt_version,
                    }
                ),
                cancelled_at,
            ),
            factory=_attempt_cancellation,
        )

    def cancel_run(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        idempotency_key: str,
        cancelled_at: datetime,
    ) -> PersistentSamplingRunCancellation:
        _aware(cancelled_at)
        return _call(
            connect=self._connect,
            project_id=project_id,
            statement="""SELECT * FROM geo_cancel_workflow_c_sampling_run_v2(
                             %s, %s, %s, %s, %s
                         )""",
            parameters=(
                project_id,
                run_id,
                _idempotency_hash(idempotency_key),
                _hash({"operation": "cancel_run", "run_id": str(run_id)}),
                cancelled_at,
            ),
            factory=_run_cancellation,
        )


def _call[T](
    *,
    connect: Callable[[], Any],
    project_id: UUID,
    statement: str,
    parameters: tuple[object, ...],
    factory: Callable[[Mapping[str, object]], T],
) -> T:
    connection = connect()
    try:
        set_project_scope(connection, project_id)
        row = connection.execute(statement, parameters).fetchone()
        if row is None:
            raise PostgresSamplingCancellationError("Sampling cancellation did not return")
        result = factory(_mapping(row))
        connection.commit()
        return result
    except PostgresSamplingCancellationError:
        connection.rollback()
        raise
    except psycopg.Error as error:
        connection.rollback()
        detail = getattr(error.diag, "message_primary", "") or ""
        if detail.startswith("Sampling "):
            raise PostgresSamplingCancellationError(detail) from error
        raise PostgresSamplingCancellationError(
            "PostgreSQL rejected the Sampling cancellation command"
        ) from error
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _attempt_cancellation(row: Mapping[str, object]) -> PersistentSamplingAttemptCancellation:
    return PersistentSamplingAttemptCancellation(
        run_id=_uuid(row, "run_id"),
        task_id=_uuid(row, "task_id"),
        attempt_id=_uuid(row, "attempt_id"),
        task_version=_positive(row, "task_version"),
        attempt_version=_positive(row, "attempt_version"),
        run_status=_text(row, "run_status"),
        cancellation_requested=_boolean(row, "cancellation_requested"),
        replayed=_boolean(row, "replayed"),
    )


def _run_cancellation(row: Mapping[str, object]) -> PersistentSamplingRunCancellation:
    return PersistentSamplingRunCancellation(
        run_id=_uuid(row, "run_id"),
        run_status=_text(row, "run_status"),
        released_task_count=_nonnegative(row, "released_task_count"),
        cancellation_requested_count=_nonnegative(row, "cancellation_requested_count"),
        attempt_ids=_uuid_tuple(row, "attempt_ids"),
        replayed=_boolean(row, "replayed"),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresSamplingCancellationError("Sampling cancellation row is invalid")
    return value


def _uuid(row: Mapping[str, object], key: str) -> UUID:
    value = row.get(key)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresSamplingCancellationError(f"Sampling cancellation {key} is invalid") from error


def _uuid_tuple(row: Mapping[str, object], key: str) -> tuple[UUID, ...]:
    value = row.get(key)
    if not isinstance(value, (list, tuple)):
        raise PostgresSamplingCancellationError(f"Sampling cancellation {key} is invalid")
    result: list[UUID] = []
    for item in value:
        try:
            result.append(item if isinstance(item, UUID) else UUID(str(item)))
        except (TypeError, ValueError) as error:
            raise PostgresSamplingCancellationError(
                f"Sampling cancellation {key} is invalid"
            ) from error
    if len(set(result)) != len(result):
        raise PostgresSamplingCancellationError(f"Sampling cancellation {key} is invalid")
    return tuple(result)


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PostgresSamplingCancellationError(f"Sampling cancellation {key} is invalid")
    return value


def _positive(row: Mapping[str, object], key: str) -> int:
    result = _nonnegative(row, key)
    if result < 1:
        raise PostgresSamplingCancellationError(f"Sampling cancellation {key} is invalid")
    return result


def _nonnegative(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresSamplingCancellationError(f"Sampling cancellation {key} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise PostgresSamplingCancellationError(f"Sampling cancellation {key} is invalid") from error
    if result < 0:
        raise PostgresSamplingCancellationError(f"Sampling cancellation {key} is invalid")
    return result


def _boolean(row: Mapping[str, object], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise PostgresSamplingCancellationError(f"Sampling cancellation {key} is invalid")
    return value


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PostgresSamplingCancellationError("Sampling cancellation time must be timezone-aware")


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _idempotency_hash(value: str) -> str:
    key = value.strip()
    if not key:
        raise PostgresSamplingCancellationError("Idempotency-Key is required")
    return _hash({"idempotency_key": key})


__all__ = [
    "PersistentSamplingAttemptCancellation",
    "PersistentSamplingRunCancellation",
    "PostgresSamplingCancellationError",
    "PostgresSamplingCancellationRepository",
]
