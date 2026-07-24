"""Project-scoped immutable read models for Workflow C analytical projections.

The analytical worker owns writes through fenced RPCs.  Internal API reads use
these projections only after setting the PostgreSQL project scope; they never
reconstruct a result from an HTTP command body or inspect worker-only Job specs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope


class WorkflowCAnalysisProjectionNotFound(RuntimeError):
    """A Project-scoped immutable analytical projection does not exist."""


class PostgresWorkflowCAnalysisReadError(RuntimeError):
    """Persisted analytical state cannot safely be rendered."""


@dataclass(frozen=True)
class StoredSemanticMetricSnapshot:
    project_id: UUID
    snapshot_hash: str
    input_set_hash: str
    suite_hash: str
    stratum_hash: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class StoredComparisonFamily:
    project_id: UUID
    family_hash: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class StoredDriftReport:
    project_id: UUID
    report_hash: str
    payload: Mapping[str, object]


class PostgresWorkflowCAnalysisReadRepository:
    """Load only fenced analytical projections under the active Project scope."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def get_semantic_snapshot(
        self, *, project_id: UUID, snapshot_hash: str
    ) -> StoredSemanticMetricSnapshot:
        row = self._one(
            project_id=project_id,
            query="""SELECT project_id, snapshot_hash, input_set_hash, metric_suite_hash,
                              source_stratum_hash, payload
                         FROM workflow_c_semantic_metric_snapshots
                        WHERE project_id = %s AND snapshot_hash = %s""",
            parameters=(project_id, snapshot_hash),
            label="semantic metric snapshot",
        )
        return _semantic_snapshot(row)

    def list_semantic_snapshots(
        self, *, project_id: UUID
    ) -> tuple[StoredSemanticMetricSnapshot, ...]:
        rows = self._many(
            project_id=project_id,
            query="""SELECT project_id, snapshot_hash, input_set_hash, metric_suite_hash,
                              source_stratum_hash, payload
                         FROM workflow_c_semantic_metric_snapshots
                        WHERE project_id = %s
                        ORDER BY computed_at DESC, snapshot_hash DESC""",
            parameters=(project_id,),
        )
        return tuple(_semantic_snapshot(row) for row in rows)

    def get_comparison_family(
        self, *, project_id: UUID, family_hash: str
    ) -> StoredComparisonFamily:
        row = self._one(
            project_id=project_id,
            query="""SELECT project_id, family_hash, payload
                         FROM workflow_c_comparison_families
                        WHERE project_id = %s AND family_hash = %s""",
            parameters=(project_id, family_hash),
            label="comparison family result",
        )
        return _comparison_family(row)

    def list_comparison_families(self, *, project_id: UUID) -> tuple[StoredComparisonFamily, ...]:
        rows = self._many(
            project_id=project_id,
            query="""SELECT project_id, family_hash, payload
                         FROM workflow_c_comparison_families
                        WHERE project_id = %s
                        ORDER BY computed_at DESC, family_hash DESC""",
            parameters=(project_id,),
        )
        return tuple(_comparison_family(row) for row in rows)

    def get_drift_report(self, *, project_id: UUID, report_hash: str) -> StoredDriftReport:
        row = self._one(
            project_id=project_id,
            query="""SELECT project_id, report_hash, payload
                         FROM workflow_c_drift_reports
                        WHERE project_id = %s AND report_hash = %s""",
            parameters=(project_id, report_hash),
            label="drift report",
        )
        return _drift_report(row)

    def list_drift_reports(self, *, project_id: UUID) -> tuple[StoredDriftReport, ...]:
        rows = self._many(
            project_id=project_id,
            query="""SELECT project_id, report_hash, payload
                         FROM workflow_c_drift_reports
                        WHERE project_id = %s
                        ORDER BY computed_at DESC, report_hash DESC""",
            parameters=(project_id,),
        )
        return tuple(_drift_report(row) for row in rows)

    def _one(
        self,
        *,
        project_id: UUID,
        query: str,
        parameters: tuple[object, ...],
        label: str,
    ) -> Mapping[str, object]:
        rows = self._many(project_id=project_id, query=query, parameters=parameters)
        if not rows:
            raise WorkflowCAnalysisProjectionNotFound(f"{label} does not exist")
        return rows[0]

    def _many(
        self,
        *,
        project_id: UUID,
        query: str,
        parameters: tuple[object, ...],
    ) -> tuple[Mapping[str, object], ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(query, parameters).fetchall()
            connection.rollback()
            return tuple(_row(row) for row in rows)
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresWorkflowCAnalysisReadError(
                "Workflow C analytical projections could not be read"
            ) from error
        finally:
            connection.close()


def _semantic_snapshot(row: Mapping[str, object]) -> StoredSemanticMetricSnapshot:
    return StoredSemanticMetricSnapshot(
        project_id=_uuid(row, "project_id"),
        snapshot_hash=_text(row, "snapshot_hash"),
        input_set_hash=_text(row, "input_set_hash"),
        suite_hash=_text(row, "metric_suite_hash"),
        stratum_hash=_text(row, "source_stratum_hash"),
        payload=_payload(row),
    )


def _comparison_family(row: Mapping[str, object]) -> StoredComparisonFamily:
    return StoredComparisonFamily(
        project_id=_uuid(row, "project_id"),
        family_hash=_text(row, "family_hash"),
        payload=_payload(row),
    )


def _drift_report(row: Mapping[str, object]) -> StoredDriftReport:
    return StoredDriftReport(
        project_id=_uuid(row, "project_id"),
        report_hash=_text(row, "report_hash"),
        payload=_payload(row),
    )


def _row(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresWorkflowCAnalysisReadError("analytical projection row is malformed")
    return MappingProxyType(dict(value))


def _payload(row: Mapping[str, object]) -> Mapping[str, object]:
    value = row.get("payload")
    if not isinstance(value, Mapping):
        raise PostgresWorkflowCAnalysisReadError("analytical projection payload is malformed")
    return MappingProxyType(dict(value))


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise PostgresWorkflowCAnalysisReadError(f"analytical projection {key} is malformed")
    return value


def _uuid(row: Mapping[str, object], key: str) -> UUID:
    value = row.get(key)
    if isinstance(value, UUID):
        return value
    raise PostgresWorkflowCAnalysisReadError(f"analytical projection {key} is malformed")


__all__ = [
    "PostgresWorkflowCAnalysisReadError",
    "PostgresWorkflowCAnalysisReadRepository",
    "StoredComparisonFamily",
    "StoredDriftReport",
    "StoredSemanticMetricSnapshot",
    "WorkflowCAnalysisProjectionNotFound",
]
