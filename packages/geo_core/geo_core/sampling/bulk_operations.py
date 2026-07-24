"""Atomic Run-level Sampling enqueue and cancellation operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

from geo_core.jobs import JobStatus
from geo_core.sampling.contracts import (
    CaptureMethod,
    SamplingConflict,
    SamplingNotFound,
    SamplingRun,
    SamplingRunStatus,
    SamplingTask,
    SamplingTaskStatus,
)
from geo_core.sampling.execution import SamplingAttempt, SamplingOutboxMessage
from geo_core.sampling.lifecycle import (
    BulkAttemptCancelResult,
    BulkAttemptEnqueueResult,
    AttemptTransitionResult,
    enqueue_sampling_attempt,
    request_sampling_cancel,
)
from geo_core.sampling.ports import SamplingRepository, SamplingUnitOfWorkFactory
from geo_core.sampling.run_state import require_active_run


_TERMINAL_TASK_STATUSES = frozenset(
    {
        SamplingTaskStatus.SUCCEEDED,
        SamplingTaskStatus.FAILED,
        SamplingTaskStatus.CANCELLED,
    }
)
_ACTIVE_JOB_STATUSES = frozenset(
    {
        JobStatus.QUEUED,
        JobStatus.RETRY_WAIT,
        JobStatus.RUNNING,
        JobStatus.FINALIZING,
    }
)


def enqueue_ready_attempts(
    unit_of_work_factory: SamplingUnitOfWorkFactory,
    admission_guard: Callable[[SamplingRun, datetime | None], None],
    *,
    project_id: UUID,
    run_id: UUID,
    requested_not_before: datetime,
    authorization_checked_at: datetime,
    max_tasks: int,
    attempt_id_factory: Callable[[SamplingTask], UUID],
) -> BulkAttemptEnqueueResult:
    if max_tasks < 1:
        raise SamplingConflict("bulk Sampling enqueue limit must be positive")
    with unit_of_work_factory(project_id=project_id) as unit_of_work:
        repository = unit_of_work.sampling
        run = _run(repository, project_id, run_id)
        admission_guard(run, authorization_checked_at)
        require_active_run(run)
        suite = repository.get_suite(project_id=project_id, suite_id=run.suite_id)
        if suite is None:
            raise SamplingNotFound("Sampling Suite does not exist")
        if suite.source_stratum.capture_method is CaptureMethod.MANUAL_UI:
            raise SamplingConflict("manual_ui Tasks require approved manual evidence imports")
        tasks = tuple(
            sorted(
                repository.list_tasks(project_id=project_id, run_id=run_id),
                key=lambda item: item.identity.task_key,
            )
        )
        limit = min(max_tasks, suite.max_daily_tasks)
        ready = tuple(
            item for item in tasks if item.status is SamplingTaskStatus.PLANNED
        )[:limit]
        attempts: list[SamplingAttempt] = []
        outboxes: list[SamplingOutboxMessage] = []
        base_not_before = max(run.admitted_not_before, requested_not_before)
        for index, task in enumerate(ready):
            not_before = base_not_before + timedelta(
                seconds=index * suite.minimum_request_interval_seconds
            )
            result = enqueue_sampling_attempt(
                task,
                run=run,
                attempt_id=attempt_id_factory(task),
                requested_not_before=not_before,
            )
            repository.save_task(result.task, expected_version=task.version)
            repository.add_attempt(result.attempt)
            unit_of_work.outbox.enqueue(result.outbox)
            attempts.append(result.attempt)
            outboxes.append(result.outbox)
        if ready and run.status is SamplingRunStatus.PLANNED:
            repository.save_run(
                replace(
                    run,
                    status=SamplingRunStatus.RUNNING,
                    version=run.version + 1,
                ),
                expected_version=run.version,
            )
        unit_of_work.commit()
    return BulkAttemptEnqueueResult(
        attempts=tuple(attempts),
        outboxes=tuple(outboxes),
        planned_task_count=len(tasks),
        enqueued_count=len(attempts),
        skipped_count=len(tasks) - len(attempts),
    )


def request_run_cancel(
    unit_of_work_factory: SamplingUnitOfWorkFactory,
    *,
    project_id: UUID,
    run_id: UUID,
    now: datetime,
) -> BulkAttemptCancelResult:
    with unit_of_work_factory(project_id=project_id) as unit_of_work:
        repository = unit_of_work.sampling
        run = _run(repository, project_id, run_id)
        if run.status in {
            SamplingRunStatus.COMPLETED,
            SamplingRunStatus.CANCELLED,
            SamplingRunStatus.FAILED,
        }:
            raise SamplingConflict("Sampling Run cannot be cancelled from its current state")
        tasks = tuple(
            sorted(
                repository.list_tasks(project_id=project_id, run_id=run_id),
                key=lambda item: item.identity.task_key,
            )
        )
        updated_attempts: list[SamplingAttempt] = []
        for task in tasks:
            if not task.attempt_ids:
                if task.status is SamplingTaskStatus.PLANNED:
                    repository.save_task(
                        replace(
                            task,
                            status=SamplingTaskStatus.CANCELLED,
                            version=task.version + 1,
                        ),
                        expected_version=task.version,
                    )
                continue
            attempt = repository.get_attempt(
                project_id=project_id,
                attempt_id=task.attempt_ids[-1],
            )
            if attempt is None:
                raise SamplingConflict("Sampling Task references a missing Attempt")
            if (
                attempt.job.status not in _ACTIVE_JOB_STATUSES
                or attempt.job.cancel_requested_at is not None
            ):
                continue
            result = request_sampling_cancel(task, attempt, now=now)
            _save_transition(repository, task, attempt, result)
            updated_attempts.append(result.attempt)
        updated_tasks = repository.list_tasks(project_id=project_id, run_id=run_id)
        next_status = (
            SamplingRunStatus.CANCELLED
            if all(task.status in _TERMINAL_TASK_STATUSES for task in updated_tasks)
            else SamplingRunStatus.CANCEL_REQUESTED
        )
        if run.status is not next_status:
            repository.save_run(
                replace(run, status=next_status, version=run.version + 1),
                expected_version=run.version,
            )
        unit_of_work.commit()
    return BulkAttemptCancelResult(
        attempts=tuple(updated_attempts),
        requested_count=len(updated_attempts),
        skipped_count=len(tasks) - len(updated_attempts),
    )


def _run(repository: SamplingRepository, project_id: UUID, run_id: UUID) -> SamplingRun:
    run = repository.get_run(project_id=project_id, run_id=run_id)
    if run is None:
        raise SamplingNotFound("Sampling Run does not exist")
    return run


def _save_transition(
    repository: SamplingRepository,
    prior_task: SamplingTask,
    prior_attempt: SamplingAttempt,
    result: AttemptTransitionResult,
) -> None:
    repository.save_task(result.task, expected_version=prior_task.version)
    repository.save_attempt(
        result.attempt,
        expected_version=prior_attempt.record_version,
    )
