"""PostgreSQL scheduler adapter for Recommendation artifact retention."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from geo_core.recommendations.artifact_maintenance_scheduler import (
    RecommendationArtifactMaintenanceSchedule,
)
from geo_core.recommendations.errors import RecommendationRuleViolation


class PostgresRecommendationArtifactMaintenanceSchedulerRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def schedule_due(
        self, *, now: datetime
    ) -> tuple[RecommendationArtifactMaintenanceSchedule, ...]:
        _require_aware(now)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM geo_schedule_recommendation_artifact_maintenance(%s)",
                    (now,),
                ).fetchall()
        except psycopg.Error as error:
            raise RecommendationRuleViolation(
                "Recommendation artifact maintenance schedule failed"
            ) from error
        return tuple(_schedule(row) for row in rows)


def _schedule(row: Mapping[str, Any]) -> RecommendationArtifactMaintenanceSchedule:
    try:
        inserted = row["inserted"]
        if not isinstance(inserted, bool):
            raise TypeError("inserted must be boolean")
        return RecommendationArtifactMaintenanceSchedule(
            project_id=UUID(str(row["project_id"])),
            job_id=UUID(str(row["job_id"])),
            outbox_id=UUID(str(row["outbox_id"])),
            inserted=inserted,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RecommendationRuleViolation(
            "Recommendation artifact maintenance schedule returned an invalid row"
        ) from error


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RecommendationRuleViolation(
            "Recommendation artifact maintenance schedule time must be timezone-aware"
        )


__all__ = ["PostgresRecommendationArtifactMaintenanceSchedulerRepository"]
