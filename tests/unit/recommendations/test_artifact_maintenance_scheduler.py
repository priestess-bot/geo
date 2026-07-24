from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from geo_core.recommendations.artifact_maintenance_scheduler import (
    RecommendationArtifactMaintenanceSchedule,
    RecommendationArtifactMaintenanceScheduler,
)
from geo_core.recommendations.errors import RecommendationRuleViolation


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
PROJECT_ONE = UUID("ab100000-0000-0000-0000-000000000001")
PROJECT_TWO = UUID("ab100000-0000-0000-0000-000000000002")


def _schedule(
    project_id: UUID, *, inserted: bool
) -> RecommendationArtifactMaintenanceSchedule:
    suffix = "03" if project_id == PROJECT_ONE else "04"
    outbox_suffix = "05" if project_id == PROJECT_ONE else "06"
    return RecommendationArtifactMaintenanceSchedule(
        project_id=project_id,
        job_id=UUID(f"ab100000-0000-0000-0000-0000000000{suffix}"),
        outbox_id=UUID(f"ab100000-0000-0000-0000-0000000000{outbox_suffix}"),
        inserted=inserted,
    )


class _Repository:
    def __init__(
        self, schedules: tuple[RecommendationArtifactMaintenanceSchedule, ...]
    ) -> None:
        self.schedules = schedules
        self.received: datetime | None = None

    def schedule_due(
        self, *, now: datetime
    ) -> tuple[RecommendationArtifactMaintenanceSchedule, ...]:
        self.received = now
        return self.schedules


def test_scheduler_coalesces_one_wake_per_project() -> None:
    repository = _Repository(
        (_schedule(PROJECT_ONE, inserted=True), _schedule(PROJECT_TWO, inserted=False))
    )

    result = RecommendationArtifactMaintenanceScheduler(
        repository=repository, clock=lambda: NOW
    ).run_once()

    assert repository.received == NOW
    assert result.scheduled_project_count == 2
    assert result.inserted_job_count == 1
    assert result.coalesced_job_count == 1


def test_scheduler_rejects_duplicate_project_wakes() -> None:
    repository = _Repository(
        (_schedule(PROJECT_ONE, inserted=True), _schedule(PROJECT_ONE, inserted=False))
    )

    with pytest.raises(RecommendationRuleViolation, match="one durable wake per Project"):
        RecommendationArtifactMaintenanceScheduler(
            repository=repository, clock=lambda: NOW
        ).run_once()


def test_scheduler_rejects_naive_clock() -> None:
    with pytest.raises(RecommendationRuleViolation, match="timezone-aware"):
        RecommendationArtifactMaintenanceScheduler(
            repository=_Repository(()), clock=lambda: NOW.replace(tzinfo=None)
        ).run_once()
