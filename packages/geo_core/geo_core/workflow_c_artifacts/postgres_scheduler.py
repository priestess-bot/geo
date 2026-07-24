"""PostgreSQL seed adapter for idle Workflow C artifact retention work."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from geo_core.sampling.contracts import SamplingRuleViolation
from geo_core.workflow_c_artifacts.scheduler import WorkflowCArtifactMaintenanceSchedule


class PostgresWorkflowCArtifactMaintenanceSchedulerRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def seed_due(
        self,
        *,
        now: datetime,
        staged_grace_seconds: int,
        max_projects: int,
    ) -> tuple[WorkflowCArtifactMaintenanceSchedule, ...]:
        _require_aware(now)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT *
                         FROM geo_seed_workflow_c_artifact_maintenance(%s, %s, %s)""",
                    (now, staged_grace_seconds, max_projects),
                ).fetchall()
        except psycopg.Error as exc:
            raise SamplingRuleViolation(
                "Workflow C artifact maintenance seed failed"
            ) from exc
        return tuple(_schedule(row) for row in rows)


def _schedule(row: Mapping[str, Any]) -> WorkflowCArtifactMaintenanceSchedule:
    try:
        return WorkflowCArtifactMaintenanceSchedule(
            project_id=UUID(str(row["project_id"])),
            job_id=UUID(str(row["job_id"])),
            outbox_id=UUID(str(row["outbox_id"])),
            inserted=bool(row["inserted"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SamplingRuleViolation(
            "Workflow C artifact maintenance seed returned an invalid row"
        ) from exc


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SamplingRuleViolation(
            "Workflow C artifact maintenance seed time must be timezone-aware"
        )


__all__ = ["PostgresWorkflowCArtifactMaintenanceSchedulerRepository"]
