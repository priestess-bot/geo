"""Broker routing identity for Recommendation artifact expiry maintenance."""

from __future__ import annotations

from geo_core.recommendations.artifact_maintenance import (
    RECOMMENDATION_ARTIFACT_MAINTENANCE_JOB_KIND,
)


RECOMMENDATION_ARTIFACT_MAINTENANCE_QUEUE = "recommendation-artifact-maintenance"
RECOMMENDATION_ARTIFACT_MAINTENANCE_ACTOR = (
    "process_recommendation_artifact_maintenance_job"
)
RECOMMENDATION_ARTIFACT_MAINTENANCE_OUTBOX_TOPICS = frozenset(
    {RECOMMENDATION_ARTIFACT_MAINTENANCE_JOB_KIND}
)


__all__ = [
    "RECOMMENDATION_ARTIFACT_MAINTENANCE_ACTOR",
    "RECOMMENDATION_ARTIFACT_MAINTENANCE_JOB_KIND",
    "RECOMMENDATION_ARTIFACT_MAINTENANCE_OUTBOX_TOPICS",
    "RECOMMENDATION_ARTIFACT_MAINTENANCE_QUEUE",
]
