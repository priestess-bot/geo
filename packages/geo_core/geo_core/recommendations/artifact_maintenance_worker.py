"""Dedicated Durable operation for Recommendation artifact retention."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.recommendations.artifact_maintenance import (
    RECOMMENDATION_ARTIFACT_MAINTENANCE_JOB_KIND,
    RecommendationArtifactMaintenance,
)


class RecommendationArtifactMaintenanceOperation:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        service: RecommendationArtifactMaintenance,
        worker_id: str,
        lease_for: timedelta,
        max_deletions: int = 100,
    ) -> None:
        if not worker_id.strip() or lease_for < timedelta(seconds=30):
            raise ValueError("Recommendation artifact maintainer identity or lease is invalid")
        if not 1 <= max_deletions <= 1000:
            raise ValueError("Recommendation artifact maintenance batch is invalid")
        self._store = store
        self._service = service
        self._worker_id = worker_id
        self._lease_for = lease_for
        self._max = max_deletions

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        if lease.kind != RECOMMENDATION_ARTIFACT_MAINTENANCE_JOB_KIND:
            raise ValueError("Recommendation artifact maintainer claimed an unsupported Job")
        try:
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                result = self._service.run_once(
                    project_id=lease.project_id,
                    worker_id=self._worker_id,
                    limit=self._max,
                )
                heartbeat.raise_if_stopped()
            details = {
                "claimed": result.claimed,
                "deleted": result.deleted,
                "retry_scheduled": result.retry_scheduled,
            }
            with self._store.fenced_transaction(lease) as connection:
                self._store.complete_in_transaction(
                    connection,
                    lease,
                    result_ref=(
                        "recommendation-artifact-maintenance://"
                        f"{lease.job_id}/{lease.fencing_generation}"
                    ),
                    details=details,
                )
            return {"status": "succeeded", "job_id": str(lease.job_id), **details}
        except (JobCancellationRequested, LostJobLease):
            raise
        except Exception as error:
            status = self._store.fail(
                lease,
                error_code="recommendation_artifact_maintenance_failed",
                details={"classification": type(error).__name__},
                retry_delay=timedelta(seconds=60),
            )
            return {"status": status, "job_id": str(lease.job_id)}


__all__ = ["RecommendationArtifactMaintenanceOperation"]
