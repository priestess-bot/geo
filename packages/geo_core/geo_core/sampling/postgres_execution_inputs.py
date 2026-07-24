"""PostgreSQL registry for server-resolved Provider Sampling execution inputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import SamplingNotFound
from geo_core.sampling.provider_execution_inputs import (
    ProviderSamplingExecutionInput,
    ProviderSamplingExecutionInputError,
)


_RETIRED_REASON_CODES = frozenset(
    {
        "authorization_expired",
        "configuration_error",
        "policy_withdrawn",
        "provider_decommissioned",
        "safety_review",
        "superseded",
    }
)


class PostgresProviderSamplingExecutionInputError(ProviderSamplingExecutionInputError):
    """PostgreSQL rejected a Provider execution-input command or read."""


@dataclass(frozen=True)
class PersistentProviderSamplingExecutionInput:
    project_id: UUID
    suite_input_option_id: UUID
    suite_input_option_hash: str
    execution: ProviderSamplingExecutionInput
    frozen_at: datetime
    status: str = "approved"
    aggregate_version: int = 1
    retired_at: datetime | None = None
    retired_by: str | None = None
    retirement_reason: str | None = None

    @property
    def execution_input_hash(self) -> str:
        return self.execution.input_hash


@dataclass(frozen=True)
class ProviderSamplingExecutionInputRetirement:
    """One optimistic, idempotent retirement of a frozen execution input."""

    project_id: UUID
    suite_input_option_id: UUID
    execution_input_hash: str
    expected_version: int
    actor_id: str
    reason: str
    retired_at: datetime


class PostgresProviderSamplingExecutionInputRepository:
    """Use the scoped registry; no API caller may write execution inputs directly."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def register(
        self,
        value: PersistentProviderSamplingExecutionInput,
        *,
        idempotency_key: str,
    ) -> PersistentProviderSamplingExecutionInput:
        command_hash = _hash(
            {
                "operation": "register",
                "suite_input_option_id": str(value.suite_input_option_id),
                "suite_input_option_hash": value.suite_input_option_hash,
                "execution_input_hash": value.execution_input_hash,
            }
        )
        return self._call(
            project_id=value.project_id,
            statement="""SELECT * FROM geo_register_workflow_c_provider_execution_input(
                           %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                       )""",
            parameters=(
                value.project_id,
                value.suite_input_option_id,
                value.suite_input_option_hash,
                value.execution_input_hash,
                _hash({"idempotency_key": _required(idempotency_key, "Idempotency-Key")}),
                command_hash,
                Jsonb(value.execution.payload()),
                value.frozen_at,
            ),
        )

    def get_for_suite(
        self, *, project_id: UUID, suite_id: UUID
    ) -> PersistentProviderSamplingExecutionInput:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT execution.*
                     FROM workflow_c_sampling_suites AS suite
                     JOIN workflow_c_sampling_provider_execution_inputs AS execution
                       ON execution.project_id = suite.project_id
                      AND execution.suite_input_option_id
                          = suite.provider_execution_input_option_id
                      AND execution.execution_input_hash
                          = suite.provider_execution_input_hash
                    WHERE suite.project_id = %s AND suite.id = %s""",
                (project_id, suite_id),
            ).fetchone()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresProviderSamplingExecutionInputError(
                "Provider execution input could not be read"
            ) from error
        finally:
            connection.close()
        if row is None:
            raise SamplingNotFound("Sampling Suite has no frozen Provider execution input")
        return _persistent(_mapping(row))

    def retire(
        self,
        value: ProviderSamplingExecutionInputRetirement,
        *,
        idempotency_key: str,
    ) -> PersistentProviderSamplingExecutionInput:
        actor_id = _actor(value.actor_id)
        reason = _reason(value.reason)
        command_hash = _hash(
            {
                "operation": "retire",
                "suite_input_option_id": str(value.suite_input_option_id),
                "execution_input_hash": _hash_value(value.execution_input_hash),
                "expected_version": _positive(value.expected_version, "expected version"),
                "actor_id": actor_id,
                "reason": reason,
                "retired_at": _datetime(value.retired_at).isoformat(),
            }
        )
        return self._call(
            project_id=value.project_id,
            statement="""SELECT * FROM geo_retire_workflow_c_provider_execution_input(
                           %s, %s, %s, %s, %s, %s, %s, %s, %s
                       )""",
            parameters=(
                value.project_id,
                value.suite_input_option_id,
                _hash_value(value.execution_input_hash),
                _positive(value.expected_version, "expected version"),
                actor_id,
                reason,
                _hash({"idempotency_key": _required(idempotency_key, "Idempotency-Key")}),
                command_hash,
                _datetime(value.retired_at),
            ),
        )

    def _call(
        self,
        *,
        project_id: UUID,
        statement: str,
        parameters: tuple[object, ...],
    ) -> PersistentProviderSamplingExecutionInput:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(statement, parameters).fetchone()
            if row is None:
                raise PostgresProviderSamplingExecutionInputError(
                    "Provider execution input command did not return"
                )
            result = _persistent(_mapping(row))
            connection.commit()
            return result
        except PostgresProviderSamplingExecutionInputError:
            connection.rollback()
            raise
        except psycopg.Error as error:
            connection.rollback()
            detail = getattr(error.diag, "message_primary", "") or ""
            if detail.startswith("Provider execution input"):
                raise PostgresProviderSamplingExecutionInputError(detail) from error
            raise PostgresProviderSamplingExecutionInputError(
                "PostgreSQL rejected the Provider execution input command"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _persistent(row: Mapping[str, object]) -> PersistentProviderSamplingExecutionInput:
    try:
        execution = ProviderSamplingExecutionInput.from_payload(_mapping(row.get("payload")))
    except ProviderSamplingExecutionInputError as error:
        raise PostgresProviderSamplingExecutionInputError(
            "Provider execution input payload is invalid"
        ) from error
    if execution.input_hash != _hash_value(row.get("execution_input_hash")):
        raise PostgresProviderSamplingExecutionInputError(
            "Provider execution input hash is corrupt"
        )
    return PersistentProviderSamplingExecutionInput(
        project_id=_uuid(row.get("project_id"), "project ID"),
        suite_input_option_id=_uuid(row.get("suite_input_option_id"), "Suite input ID"),
        suite_input_option_hash=_hash_value(row.get("suite_input_option_hash")),
        execution=execution,
        frozen_at=_datetime(row.get("frozen_at")),
        status=_status(row),
        aggregate_version=_positive(row.get("aggregate_version"), "aggregate version"),
        retired_at=_optional_datetime(row.get("retired_at")),
        retired_by=_optional_text(row.get("retired_by")),
        retirement_reason=_optional_text(row.get("retirement_reason")),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresProviderSamplingExecutionInputError(
            "Provider execution input row is invalid"
        )
    return value


def _uuid(value: object, label: str) -> UUID:
    try:
        result = UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresProviderSamplingExecutionInputError(
            f"Provider execution input {label} is invalid"
        ) from error
    if result.int == 0:
        raise PostgresProviderSamplingExecutionInputError(
            f"Provider execution input {label} is invalid"
        )
    return result


def _hash_value(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        item not in "0123456789abcdef" for item in value
    ):
        raise PostgresProviderSamplingExecutionInputError(
            "Provider execution input hash is invalid"
        )
    return value


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PostgresProviderSamplingExecutionInputError(
            "Provider execution input timestamp is invalid"
        )
    return value


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _datetime(value)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PostgresProviderSamplingExecutionInputError(
            "Provider execution input lifecycle value is invalid"
        )
    return value


def _status(row: Mapping[str, object]) -> str:
    status = row.get("status")
    retired_at = _optional_datetime(row.get("retired_at"))
    retired_by = _optional_text(row.get("retired_by"))
    reason = _optional_text(row.get("retirement_reason"))
    if status == "approved" and retired_at is retired_by is reason is None:
        return "approved"
    if (
        status == "retired"
        and retired_at is not None
        and retired_by
        and reason in _RETIRED_REASON_CODES
    ):
        return "retired"
    raise PostgresProviderSamplingExecutionInputError(
        "Provider execution input lifecycle is corrupt"
    )


def _positive(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PostgresProviderSamplingExecutionInputError(
            f"Provider execution input {label} is invalid"
        )
    return value


def _actor(value: str) -> str:
    return _bounded(value, "actor", maximum=200)


def _reason(value: str) -> str:
    result = _bounded(value, "retirement reason", maximum=64)
    if result not in _RETIRED_REASON_CODES:
        raise PostgresProviderSamplingExecutionInputError(
            "Provider execution input retirement reason is invalid"
        )
    return result


def _bounded(value: str, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise PostgresProviderSamplingExecutionInputError(
            f"Provider execution input {label} is invalid"
        )
    result = value.strip()
    if not result or len(result) > maximum:
        raise PostgresProviderSamplingExecutionInputError(
            f"Provider execution input {label} is invalid"
        )
    return result


def _required(value: str, label: str) -> str:
    result = value.strip()
    if not result:
        raise PostgresProviderSamplingExecutionInputError(f"{label} is required")
    return result


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "PersistentProviderSamplingExecutionInput",
    "ProviderSamplingExecutionInputRetirement",
    "PostgresProviderSamplingExecutionInputError",
    "PostgresProviderSamplingExecutionInputRepository",
]
