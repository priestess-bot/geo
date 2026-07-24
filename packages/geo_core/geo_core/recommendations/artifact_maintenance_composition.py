"""Least-privilege composition for Recommendation artifact expiry deletion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from geo_core.recommendations.artifact_maintenance import (
    RecommendationArtifactMaintenance,
)
from geo_core.recommendations.generation_artifact_contracts import (
    RecommendationTaskArtifactDeletionTarget,
    RecommendationTaskObjectStore,
)
from geo_core.recommendations.generation_artifact_serialization import (
    deletion_receipt,
)
from geo_core.recommendations.postgres.artifact_maintenance import (
    PostgresRecommendationArtifactDeletionRepository,
)


class RecommendationArtifactObjectEraser:
    """Delete only the wrapped-key manifest first, then its ciphertext payload."""

    def __init__(self, object_store: RecommendationTaskObjectStore) -> None:
        self._objects = object_store

    def crypto_erase(self, target: RecommendationTaskArtifactDeletionTarget) -> str:
        if not self._objects.delete_s3_uri(uri=target.reference.uri):
            raise RuntimeError("Recommendation artifact manifest delete was rejected")
        return deletion_receipt(target, phase="crypto_erased")

    def delete_ciphertext(
        self, target: RecommendationTaskArtifactDeletionTarget
    ) -> str:
        if not self._objects.delete_s3_uri(uri=target.payload_uri):
            raise RuntimeError("Recommendation artifact ciphertext delete was rejected")
        return deletion_receipt(target, phase="deleted")


@dataclass(frozen=True)
class RecommendationArtifactMaintenanceComposition:
    service: RecommendationArtifactMaintenance


def build_recommendation_artifact_maintenance_composition(
    *,
    connection_factory: Callable[[], Any],
    object_store: RecommendationTaskObjectStore,
    deletion_lease_seconds: int = 120,
    retry_delay: timedelta = timedelta(seconds=60),
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RecommendationArtifactMaintenanceComposition:
    return RecommendationArtifactMaintenanceComposition(
        service=RecommendationArtifactMaintenance(
            repository=PostgresRecommendationArtifactDeletionRepository(
                connection_factory,
                lease_seconds=deletion_lease_seconds,
                retry_delay=retry_delay,
            ),
            eraser=RecommendationArtifactObjectEraser(object_store),
            clock=clock,
        )
    )


__all__ = [
    "RecommendationArtifactMaintenanceComposition",
    "RecommendationArtifactObjectEraser",
    "build_recommendation_artifact_maintenance_composition",
]
