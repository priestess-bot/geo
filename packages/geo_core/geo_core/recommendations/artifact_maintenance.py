"""Idempotent crypto-erase maintenance for Recommendation Prompt artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from geo_core.recommendations.generation_artifacts import (
    RecommendationTaskArtifactDeletionTarget,
)


RECOMMENDATION_ARTIFACT_MAINTENANCE_JOB_KIND = "recommendation.artifact_maintenance"


class RecommendationArtifactDeletionPhase(StrEnum):
    DELETION_PENDING = "deletion_pending"
    CRYPTO_ERASED = "crypto_erased"


@dataclass(frozen=True)
class RecommendationArtifactDeletionLease:
    intent_id: UUID
    project_id: UUID
    parent_job_id: UUID
    child_job_id: UUID
    lease_token: UUID
    fencing_generation: int
    attempt_count: int
    phase: RecommendationArtifactDeletionPhase
    target: RecommendationTaskArtifactDeletionTarget

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", RecommendationArtifactDeletionPhase(self.phase))
        if min(
            self.intent_id.int,
            self.project_id.int,
            self.parent_job_id.int,
            self.child_job_id.int,
            self.lease_token.int,
        ) == 0:
            raise ValueError("Recommendation artifact deletion identities cannot be zero")
        if self.fencing_generation < 1 or self.attempt_count < 1:
            raise ValueError("Recommendation artifact deletion lease is invalid")


class RecommendationArtifactDeletionRepository(Protocol):
    def enqueue_due(self, *, project_id: UUID, now: datetime) -> None: ...

    def claim(
        self,
        *,
        project_id: UUID,
        worker_id: str,
        now: datetime,
        limit: int,
    ) -> tuple[RecommendationArtifactDeletionLease, ...]: ...

    def mark_crypto_erased(
        self,
        lease: RecommendationArtifactDeletionLease,
        *,
        receipt_hash: str,
        erased_at: datetime,
    ) -> RecommendationArtifactDeletionLease: ...

    def mark_deleted(
        self,
        lease: RecommendationArtifactDeletionLease,
        *,
        receipt_hash: str,
        deleted_at: datetime,
    ) -> None: ...

    def retry(
        self,
        lease: RecommendationArtifactDeletionLease,
        *,
        error_code: str,
        failed_at: datetime,
    ) -> None: ...


class RecommendationArtifactEraser(Protocol):
    def crypto_erase(self, target: RecommendationTaskArtifactDeletionTarget) -> str: ...

    def delete_ciphertext(
        self, target: RecommendationTaskArtifactDeletionTarget
    ) -> str: ...


@dataclass(frozen=True)
class RecommendationArtifactMaintenanceResult:
    claimed: int
    deleted: int
    retry_scheduled: int


class RecommendationArtifactMaintenance:
    def __init__(
        self,
        *,
        repository: RecommendationArtifactDeletionRepository,
        eraser: RecommendationArtifactEraser,
        clock,
    ) -> None:
        self._repository = repository
        self._eraser = eraser
        self._clock = clock

    def run_once(
        self,
        *,
        project_id: UUID,
        worker_id: str,
        limit: int = 50,
    ) -> RecommendationArtifactMaintenanceResult:
        if not worker_id.strip() or not 1 <= limit <= 1000:
            raise ValueError("Recommendation artifact maintenance worker/limit is invalid")
        now = self._clock()
        self._repository.enqueue_due(project_id=project_id, now=now)
        leases = self._repository.claim(
            project_id=project_id,
            worker_id=worker_id,
            now=now,
            limit=limit,
        )
        if any(lease.project_id != project_id for lease in leases):
            raise RuntimeError(
                "Recommendation artifact repository returned another Project's lease"
            )
        deleted = 0
        retry = 0
        for lease in leases:
            current = lease
            try:
                if current.phase is RecommendationArtifactDeletionPhase.DELETION_PENDING:
                    receipt = self._eraser.crypto_erase(current.target)
                    current = self._repository.mark_crypto_erased(
                        current,
                        receipt_hash=receipt,
                        erased_at=self._clock(),
                    )
                receipt = self._eraser.delete_ciphertext(current.target)
                self._repository.mark_deleted(
                    current,
                    receipt_hash=receipt,
                    deleted_at=self._clock(),
                )
                deleted += 1
            except Exception as error:
                self._repository.retry(
                    current,
                    error_code=type(error).__name__,
                    failed_at=self._clock(),
                )
                retry += 1
        return RecommendationArtifactMaintenanceResult(len(leases), deleted, retry)


__all__ = [
    "RECOMMENDATION_ARTIFACT_MAINTENANCE_JOB_KIND",
    "RecommendationArtifactDeletionLease",
    "RecommendationArtifactDeletionPhase",
    "RecommendationArtifactDeletionRepository",
    "RecommendationArtifactMaintenance",
    "RecommendationArtifactMaintenanceResult",
    "RecommendationArtifactEraser",
]
