from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from geo_core.jobs.postgres import JobCancellationRequested, PostgresDurableJobStore
from geo_core.placements.application import PlacementApplication
from geo_core.placements.domain import (
    PlacementConflict,
    PlacementRuleViolation,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.placement_worker_support import (
    ContentFailureVerifier,
    FakeVerifier,
    RetryableVerifier,
)
from tests.integration.publication_verification_terminal_support import (
    durable_job_state as _durable_job_state,
    make_job_due as _make_job_due,
    mark_newer_verification_active as _mark_newer_verification_active,
    mark_submission_verifying as _mark_submission_verifying,
    new_verification as _new_verification,
    open_due_measurement as _open_due_measurement,
    process_with_measurement_job_locked as _process_with_measurement_job_locked,
    prepare_exhausted_verification_job as _prepare_exhausted_verification_job,
    publication_request_id as _publication_request_id,
    set_existing_verification_result as _set_existing_verification_result,
    set_submission_status as _set_submission_status,
    terminalize_job_without_projection as _terminalize_job_without_projection,
    verification_dispatcher as _verification_dispatcher,
    verification_state as _verification_state,
)


class _CancellationVerifier:
    def verify(self, url: str, **expected: object) -> None:
        del url, expected
        raise JobCancellationRequested("verification cancellation fixture")


class _UnexpectedVerifier:
    def verify(self, url: str, **expected: object) -> None:
        del url, expected
        raise RuntimeError("unexpected verification fixture")


def exercise_verification_terminal_reconciliation(
    application: PlacementApplication,
    store: PostgresDurableJobStore,
    repository: PlacementWorkerRepository,
    *,
    admin_url: str,
    project_id: UUID,
    campaign_id: UUID,
    version_id: UUID,
    destination_id: UUID,
    owner_id: UUID,
    suffix: str,
) -> None:
    replay_submission, initial_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-authoritative-replay",
        publication_attempt=54,
    )
    successful_dispatcher = _verification_dispatcher(
        store,
        repository,
        FakeVerifier(),
        worker_id="integration-verification-initial-success",
    )
    assert successful_dispatcher.process(
        job_id=initial_job.id, project_id=project_id
    )["status"] == "verified"
    transient_job = application.replay_job(
        project_id=project_id,
        campaign_id=campaign_id,
        source_job_id=initial_job.id,
        actor_id=owner_id,
        idempotency_key=f"replay-{suffix}-transient-reverify",
    )
    assert application.request_verification(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=replay_submission,
        idempotency_key=f"verification-{suffix}-authoritative-replay",
    ).id == initial_job.id
    transient_dispatcher = _verification_dispatcher(
        store,
        repository,
        RetryableVerifier(),
        worker_id="integration-verification-transient-reverify",
    )
    assert transient_dispatcher.process(
        job_id=transient_job.id, project_id=project_id
    )["status"] == "retry_wait"
    assert _verification_state(admin_url, project_id, transient_job.id)[:3] == (
        "retry_wait",
        "verified",
        "published",
    )
    due_result, task_id, monitoring_query_id = _open_due_measurement(
        admin_url,
        store=store,
        repository=repository,
        project_id=project_id,
        submission_id=replay_submission,
        offset=28,
    )
    assert due_result["status"] == "awaiting_manual_samples"
    assert task_id is not None
    application.cancel_job(
        project_id=project_id,
        campaign_id=campaign_id,
        job_id=transient_job.id,
        actor_id=owner_id,
    )
    assert _verification_state(admin_url, project_id, transient_job.id)[:3] == (
        "cancelled",
        "verified",
        "published",
    )
    replay_job = application.replay_job(
        project_id=project_id,
        campaign_id=campaign_id,
        source_job_id=initial_job.id,
        actor_id=owner_id,
        idempotency_key=f"replay-{suffix}-authoritative-failure",
    )
    failed_dispatcher = _verification_dispatcher(
        store,
        repository,
        ContentFailureVerifier(),
        worker_id="integration-verification-authoritative-failure",
    )
    assert failed_dispatcher.process(
        job_id=replay_job.id, project_id=project_id
    )["status"] == "verification_failed"
    replay_state = _verification_state(admin_url, project_id, replay_job.id)
    assert replay_state[:3] == ("succeeded", "failed", "failed")
    assert replay_state[3]["success"] is False
    assert len(
        application.list_verification_attempts(
            project_id=project_id,
            campaign_id=campaign_id,
            submission_id=replay_submission,
        )
    ) == 3
    with pytest.raises(PlacementRuleViolation, match="currently verified"):
        application.record_measurement(
            project_id=project_id,
            campaign_id=campaign_id,
            submission_id=replay_submission,
            monitoring_query_id=monitoring_query_id,
            measured_at=datetime.now(UTC),
            citation_present=False,
            recommendation_position=None,
            result_snapshot_uri="s3://fixture/not-written",
            metrics={},
        )
    with pytest.raises(PlacementConflict, match="currently verified"):
        application.complete_measurement_collection_task(
            project_id=project_id,
            campaign_id=campaign_id,
            task_id=task_id,
            actor_id=owner_id,
        )
    deferred_job, deferred_task, _ = _open_due_measurement(
        admin_url,
        store=store,
        repository=repository,
        project_id=project_id,
        submission_id=replay_submission,
        offset=56,
    )
    assert deferred_job["status"] == "retry_wait"
    assert deferred_task is None
    assert _durable_job_state(
        admin_url,
        project_id=project_id,
        job_id=UUID(str(deferred_job["job_id"])),
    ) == ("retry_wait", 0)
    for _ in range(4):
        repeated_defer, repeated_task, _ = _open_due_measurement(
            admin_url,
            store=store,
            repository=repository,
            project_id=project_id,
            submission_id=replay_submission,
            offset=56,
        )
        assert repeated_defer["status"] == "retry_wait"
        assert repeated_task is None
    assert _durable_job_state(
        admin_url,
        project_id=project_id,
        job_id=UUID(str(deferred_job["job_id"])),
    ) == ("retry_wait", 0)
    recovery_job = application.request_verification(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=replay_submission,
        idempotency_key=f"verification-{suffix}-measurement-recovery",
    )
    assert successful_dispatcher.process(
        job_id=recovery_job.id, project_id=project_id
    )["status"] == "verified"
    recovered_result, recovered_task, _ = _open_due_measurement(
        admin_url,
        store=store,
        repository=repository,
        project_id=project_id,
        submission_id=replay_submission,
        offset=56,
    )
    assert recovered_result["status"] == "awaiting_manual_samples"
    assert recovered_task is not None
    exhausted_retry_job = application.replay_job(
        project_id=project_id,
        campaign_id=campaign_id,
        source_job_id=recovery_job.id,
        actor_id=owner_id,
        idempotency_key=f"replay-{suffix}-retryable-exhaustion",
    )
    retry_status: object = None
    for _ in range(10):
        retry_status = transient_dispatcher.process(
            job_id=exhausted_retry_job.id, project_id=project_id
        )["status"]
        if retry_status == "dead_lettered":
            break
        assert retry_status == "retry_wait"
        _make_job_due(
            admin_url,
            project_id=project_id,
            job_id=exhausted_retry_job.id,
        )
    assert retry_status == "dead_lettered"
    assert _verification_state(
        admin_url, project_id, exhausted_retry_job.id
    )[:3] == ("dead_lettered", "verified", "published")
    lock_probe_job = application.request_verification(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=replay_submission,
        idempotency_key=f"verification-{suffix}-measurement-lock-probe",
    )
    assert _process_with_measurement_job_locked(
        admin_url,
        dispatcher=successful_dispatcher,
        project_id=project_id,
        submission_id=replay_submission,
        verification_job_id=lock_probe_job.id,
        offset=84,
    )["status"] == "verified"
    _set_submission_status(
        admin_url,
        project_id=project_id,
        submission_id=replay_submission,
        status="blocked",
    )
    terminal_measurement, terminal_task, _ = _open_due_measurement(
        admin_url,
        store=store,
        repository=repository,
        project_id=project_id,
        submission_id=replay_submission,
        offset=84,
    )
    assert terminal_measurement["status"] == "skipped"
    assert terminal_task is None

    request_terminal_submission, request_terminal_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-request-terminal",
        publication_attempt=55,
    )
    request_terminal_id = _publication_request_id(
        admin_url,
        project_id=project_id,
        submission_id=request_terminal_submission,
    )
    awaiting_submission = application.create_submission(
        project_id=project_id,
        campaign_id=campaign_id,
        publication_request_id=request_terminal_id,
        submitted_url=None,
        provider_submission_id=None,
        idempotency_key=f"submission-{suffix}-request-terminal-awaiting",
        submitted_by=owner_id,
    )
    application.transition_publication(
        project_id=project_id,
        campaign_id=campaign_id,
        publication_request_id=request_terminal_id,
        status="cancelled",
        reason="operator cancelled publication",
        actor_id=owner_id,
    )
    with pytest.raises(PlacementRuleViolation, match="cannot be verified"):
        application.request_verification(
            project_id=project_id,
            campaign_id=campaign_id,
            submission_id=request_terminal_submission,
            idempotency_key=f"verification-{suffix}-request-terminal-new",
        )
    with pytest.raises(PlacementRuleViolation, match="cannot accept new submissions"):
        application.create_submission(
            project_id=project_id,
            campaign_id=campaign_id,
            publication_request_id=request_terminal_id,
            submitted_url=f"https://reddit.com/{suffix}-request-terminal-new",
            provider_submission_id=None,
            idempotency_key=f"submission-{suffix}-request-terminal-new",
            submitted_by=owner_id,
        )
    with pytest.raises(PlacementRuleViolation, match="cannot accept a URL backfill"):
        application.backfill_submission_url(
            project_id=project_id,
            campaign_id=campaign_id,
            submission_id=awaiting_submission.id,
            submitted_url=f"https://reddit.com/{suffix}-request-terminal-backfill",
            actor_id=owner_id,
        )
    terminal_dispatcher = _verification_dispatcher(
        store,
        repository,
        FakeVerifier(),
        worker_id="integration-verification-request-terminal",
    )
    assert terminal_dispatcher.process(
        job_id=request_terminal_job.id, project_id=project_id
    )["status"] == "failed"
    request_terminal_state = _verification_state(
        admin_url, project_id, request_terminal_job.id
    )
    assert request_terminal_state[:3] == ("failed", "failed", "cancelled")
    assert request_terminal_state[3] is None

    blocked_submission, blocked_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-submission-blocked",
        publication_attempt=56,
    )
    application.transition_submission(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=blocked_submission,
        status="blocked",
        reason="operator blocked submission",
        actor_id=owner_id,
    )
    assert terminal_dispatcher.process(
        job_id=blocked_job.id, project_id=project_id
    )["status"] == "failed"
    assert _verification_state(admin_url, project_id, blocked_job.id)[:3] == (
        "failed",
        "blocked",
        "failed",
    )

    shared_submission, shared_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-shared-request-cancel",
        publication_attempt=57,
    )
    shared_request = _publication_request_id(
        admin_url, project_id=project_id, submission_id=shared_submission
    )
    second_submission = application.create_submission(
        project_id=project_id,
        campaign_id=campaign_id,
        publication_request_id=shared_request,
        submitted_url=f"https://reddit.com/{suffix}-shared-request-success",
        provider_submission_id=None,
        idempotency_key=f"submission-{suffix}-shared-request-success",
        submitted_by=owner_id,
    )
    _mark_submission_verifying(
        admin_url,
        project_id=project_id,
        submission_id=shared_submission,
        value="shared-request-cancel",
    )
    assert application.cancel_job(
        project_id=project_id,
        campaign_id=campaign_id,
        job_id=shared_job.id,
        actor_id=owner_id,
    ).status == "cancelled"
    assert _verification_state(admin_url, project_id, shared_job.id)[:4] == (
        "cancelled",
        "cancelled",
        "publishing",
        {"existing": "shared-request-cancel"},
    )
    second_job = application.request_verification(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=second_submission.id,
        idempotency_key=f"verification-{suffix}-shared-request-success",
    )
    shared_dispatcher = _verification_dispatcher(
        store,
        repository,
        FakeVerifier(),
        worker_id="integration-verification-shared-request",
    )
    assert shared_dispatcher.process(
        job_id=second_job.id, project_id=project_id
    )["status"] == "verified"
    failed_sibling = application.create_submission(
        project_id=project_id,
        campaign_id=campaign_id,
        publication_request_id=shared_request,
        submitted_url=f"https://reddit.com/{suffix}-shared-request-failure",
        provider_submission_id=None,
        idempotency_key=f"submission-{suffix}-shared-request-failure",
        submitted_by=owner_id,
    )
    failed_sibling_job = application.request_verification(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=failed_sibling.id,
        idempotency_key=f"verification-{suffix}-shared-request-failure",
    )
    sibling_failure_dispatcher = _verification_dispatcher(
        store,
        repository,
        ContentFailureVerifier(),
        worker_id="integration-verification-shared-request-failure",
    )
    assert sibling_failure_dispatcher.process(
        job_id=failed_sibling_job.id, project_id=project_id
    )["status"] == "verification_failed"
    assert _verification_state(admin_url, project_id, failed_sibling_job.id)[:3] == (
        "succeeded",
        "failed",
        "published",
    )
    retrying_sibling = application.create_submission(
        project_id=project_id,
        campaign_id=campaign_id,
        publication_request_id=shared_request,
        submitted_url=f"https://reddit.com/{suffix}-shared-request-retry",
        provider_submission_id=None,
        idempotency_key=f"submission-{suffix}-shared-request-retry",
        submitted_by=owner_id,
    )
    retrying_sibling_job = application.request_verification(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=retrying_sibling.id,
        idempotency_key=f"verification-{suffix}-shared-request-retry",
    )
    sibling_retry_dispatcher = _verification_dispatcher(
        store,
        repository,
        RetryableVerifier(),
        worker_id="integration-verification-shared-request-retry",
    )
    assert sibling_retry_dispatcher.process(
        job_id=retrying_sibling_job.id, project_id=project_id
    )["status"] == "retry_wait"
    assert _verification_state(admin_url, project_id, retrying_sibling_job.id)[:3] == (
        "retry_wait",
        "verifying",
        "published",
    )
    application.cancel_job(
        project_id=project_id,
        campaign_id=campaign_id,
        job_id=retrying_sibling_job.id,
        actor_id=owner_id,
    )
    assert _verification_state(admin_url, project_id, retrying_sibling_job.id)[:3] == (
        "cancelled",
        "cancelled",
        "published",
    )
    assert shared_dispatcher.process(
        job_id=shared_job.id, project_id=project_id
    )["status"] == "terminal"
    assert _verification_state(admin_url, project_id, shared_job.id)[:3] == (
        "cancelled",
        "cancelled",
        "published",
    )

    queued_submission, queued_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-queued-api-cancel",
        publication_attempt=58,
    )
    _set_existing_verification_result(
        admin_url,
        project_id=project_id,
        submission_id=queued_submission,
        value={"existing": "queued-api-cancel"},
    )
    assert application.cancel_job(
        project_id=project_id,
        campaign_id=campaign_id,
        job_id=queued_job.id,
        actor_id=owner_id,
    ).status == "cancelled"
    expected_queued_cancel = (
        "cancelled",
        "cancelled",
        "cancelled",
        {"existing": "queued-api-cancel"},
        0,
    )
    assert _verification_state(admin_url, project_id, queued_job.id) == (
        expected_queued_cancel
    )
    assert application.cancel_job(
        project_id=project_id,
        campaign_id=campaign_id,
        job_id=queued_job.id,
        actor_id=owner_id,
    ).status == "cancelled"
    assert _verification_state(admin_url, project_id, queued_job.id) == (
        expected_queued_cancel
    )

    retry_cancel_submission, retry_cancel_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-retry-api-cancel",
        publication_attempt=59,
    )
    _set_existing_verification_result(
        admin_url,
        project_id=project_id,
        submission_id=retry_cancel_submission,
        value={"existing": "retry-api-cancel"},
    )
    retry_cancel_dispatcher = _verification_dispatcher(
        store,
        repository,
        _UnexpectedVerifier(),
        worker_id="integration-verification-retry-api-cancel",
    )
    assert retry_cancel_dispatcher.process(
        job_id=retry_cancel_job.id, project_id=project_id
    )["status"] == "retry_wait"
    assert application.cancel_job(
        project_id=project_id,
        campaign_id=campaign_id,
        job_id=retry_cancel_job.id,
        actor_id=owner_id,
    ).status == "cancelled"
    assert _verification_state(admin_url, project_id, retry_cancel_job.id) == (
        "cancelled",
        "cancelled",
        "cancelled",
        {"existing": "retry-api-cancel"},
        0,
    )

    cancelled_submission, cancelled_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-cancelled-terminal",
        publication_attempt=60,
    )
    _set_existing_verification_result(
        admin_url,
        project_id=project_id,
        submission_id=cancelled_submission,
        value={"existing": "cancelled"},
    )
    cancelled_dispatcher = _verification_dispatcher(
        store,
        repository,
        _CancellationVerifier(),
        worker_id="integration-verification-cancelled",
    )
    assert cancelled_dispatcher.process(
        job_id=cancelled_job.id, project_id=project_id
    )["status"] == "cancelled"
    assert _verification_state(admin_url, project_id, cancelled_job.id) == (
        "cancelled",
        "cancelled",
        "cancelled",
        {"existing": "cancelled"},
        0,
    )

    unexpected_submission, unexpected_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-unexpected-terminal",
        publication_attempt=61,
    )
    _set_existing_verification_result(
        admin_url,
        project_id=project_id,
        submission_id=unexpected_submission,
        value={"existing": "unexpected"},
    )
    unexpected_dispatcher = _verification_dispatcher(
        store,
        repository,
        _UnexpectedVerifier(),
        worker_id="integration-verification-unexpected",
    )
    statuses: list[object] = []
    for _ in range(10):
        result = unexpected_dispatcher.process(
            job_id=unexpected_job.id, project_id=project_id
        )
        statuses.append(result["status"])
        if result["status"] == "dead_lettered":
            break
        assert result["status"] == "retry_wait"
        _make_job_due(admin_url, project_id=project_id, job_id=unexpected_job.id)
    assert statuses[-1] == "dead_lettered"
    expected_unexpected = (
        "dead_lettered",
        "failed",
        "failed",
        {"existing": "unexpected"},
        0,
    )
    assert _verification_state(admin_url, project_id, unexpected_job.id) == (
        expected_unexpected
    )

    newer_job = application.request_verification(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=unexpected_submission,
        idempotency_key=f"verification-{suffix}-newer-owner",
    )
    _mark_newer_verification_active(
        admin_url,
        project_id=project_id,
        submission_id=unexpected_submission,
    )
    assert unexpected_dispatcher.process(
        job_id=unexpected_job.id, project_id=project_id
    )["status"] == "terminal"
    state_with_newer_job = _verification_state(admin_url, project_id, unexpected_job.id)
    assert state_with_newer_job[:3] == ("dead_lettered", "verifying", "publishing")
    assert state_with_newer_job[3:] == ({"existing": "newer-job"}, 0)

    _terminalize_job_without_projection(
        admin_url,
        project_id=project_id,
        job_id=newer_job.id,
    )
    assert unexpected_dispatcher.process(
        job_id=unexpected_job.id, project_id=project_id
    )["status"] == "terminal"
    assert _verification_state(
        admin_url, project_id, unexpected_job.id
    ) == state_with_newer_job

    newer_dispatcher = _verification_dispatcher(
        store,
        repository,
        FakeVerifier(),
        worker_id="integration-verification-newer-owner",
    )
    assert newer_dispatcher.process(
        job_id=newer_job.id, project_id=project_id
    )["status"] == "terminal"
    assert _verification_state(admin_url, project_id, newer_job.id)[:3] == (
        "dead_lettered",
        "failed",
        "failed",
    )
    success_job = application.request_verification(
        project_id=project_id,
        campaign_id=campaign_id,
        submission_id=unexpected_submission,
        idempotency_key=f"verification-{suffix}-success-owner",
    )
    assert newer_dispatcher.process(
        job_id=success_job.id, project_id=project_id
    )["status"] == "verified"
    assert unexpected_dispatcher.process(
        job_id=unexpected_job.id, project_id=project_id
    )["status"] == "terminal"
    state_after_newer_success = _verification_state(
        admin_url, project_id, unexpected_job.id
    )
    assert state_after_newer_success[:3] == ("dead_lettered", "verified", "published")
    assert state_after_newer_success[3]["success"] is True
    assert state_after_newer_success[4] == 0
    assert unexpected_dispatcher.process(
        job_id=unexpected_job.id, project_id=project_id
    )["status"] == "terminal"
    assert _verification_state(
        admin_url, project_id, unexpected_job.id
    ) == state_after_newer_success

    budget_submission, budget_job = _new_verification(
        application,
        project_id=project_id,
        campaign_id=campaign_id,
        version_id=version_id,
        destination_id=destination_id,
        owner_id=owner_id,
        suffix=f"{suffix}-claim-budget-terminal",
        publication_attempt=62,
    )
    _prepare_exhausted_verification_job(
        admin_url,
        project_id=project_id,
        job_id=budget_job.id,
        submission_id=budget_submission,
    )
    budget_dispatcher = _verification_dispatcher(
        store,
        repository,
        _UnexpectedVerifier(),
        worker_id="integration-verification-claim-budget",
    )
    assert budget_dispatcher.process(
        job_id=budget_job.id, project_id=project_id
    )["status"] == "dead_lettered"
    expected_budget = (
        "dead_lettered",
        "failed",
        "failed",
        {"existing": "claim-budget"},
        0,
    )
    assert _verification_state(admin_url, project_id, budget_job.id) == expected_budget
    assert budget_dispatcher.process(
        job_id=budget_job.id, project_id=project_id
    )["status"] == "terminal"
    assert _verification_state(admin_url, project_id, budget_job.id) == expected_budget
