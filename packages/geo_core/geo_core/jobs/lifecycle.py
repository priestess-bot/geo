from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from uuid import UUID, uuid4


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    FINALIZING = "finalizing"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.DEAD_LETTERED, JobStatus.CANCELLED}
)


class LeaseConflict(RuntimeError):
    """Raised when a worker no longer owns the current fencing generation."""


class InvalidTransition(ValueError):
    """Raised when a lifecycle operation is not valid from the current state."""


@dataclass(frozen=True)
class DomainJobSpec:
    """Typed, immutable input attached one-to-one to a durable job."""

    kind: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("job kind must not be empty")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class DurableJob:
    id: UUID
    project_id: UUID
    spec: DomainJobSpec
    input_hash: str
    idempotency_key: str
    status: JobStatus = JobStatus.QUEUED
    priority: int = 0
    attempt_count: int = 0
    max_attempts: int = 3
    next_run_at: datetime | None = None
    lease_owner: str | None = None
    lease_token: UUID | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    fencing_generation: int = 0
    cancel_requested_at: datetime | None = None
    parent_job_id: UUID | None = None
    replay_nonce: int = 0
    result_ref: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        invalid_hash = len(self.input_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.input_hash
        )
        if invalid_hash:
            raise ValueError("input_hash must be a SHA-256 hex digest")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")


def _assert_fence(job: DurableJob, *, token: UUID, generation: int, now: datetime) -> None:
    if (
        job.status not in {JobStatus.RUNNING, JobStatus.FINALIZING}
        or job.lease_token != token
        or job.fencing_generation != generation
        or job.lease_expires_at is None
        or job.lease_expires_at <= now
    ):
        raise LeaseConflict("job lease is absent, expired, or fenced by another worker")


def claim(job: DurableJob, *, worker_id: str, now: datetime, lease_for: timedelta) -> DurableJob:
    """Claim due work or atomically reclaim an expired running/finalizing lease."""
    due = job.next_run_at is None or job.next_run_at <= now
    fresh = job.status in {JobStatus.QUEUED, JobStatus.RETRY_WAIT} and due
    expired = (
        job.status in {JobStatus.RUNNING, JobStatus.FINALIZING}
        and job.lease_expires_at is not None
        and job.lease_expires_at <= now
    )
    if not worker_id.strip() or lease_for <= timedelta(0):
        raise ValueError("worker_id and a positive lease duration are required")
    if not (fresh or expired):
        raise InvalidTransition("job is not claimable")
    if job.cancel_requested_at is not None:
        return replace(
            job,
            status=JobStatus.CANCELLED,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            heartbeat_at=None,
        )
    attempt_count = job.attempt_count + 1
    if attempt_count > job.max_attempts:
        return replace(
            job,
            status=JobStatus.DEAD_LETTERED,
            lease_owner=None,
            lease_token=None,
            lease_expires_at=None,
            error_code="attempt_budget_exhausted",
        )
    return replace(
        job,
        status=JobStatus.RUNNING,
        attempt_count=attempt_count,
        lease_owner=worker_id,
        lease_token=uuid4(),
        lease_expires_at=now + lease_for,
        heartbeat_at=now,
        fencing_generation=job.fencing_generation + 1,
        error_code=None,
    )


def heartbeat(
    job: DurableJob,
    *,
    token: UUID,
    generation: int,
    now: datetime,
    lease_for: timedelta,
) -> DurableJob:
    _assert_fence(job, token=token, generation=generation, now=now)
    if lease_for <= timedelta(0):
        raise ValueError("lease duration must be positive")
    return replace(job, heartbeat_at=now, lease_expires_at=now + lease_for)


def start_finalizing(
    job: DurableJob, *, token: UUID, generation: int, now: datetime
) -> DurableJob:
    _assert_fence(job, token=token, generation=generation, now=now)
    if job.status != JobStatus.RUNNING:
        raise InvalidTransition("only a running job can begin finalizing")
    return replace(job, status=JobStatus.FINALIZING)


def request_cancel(job: DurableJob, *, now: datetime) -> DurableJob:
    if job.status in TERMINAL_STATUSES:
        return job
    if job.status in {JobStatus.QUEUED, JobStatus.RETRY_WAIT}:
        return replace(job, status=JobStatus.CANCELLED, cancel_requested_at=now)
    return replace(job, cancel_requested_at=now)


def acknowledge_cancel(
    job: DurableJob, *, token: UUID, generation: int, now: datetime
) -> DurableJob:
    _assert_fence(job, token=token, generation=generation, now=now)
    if job.cancel_requested_at is None:
        raise InvalidTransition("job has no cancellation request")
    return replace(
        job,
        status=JobStatus.CANCELLED,
        lease_owner=None,
        lease_token=None,
        lease_expires_at=None,
        heartbeat_at=None,
    )


def complete(
    job: DurableJob,
    *,
    token: UUID,
    generation: int,
    now: datetime,
    result_ref: str,
) -> DurableJob:
    _assert_fence(job, token=token, generation=generation, now=now)
    if job.status not in {JobStatus.RUNNING, JobStatus.FINALIZING}:
        raise InvalidTransition("job cannot complete from its current state")
    if not result_ref.strip():
        raise ValueError("result_ref must not be empty")
    return replace(
        job,
        status=JobStatus.SUCCEEDED,
        result_ref=result_ref,
        lease_owner=None,
        lease_token=None,
        lease_expires_at=None,
        heartbeat_at=None,
    )


def fail(
    job: DurableJob,
    *,
    token: UUID,
    generation: int,
    now: datetime,
    error_code: str,
    retry_at: datetime | None,
) -> DurableJob:
    _assert_fence(job, token=token, generation=generation, now=now)
    if not error_code.strip():
        raise ValueError("error_code must not be empty")
    retryable = retry_at is not None and job.attempt_count < job.max_attempts
    exhausted = retry_at is not None and job.attempt_count >= job.max_attempts
    status = (
        JobStatus.RETRY_WAIT
        if retryable
        else JobStatus.DEAD_LETTERED
        if exhausted
        else JobStatus.FAILED
    )
    return replace(
        job,
        status=status,
        next_run_at=retry_at,
        error_code=error_code,
        lease_owner=None,
        lease_token=None,
        lease_expires_at=None,
        heartbeat_at=None,
    )


def replay(job: DurableJob, *, new_id: UUID, idempotency_key: str, now: datetime) -> DurableJob:
    """Create a new lineage node; retrying never creates a second job."""
    if job.status not in TERMINAL_STATUSES:
        raise InvalidTransition("only terminal jobs can be replayed")
    return DurableJob(
        id=new_id,
        project_id=job.project_id,
        spec=job.spec,
        input_hash=job.input_hash,
        idempotency_key=idempotency_key,
        max_attempts=job.max_attempts,
        next_run_at=now,
        parent_job_id=job.id,
        replay_nonce=job.replay_nonce + 1,
    )
