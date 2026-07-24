"""Typed PostgreSQL admission for a first Provider Sampling Attempt."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from types import MappingProxyType
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.model_gateway import canonical_json_hash
from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import SamplingConflict
from geo_core.sampling.postgres_worker_contracts import (
    ProviderSamplingWorkerSpec,
    WorkflowCSamplingSpecError,
    parse_provider_sampling_spec,
)


class PostgresSamplingAttemptError(SamplingConflict):
    """PostgreSQL rejected a Provider Sampling Attempt admission."""


@dataclass(frozen=True)
class ProviderSamplingAttemptAdmission:
    """Secret-free frozen Worker spec for one first Provider Attempt."""

    project_id: UUID
    run_id: UUID
    task_id: UUID
    attempt_id: UUID
    expected_task_version: int
    requested_not_before: datetime
    authorization_checked_at: datetime
    spec_payload: Mapping[str, object]
    spec_hash: str = field(init=False)
    spec: ProviderSamplingWorkerSpec = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.expected_task_version < 1:
            raise PostgresSamplingAttemptError("Sampling Task version must be positive")
        if (
            self.requested_not_before.tzinfo is None
            or self.requested_not_before.utcoffset() is None
            or self.requested_not_before.year < 2000
        ):
            raise PostgresSamplingAttemptError(
                "Sampling requested-not-before time must be timezone-aware"
            )
        if (
            self.authorization_checked_at.tzinfo is None
            or self.authorization_checked_at.utcoffset() is None
        ):
            raise PostgresSamplingAttemptError("Sampling authorization time must be timezone-aware")
        payload = MappingProxyType(dict(self.spec_payload))
        try:
            spec = parse_provider_sampling_spec(payload)
        except WorkflowCSamplingSpecError as error:
            raise PostgresSamplingAttemptError("Provider Sampling spec is invalid") from error
        if (
            spec.run_id != self.run_id
            or spec.task_id != self.task_id
            or spec.attempt_id != self.attempt_id
            or spec.task_version != self.expected_task_version + 1
            or spec.attempt_version != 1
        ):
            raise PostgresSamplingAttemptError("Provider Sampling spec has inconsistent lineage")
        object.__setattr__(self, "spec_payload", payload)
        object.__setattr__(self, "spec", spec)
        object.__setattr__(self, "spec_hash", canonical_json_hash(payload))


@dataclass(frozen=True)
class PersistentProviderSamplingAttempt:
    attempt_id: UUID
    durable_job_id: UUID
    task_version: int
    attempt_version: int
    run_version: int
    replayed: bool

    def __post_init__(self) -> None:
        if min(self.task_version, self.attempt_version, self.run_version) < 1:
            raise PostgresSamplingAttemptError("Sampling Attempt versions are invalid")


class PostgresProviderSamplingAttemptRepository:
    """Consume a frozen Run reservation through the scoped 0042 RPC."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def enqueue(
        self,
        admission: ProviderSamplingAttemptAdmission,
        *,
        idempotency_key: str,
    ) -> PersistentProviderSamplingAttempt:
        job_key = f"sampling.provider:{admission.project_id}:{admission.attempt_id}"
        input_hash = _hash(
            {
                "operation": "enqueue",
                "attempt_id": str(admission.attempt_id),
                "run_id": str(admission.run_id),
                "task_id": str(admission.task_id),
                "expected_task_version": admission.expected_task_version,
                "requested_not_before": admission.requested_not_before.isoformat(),
                "spec_hash": admission.spec_hash,
                "job_idempotency_key": job_key,
            }
        )
        connection = self._connect()
        try:
            set_project_scope(connection, admission.project_id)
            row = connection.execute(
                """SELECT * FROM geo_schedule_workflow_c_provider_sampling_attempt(
                       %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s
                   )""",
                (
                    admission.project_id,
                    admission.attempt_id,
                    _idempotency_hash(idempotency_key),
                    input_hash,
                    admission.run_id,
                    admission.task_id,
                    admission.expected_task_version,
                    admission.spec_hash,
                    Jsonb(dict(admission.spec_payload)),
                    job_key,
                    admission.authorization_checked_at,
                    admission.requested_not_before,
                ),
            ).fetchone()
            if row is None:
                raise PostgresSamplingAttemptError("Sampling Attempt command did not return")
            result = _attempt(_mapping(row))
            connection.commit()
            return result
        except PostgresSamplingAttemptError:
            connection.rollback()
            raise
        except psycopg.Error as error:
            connection.rollback()
            detail = getattr(error.diag, "message_primary", "") or ""
            if detail.startswith(("Sampling ", "Provider Sampling ")):
                raise PostgresSamplingAttemptError(detail) from error
            raise PostgresSamplingAttemptError(
                "PostgreSQL rejected the Provider Sampling Attempt command"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _attempt(row: Mapping[str, object]) -> PersistentProviderSamplingAttempt:
    return PersistentProviderSamplingAttempt(
        attempt_id=_uuid(row, "attempt_id"),
        durable_job_id=_uuid(row, "durable_job_id"),
        task_version=_positive(row, "task_version"),
        attempt_version=_positive(row, "attempt_version"),
        run_version=_positive(row, "run_version"),
        replayed=_boolean(row, "replayed"),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresSamplingAttemptError("Sampling Attempt row is invalid")
    return value


def _uuid(row: Mapping[str, object], key: str) -> UUID:
    value = row.get(key)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresSamplingAttemptError(f"Sampling Attempt {key} is invalid") from error


def _positive(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresSamplingAttemptError(f"Sampling Attempt {key} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise PostgresSamplingAttemptError(f"Sampling Attempt {key} is invalid") from error
    if result < 1:
        raise PostgresSamplingAttemptError(f"Sampling Attempt {key} is invalid")
    return result


def _boolean(row: Mapping[str, object], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise PostgresSamplingAttemptError(f"Sampling Attempt {key} is invalid")
    return value


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _idempotency_hash(value: str) -> str:
    key = value.strip()
    if not key:
        raise PostgresSamplingAttemptError("Idempotency-Key is required")
    return _hash({"idempotency_key": key})


__all__ = [
    "PersistentProviderSamplingAttempt",
    "PostgresProviderSamplingAttemptRepository",
    "PostgresSamplingAttemptError",
    "ProviderSamplingAttemptAdmission",
]
