from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from geo_core.jobs import (
    DurableJob,
    DomainJobSpec,
    JobStatus,
    LeaseConflict,
    acknowledge_cancel,
    claim,
    complete,
    fail,
    heartbeat,
    replay,
    request_cancel,
    start_finalizing,
)


NOW = datetime(2026, 7, 15, tzinfo=UTC)


def make_job(*, max_attempts: int = 3) -> DurableJob:
    return DurableJob(
        id=uuid4(),
        project_id=uuid4(),
        spec=DomainJobSpec("placement.generate", {"brief_version_id": str(uuid4())}),
        input_hash="a" * 64,
        idempotency_key="generate:one",
        max_attempts=max_attempts,
        next_run_at=NOW,
    )


def lease(job: DurableJob) -> tuple[UUID, int]:
    assert job.lease_token is not None
    return job.lease_token, job.fencing_generation


def test_claim_heartbeat_finalize_and_complete() -> None:
    running = claim(make_job(), worker_id="worker-1", now=NOW, lease_for=timedelta(minutes=5))
    token, generation = lease(running)
    renewed = heartbeat(
        running,
        token=token,
        generation=generation,
        now=NOW + timedelta(minutes=1),
        lease_for=timedelta(minutes=5),
    )
    finalizing = start_finalizing(
        renewed, token=token, generation=generation, now=NOW + timedelta(minutes=2)
    )
    done = complete(
        finalizing,
        token=token,
        generation=generation,
        now=NOW + timedelta(minutes=3),
        result_ref="artifact://result/1",
    )
    assert done.status == JobStatus.SUCCEEDED
    assert done.result_ref == "artifact://result/1"
    assert done.lease_token is None


def test_expired_lease_is_reclaimed_with_a_new_fence() -> None:
    first = claim(make_job(), worker_id="worker-1", now=NOW, lease_for=timedelta(seconds=30))
    old_token, old_generation = lease(first)
    reclaimed = claim(
        first, worker_id="worker-2", now=NOW + timedelta(seconds=31), lease_for=timedelta(minutes=1)
    )
    assert reclaimed.attempt_count == 2
    assert reclaimed.fencing_generation == old_generation + 1
    assert reclaimed.lease_token != old_token
    with pytest.raises(LeaseConflict):
        complete(
            reclaimed,
            token=old_token,
            generation=old_generation,
            now=NOW + timedelta(seconds=32),
            result_ref="artifact://stale",
        )


def test_retry_reuses_job_and_replay_creates_lineage() -> None:
    running = claim(make_job(), worker_id="worker", now=NOW, lease_for=timedelta(minutes=1))
    token, generation = lease(running)
    waiting = fail(
        running,
        token=token,
        generation=generation,
        now=NOW + timedelta(seconds=10),
        error_code="provider_timeout",
        retry_at=NOW + timedelta(minutes=2),
    )
    assert waiting.id == running.id
    assert waiting.status == JobStatus.RETRY_WAIT
    second = claim(
        waiting,
        worker_id="worker",
        now=NOW + timedelta(minutes=2),
        lease_for=timedelta(minutes=1),
    )
    token, generation = lease(second)
    dead = fail(
        second,
        token=token,
        generation=generation,
        now=NOW + timedelta(minutes=2, seconds=10),
        error_code="schema_invalid",
        retry_at=None,
    )
    assert dead.status == JobStatus.FAILED
    new_id = uuid4()
    replacement = replay(
        dead,
        new_id=new_id,
        idempotency_key="operator-replay:one",
        now=NOW + timedelta(minutes=3),
    )
    assert replacement.id == new_id
    assert replacement.parent_job_id == dead.id
    assert replacement.replay_nonce == dead.replay_nonce + 1
    assert replacement.attempt_count == 0


def test_attempt_budget_dead_letters_instead_of_calling_provider_again() -> None:
    job = make_job(max_attempts=1)
    running = claim(job, worker_id="worker", now=NOW, lease_for=timedelta(seconds=1))
    exhausted = claim(
        running,
        worker_id="worker-2",
        now=NOW + timedelta(seconds=2),
        lease_for=timedelta(seconds=1),
    )
    assert exhausted.status == JobStatus.DEAD_LETTERED
    assert exhausted.error_code == "attempt_budget_exhausted"


def test_running_job_cancellation_requires_current_fence_acknowledgement() -> None:
    running = claim(make_job(), worker_id="worker", now=NOW, lease_for=timedelta(minutes=1))
    token, generation = lease(running)
    requested = request_cancel(running, now=NOW + timedelta(seconds=1))
    cancelled = acknowledge_cancel(
        requested,
        token=token,
        generation=generation,
        now=NOW + timedelta(seconds=2),
    )
    assert cancelled.status == JobStatus.CANCELLED
    assert cancelled.cancel_requested_at == NOW + timedelta(seconds=1)
