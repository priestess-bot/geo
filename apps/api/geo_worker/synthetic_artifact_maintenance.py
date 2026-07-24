"""Durable Job operation for Synthetic raw-artifact retention maintenance."""

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
from geo_core.synthetic_lab.artifact_maintenance import SyntheticArtifactMaintenanceService
from geo_core.synthetic_lab.artifact_maintenance_contracts import (
    SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND,
)


class SyntheticArtifactMaintenanceOperation:
    """Complete the parent Job only after the fenced maintenance pass returns."""

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        service: SyntheticArtifactMaintenanceService,
        lease_for: timedelta,
    ) -> None:
        if lease_for < timedelta(seconds=30):
            raise ValueError("Synthetic artifact maintenance Job lease is too short")
        self._store = store
        self._service = service
        self._lease_for = lease_for

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        if lease.kind != SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND:
            raise ValueError("Synthetic artifact maintenance claimed an unsupported Job")
        try:
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                heartbeat.raise_if_stopped()
                self._store.heartbeat(lease, lease_for=self._lease_for)
                result = self._service.run_once(project_id=lease.project_id)
                heartbeat.raise_if_stopped()
            details = {
                "staged_expiry_count": result.staged_expiry_count,
                "claimed_count": result.claimed_count,
                "crypto_erased_count": result.crypto_erased_count,
                "completed_count": result.completed_count,
                "retry_count": result.retry_count,
            }
            with self._store.fenced_transaction(lease) as connection:
                self._store.complete_in_transaction(
                    connection,
                    lease,
                    result_ref=(
                        "synthetic-artifact-maintenance://"
                        f"{lease.job_id}/{lease.fencing_generation}"
                    ),
                    details=details,
                )
            return {"status": "succeeded", "job_id": str(lease.job_id), **details}
        except (JobCancellationRequested, LostJobLease):
            raise
        except Exception as error:
            self._store.heartbeat(lease, lease_for=self._lease_for)
            status = self._store.fail(
                lease,
                error_code="synthetic_artifact_maintenance_failed",
                details={"classification": type(error).__name__},
                retry_delay=timedelta(seconds=60),
            )
            return {"status": status, "job_id": str(lease.job_id)}


__all__ = ["SyntheticArtifactMaintenanceOperation"]
