"""PostgreSQL repository and stable facade for statistical protocols."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.project_scope import set_project_scope
from geo_core.statistical_methods.contracts import canonical_hash
from geo_core.workflow_c_statistical_protocol_models import (
    ComparisonPlanDefinition,
    DriftProtocolDefinition,
    STATISTICAL_PROTOCOL_NAMESPACE as STATISTICAL_PROTOCOL_NAMESPACE,
    StatisticalProtocolDefinition,
    StatisticalProtocolKind,
    StatisticalProtocolNotFound,
    StatisticalProtocolStatus,
    StatisticalProtocolVersion,
    new_statistical_protocol,
    parse_statistical_protocol_definition,
    transition_statistical_protocol,
)
from geo_core.workflow_c_statistical_protocol_values import (
    StatisticalProtocolError,
    datetime_value as _datetime,
    idempotency_hash as _idempotency_hash,
    integer_value as _integer,
    mapping_value as _mapping,
    optional_datetime as _optional_datetime,
    optional_text as _optional_text,
    optional_uuid as _optional_uuid,
    row_text as _text_value,
    text_value as _text,
    uuid_value as _uuid,
)


class PostgresWorkflowCStatisticalProtocolRepository:
    """Persist statistical protocol lifecycle only through scoped RPCs."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock

    def create(
        self, protocol: StatisticalProtocolVersion, *, idempotency_key: str
    ) -> StatisticalProtocolVersion:
        input_hash = canonical_hash(
            {
                "operation": "create",
                "protocol_id": str(protocol.id),
                "kind": protocol.kind.value,
                "definition_hash": protocol.definition_hash,
                "created_by": protocol.created_by,
            }
        )
        return self._call(
            project_id=protocol.project_id,
            statement="""SELECT * FROM geo_create_workflow_c_statistical_protocol(
                           %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                           %s, %s, %s, %s
                       )""",
            parameters=(
                protocol.project_id,
                protocol.id,
                protocol.kind.value,
                protocol.series_id,
                protocol.version,
                protocol.supersedes_protocol_id,
                protocol.definition_hash,
                Jsonb(protocol.definition.canonical_value()),
                protocol.created_by,
                _idempotency_hash(idempotency_key),
                input_hash,
                protocol.created_at,
            ),
        )

    def transition(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        expected_aggregate_version: int,
        target_status: StatisticalProtocolStatus,
        actor_id: str,
        idempotency_key: str,
        reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> StatisticalProtocolVersion:
        if target_status not in {
            StatisticalProtocolStatus.IN_REVIEW,
            StatisticalProtocolStatus.APPROVED,
            StatisticalProtocolStatus.RETIRED,
        }:
            raise StatisticalProtocolError("statistical transition target is invalid")
        actor = _text(actor_id, "actor")
        normalized_reason = None if reason is None else _text(reason, "reason")
        input_hash = canonical_hash(
            {
                "operation": target_status.value,
                "protocol_id": str(protocol_id),
                "expected_aggregate_version": expected_aggregate_version,
                "actor_id": actor,
                "reason": normalized_reason,
            }
        )
        return self._call(
            project_id=project_id,
            statement="""SELECT * FROM geo_transition_workflow_c_statistical_protocol(
                           %s, %s, %s, %s, %s, %s, %s, %s, %s
                       )""",
            parameters=(
                project_id,
                protocol_id,
                expected_aggregate_version,
                target_status.value,
                actor,
                normalized_reason,
                _idempotency_hash(idempotency_key),
                input_hash,
                occurred_at or self._clock(),
            ),
        )

    def get(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> StatisticalProtocolVersion:
        rows = self._read(
            project_id=project_id,
            statement="""SELECT * FROM workflow_c_statistical_protocol_versions
                          WHERE project_id = %s AND id = %s""",
            parameters=(project_id, protocol_id),
        )
        if not rows:
            raise StatisticalProtocolNotFound("statistical protocol does not exist")
        return _protocol(rows[0])

    def list(
        self,
        *,
        project_id: UUID,
        kind: StatisticalProtocolKind | None = None,
    ) -> tuple[StatisticalProtocolVersion, ...]:
        if kind is None:
            statement = """SELECT * FROM workflow_c_statistical_protocol_versions
                           WHERE project_id = %s ORDER BY created_at DESC, id DESC"""
            parameters: tuple[object, ...] = (project_id,)
        else:
            statement = """SELECT * FROM workflow_c_statistical_protocol_versions
                           WHERE project_id = %s AND protocol_kind = %s
                           ORDER BY created_at DESC, id DESC"""
            parameters = (project_id, StatisticalProtocolKind(kind).value)
        return tuple(
            _protocol(row)
            for row in self._read(
                project_id=project_id,
                statement=statement,
                parameters=parameters,
            )
        )

    def _call(
        self,
        *,
        project_id: UUID,
        statement: str,
        parameters: tuple[object, ...],
    ) -> StatisticalProtocolVersion:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(statement, parameters).fetchone()
            if row is None:
                raise StatisticalProtocolError("statistical command returned no aggregate")
            result = _protocol(_mapping(row))
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _read(
        self,
        *,
        project_id: UUID,
        statement: str,
        parameters: tuple[object, ...],
    ) -> tuple[Mapping[str, object], ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(statement, parameters).fetchall()
            connection.rollback()
            return tuple(_mapping(row) for row in rows)
        except psycopg.Error as error:
            connection.rollback()
            raise StatisticalProtocolError("statistical protocols could not be read") from error
        finally:
            connection.close()


def _protocol(row: Mapping[str, object]) -> StatisticalProtocolVersion:
    definition = parse_statistical_protocol_definition(_mapping(row.get("definition")))
    if definition.definition_hash != _text_value(row, "definition_hash"):
        raise StatisticalProtocolError("statistical protocol hash is corrupt")
    return StatisticalProtocolVersion(
        id=_uuid(row, "id"),
        project_id=_uuid(row, "project_id"),
        series_id=_uuid(row, "series_id"),
        version=_integer(row, "version"),
        supersedes_protocol_id=_optional_uuid(row, "supersedes_protocol_id"),
        status=StatisticalProtocolStatus(_text_value(row, "status")),
        definition=definition,
        created_by=_text_value(row, "created_by"),
        created_at=_datetime(row, "created_at"),
        updated_at=_datetime(row, "updated_at"),
        aggregate_version=_integer(row, "aggregate_version"),
        submitted_by=_optional_text(row, "submitted_by"),
        submitted_at=_optional_datetime(row, "submitted_at"),
        approved_by=_optional_text(row, "approved_by"),
        approved_at=_optional_datetime(row, "approved_at"),
        retired_by=_optional_text(row, "retired_by"),
        retired_at=_optional_datetime(row, "retired_at"),
        decision_reason=_optional_text(row, "decision_reason"),
    )


__all__ = [
    "ComparisonPlanDefinition",
    "DriftProtocolDefinition",
    "PostgresWorkflowCStatisticalProtocolRepository",
    "StatisticalProtocolDefinition",
    "StatisticalProtocolError",
    "StatisticalProtocolKind",
    "StatisticalProtocolNotFound",
    "StatisticalProtocolStatus",
    "StatisticalProtocolVersion",
    "new_statistical_protocol",
    "parse_statistical_protocol_definition",
    "transition_statistical_protocol",
]
