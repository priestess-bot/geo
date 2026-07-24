"""Fenced deletion worker for orphaned and retention-expired Provider artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from geo_core.model_gateway.artifact_lifecycle import (
    ProviderArtifactDeletionLease,
    ProviderArtifactDeletionReceipt,
    ProviderArtifactLifecycleRepository,
)
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.model_gateway.provider_adapters.artifacts import (
    ProviderArtifactObjectStore,
)


@dataclass(frozen=True)
class ProviderArtifactDeletionRun:
    unstaged_key_destroyed_count: int
    expiry_staged_count: int
    claimed_count: int
    completed_count: int
    failed_count: int


class ProviderArtifactDeletionService:
    def __init__(
        self,
        *,
        repository: ProviderArtifactLifecycleRepository,
        object_store: ProviderArtifactObjectStore,
        worker_id: str,
        staged_grace_seconds: int = 3600,
        lease_seconds: int = 300,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("Provider artifact deletion worker ID is required")
        self._repository = repository
        self._store = object_store
        self._worker_id = worker_id
        self._staged_grace_seconds = staged_grace_seconds
        self._lease_seconds = lease_seconds

    def run_once(self, *, now: datetime, limit: int = 25) -> ProviderArtifactDeletionRun:
        unstaged = self._repository.destroy_unstaged_keys(
            now=now,
            grace_seconds=self._staged_grace_seconds,
        )
        staged = self._repository.enqueue_expired(
            now=now,
            staged_grace_seconds=self._staged_grace_seconds,
        )
        leases = self._repository.claim_deletions(
            worker_id=self._worker_id,
            now=now,
            lease_seconds=self._lease_seconds,
            limit=limit,
        )
        completed = 0
        failed = 0
        for lease in leases:
            try:
                self._delete(lease, now=now)
            except Exception:
                failed += 1
                self._repository.fail_deletion(
                    lease,
                    now=now,
                    error_code="object_store_delete_failed",
                )
            else:
                completed += 1
        return ProviderArtifactDeletionRun(
            unstaged, staged, len(leases), completed, failed
        )

    def _delete(self, lease: ProviderArtifactDeletionLease, *, now: datetime) -> None:
        deleted: list[dict[str, str]] = []
        for artifact in lease.artifacts:
            self._store.delete_s3_uri(uri=artifact.manifest_uri)
            self._store.delete_s3_uri(uri=artifact.payload_uri)
            deleted.append(
                {
                    "artifact_id": str(artifact.artifact_id),
                    "kind": artifact.kind.value,
                    "manifest_hash": artifact.manifest_hash,
                    "payload_hash": artifact.payload_hash,
                }
            )
        receipt = ProviderArtifactDeletionReceipt(
            lease=lease,
            deletion_receipt_hash=canonical_json_hash(
                {
                    "schema_version": 1,
                    "project_id": lease.project_id,
                    "bundle_id": lease.bundle_id,
                    "outbox_id": lease.outbox_id,
                    "reason": lease.reason,
                    "fencing_generation": lease.fencing_generation,
                    "deleted": deleted,
                }
            ),
            deleted_at=now,
        )
        self._repository.complete_deletion(receipt)


__all__ = ["ProviderArtifactDeletionRun", "ProviderArtifactDeletionService"]
