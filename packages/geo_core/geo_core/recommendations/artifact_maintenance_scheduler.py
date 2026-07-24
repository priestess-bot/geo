"""Project-scoped Durable Job scheduling for Recommendation artifact retention."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from geo_core.recommendations.errors import RecommendationRuleViolation


@dataclass(frozen=True)
class RecommendationArtifactMaintenanceSchedule:
    project_id: UUID
    job_id: UUID
    outbox_id: UUID
    inserted: bool

    def __post_init__(self) -> None:
        if min(self.project_id.int, self.job_id.int, self.outbox_id.int) == 0:
            raise RecommendationRuleViolation(
                "Recommendation artifact maintenance schedule identities cannot be zero"
            )


@dataclass(frozen=True)
class RecommendationArtifactMaintenanceSeedResult:
    scheduled_project_count: int
    inserted_job_count: int
    coalesced_job_count: int

    def __post_init__(self) -> None:
        values = (
            self.scheduled_project_count,
            self.inserted_job_count,
            self.coalesced_job_count,
        )
        if any(value < 0 for value in values):
            raise RecommendationRuleViolation(
                "Recommendation artifact maintenance seed counts cannot be negative"
            )
        if self.inserted_job_count + self.coalesced_job_count != self.scheduled_project_count:
            raise RecommendationRuleViolation(
                "Recommendation artifact maintenance seed counts are inconsistent"
            )


class RecommendationArtifactMaintenanceSchedulerRepository(Protocol):
    def schedule_due(
        self, *, now: datetime
    ) -> tuple[RecommendationArtifactMaintenanceSchedule, ...]: ...


class RecommendationArtifactMaintenanceScheduler:
    """Atomically stage due deletion intents and wake one Job per Project."""

    def __init__(
        self,
        *,
        repository: RecommendationArtifactMaintenanceSchedulerRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._clock = clock

    def run_once(self) -> RecommendationArtifactMaintenanceSeedResult:
        now = self._now()
        scheduled = self._repository.schedule_due(now=now)
        project_ids = {item.project_id for item in scheduled}
        job_ids = {item.job_id for item in scheduled}
        outbox_ids = {item.outbox_id for item in scheduled}
        if (
            len(project_ids) != len(scheduled)
            or len(job_ids) != len(scheduled)
            or len(outbox_ids) != len(scheduled)
        ):
            raise RecommendationRuleViolation(
                "Recommendation artifact maintenance must return one durable wake per Project"
            )
        inserted = sum(1 for item in scheduled if item.inserted)
        return RecommendationArtifactMaintenanceSeedResult(
            scheduled_project_count=len(scheduled),
            inserted_job_count=inserted,
            coalesced_job_count=len(scheduled) - inserted,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RecommendationRuleViolation(
                "Recommendation artifact maintenance scheduler clock must be timezone-aware"
            )
        return value


__all__ = [
    "RecommendationArtifactMaintenanceSchedule",
    "RecommendationArtifactMaintenanceScheduler",
    "RecommendationArtifactMaintenanceSchedulerRepository",
    "RecommendationArtifactMaintenanceSeedResult",
]
