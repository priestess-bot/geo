"""Retention worker service for Synthetic raw and derived artifacts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from geo_core.synthetic_lab.artifact_maintenance_contracts import (
    SyntheticArtifactMaintenanceRepository,
    SyntheticArtifactMaintenanceResult,
)
from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.raw_artifact_storage import RawArtifactStores


class SyntheticArtifactMaintenanceService:
    """Erase data keys and tombstone first; object deletion remains retryable."""

    def __init__(
        self,
        *,
        repository: SyntheticArtifactMaintenanceRepository,
        stores: RawArtifactStores,
        worker_id: str,
        expiry_batch_size: int = 100,
        deletion_lease_seconds: int = 120,
        max_deletions: int = 100,
        retry_delay_seconds: int = 60,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not worker_id.strip() or len(worker_id) > 240:
            raise SyntheticLabContractError("Synthetic artifact maintenance worker identity is invalid")
        if not 1 <= expiry_batch_size <= 1_000:
            raise SyntheticLabContractError("Synthetic artifact expiry batch is invalid")
        if not 5 <= deletion_lease_seconds <= 3_600:
            raise SyntheticLabContractError("Synthetic artifact deletion lease is invalid")
        if not 1 <= max_deletions <= 100:
            raise SyntheticLabContractError("Synthetic artifact deletion batch is invalid")
        if not 1 <= retry_delay_seconds <= 86_400:
            raise SyntheticLabContractError("Synthetic artifact retry delay is invalid")
        self._repository = repository
        self._stores = stores
        self._worker_id = worker_id
        self._expiry_batch_size = expiry_batch_size
        self._deletion_lease_seconds = deletion_lease_seconds
        self._max_deletions = max_deletions
        self._retry_delay = retry_delay_seconds
        self._clock = clock

    def run_once(self, *, project_id: UUID) -> SyntheticArtifactMaintenanceResult:
        if project_id.int == 0:
            raise SyntheticLabContractError("Synthetic artifact maintenance Project is invalid")
        cycle_started_at = self._now()
        staged = self._repository.stage_due_expirations(
            project_id=project_id,
            now=cycle_started_at,
            limit=self._expiry_batch_size,
        )
        leases = self._repository.claim_deletions(
            project_id=project_id,
            worker_id=self._worker_id,
            now=cycle_started_at,
            batch_size=self._max_deletions,
            lease_seconds=self._deletion_lease_seconds,
        )
        if len(leases) > self._max_deletions:
            raise SyntheticLabContractError("Synthetic artifact deletion claim exceeds its batch")
        if any(lease.project_id != project_id for lease in leases):
            raise SyntheticLabContractError(
                "Synthetic artifact maintenance claim crosses Project scope"
            )
        erased = completed = retried = 0
        for lease in leases:
            if self._repository.crypto_erase_and_tombstone(lease, erased_at=self._now()):
                erased += 1
            try:
                store = self._stores.for_tier(lease.storage_tier)
                # Delete both idempotently. A partial remote success is retried safely.
                store.delete_s3_uri(uri=lease.manifest_uri)
                store.delete_s3_uri(uri=lease.payload_uri)
            except BaseException as error:
                attempted_at = self._now()
                self._repository.fail_object_deletion(
                    lease,
                    error_code=_error_code(error),
                    next_attempt_at=attempted_at + timedelta(seconds=self._retry_delay),
                )
                retried += 1
                continue
            self._repository.complete_object_deletion(lease, deleted_at=self._now())
            completed += 1
        return SyntheticArtifactMaintenanceResult(
            staged_expiry_count=staged,
            claimed_count=len(leases),
            crypto_erased_count=erased,
            completed_count=completed,
            retry_count=retried,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise SyntheticLabContractError(
                "Synthetic artifact maintenance clock must be timezone-aware"
            )
        return value


def _error_code(error: BaseException) -> str:
    name = type(error).__name__
    normalized = "".join(
        character.lower() if character.isalnum() else "_" for character in name
    ).strip("_")
    return (normalized or "object_delete_failed")[:63]


__all__ = ["SyntheticArtifactMaintenanceService"]
