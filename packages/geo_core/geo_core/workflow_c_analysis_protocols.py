"""Project-scoped PostgreSQL repository for Workflow C Metric Protocols."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hashlib
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.project_scope import set_project_scope
from geo_core.workflow_c_analysis_admission import (
    MetricProtocolStatus,
    MetricProtocolVersion,
    WorkflowCAnalysisAdmissionError,
    command_input_hash,
    metric_protocol_definition,
)


class WorkflowCMetricProtocolNotFound(LookupError):
    """A Metric Protocol is absent from the caller's Project scope."""


class PostgresWorkflowCMetricProtocolError(WorkflowCAnalysisAdmissionError):
    """PostgreSQL rejected or returned a corrupt Metric Protocol."""


class PostgresWorkflowCMetricProtocolRepository:
    """Persist Metric Protocol lifecycle commands through controlled SQL RPCs."""

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
        protocol: MetricProtocolVersion,
        *,
        idempotency_key: str,
    ) -> MetricProtocolVersion:
        if protocol.status is not MetricProtocolStatus.DRAFT:
            raise PostgresWorkflowCMetricProtocolError(
                "only a draft Metric Protocol can be created"
            )
        input_hash = command_input_hash(
            {
                "operation": "create",
                "protocol_id": str(protocol.id),
                "series_id": str(protocol.series_id),
                "version": protocol.version,
                "supersedes_protocol_id": (
                    str(protocol.supersedes_protocol_id)
                    if protocol.supersedes_protocol_id
                    else None
                ),
                "protocol_hash": protocol.protocol_hash,
                "created_by": protocol.created_by,
            }
        )
        return self._call(
            project_id=protocol.project_id,
            statement="""SELECT * FROM geo_create_workflow_c_metric_protocol(
                           %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s
                       )""",
            parameters=(
                protocol.project_id,
                protocol.id,
                protocol.series_id,
                protocol.version,
                protocol.supersedes_protocol_id,
                protocol.protocol_hash,
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
        target_status: MetricProtocolStatus,
        actor_id: str,
        idempotency_key: str,
        reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> MetricProtocolVersion:
        if target_status not in {
            MetricProtocolStatus.IN_REVIEW,
            MetricProtocolStatus.APPROVED,
            MetricProtocolStatus.RETIRED,
        }:
            raise PostgresWorkflowCMetricProtocolError(
                "Metric Protocol transition target is invalid"
            )
        actor = _nonempty(actor_id, "actor id")
        normalized_reason = None if reason is None else _nonempty(reason, "decision reason")
        input_hash = command_input_hash(
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
            statement="""SELECT * FROM geo_transition_workflow_c_metric_protocol(
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

    def get(self, *, project_id: UUID, protocol_id: UUID) -> MetricProtocolVersion:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT * FROM workflow_c_metric_protocol_versions
                   WHERE project_id = %s AND id = %s""",
                (project_id, protocol_id),
            ).fetchone()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresWorkflowCMetricProtocolError(
                "Metric Protocol could not be read"
            ) from error
        finally:
            connection.close()
        if row is None:
            raise WorkflowCMetricProtocolNotFound("Metric Protocol does not exist")
        return _protocol(_mapping(row))

    def list(
        self,
        *,
        project_id: UUID,
        status: MetricProtocolStatus | None = None,
    ) -> tuple[MetricProtocolVersion, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            if status is None:
                rows = connection.execute(
                    """SELECT * FROM workflow_c_metric_protocol_versions
                       WHERE project_id = %s
                       ORDER BY created_at DESC, id DESC""",
                    (project_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM workflow_c_metric_protocol_versions
                       WHERE project_id = %s AND status = %s
                       ORDER BY created_at DESC, id DESC""",
                    (project_id, MetricProtocolStatus(status).value),
                ).fetchall()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresWorkflowCMetricProtocolError(
                "Metric Protocols could not be listed"
            ) from error
        finally:
            connection.close()
        return tuple(_protocol(_mapping(row)) for row in rows)

    def _call(
        self,
        *,
        project_id: UUID,
        statement: str,
        parameters: tuple[object, ...],
    ) -> MetricProtocolVersion:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(statement, parameters).fetchone()
            if row is None:
                raise PostgresWorkflowCMetricProtocolError(
                    "Metric Protocol command returned no aggregate"
                )
            protocol = _protocol(_mapping(row))
            connection.commit()
            return protocol
        except PostgresWorkflowCMetricProtocolError:
            connection.rollback()
            raise
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresWorkflowCMetricProtocolError(
                "PostgreSQL rejected the Metric Protocol command"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _protocol(row: Mapping[str, object]) -> MetricProtocolVersion:
    definition = metric_protocol_definition(_mapping(row.get("definition")))
    stored_hash = _text(row, "protocol_hash")
    if definition.protocol_hash != stored_hash:
        raise PostgresWorkflowCMetricProtocolError("Metric Protocol hash is corrupt")
    try:
        return MetricProtocolVersion(
            id=_uuid(row, "id"),
            project_id=_uuid(row, "project_id"),
            series_id=_uuid(row, "series_id"),
            version=_integer(row, "version"),
            supersedes_protocol_id=_optional_uuid(row, "supersedes_protocol_id"),
            status=MetricProtocolStatus(_text(row, "status")),
            definition=definition,
            created_by=_text(row, "created_by"),
            submitted_by=_optional_text(row, "submitted_by"),
            submitted_at=_optional_datetime(row, "submitted_at"),
            approved_by=_optional_text(row, "approved_by"),
            approved_at=_optional_datetime(row, "approved_at"),
            retired_by=_optional_text(row, "retired_by"),
            retired_at=_optional_datetime(row, "retired_at"),
            decision_reason=_optional_text(row, "decision_reason"),
            aggregate_version=_integer(row, "aggregate_version"),
            created_at=_datetime(row, "created_at"),
            updated_at=_datetime(row, "updated_at"),
        )
    except (ValueError, WorkflowCAnalysisAdmissionError) as error:
        raise PostgresWorkflowCMetricProtocolError(
            "Metric Protocol lifecycle row is corrupt"
        ) from error


def _idempotency_hash(value: str) -> str:
    key = _nonempty(value, "Metric Protocol Idempotency-Key", maximum=200)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _nonempty(value: str, label: str, *, maximum: int = 2_000) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise PostgresWorkflowCMetricProtocolError(f"{label} is invalid")
    return normalized


def _mapping(value: object | None) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise PostgresWorkflowCMetricProtocolError("Metric Protocol row is malformed")


def _uuid(row: Mapping[str, object], field: str) -> UUID:
    value = row.get(field)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCMetricProtocolError(
            f"Metric Protocol {field} is malformed"
        ) from error


def _optional_uuid(row: Mapping[str, object], field: str) -> UUID | None:
    return None if row.get(field) is None else _uuid(row, field)


def _integer(row: Mapping[str, object], field: str) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresWorkflowCMetricProtocolError(f"Metric Protocol {field} is malformed")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCMetricProtocolError(
            f"Metric Protocol {field} is malformed"
        ) from error


def _datetime(row: Mapping[str, object], field: str) -> datetime:
    value = row.get(field)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PostgresWorkflowCMetricProtocolError(f"Metric Protocol {field} is malformed")
    return value


def _optional_datetime(row: Mapping[str, object], field: str) -> datetime | None:
    return None if row.get(field) is None else _datetime(row, field)


def _text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str):
        raise PostgresWorkflowCMetricProtocolError(f"Metric Protocol {field} is malformed")
    return _nonempty(value, field)


def _optional_text(row: Mapping[str, object], field: str) -> str | None:
    return None if row.get(field) is None else _text(row, field)


__all__ = [
    "PostgresWorkflowCMetricProtocolError",
    "PostgresWorkflowCMetricProtocolRepository",
    "WorkflowCMetricProtocolNotFound",
]
