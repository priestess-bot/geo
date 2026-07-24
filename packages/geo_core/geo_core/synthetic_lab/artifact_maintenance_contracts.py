"""Pure contracts for least-privilege Synthetic raw-artifact retention work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactStorageTier


SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND = "synthetic_lab.artifact_maintenance"
SYNTHETIC_ARTIFACT_MAINTENANCE_QUEUE = "synthetic-artifact-maintenance"
SYNTHETIC_ARTIFACT_MAINTENANCE_ACTOR = "process_synthetic_artifact_maintenance_job"
SYNTHETIC_ARTIFACT_MAINTENANCE_OUTBOX_TOPICS = frozenset(
    {SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND}
)


@dataclass(frozen=True, kw_only=True)
class SyntheticArtifactDeletionLease:
    """One object deletion lease, fenced independently from its Durable Job."""

    outbox_id: UUID
    project_id: UUID
    artifact_id: UUID
    artifact_generation: int
    manifest_hash: str
    payload_uri: str
    manifest_uri: str
    storage_tier: ArtifactStorageTier
    lease_token: UUID
    deletion_fencing_generation: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "storage_tier", ArtifactStorageTier(self.storage_tier))
        if self.artifact_generation < 1 or self.deletion_fencing_generation < 1:
            raise SyntheticLabContractError("Synthetic artifact deletion fence is invalid")
        if len(self.manifest_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.manifest_hash
        ):
            raise SyntheticLabContractError("Synthetic artifact deletion manifest hash is invalid")
        if self.storage_tier is ArtifactStorageTier.NONE:
            raise SyntheticLabContractError("Synthetic artifact deletion has no storage tier")
        for uri in (self.payload_uri, self.manifest_uri):
            if not uri.startswith("s3://"):
                raise SyntheticLabContractError("Synthetic artifact deletion object URI is invalid")


@dataclass(frozen=True, kw_only=True)
class SyntheticArtifactMaintenanceResult:
    staged_expiry_count: int
    claimed_count: int
    crypto_erased_count: int
    completed_count: int
    retry_count: int

    def __post_init__(self) -> None:
        if min(
            self.staged_expiry_count,
            self.claimed_count,
            self.crypto_erased_count,
            self.completed_count,
            self.retry_count,
        ) < 0:
            raise SyntheticLabContractError("Synthetic artifact maintenance counts are invalid")
        if self.crypto_erased_count > self.claimed_count:
            raise SyntheticLabContractError("Synthetic artifact crypto-erasure count exceeds claims")
        if self.completed_count + self.retry_count > self.claimed_count:
            raise SyntheticLabContractError("Synthetic artifact terminal maintenance count exceeds claims")


class SyntheticArtifactMaintenanceRepository(Protocol):
    def stage_due_expirations(
        self,
        *,
        project_id: UUID,
        now: datetime,
        limit: int,
    ) -> int: ...

    def claim_deletions(
        self,
        *,
        project_id: UUID,
        worker_id: str,
        now: datetime,
        batch_size: int,
        lease_seconds: int,
    ) -> tuple[SyntheticArtifactDeletionLease, ...]: ...

    def crypto_erase_and_tombstone(
        self,
        lease: SyntheticArtifactDeletionLease,
        *,
        erased_at: datetime,
    ) -> bool:
        """Fence irreversible DEK erasure before remote object deletion."""

    def complete_object_deletion(
        self,
        lease: SyntheticArtifactDeletionLease,
        *,
        deleted_at: datetime,
    ) -> None: ...

    def fail_object_deletion(
        self,
        lease: SyntheticArtifactDeletionLease,
        *,
        error_code: str,
        next_attempt_at: datetime,
    ) -> None: ...


__all__ = [
    "SYNTHETIC_ARTIFACT_MAINTENANCE_ACTOR",
    "SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_KIND",
    "SYNTHETIC_ARTIFACT_MAINTENANCE_OUTBOX_TOPICS",
    "SYNTHETIC_ARTIFACT_MAINTENANCE_QUEUE",
    "SyntheticArtifactDeletionLease",
    "SyntheticArtifactMaintenanceRepository",
    "SyntheticArtifactMaintenanceResult",
]
