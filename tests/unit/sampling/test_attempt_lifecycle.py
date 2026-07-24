from __future__ import annotations

from datetime import timedelta
import json
from uuid import UUID, uuid4

import pytest

from geo_core.jobs import JobStatus, LeaseConflict
from geo_core.sampling import (
    AttemptTerminalStatus,
    CaptureMethod,
    EvidenceStatus,
    SamplingTaskStatus,
    acknowledge_sampling_cancel,
    claim_sampling_attempt,
    enqueue_sampling_attempt,
    fail_sampling_attempt,
    finalize_sampling_observation,
    heartbeat_sampling_attempt,
    request_sampling_cancel,
)
from geo_core.sampling.execution import SamplingAttempt

from tests.unit.sampling.factories import NOW, make_evidence, make_run, make_suite


def test_retry_creates_new_attempt_without_changing_task_or_denominator() -> None:
    suite = make_suite(CaptureMethod.MANUAL_UI)
    _, run, tasks = make_run(suite)
    original = tasks[0]
    first = enqueue_sampling_attempt(
        original,
        run=run,
        attempt_id=uuid4(),
        requested_not_before=NOW,
    )
    execute_at = run.admitted_not_before + timedelta(seconds=1)
    claimed = claim_sampling_attempt(
        first.task,
        first.attempt,
        worker_id="sampling-worker-1",
        now=execute_at,
        lease_for=timedelta(minutes=2),
    )
    failed = fail_sampling_attempt(
        claimed.task,
        claimed.attempt,
        token=_token(claimed.attempt),
        generation=claimed.attempt.job.fencing_generation,
        now=execute_at + timedelta(seconds=1),
        error_code="provider_timeout",
    )

    second = enqueue_sampling_attempt(
        failed.task,
        run=run,
        attempt_id=uuid4(),
        requested_not_before=execute_at + timedelta(seconds=10),
    )

    assert failed.task.status is SamplingTaskStatus.RETRY_READY
    assert second.attempt.ordinal == 2
    assert second.attempt.id != first.attempt.id
    assert second.task.identity == original.identity
    assert second.task.identity.task_key in run.planned_task_keys
    assert len(run.planned_task_keys) == suite.planned_task_count


def test_attempt_response_and_verification_lineage_never_changes_task_identity() -> None:
    suite = make_suite(CaptureMethod.MANUAL_UI)
    _, run, tasks = make_run(suite)
    task_key = tasks[0].identity.task_key
    enqueued = enqueue_sampling_attempt(
        tasks[0], run=run, attempt_id=uuid4(), requested_not_before=NOW
    )
    execute_at = run.admitted_not_before + timedelta(seconds=1)
    claimed = claim_sampling_attempt(
        enqueued.task,
        enqueued.attempt,
        worker_id="manual-import-worker",
        now=execute_at,
        lease_for=timedelta(minutes=2),
    )
    evidence = make_evidence(
        claimed.task,
        provider_response_id="response-after-execution",
        egress_verification_id="verification-after-execution",
    )
    completed = finalize_sampling_observation(
        claimed.task,
        claimed.attempt,
        suite=suite,
        token=_token(claimed.attempt),
        generation=claimed.attempt.job.fencing_generation,
        now=execute_at + timedelta(seconds=1),
        evidence_status=EvidenceStatus.COMPLETE,
        ineligible_reasons=(),
        evidence=evidence,
    )

    assert completed.task.identity.task_key == task_key
    assert completed.attempt.provider_response_id == "response-after-execution"
    assert completed.attempt.egress_verification_id == "verification-after-execution"
    assert completed.observation.evidence.egress_verification_id == (
        "verification-after-execution"
    )
    assert task_key in run.planned_task_keys


def test_job_and_outbox_payload_have_an_exact_non_secret_whitelist() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    result = enqueue_sampling_attempt(
        tasks[0], run=run, attempt_id=uuid4(), requested_not_before=NOW
    )
    payload = dict(result.outbox.payload)
    expected = {
        "project_id",
        "run_id",
        "task_id",
        "task_key",
        "attempt_id",
        "capture_method",
        "adapter_release",
        "question_id",
        "question_version",
        "location_control",
        "location_evidence_hash",
        "requested_country",
        "requested_region",
        "requested_locale",
        "requested_language",
        "effective_country",
        "effective_region",
        "effective_locale",
        "effective_language",
        "not_before",
    }

    assert set(payload) == expected
    assert payload == dict(result.attempt.job.spec.payload)
    serialized = json.dumps(payload).lower()
    for forbidden in ("password", "credential", "authorization", "secret", "api_key"):
        assert forbidden not in serialized


def test_heartbeat_extends_current_lease_with_same_fencing_generation() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    enqueued = enqueue_sampling_attempt(
        tasks[0], run=run, attempt_id=uuid4(), requested_not_before=NOW
    )
    execute_at = run.admitted_not_before + timedelta(seconds=1)
    claimed = claim_sampling_attempt(
        enqueued.task,
        enqueued.attempt,
        worker_id="sampling-worker",
        now=execute_at,
        lease_for=timedelta(seconds=30),
    )
    heartbeat_at = execute_at + timedelta(seconds=10)
    updated = heartbeat_sampling_attempt(
        claimed.attempt,
        token=_token(claimed.attempt),
        generation=claimed.attempt.job.fencing_generation,
        now=heartbeat_at,
        lease_for=timedelta(minutes=3),
    )

    assert updated.job.heartbeat_at == heartbeat_at
    assert updated.job.lease_expires_at == heartbeat_at + timedelta(minutes=3)
    assert updated.job.fencing_generation == claimed.attempt.job.fencing_generation


def test_expired_or_lost_lease_cannot_commit_observation() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    enqueued = enqueue_sampling_attempt(
        tasks[0], run=run, attempt_id=uuid4(), requested_not_before=NOW
    )
    execute_at = run.admitted_not_before + timedelta(seconds=1)
    claimed = claim_sampling_attempt(
        enqueued.task,
        enqueued.attempt,
        worker_id="sampling-worker-old",
        now=execute_at,
        lease_for=timedelta(seconds=10),
    )
    expired_at = execute_at + timedelta(seconds=10)

    with pytest.raises(LeaseConflict):
        finalize_sampling_observation(
            claimed.task,
            claimed.attempt,
            suite=suite,
            token=_token(claimed.attempt),
            generation=claimed.attempt.job.fencing_generation,
            now=expired_at,
            evidence_status=EvidenceStatus.COMPLETE,
            ineligible_reasons=(),
            evidence=make_evidence(claimed.task),
        )

    reclaimed = claim_sampling_attempt(
        claimed.task,
        claimed.attempt,
        worker_id="sampling-worker-new",
        now=expired_at,
        lease_for=timedelta(minutes=1),
    )
    assert reclaimed.attempt.job.status is JobStatus.DEAD_LETTERED
    assert reclaimed.attempt.terminal_status is AttemptTerminalStatus.FAILED
    assert reclaimed.task.status is SamplingTaskStatus.RETRY_READY


def test_queued_and_running_cancellation_have_explicit_terminal_paths() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    queued = enqueue_sampling_attempt(
        tasks[0], run=run, attempt_id=uuid4(), requested_not_before=NOW
    )
    cancelled_queued = request_sampling_cancel(
        queued.task, queued.attempt, now=run.admitted_not_before
    )
    assert cancelled_queued.task.status is SamplingTaskStatus.CANCELLED
    assert cancelled_queued.attempt.terminal_status is AttemptTerminalStatus.CANCELLED

    running_input = enqueue_sampling_attempt(
        tasks[1], run=run, attempt_id=uuid4(), requested_not_before=NOW
    )
    execute_at = run.admitted_not_before + timedelta(seconds=1)
    running = claim_sampling_attempt(
        running_input.task,
        running_input.attempt,
        worker_id="sampling-worker",
        now=execute_at,
        lease_for=timedelta(minutes=1),
    )
    requested = request_sampling_cancel(
        running.task, running.attempt, now=execute_at + timedelta(seconds=1)
    )
    assert requested.task.status is SamplingTaskStatus.CANCEL_REQUESTED
    acknowledged = acknowledge_sampling_cancel(
        requested.task,
        requested.attempt,
        token=_token(requested.attempt),
        generation=requested.attempt.job.fencing_generation,
        now=execute_at + timedelta(seconds=2),
    )
    assert acknowledged.task.status is SamplingTaskStatus.CANCELLED
    assert acknowledged.attempt.job.status is JobStatus.CANCELLED


def _token(attempt: SamplingAttempt) -> UUID:
    token = attempt.job.lease_token
    assert token is not None
    return token
