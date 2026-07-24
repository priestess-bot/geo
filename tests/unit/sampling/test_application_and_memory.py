from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from geo_core.jobs import LeaseConflict
from geo_core.sampling import (
    EvidenceStatus,
    InMemorySamplingStore,
    SamplingApplication,
    SamplingConflict,
    SamplingRunStatus,
    SamplingTaskStatus,
)
from geo_core.sampling.admission import SamplingAdmissionCommand, admit_sampling_suite

from tests.unit.sampling.factories import NOW, make_evidence, make_policy, make_suite


def _seed_application():
    store = InMemorySamplingStore()
    application = SamplingApplication(store.unit_of_work_factory())
    suite = make_suite()
    policy = make_policy(suite)
    grant = admit_sampling_suite(
        suite,
        policy=policy,
        command=SamplingAdmissionCommand(
            idempotency_key=f"admission:{suite.id}",
            purpose="geo_measurement",
            requested_at=NOW,
            requested_not_before=NOW,
        ),
    )
    application.register_suite(suite)
    run, tasks = application.create_run(
        project_id=suite.project_id,
        suite_id=suite.id,
        grant=grant,
        run_id=uuid4(),
        created_at=NOW,
    )
    return store, application, suite, run, tasks


def test_suite_run_attempt_and_outbox_are_idempotent() -> None:
    store, application, suite, run, tasks = _seed_application()

    application.register_suite(suite)
    attempt_id = uuid4()
    first = application.enqueue_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=tasks[0].id,
        expected_task_version=tasks[0].version,
        attempt_id=attempt_id,
        requested_not_before=NOW,
    )
    replayed = application.enqueue_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=tasks[0].id,
        expected_task_version=tasks[0].version,
        attempt_id=attempt_id,
        requested_not_before=NOW,
    )

    assert replayed.attempt == first.attempt
    assert replayed.outbox == first.outbox
    assert len(store.outbox_messages(project_id=suite.project_id)) == 1
    assert store.attempt(project_id=suite.project_id, attempt_id=attempt_id) == first.attempt

    with pytest.raises(SamplingConflict, match="another command"):
        application.enqueue_attempt(
            project_id=suite.project_id,
            run_id=run.id,
            task_id=tasks[0].id,
            expected_task_version=first.task.version,
            attempt_id=attempt_id,
            requested_not_before=run.admitted_not_before + timedelta(minutes=5),
        )


def test_application_commits_fenced_observation_atomically_and_replays_it() -> None:
    store, application, suite, run, tasks = _seed_application()
    enqueued = application.enqueue_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=tasks[0].id,
        expected_task_version=tasks[0].version,
        attempt_id=uuid4(),
        requested_not_before=NOW,
    )
    execute_at = run.admitted_not_before + timedelta(seconds=1)
    claimed = application.claim_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=enqueued.task.id,
        attempt_id=enqueued.attempt.id,
        expected_task_version=enqueued.task.version,
        expected_attempt_version=enqueued.attempt.record_version,
        worker_id="sampling-worker",
        now=execute_at,
        lease_for=timedelta(minutes=2),
    )
    token = claimed.attempt.job.lease_token
    assert token is not None
    evidence = make_evidence(
        claimed.task, provider_response_id="provider-response-42"
    )
    completed = application.finalize_observation(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=claimed.task.id,
        attempt_id=claimed.attempt.id,
        expected_task_version=claimed.task.version,
        expected_attempt_version=claimed.attempt.record_version,
        token=token,
        generation=claimed.attempt.job.fencing_generation,
        now=execute_at + timedelta(seconds=2),
        evidence_status=EvidenceStatus.COMPLETE,
        ineligible_reasons=(),
        evidence=evidence,
    )
    replayed = application.finalize_observation(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=claimed.task.id,
        attempt_id=claimed.attempt.id,
        expected_task_version=claimed.task.version,
        expected_attempt_version=claimed.attempt.record_version,
        token=token,
        generation=claimed.attempt.job.fencing_generation,
        now=execute_at + timedelta(seconds=2),
        evidence_status=EvidenceStatus.COMPLETE,
        ineligible_reasons=(),
        evidence=evidence,
    )

    assert replayed.observation == completed.observation
    assert store.observation(
        project_id=suite.project_id, run_id=run.id, task_id=claimed.task.id
    ) == completed.observation
    assert store.task(
        project_id=suite.project_id, run_id=run.id, task_id=claimed.task.id
    ) == completed.task


def test_application_lost_lease_leaves_no_observation_or_terminal_write() -> None:
    store, application, suite, run, tasks = _seed_application()
    enqueued = application.enqueue_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=tasks[0].id,
        expected_task_version=tasks[0].version,
        attempt_id=uuid4(),
        requested_not_before=NOW,
    )
    execute_at = run.admitted_not_before + timedelta(seconds=1)
    execute_at = run.admitted_not_before + timedelta(seconds=1)
    claimed = application.claim_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=enqueued.task.id,
        attempt_id=enqueued.attempt.id,
        expected_task_version=enqueued.task.version,
        expected_attempt_version=enqueued.attempt.record_version,
        worker_id="sampling-worker",
        now=execute_at,
        lease_for=timedelta(seconds=10),
    )
    token = claimed.attempt.job.lease_token
    assert token is not None

    with pytest.raises(LeaseConflict):
        application.finalize_observation(
            project_id=suite.project_id,
            run_id=run.id,
            task_id=claimed.task.id,
            attempt_id=claimed.attempt.id,
            expected_task_version=claimed.task.version,
            expected_attempt_version=claimed.attempt.record_version,
            token=token,
            generation=claimed.attempt.job.fencing_generation,
            now=execute_at + timedelta(seconds=10),
            evidence_status=EvidenceStatus.COMPLETE,
            ineligible_reasons=(),
            evidence=make_evidence(claimed.task),
        )

    assert store.observation(
        project_id=suite.project_id, run_id=run.id, task_id=claimed.task.id
    ) is None
    assert store.attempt(
        project_id=suite.project_id, attempt_id=claimed.attempt.id
    ) == claimed.attempt


def test_run_cancel_terminalizes_unqueued_tasks_and_blocks_more_work() -> None:
    store, application, suite, run, tasks = _seed_application()
    enqueued = application.enqueue_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=tasks[0].id,
        expected_task_version=tasks[0].version,
        attempt_id=uuid4(),
        requested_not_before=NOW,
    )

    cancelled = application.request_run_cancel(
        project_id=suite.project_id,
        run_id=run.id,
        now=NOW + timedelta(seconds=1),
    )

    assert cancelled.requested_count == 1
    assert store.run(project_id=suite.project_id, run_id=run.id).status is SamplingRunStatus.CANCELLED
    assert all(
        task.status is SamplingTaskStatus.CANCELLED
        for task in (
            store.task(project_id=suite.project_id, run_id=run.id, task_id=item.id)
            for item in tasks
        )
    )
    with pytest.raises(SamplingConflict, match="not accepting new work"):
        application.enqueue_attempt(
            project_id=suite.project_id,
            run_id=run.id,
            task_id=tasks[1].id,
            expected_task_version=tasks[1].version,
            attempt_id=uuid4(),
            requested_not_before=NOW,
        )
    assert store.attempt(project_id=suite.project_id, attempt_id=enqueued.attempt.id) is not None


def test_active_run_cancel_closes_after_worker_acknowledges() -> None:
    store, application, suite, run, tasks = _seed_application()
    enqueued = application.enqueue_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=tasks[0].id,
        expected_task_version=tasks[0].version,
        attempt_id=uuid4(),
        requested_not_before=NOW,
    )
    execute_at = run.admitted_not_before + timedelta(seconds=1)
    claimed = application.claim_attempt(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=enqueued.task.id,
        attempt_id=enqueued.attempt.id,
        expected_task_version=enqueued.task.version,
        expected_attempt_version=enqueued.attempt.record_version,
        worker_id="sampling-worker",
        now=execute_at,
        lease_for=timedelta(minutes=2),
    )
    token = claimed.attempt.job.lease_token
    assert token is not None

    cancelled = application.request_run_cancel(
        project_id=suite.project_id,
        run_id=run.id,
        now=execute_at + timedelta(seconds=1),
    )

    assert cancelled.requested_count == 1
    assert store.run(project_id=suite.project_id, run_id=run.id).status is SamplingRunStatus.CANCEL_REQUESTED
    current_task = store.task(project_id=suite.project_id, run_id=run.id, task_id=claimed.task.id)
    current_attempt = store.attempt(project_id=suite.project_id, attempt_id=claimed.attempt.id)
    assert current_task is not None and current_attempt is not None
    acknowledged = application.acknowledge_cancel(
        project_id=suite.project_id,
        run_id=run.id,
        task_id=current_task.id,
        attempt_id=current_attempt.id,
        expected_task_version=current_task.version,
        expected_attempt_version=current_attempt.record_version,
        token=token,
        generation=current_attempt.job.fencing_generation,
        now=execute_at + timedelta(seconds=2),
    )

    assert acknowledged.task.status is SamplingTaskStatus.CANCELLED
    assert store.run(project_id=suite.project_id, run_id=run.id).status is SamplingRunStatus.CANCELLED


def test_stale_concurrent_uow_cannot_overwrite_task_even_with_same_result() -> None:
    store, _, suite, run, tasks = _seed_application()
    factory = store.unit_of_work_factory()
    first = factory(project_id=suite.project_id)
    second = factory(project_id=suite.project_id)
    first.__enter__()
    second.__enter__()
    try:
        first_task = first.sampling.get_task(
            project_id=suite.project_id, run_id=run.id, task_id=tasks[0].id
        )
        second_task = second.sampling.get_task(
            project_id=suite.project_id, run_id=run.id, task_id=tasks[0].id
        )
        assert first_task is not None and second_task is not None
        first.sampling.save_task(
            replace(
                first_task,
                status=SamplingTaskStatus.CANCELLED,
                version=first_task.version + 1,
            ),
            expected_version=first_task.version,
        )
        second.sampling.save_task(
            replace(
                second_task,
                status=SamplingTaskStatus.CANCELLED,
                version=second_task.version + 1,
            ),
            expected_version=second_task.version,
        )
        first.commit()
        with pytest.raises(SamplingConflict, match="concurrent"):
            second.commit()
    finally:
        first.__exit__(None, None, None)
        second.__exit__(None, None, None)


def test_concurrent_identical_create_is_an_idempotent_success() -> None:
    store = InMemorySamplingStore()
    suite = make_suite()
    factory = store.unit_of_work_factory()
    first = factory(project_id=suite.project_id)
    second = factory(project_id=suite.project_id)
    first.__enter__()
    second.__enter__()
    try:
        first.sampling.add_suite(suite)
        second.sampling.add_suite(suite)
        first.commit()
        second.commit()
    finally:
        first.__exit__(None, None, None)
        second.__exit__(None, None, None)

    assert store.suite(project_id=suite.project_id, suite_id=suite.id) == suite


def test_project_scoped_uow_rejects_cross_project_read() -> None:
    store, _, suite, _, _ = _seed_application()

    with store.unit_of_work_factory()(project_id=suite.project_id) as unit_of_work:
        with pytest.raises(SamplingConflict, match="scope"):
            unit_of_work.sampling.get_suite(
                project_id=uuid4(), suite_id=suite.id
            )
