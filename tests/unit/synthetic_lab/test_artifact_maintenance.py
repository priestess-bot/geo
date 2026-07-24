from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from geo_core.synthetic_lab.artifact_maintenance import SyntheticArtifactMaintenanceService
from geo_core.synthetic_lab.artifact_maintenance_contracts import (
    SyntheticArtifactDeletionLease,
)
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactStorageTier
from geo_core.synthetic_lab.raw_artifact_storage import RawArtifactStores


NOW = datetime(2026, 7, 23, 12, tzinfo=UTC)


@dataclass
class _Store:
    events: list[str]
    fail_payload: bool = False

    def delete_s3_uri(self, *, uri: str) -> bool:
        self.events.append(f"delete:{uri.rsplit('/', 1)[-1]}")
        if self.fail_payload and uri.endswith("payload.bin"):
            raise RuntimeError("object delete failure")
        return True


class _Repository:
    def __init__(self, lease: SyntheticArtifactDeletionLease, timeline: list[str]) -> None:
        self.lease = lease
        self.events = timeline
        self.erased = False

    def stage_due_expirations(self, *, project_id, now, limit):
        assert project_id == self.lease.project_id
        assert now == NOW and limit == 100
        self.events.append("stage")
        return 1

    def claim_deletions(self, *, project_id, worker_id, now, batch_size, lease_seconds):
        assert project_id == self.lease.project_id and now == NOW
        assert worker_id == "synthetic-maintainer"
        assert batch_size == 100 and lease_seconds == 120
        self.events.append("claim")
        return (self.lease,)

    def crypto_erase_and_tombstone(self, lease, *, erased_at):
        assert lease == self.lease and erased_at == NOW
        self.events.append("crypto-erase")
        newly_erased = not self.erased
        self.erased = True
        return newly_erased

    def complete_object_deletion(self, lease, *, deleted_at):
        assert lease == self.lease and deleted_at == NOW and self.erased
        self.events.append("complete")

    def fail_object_deletion(self, lease, *, error_code, next_attempt_at):
        assert lease == self.lease and self.erased
        assert error_code == "runtimeerror"
        assert next_attempt_at > NOW
        self.events.append("retry")


def _lease() -> SyntheticArtifactDeletionLease:
    return SyntheticArtifactDeletionLease(
        outbox_id=uuid4(),
        project_id=uuid4(),
        artifact_id=uuid4(),
        artifact_generation=1,
        manifest_hash="a" * 64,
        payload_uri="s3://synthetic-raw/synthetic-raw/project/payload.bin",
        manifest_uri="s3://synthetic-raw/synthetic-raw/project/manifest.json",
        storage_tier=ArtifactStorageTier.RESTRICTED_INDEPENDENT_DEK,
        lease_token=uuid4(),
        deletion_fencing_generation=1,
    )


def _service(repository: _Repository, store: _Store) -> SyntheticArtifactMaintenanceService:
    return SyntheticArtifactMaintenanceService(
        repository=repository,
        stores=RawArtifactStores(
            encrypted_raw=store,
            restricted_independent_dek=store,
            derived_project=store,
        ),
        worker_id="synthetic-maintainer",
        clock=lambda: NOW,
    )


def test_crypto_erasure_and_tombstone_precede_each_remote_delete() -> None:
    lease = _lease()
    timeline: list[str] = []
    store = _Store(timeline)
    repository = _Repository(lease, timeline)

    result = _service(repository, store).run_once(project_id=lease.project_id)

    assert result.crypto_erased_count == 1
    assert result.completed_count == 1
    assert timeline == [
        "stage",
        "claim",
        "crypto-erase",
        "delete:manifest.json",
        "delete:payload.bin",
        "complete",
    ]


def test_remote_failure_is_retryable_after_irreversible_crypto_erasure() -> None:
    lease = _lease()
    timeline: list[str] = []
    store = _Store(timeline, fail_payload=True)
    repository = _Repository(lease, timeline)

    result = _service(repository, store).run_once(project_id=lease.project_id)

    assert result.crypto_erased_count == 1
    assert result.completed_count == 0
    assert result.retry_count == 1
    assert timeline == [
        "stage",
        "claim",
        "crypto-erase",
        "delete:manifest.json",
        "delete:payload.bin",
        "retry",
    ]
