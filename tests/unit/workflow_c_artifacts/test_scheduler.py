from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from geo_core.sampling import SamplingRuleViolation
from geo_core.workflow_c_artifacts.scheduler import (
    WorkflowCArtifactMaintenanceSchedule,
    WorkflowCArtifactMaintenanceScheduler,
)


NOW = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)
PROJECT_ONE = UUID("cc200000-0000-0000-0000-000000000001")
PROJECT_TWO = UUID("cc200000-0000-0000-0000-000000000002")


def _schedule(project_id: UUID, *, inserted: bool) -> WorkflowCArtifactMaintenanceSchedule:
    suffix = "03" if project_id == PROJECT_ONE else "04"
    outbox_suffix = "05" if project_id == PROJECT_ONE else "06"
    return WorkflowCArtifactMaintenanceSchedule(
        project_id=project_id,
        job_id=UUID(f"cc200000-0000-0000-0000-0000000000{suffix}"),
        outbox_id=UUID(f"cc200000-0000-0000-0000-0000000000{outbox_suffix}"),
        inserted=inserted,
    )


class _Repository:
    def __init__(self, schedules: tuple[WorkflowCArtifactMaintenanceSchedule, ...]) -> None:
        self.schedules = schedules
        self.received: tuple[datetime, int, int] | None = None

    def seed_due(
        self, *, now: datetime, staged_grace_seconds: int, max_projects: int
    ) -> tuple[WorkflowCArtifactMaintenanceSchedule, ...]:
        self.received = (now, staged_grace_seconds, max_projects)
        return self.schedules


def test_seed_counts_inserted_and_coalesced_project_wakes() -> None:
    repository = _Repository(
        (_schedule(PROJECT_ONE, inserted=True), _schedule(PROJECT_TWO, inserted=False))
    )

    result = WorkflowCArtifactMaintenanceScheduler(
        repository=repository,
        staged_grace_seconds=900,
        max_projects=100,
        clock=lambda: NOW,
    ).run_once()

    assert repository.received == (NOW, 900, 100)
    assert result.scheduled_project_count == 2
    assert result.inserted_job_count == 1
    assert result.coalesced_job_count == 1


def test_seed_rejects_duplicate_project_wakes() -> None:
    repository = _Repository(
        (_schedule(PROJECT_ONE, inserted=True), _schedule(PROJECT_ONE, inserted=False))
    )

    with pytest.raises(SamplingRuleViolation, match="one durable wake per Project"):
        WorkflowCArtifactMaintenanceScheduler(
            repository=repository, clock=lambda: NOW
        ).run_once()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"staged_grace_seconds": 59}, "staged grace"),
        ({"max_projects": 0}, "seed batch"),
    ],
)
def test_scheduler_rejects_invalid_configuration(
    kwargs: dict[str, int], message: str
) -> None:
    with pytest.raises(SamplingRuleViolation, match=message):
        WorkflowCArtifactMaintenanceScheduler(repository=_Repository(()), **kwargs)


def test_scheduler_requires_timezone_aware_clock() -> None:
    with pytest.raises(SamplingRuleViolation, match="timezone-aware"):
        WorkflowCArtifactMaintenanceScheduler(
            repository=_Repository(()), clock=lambda: NOW.replace(tzinfo=None)
        ).run_once()
