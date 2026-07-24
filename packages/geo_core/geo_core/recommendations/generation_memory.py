"""Thread-safe in-memory Recommendation generation Job repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from threading import RLock
from uuid import UUID, uuid4

from geo_core.recommendations.generation_contracts import (
    GenerationJobOwnership,
    GenerationJobStatus,
    RecommendationGenerationConflict,
    RecommendationGenerationJob,
    RecommendationGenerationResult,
    RecommendationGenerationSpec,
)


class InMemoryRecommendationGenerationRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._jobs: dict[tuple[UUID, UUID], RecommendationGenerationJob] = {}
        self._idempotency: dict[tuple[UUID, str], UUID] = {}
        self._results: dict[tuple[UUID, UUID], RecommendationGenerationResult] = {}
        self._cancellations: dict[
            tuple[UUID, str], tuple[UUID, int | None, RecommendationGenerationJob]
        ] = {}

    def create_job(
        self,
        *,
        job_id: UUID,
        spec: RecommendationGenerationSpec,
        idempotency_key_hash: str,
    ) -> tuple[RecommendationGenerationJob, bool]:
        identity = (spec.project_id, idempotency_key_hash)
        with self._lock:
            existing_id = self._idempotency.get(identity)
            if existing_id is not None:
                existing = self._jobs[(spec.project_id, existing_id)]
                if existing.input_hash != spec.input_hash:
                    raise RecommendationGenerationConflict(
                        "generation Idempotency-Key owns another input hash"
                    )
                return existing, True
            job = RecommendationGenerationJob(
                id=job_id,
                spec=spec,
                input_hash=spec.input_hash,
                idempotency_key_hash=idempotency_key_hash,
            )
            self._jobs[(spec.project_id, job_id)] = job
            self._idempotency[identity] = job_id
            return job, False

    def claim_job(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> RecommendationGenerationJob:
        if not worker_id.strip() or lease_for <= timedelta(0):
            raise RecommendationGenerationConflict("worker and positive lease are required")
        with self._lock:
            job = self._get(project_id, job_id)
            claimable = job.status == GenerationJobStatus.QUEUED or (
                job.status == GenerationJobStatus.RUNNING
                and job.lease_expires_at is not None
                and job.lease_expires_at <= now
            )
            if not claimable:
                raise RecommendationGenerationConflict("generation Job is not claimable")
            if job.cancel_requested:
                cancelled = replace(
                    job,
                    status=GenerationJobStatus.CANCELLED,
                    version=job.version + 1,
                    lease_id=None,
                    lease_expires_at=None,
                )
                self._jobs[(project_id, job_id)] = cancelled
                return cancelled
            claimed = replace(
                job,
                status=GenerationJobStatus.RUNNING,
                version=job.version + 1,
                lease_id=uuid4(),
                lease_expires_at=now + lease_for,
                fencing_token=job.fencing_token + 1,
            )
            self._jobs[(project_id, job_id)] = claimed
            return claimed

    def get_job(
        self, *, project_id: UUID, job_id: UUID
    ) -> RecommendationGenerationJob:
        with self._lock:
            return self._get(project_id, job_id)

    def request_cancel(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        expected_version: int | None = None,
        idempotency_key_hash: str | None = None,
    ) -> RecommendationGenerationJob:
        with self._lock:
            command_key = (
                (project_id, idempotency_key_hash)
                if idempotency_key_hash is not None
                else None
            )
            if command_key is not None and command_key in self._cancellations:
                existing_job_id, existing_version, existing_result = self._cancellations[
                    command_key
                ]
                if existing_job_id != job_id or existing_version != expected_version:
                    raise RecommendationGenerationConflict(
                        "generation cancellation Idempotency-Key owns another request"
                    )
                return existing_result
            job = self._get(project_id, job_id)
            if expected_version is not None and job.version != expected_version:
                raise RecommendationGenerationConflict(
                    "generation cancellation version changed"
                )
            if job.status == GenerationJobStatus.QUEUED:
                updated = replace(
                    job,
                    status=GenerationJobStatus.CANCELLED,
                    version=job.version + 1,
                    cancel_requested=True,
                )
            elif job.status == GenerationJobStatus.RUNNING:
                updated = replace(job, version=job.version + 1, cancel_requested=True)
            else:
                updated = job
            self._jobs[(project_id, job_id)] = updated
            if command_key is not None:
                self._cancellations[command_key] = (job_id, expected_version, updated)
            return updated

    def require_owned(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
        now: datetime,
    ) -> RecommendationGenerationJob:
        with self._lock:
            return self._owned(project_id, job_id, ownership, now)

    def reserve_model_call(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
        now: datetime,
    ) -> RecommendationGenerationJob:
        with self._lock:
            job = self._owned(project_id, job_id, ownership, now)
            if job.cancel_requested:
                raise RecommendationGenerationConflict("cancelled Job cannot reserve a model call")
            if job.consumed_model_calls >= job.spec.maximum_model_calls:
                raise RecommendationGenerationConflict("generation model call budget exhausted")
            updated = replace(
                job,
                version=job.version + 1,
                consumed_model_calls=job.consumed_model_calls + 1,
            )
            self._jobs[(project_id, job_id)] = updated
            return updated

    def finish_job(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
        now: datetime,
        status: GenerationJobStatus,
        expected_input_hash: str,
        result: RecommendationGenerationResult | None,
        error_code: str | None,
    ) -> RecommendationGenerationJob:
        terminal = {
            GenerationJobStatus.SUCCEEDED,
            GenerationJobStatus.FAILED,
            GenerationJobStatus.CANCELLED,
            GenerationJobStatus.REJECTED_STALE_INPUT,
        }
        if status not in terminal:
            raise RecommendationGenerationConflict("generation finish status is not terminal")
        with self._lock:
            job = self._owned(project_id, job_id, ownership, now)
            if job.input_hash != expected_input_hash:
                raise RecommendationGenerationConflict("generation terminal input hash changed")
            if job.cancel_requested and status != GenerationJobStatus.CANCELLED:
                raise RecommendationGenerationConflict("cancelled Job rejects non-cancel terminal")
            if status == GenerationJobStatus.SUCCEEDED and result is None:
                raise RecommendationGenerationConflict("successful generation requires a result")
            if status != GenerationJobStatus.SUCCEEDED and result is not None:
                raise RecommendationGenerationConflict("failed generation cannot persist a result")
            updated = replace(
                job,
                status=status,
                version=job.version + 1,
                lease_id=None,
                lease_expires_at=None,
                error_code=error_code,
            )
            self._jobs[(project_id, job_id)] = updated
            if result is not None:
                self._results[(project_id, job_id)] = result
            return updated

    def result(self, *, project_id: UUID, job_id: UUID) -> RecommendationGenerationResult | None:
        with self._lock:
            return self._results.get((project_id, job_id))

    def job(self, *, project_id: UUID, job_id: UUID) -> RecommendationGenerationJob:
        return self.get_job(project_id=project_id, job_id=job_id)

    def _owned(
        self,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
        now: datetime,
    ) -> RecommendationGenerationJob:
        job = self._get(project_id, job_id)
        if (
            job.status != GenerationJobStatus.RUNNING
            or job.lease_id != ownership.lease_id
            or job.fencing_token != ownership.fencing_token
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            raise RecommendationGenerationConflict("generation lease is lost or fenced")
        return job

    def _get(self, project_id: UUID, job_id: UUID) -> RecommendationGenerationJob:
        try:
            return self._jobs[(project_id, job_id)]
        except KeyError as exc:
            raise RecommendationGenerationConflict("generation Job does not exist") from exc
