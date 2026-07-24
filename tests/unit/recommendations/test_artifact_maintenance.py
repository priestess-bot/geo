from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from geo_core.recommendations.artifact_maintenance import (
    RecommendationArtifactDeletionLease,
    RecommendationArtifactDeletionPhase,
    RecommendationArtifactMaintenance,
)
from geo_core.recommendations.generation_artifacts import (
    RecommendationTaskArtifactDeletionTarget,
    RecommendationTaskArtifactRef,
)


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


class _Repository:
    def __init__(self, lease: RecommendationArtifactDeletionLease) -> None:
        self.lease = lease
        self.erased: list[str] = []
        self.deleted: list[str] = []
        self.retries: list[tuple[RecommendationArtifactDeletionPhase, str]] = []

    def enqueue_due(self, *, project_id, now):
        assert project_id == self.lease.project_id
        assert now == NOW

    def claim(self, *, project_id, worker_id, now, limit):
        assert project_id == self.lease.project_id
        assert worker_id == "artifact-maintenance-1" and now == NOW and limit == 50
        return (self.lease,)

    def mark_crypto_erased(self, lease, *, receipt_hash, erased_at):
        assert lease.phase is RecommendationArtifactDeletionPhase.DELETION_PENDING
        assert erased_at == NOW and len(receipt_hash) == 64
        self.erased.append(receipt_hash)
        return replace(lease, phase=RecommendationArtifactDeletionPhase.CRYPTO_ERASED)

    def mark_deleted(self, lease, *, receipt_hash, deleted_at):
        assert lease.phase is RecommendationArtifactDeletionPhase.CRYPTO_ERASED
        assert deleted_at == NOW and len(receipt_hash) == 64
        self.deleted.append(receipt_hash)

    def retry(self, lease, *, error_code, failed_at):
        assert failed_at == NOW
        self.retries.append((lease.phase, error_code))


class _Eraser:
    def __init__(self, *, fail_ciphertext: bool = False) -> None:
        self.fail_ciphertext = fail_ciphertext
        self.events: list[str] = []

    def crypto_erase(self, target):
        assert target == _target()
        self.events.append("manifest")
        return "a" * 64

    def delete_ciphertext(self, target):
        assert target == _target()
        self.events.append("payload")
        if self.fail_ciphertext:
            raise RuntimeError("object store unavailable")
        return "b" * 64


def test_maintenance_crypto_erases_wrapped_key_before_deleting_ciphertext() -> None:
    repository = _Repository(_lease())
    eraser = _Eraser()
    maintenance = RecommendationArtifactMaintenance(
        repository=repository,
        eraser=eraser,
        clock=lambda: NOW,
    )

    result = maintenance.run_once(
        project_id=repository.lease.project_id,
        worker_id="artifact-maintenance-1",
    )

    assert (result.claimed, result.deleted, result.retry_scheduled) == (1, 1, 0)
    assert eraser.events == ["manifest", "payload"]
    assert repository.erased == ["a" * 64]
    assert repository.deleted == ["b" * 64]


def test_ciphertext_failure_retries_from_crypto_erased_tombstone() -> None:
    repository = _Repository(_lease())
    eraser = _Eraser(fail_ciphertext=True)
    maintenance = RecommendationArtifactMaintenance(
        repository=repository,
        eraser=eraser,
        clock=lambda: NOW,
    )

    result = maintenance.run_once(
        project_id=repository.lease.project_id,
        worker_id="artifact-maintenance-1",
    )

    assert (result.deleted, result.retry_scheduled) == (0, 1)
    assert repository.retries == [
        (RecommendationArtifactDeletionPhase.CRYPTO_ERASED, "RuntimeError")
    ]
    assert eraser.events == ["manifest", "payload"]


def _lease() -> RecommendationArtifactDeletionLease:
    return RecommendationArtifactDeletionLease(
        intent_id=uuid4(),
        project_id=uuid4(),
        parent_job_id=uuid4(),
        child_job_id=uuid4(),
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        phase=RecommendationArtifactDeletionPhase.DELETION_PENDING,
        target=_target(),
    )


def _target() -> RecommendationTaskArtifactDeletionTarget:
    return RecommendationTaskArtifactDeletionTarget(
        reference=RecommendationTaskArtifactRef(
            uri="s3://recommendation-artifacts/task/manifest.json",
            manifest_hash="a" * 64,
            payload_uri="s3://recommendation-artifacts/task/payload.bin",
            payload_hash="c" * 64,
            content_hash="b" * 64,
            byte_size=10,
        ),
        payload_uri="s3://recommendation-artifacts/task/payload.bin",
        payload_hash="c" * 64,
        expires_at=NOW - timedelta(minutes=1),
        tombstone_hash="d" * 64,
    )
