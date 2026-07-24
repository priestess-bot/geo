"""Transactional Sampling Core command service."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Callable
from uuid import UUID

from geo_core.sampling.admission import SamplingAdmissionGrant
from geo_core.sampling.assessment import assess_sampling_run, complete_sampling_run
from geo_core.sampling.contracts import (
    EvidenceStatus,
    SamplingConflict,
    SamplingNotFound,
    SamplingRun,
    SamplingRunAssessment,
    SamplingRunStatus,
    SamplingSuite,
    SamplingTask,
)
from geo_core.sampling.execution import (
    ObservationEvidence,
    SamplingActualLocationLineage,
    SamplingAttempt,
    SamplingJobCommand,
    build_sampling_job,
)
from geo_core.sampling.lifecycle import (
    AttemptEnqueueResult,
    AttemptTransitionResult,
    BulkAttemptEnqueueResult,
    BulkAttemptCancelResult,
    ObservationCommitResult,
    acknowledge_sampling_cancel,
    begin_sampling_finalization,
    claim_sampling_attempt,
    enqueue_sampling_attempt,
    fail_sampling_attempt,
    finalize_sampling_observation,
    heartbeat_sampling_attempt,
    materialize_sampling_run,
    request_sampling_cancel,
)
from geo_core.sampling.bulk_operations import (
    enqueue_ready_attempts as bulk_enqueue_ready_attempts,
    request_run_cancel as bulk_request_run_cancel,
)
from geo_core.sampling.ports import SamplingRepository, SamplingUnitOfWorkFactory
from geo_core.sampling.run_state import close_cancelled_run_if_terminal, require_active_run


class SamplingApplication:
    def __init__(
        self,
        unit_of_work_factory: SamplingUnitOfWorkFactory,
        *,
        admission_guard: Callable[[SamplingRun, datetime], None] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._admission_guard = admission_guard

    def register_suite(self, suite: SamplingSuite) -> SamplingSuite:
        with self._unit_of_work_factory(project_id=suite.project_id) as unit_of_work:
            unit_of_work.sampling.add_suite(suite)
            unit_of_work.commit()
        return suite

    def create_run(
        self,
        *,
        project_id: UUID,
        suite_id: UUID,
        grant: SamplingAdmissionGrant,
        run_id: UUID,
        created_at: datetime,
    ) -> tuple[SamplingRun, tuple[SamplingTask, ...]]:
        with self._unit_of_work_factory(project_id=project_id) as unit_of_work:
            suite = _suite(unit_of_work.sampling, project_id, suite_id)
            run, tasks = materialize_sampling_run(
                suite, grant=grant, run_id=run_id, created_at=created_at
            )
            unit_of_work.sampling.add_run(run)
            unit_of_work.sampling.add_tasks(tasks)
            unit_of_work.commit()
        return run, tasks

    def enqueue_attempt(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        expected_task_version: int,
        attempt_id: UUID,
        requested_not_before: datetime,
        authorization_checked_at: datetime | None = None,
    ) -> AttemptEnqueueResult:
        with self._unit_of_work_factory(project_id=project_id) as unit_of_work:
            repository = unit_of_work.sampling
            run = _run(repository, project_id, run_id)
            self._require_current_admission(run, at=authorization_checked_at)
            require_active_run(run)
            task = _task(repository, project_id, run_id, task_id)
            existing = repository.get_attempt(project_id=project_id, attempt_id=attempt_id)
            if existing is not None:
                return _replay_enqueue(
                    task,
                    run,
                    existing,
                    requested_not_before=requested_not_before,
                )
            if task.version != expected_task_version:
                raise SamplingConflict("Sampling Task optimistic version check failed")
            result = enqueue_sampling_attempt(
                task,
                run=run,
                attempt_id=attempt_id,
                requested_not_before=requested_not_before,
            )
            repository.save_task(result.task, expected_version=task.version)
            repository.add_attempt(result.attempt)
            unit_of_work.outbox.enqueue(result.outbox)
            if run.status is SamplingRunStatus.PLANNED:
                repository.save_run(
                    replace(
                        run,
                        status=SamplingRunStatus.RUNNING,
                        version=run.version + 1,
                    ),
                    expected_version=run.version,
                )
            unit_of_work.commit()
        return result

    def enqueue_ready_attempts(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        requested_not_before: datetime,
        authorization_checked_at: datetime,
        max_tasks: int,
        attempt_id_factory: Callable[[SamplingTask], UUID],
    ) -> BulkAttemptEnqueueResult:
        return bulk_enqueue_ready_attempts(
            self._unit_of_work_factory,
            lambda run, checked_at: self._require_current_admission(
                run,
                at=checked_at,
            ),
            project_id=project_id,
            run_id=run_id,
            requested_not_before=requested_not_before,
            authorization_checked_at=authorization_checked_at,
            max_tasks=max_tasks,
            attempt_id_factory=attempt_id_factory,
        )

    def request_run_cancel(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        now: datetime,
    ) -> BulkAttemptCancelResult:
        return bulk_request_run_cancel(
            self._unit_of_work_factory,
            project_id=project_id,
            run_id=run_id,
            now=now,
        )

    def claim_attempt(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> AttemptTransitionResult:
        with self._unit_of_work_factory(project_id=project_id) as unit_of_work:
            repository = unit_of_work.sampling
            task, attempt = _task_attempt(repository, project_id, run_id, task_id, attempt_id)
            run = _run(repository, project_id, run_id)
            self._require_current_admission(run, at=now)
            require_active_run(run)
            _require_versions(
                task,
                attempt,
                expected_task_version=expected_task_version,
                expected_attempt_version=expected_attempt_version,
            )
            result = claim_sampling_attempt(
                task, attempt, worker_id=worker_id, now=now, lease_for=lease_for
            )
            _save_transition(repository, task, attempt, result)
            unit_of_work.commit()
        return result

    def _require_current_admission(self, run: SamplingRun, *, at: datetime | None) -> None:
        if self._admission_guard is None:
            return
        if at is None:
            raise SamplingConflict("current Sampling admission check time is required")
        self._admission_guard(run, at)

    def heartbeat_attempt(
        self,
        *,
        project_id: UUID,
        attempt_id: UUID,
        expected_attempt_version: int,
        token: UUID,
        generation: int,
        now: datetime,
        lease_for: timedelta,
    ) -> SamplingAttempt:
        with self._unit_of_work_factory(project_id=project_id) as unit_of_work:
            repository = unit_of_work.sampling
            attempt = _attempt(repository, project_id, attempt_id)
            if attempt.record_version != expected_attempt_version:
                raise SamplingConflict("Sampling Attempt optimistic version check failed")
            updated = heartbeat_sampling_attempt(
                attempt,
                token=token,
                generation=generation,
                now=now,
                lease_for=lease_for,
            )
            repository.save_attempt(updated, expected_version=attempt.record_version)
            unit_of_work.commit()
        return updated

    def begin_finalization(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        token: UUID,
        generation: int,
        now: datetime,
    ) -> AttemptTransitionResult:
        return self._transition(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            expected_task_version=expected_task_version,
            expected_attempt_version=expected_attempt_version,
            operation=lambda task, attempt: begin_sampling_finalization(
                task,
                attempt,
                token=token,
                generation=generation,
                now=now,
            ),
        )

    def finalize_observation(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        token: UUID,
        generation: int,
        now: datetime,
        evidence_status: EvidenceStatus,
        ineligible_reasons: tuple[str, ...],
        evidence: ObservationEvidence,
        actual_location: SamplingActualLocationLineage | None = None,
    ) -> ObservationCommitResult:
        with self._unit_of_work_factory(project_id=project_id) as unit_of_work:
            repository = unit_of_work.sampling
            task, attempt = _task_attempt(repository, project_id, run_id, task_id, attempt_id)
            existing = repository.get_observation(
                project_id=project_id, run_id=run_id, task_id=task_id
            )
            if existing is not None:
                if (
                    existing.winning_attempt_id != attempt_id
                    or existing.evidence != evidence
                    or existing.evidence_status is not evidence_status
                    or existing.ineligible_reasons != tuple(sorted(set(ineligible_reasons)))
                    or existing.actual_location != actual_location
                ):
                    raise SamplingConflict(
                        "Sampling Task already has a different winning Observation"
                    )
                return ObservationCommitResult(task, attempt, existing)
            _require_versions(
                task,
                attempt,
                expected_task_version=expected_task_version,
                expected_attempt_version=expected_attempt_version,
            )
            suite = _suite(repository, project_id, task.identity.suite_id)
            result = finalize_sampling_observation(
                task,
                attempt,
                suite=suite,
                token=token,
                generation=generation,
                now=now,
                evidence_status=evidence_status,
                ineligible_reasons=ineligible_reasons,
                evidence=evidence,
                actual_location=actual_location,
            )
            _save_transition(repository, task, attempt, result)
            repository.add_observation(result.observation)
            unit_of_work.commit()
        return result

    def fail_attempt(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        token: UUID,
        generation: int,
        now: datetime,
        error_code: str,
    ) -> AttemptTransitionResult:
        return self._transition(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            expected_task_version=expected_task_version,
            expected_attempt_version=expected_attempt_version,
            operation=lambda task, attempt: fail_sampling_attempt(
                task,
                attempt,
                token=token,
                generation=generation,
                now=now,
                error_code=error_code,
            ),
        )

    def request_cancel(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        now: datetime,
    ) -> AttemptTransitionResult:
        return self._transition(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            expected_task_version=expected_task_version,
            expected_attempt_version=expected_attempt_version,
            operation=lambda task, attempt: request_sampling_cancel(task, attempt, now=now),
        )

    def acknowledge_cancel(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        token: UUID,
        generation: int,
        now: datetime,
    ) -> AttemptTransitionResult:
        return self._transition(
            project_id=project_id,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            expected_task_version=expected_task_version,
            expected_attempt_version=expected_attempt_version,
            operation=lambda task, attempt: acknowledge_sampling_cancel(
                task,
                attempt,
                token=token,
                generation=generation,
                now=now,
            ),
        )

    def assess_run(self, *, project_id: UUID, run_id: UUID) -> SamplingRunAssessment:
        with self._unit_of_work_factory(project_id=project_id) as unit_of_work:
            repository = unit_of_work.sampling
            run = _run(repository, project_id, run_id)
            suite = _suite(repository, project_id, run.suite_id)
            return assess_sampling_run(
                suite,
                run,
                tasks=repository.list_tasks(project_id=project_id, run_id=run_id),
                observations=repository.list_observations(project_id=project_id, run_id=run_id),
            )

    def complete_run(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        expected_run_version: int,
    ) -> tuple[SamplingRun, SamplingRunAssessment]:
        with self._unit_of_work_factory(project_id=project_id) as unit_of_work:
            repository = unit_of_work.sampling
            run = _run(repository, project_id, run_id)
            if run.version != expected_run_version:
                raise SamplingConflict("Sampling Run optimistic version check failed")
            suite = _suite(repository, project_id, run.suite_id)
            completed, assessment = complete_sampling_run(
                suite,
                run,
                tasks=repository.list_tasks(project_id=project_id, run_id=run_id),
                observations=repository.list_observations(project_id=project_id, run_id=run_id),
            )
            if completed != run:
                repository.save_run(completed, expected_version=run.version)
                unit_of_work.commit()
        return completed, assessment

    def _transition(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        expected_task_version: int,
        expected_attempt_version: int,
        operation: Callable[[SamplingTask, SamplingAttempt], AttemptTransitionResult],
    ) -> AttemptTransitionResult:
        with self._unit_of_work_factory(project_id=project_id) as unit_of_work:
            repository = unit_of_work.sampling
            task, attempt = _task_attempt(repository, project_id, run_id, task_id, attempt_id)
            _require_versions(
                task,
                attempt,
                expected_task_version=expected_task_version,
                expected_attempt_version=expected_attempt_version,
            )
            result = operation(task, attempt)
            _save_transition(repository, task, attempt, result)
            close_cancelled_run_if_terminal(repository, project_id=project_id, run_id=run_id)
            unit_of_work.commit()
        return result


def _suite(repository: SamplingRepository, project_id: UUID, suite_id: UUID) -> SamplingSuite:
    suite = repository.get_suite(project_id=project_id, suite_id=suite_id)
    if suite is None:
        raise SamplingNotFound("Sampling Suite does not exist")
    return suite


def _run(repository: SamplingRepository, project_id: UUID, run_id: UUID) -> SamplingRun:
    run = repository.get_run(project_id=project_id, run_id=run_id)
    if run is None:
        raise SamplingNotFound("Sampling Run does not exist")
    return run


def _task(
    repository: SamplingRepository,
    project_id: UUID,
    run_id: UUID,
    task_id: UUID,
) -> SamplingTask:
    task = repository.get_task(project_id=project_id, run_id=run_id, task_id=task_id)
    if task is None:
        raise SamplingNotFound("Sampling Task does not exist")
    return task


def _attempt(repository: SamplingRepository, project_id: UUID, attempt_id: UUID) -> SamplingAttempt:
    attempt = repository.get_attempt(project_id=project_id, attempt_id=attempt_id)
    if attempt is None:
        raise SamplingNotFound("Sampling Attempt does not exist")
    return attempt


def _task_attempt(
    repository: SamplingRepository,
    project_id: UUID,
    run_id: UUID,
    task_id: UUID,
    attempt_id: UUID,
) -> tuple[SamplingTask, SamplingAttempt]:
    return (
        _task(repository, project_id, run_id, task_id),
        _attempt(repository, project_id, attempt_id),
    )


def _require_versions(
    task: SamplingTask,
    attempt: SamplingAttempt,
    *,
    expected_task_version: int,
    expected_attempt_version: int,
) -> None:
    if task.version != expected_task_version or attempt.record_version != expected_attempt_version:
        raise SamplingConflict("Sampling Task/Attempt optimistic version check failed")


def _save_transition(
    repository: SamplingRepository,
    old_task: SamplingTask,
    old_attempt: SamplingAttempt,
    result: AttemptTransitionResult | ObservationCommitResult,
) -> None:
    repository.save_task(result.task, expected_version=old_task.version)
    repository.save_attempt(result.attempt, expected_version=old_attempt.record_version)


def _replay_enqueue(
    task: SamplingTask,
    run: SamplingRun,
    existing: SamplingAttempt,
    *,
    requested_not_before: datetime,
) -> AttemptEnqueueResult:
    if (
        existing.task_id != task.id
        or existing.run_id != task.run_id
        or existing.id not in task.attempt_ids
    ):
        raise SamplingConflict("Attempt idempotency key was reused for another Task")
    command = SamplingJobCommand(
        project_id=task.project_id,
        run_id=task.run_id,
        task_id=task.id,
        task_key=task.identity.task_key,
        attempt_id=existing.id,
        capture_method=task.identity.capture_method,
        adapter_release=task.identity.adapter_release,
        question_id=task.identity.question_id,
        question_version=task.identity.question_version,
        location_control=task.identity.location_control,
        location_evidence_hash=task.identity.location_evidence_hash,
        requested_country=task.identity.requested_country,
        requested_region=task.identity.requested_region,
        requested_locale=task.identity.requested_locale,
        requested_language=task.identity.requested_language,
        effective_country=task.identity.effective_country,
        effective_region=task.identity.effective_region,
        effective_locale=task.identity.effective_locale,
        effective_language=task.identity.effective_language,
        not_before=max(run.admitted_not_before, requested_not_before),
    )
    expected_job, outbox = build_sampling_job(command=command)
    if (
        existing.job.spec != expected_job.spec
        or existing.job.input_hash != expected_job.input_hash
        or existing.job.idempotency_key != expected_job.idempotency_key
        or existing.job.next_run_at != expected_job.next_run_at
    ):
        raise SamplingConflict("Attempt idempotency key was reused with another command")
    return AttemptEnqueueResult(task, existing, outbox)
