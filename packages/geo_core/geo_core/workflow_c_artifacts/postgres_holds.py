"""PostgreSQL two-person legal-hold command adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import SamplingRuleViolation
from geo_core.workflow_c_artifacts.holds import (
    WorkflowCArtifactHoldAction,
    WorkflowCArtifactHoldRequest,
    WorkflowCArtifactHoldStatus,
)


class PostgresWorkflowCArtifactHoldRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def request(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        request_id: UUID,
        action: WorkflowCArtifactHoldAction,
        actor_id: str,
        reason: str,
        requested_at: datetime,
        hold_until: datetime | None,
    ) -> WorkflowCArtifactHoldRequest:
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                row = connection.execute(
                    """SELECT * FROM geo_request_workflow_c_artifact_hold(
                           %s, %s, %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        project_id,
                        artifact_id,
                        request_id,
                        action.value,
                        actor_id,
                        reason,
                        requested_at,
                        hold_until,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise SamplingRuleViolation(
                "Workflow C artifact hold request was rejected"
            ) from exc
        return _request(row)

    def decide(
        self,
        *,
        project_id: UUID,
        request_id: UUID,
        expected_version: int,
        actor_id: str,
        approved: bool,
        reason: str,
        decided_at: datetime,
    ) -> WorkflowCArtifactHoldRequest:
        try:
            with self._connect() as connection:
                set_project_scope(connection, project_id)
                row = connection.execute(
                    """SELECT * FROM geo_decide_workflow_c_artifact_hold(
                           %s, %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        project_id,
                        request_id,
                        expected_version,
                        actor_id,
                        approved,
                        reason,
                        decided_at,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise SamplingRuleViolation(
                "Workflow C artifact hold decision was rejected"
            ) from exc
        return _request(row)


def _request(row: Mapping[str, Any] | None) -> WorkflowCArtifactHoldRequest:
    if row is None:
        raise SamplingRuleViolation("Workflow C artifact hold command returned no result")
    return WorkflowCArtifactHoldRequest(
        id=row["id"],
        project_id=row["project_id"],
        artifact_id=row["artifact_id"],
        action=WorkflowCArtifactHoldAction(str(row["action"])),
        status=WorkflowCArtifactHoldStatus(str(row["status"])),
        requested_by=str(row["requested_by"]),
        requested_at=row["requested_at"],
        request_reason=str(row["request_reason"]),
        hold_until=row["hold_until"],
        decided_by=(str(row["decided_by"]) if row["decided_by"] is not None else None),
        decided_at=row["decided_at"],
        decision_reason=(
            str(row["decision_reason"])
            if row["decision_reason"] is not None
            else None
        ),
        aggregate_version=int(row["aggregate_version"]),
    )


__all__ = ["PostgresWorkflowCArtifactHoldRepository"]
