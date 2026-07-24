"""Persistent project-scoped scheduling for Workflow C artifact retention."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from geo_core.sampling.contracts import SamplingRuleViolation


@dataclass(frozen=True)
class WorkflowCArtifactMaintenanceSchedule:
    project_id: UUID
    job_id: UUID
    outbox_id: UUID
    inserted: bool


@dataclass(frozen=True)
class WorkflowCArtifactMaintenanceSeedResult:
    scheduled_project_count: int
    inserted_job_count: int
    coalesced_job_count: int

    def __post_init__(self) -> None:
        if min(
            self.scheduled_project_count,
            self.inserted_job_count,
            self.coalesced_job_count,
        ) < 0:
            raise SamplingRuleViolation("Workflow C maintenance seed counts cannot be negative")
        if self.inserted_job_count + self.coalesced_job_count != self.scheduled_project_count:
            raise SamplingRuleViolation("Workflow C maintenance seed counts are inconsistent")


class WorkflowCArtifactMaintenanceSchedulerRepository(Protocol):
    def seed_due(
        self,
        *,
        now: datetime,
        staged_grace_seconds: int,
        max_projects: int,
    ) -> tuple[WorkflowCArtifactMaintenanceSchedule, ...]: ...


class WorkflowCArtifactMaintenanceScheduler:
    """Discover due Projects and atomically wake their Durable maintenance Job."""

    def __init__(
        self,
        *,
        repository: WorkflowCArtifactMaintenanceSchedulerRepository,
        staged_grace_seconds: int = 900,
        max_projects: int = 100,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 60 <= staged_grace_seconds <= 86_400:
            raise SamplingRuleViolation("Workflow C staged grace is out of bounds")
        if not 1 <= max_projects <= 1000:
            raise SamplingRuleViolation("Workflow C maintenance seed batch is out of bounds")
        self._repository = repository
        self._staged_grace_seconds = staged_grace_seconds
        self._max_projects = max_projects
        self._clock = clock

    def run_once(self) -> WorkflowCArtifactMaintenanceSeedResult:
        now = self._now()
        scheduled = self._repository.seed_due(
            now=now,
            staged_grace_seconds=self._staged_grace_seconds,
            max_projects=self._max_projects,
        )
        project_ids = {item.project_id for item in scheduled}
        job_ids = {item.job_id for item in scheduled}
        outbox_ids = {item.outbox_id for item in scheduled}
        if (
            len(project_ids) != len(scheduled)
            or len(job_ids) != len(scheduled)
            or len(outbox_ids) != len(scheduled)
        ):
            raise SamplingRuleViolation(
                "Workflow C maintenance seed did not return one durable wake per Project"
            )
        inserted = sum(1 for item in scheduled if item.inserted)
        return WorkflowCArtifactMaintenanceSeedResult(
            scheduled_project_count=len(scheduled),
            inserted_job_count=inserted,
            coalesced_job_count=len(scheduled) - inserted,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise SamplingRuleViolation(
                "Workflow C maintenance scheduler clock must be timezone-aware"
            )
        return value


__all__ = [
    "WorkflowCArtifactMaintenanceSchedule",
    "WorkflowCArtifactMaintenanceScheduler",
    "WorkflowCArtifactMaintenanceSchedulerRepository",
    "WorkflowCArtifactMaintenanceSeedResult",
]
