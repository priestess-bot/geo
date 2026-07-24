"""Deterministic Sampling Run materialization and fenced Attempt lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

from geo_core.jobs import (
    JobStatus,
    acknowledge_cancel,
    claim,
    complete,
    fail,
    heartbeat,
    request_cancel,
    start_finalizing,
)
from geo_core.sampling.admission import SamplingAdmissionGrant
from geo_core.sampling.contracts import (
    EvidenceStatus,
    SamplingRuleViolation,
    SamplingRun,
    SamplingRunStatus,
    SamplingSuite,
    SamplingTask,
    SamplingTaskIdentity,
    SamplingTaskStatus,
    sampling_task_id,
)
from geo_core.sampling.execution import (
    AttemptTerminalStatus,
    ObservationEvidence,
    SamplingActualLocationLineage,
    SamplingAttempt,
    SamplingJobCommand,
    SamplingObservation,
    SamplingOutboxMessage,
    build_sampling_job,
    observation_id,
)


@dataclass(frozen=True)
class AttemptEnqueueResult:
    task: SamplingTask
    attempt: SamplingAttempt
    outbox: SamplingOutboxMessage


@dataclass(frozen=True)
class BulkAttemptEnqueueResult:
    attempts: tuple[SamplingAttempt, ...]
    outboxes: tuple[SamplingOutboxMessage, ...]
    planned_task_count: int
    enqueued_count: int
    skipped_count: int


@dataclass(frozen=True)
class BulkAttemptCancelResult:
    attempts: tuple[SamplingAttempt, ...]
    requested_count: int
    skipped_count: int


@dataclass(frozen=True)
class AttemptTransitionResult:
    task: SamplingTask
    attempt: SamplingAttempt


@dataclass(frozen=True)
class ObservationCommitResult:
    task: SamplingTask
    attempt: SamplingAttempt
    observation: SamplingObservation


def materialize_sampling_run(
    suite: SamplingSuite,
    *,
    grant: SamplingAdmissionGrant,
    run_id: UUID,
    created_at: datetime,
) -> tuple[SamplingRun, tuple[SamplingTask, ...]]:
    """Freeze the full planned denominator before any external work is enqueued."""
    if (
        grant.suite_id != suite.id
        or grant.suite_hash != suite.suite_hash
        or grant.reserved_task_count != suite.planned_task_count
    ):
        raise SamplingRuleViolation("admission Grant does not cover the frozen Suite")
    identities = tuple(
        _task_identity(suite, question_id, question_version, repetition)
        for question_id, question_version in (
            (question.question_id, question.question_version) for question in suite.questions
        )
        for repetition in range(1, suite.repetitions + 1)
    )
    tasks = tuple(
        SamplingTask(
            id=sampling_task_id(run_id, identity.task_key),
            project_id=suite.project_id,
            run_id=run_id,
            identity=identity,
        )
        for identity in identities
    )
    planned_keys = tuple(sorted(task.identity.task_key for task in tasks))
    if len(planned_keys) != suite.planned_task_count:
        raise SamplingRuleViolation("materialized Task count differs from frozen Suite")
    run = SamplingRun(
        id=run_id,
        project_id=suite.project_id,
        suite_id=suite.id,
        suite_hash=suite.suite_hash,
        admission_policy_id=grant.policy_id,
        admission_policy_hash=grant.policy_hash,
        admission_grant_hash=grant.grant_hash,
        purpose=grant.purpose,
        authorization_reference=grant.authorization_reference,
        authorization_valid_until=grant.authorization_valid_until,
        admission_policy_version=grant.policy_version,
        reserved_task_count=grant.reserved_task_count,
        planned_task_keys=planned_keys,
        status=SamplingRunStatus.PLANNED,
        admitted_not_before=grant.not_before,
        created_at=created_at,
    )
    return run, tasks


def enqueue_sampling_attempt(
    task: SamplingTask,
    *,
    run: SamplingRun,
    attempt_id: UUID,
    requested_not_before: datetime,
) -> AttemptEnqueueResult:
    if task.run_id != run.id or task.project_id != run.project_id:
        raise SamplingRuleViolation("Task and Run scope do not match")
    if task.identity.task_key not in run.planned_task_keys:
        raise SamplingRuleViolation("Task is outside the frozen Run denominator")
    if task.status not in {SamplingTaskStatus.PLANNED, SamplingTaskStatus.RETRY_READY}:
        raise SamplingRuleViolation("Task is not ready for a new Attempt")
    if attempt_id in task.attempt_ids:
        raise SamplingRuleViolation("Attempt id is already attached to this Task")
    if len(task.attempt_ids) >= task.max_attempts:
        raise SamplingRuleViolation("Task Attempt budget is exhausted")
    not_before = max(run.admitted_not_before, requested_not_before)
    command = SamplingJobCommand(
        project_id=task.project_id,
        run_id=task.run_id,
        task_id=task.id,
        task_key=task.identity.task_key,
        attempt_id=attempt_id,
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
        not_before=not_before,
    )
    job, outbox = build_sampling_job(command=command)
    attempt = SamplingAttempt(
        id=attempt_id,
        project_id=task.project_id,
        run_id=task.run_id,
        task_id=task.id,
        task_key=task.identity.task_key,
        ordinal=len(task.attempt_ids) + 1,
        job=job,
    )
    updated_task = replace(
        task,
        status=SamplingTaskStatus.QUEUED,
        attempt_ids=(*task.attempt_ids, attempt_id),
        version=task.version + 1,
    )
    return AttemptEnqueueResult(updated_task, attempt, outbox)


def claim_sampling_attempt(
    task: SamplingTask,
    attempt: SamplingAttempt,
    *,
    worker_id: str,
    now: datetime,
    lease_for: timedelta,
) -> AttemptTransitionResult:
    _require_current_attempt(task, attempt)
    claimed = claim(attempt.job, worker_id=worker_id, now=now, lease_for=lease_for)
    if claimed.status is JobStatus.CANCELLED:
        status = SamplingTaskStatus.CANCELLED
        terminal = AttemptTerminalStatus.CANCELLED
    elif claimed.status is JobStatus.DEAD_LETTERED:
        status = _failed_task_status(task)
        terminal = AttemptTerminalStatus.FAILED
    else:
        status = SamplingTaskStatus.RUNNING
        terminal = None
    return AttemptTransitionResult(
        replace(task, status=status, version=task.version + 1),
        replace(
            attempt,
            job=claimed,
            record_version=attempt.record_version + 1,
            terminal_status=terminal,
        ),
    )


def heartbeat_sampling_attempt(
    attempt: SamplingAttempt,
    *,
    token: UUID,
    generation: int,
    now: datetime,
    lease_for: timedelta,
) -> SamplingAttempt:
    updated_job = heartbeat(
        attempt.job,
        token=token,
        generation=generation,
        now=now,
        lease_for=lease_for,
    )
    return replace(attempt, job=updated_job, record_version=attempt.record_version + 1)


def begin_sampling_finalization(
    task: SamplingTask,
    attempt: SamplingAttempt,
    *,
    token: UUID,
    generation: int,
    now: datetime,
) -> AttemptTransitionResult:
    _require_current_attempt(task, attempt)
    updated_job = start_finalizing(attempt.job, token=token, generation=generation, now=now)
    return AttemptTransitionResult(
        replace(task, status=SamplingTaskStatus.FINALIZING, version=task.version + 1),
        replace(attempt, job=updated_job, record_version=attempt.record_version + 1),
    )


def finalize_sampling_observation(
    task: SamplingTask,
    attempt: SamplingAttempt,
    *,
    suite: SamplingSuite,
    token: UUID,
    generation: int,
    now: datetime,
    evidence_status: EvidenceStatus,
    ineligible_reasons: tuple[str, ...],
    evidence: ObservationEvidence,
    actual_location: SamplingActualLocationLineage | None = None,
) -> ObservationCommitResult:
    """Complete the Durable Job before exposing a winning Observation."""
    _require_current_attempt(task, attempt)
    _require_suite_identity(task, suite)
    result_id = observation_id(
        task.identity,
        attempt_id=attempt.id,
        evidence=evidence,
        actual_location=actual_location,
    )
    completed_job = complete(
        attempt.job,
        token=token,
        generation=generation,
        now=now,
        result_ref=f"sampling-observation:{result_id}",
    )
    observation = SamplingObservation(
        id=result_id,
        project_id=task.project_id,
        run_id=task.run_id,
        task_id=task.id,
        task_key=task.identity.task_key,
        winning_attempt_id=attempt.id,
        source_stratum=suite.source_stratum,
        source_stratum_hash=suite.source_stratum.stratum_hash,
        actual_location=actual_location,
        evidence_status=evidence_status,
        ineligible_reasons=ineligible_reasons,
        evidence=evidence,
        observed_at=now,
    )
    updated_attempt = replace(
        attempt,
        job=completed_job,
        record_version=attempt.record_version + 1,
        provider_response_id=evidence.provider_response_id,
        egress_verification_id=evidence.egress_verification_id,
        raw_artifact_hash=evidence.raw_artifact.content_hash,
        actual_location=actual_location,
        terminal_status=AttemptTerminalStatus.SUCCEEDED,
    )
    updated_task = replace(task, status=SamplingTaskStatus.SUCCEEDED, version=task.version + 1)
    return ObservationCommitResult(updated_task, updated_attempt, observation)


def fail_sampling_attempt(
    task: SamplingTask,
    attempt: SamplingAttempt,
    *,
    token: UUID,
    generation: int,
    now: datetime,
    error_code: str,
) -> AttemptTransitionResult:
    _require_current_attempt(task, attempt)
    failed_job = fail(
        attempt.job,
        token=token,
        generation=generation,
        now=now,
        error_code=error_code,
        retry_at=None,
    )
    return AttemptTransitionResult(
        replace(task, status=_failed_task_status(task), version=task.version + 1),
        replace(
            attempt,
            job=failed_job,
            record_version=attempt.record_version + 1,
            terminal_status=AttemptTerminalStatus.FAILED,
        ),
    )


def request_sampling_cancel(
    task: SamplingTask,
    attempt: SamplingAttempt,
    *,
    now: datetime,
) -> AttemptTransitionResult:
    _require_current_attempt(task, attempt)
    if attempt.job.status in {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.DEAD_LETTERED,
        JobStatus.CANCELLED,
    }:
        raise SamplingRuleViolation("a terminal Sampling Attempt cannot be cancelled again")
    updated_job = request_cancel(attempt.job, now=now)
    if updated_job.status is JobStatus.CANCELLED:
        task_status = SamplingTaskStatus.CANCELLED
        terminal = AttemptTerminalStatus.CANCELLED
    else:
        task_status = SamplingTaskStatus.CANCEL_REQUESTED
        terminal = None
    return AttemptTransitionResult(
        replace(task, status=task_status, version=task.version + 1),
        replace(
            attempt,
            job=updated_job,
            record_version=attempt.record_version + 1,
            terminal_status=terminal,
        ),
    )


def acknowledge_sampling_cancel(
    task: SamplingTask,
    attempt: SamplingAttempt,
    *,
    token: UUID,
    generation: int,
    now: datetime,
) -> AttemptTransitionResult:
    _require_current_attempt(task, attempt)
    updated_job = acknowledge_cancel(attempt.job, token=token, generation=generation, now=now)
    return AttemptTransitionResult(
        replace(task, status=SamplingTaskStatus.CANCELLED, version=task.version + 1),
        replace(
            attempt,
            job=updated_job,
            record_version=attempt.record_version + 1,
            terminal_status=AttemptTerminalStatus.CANCELLED,
        ),
    )


def _task_identity(
    suite: SamplingSuite,
    question_id: str,
    question_version: str,
    repetition: int,
) -> SamplingTaskIdentity:
    source = suite.source_stratum
    return SamplingTaskIdentity(
        suite_id=suite.id,
        suite_hash=suite.suite_hash,
        platform=source.platform,
        question_id=question_id,
        question_version=question_version,
        repetition=repetition,
        region=source.region,
        language=source.language,
        capture_method=source.capture_method,
        adapter_release=source.adapter_release,
        account_cohort=source.account_cohort,
        egress_policy_category=source.egress_policy_category,
        location_control=source.location_control,
        location_evidence_hash=source.location_evidence_hash,
        requested_country=source.requested_country,
        requested_region=source.requested_region,
        requested_locale=source.requested_locale,
        requested_language=source.requested_language,
        effective_country=source.effective_country,
        effective_region=source.effective_region,
        effective_locale=source.effective_locale,
        effective_language=source.effective_language,
        source_stratum_hash=source.stratum_hash,
    )


def _require_current_attempt(task: SamplingTask, attempt: SamplingAttempt) -> None:
    if (
        attempt.project_id != task.project_id
        or attempt.run_id != task.run_id
        or attempt.task_id != task.id
        or attempt.task_key != task.identity.task_key
        or not task.attempt_ids
        or task.attempt_ids[-1] != attempt.id
    ):
        raise SamplingRuleViolation("Attempt is not the current Attempt for this Task")


def _require_suite_identity(task: SamplingTask, suite: SamplingSuite) -> None:
    source = suite.source_stratum
    if (
        task.project_id != suite.project_id
        or task.identity.suite_id != suite.id
        or task.identity.suite_hash != suite.suite_hash
        or task.identity.source_stratum_hash != source.stratum_hash
        or task.identity.platform != source.platform
        or task.identity.region != source.region
        or task.identity.language != source.language
        or task.identity.capture_method is not source.capture_method
        or task.identity.adapter_release != source.adapter_release
        or task.identity.account_cohort != source.account_cohort
        or task.identity.egress_policy_category != source.egress_policy_category
        or task.identity.location_control is not source.location_control
        or task.identity.location_evidence_hash != source.location_evidence_hash
        or task.identity.requested_country != source.requested_country
        or task.identity.requested_region != source.requested_region
        or task.identity.requested_locale != source.requested_locale
        or task.identity.requested_language != source.requested_language
        or task.identity.effective_country != source.effective_country
        or task.identity.effective_region != source.effective_region
        or task.identity.effective_locale != source.effective_locale
        or task.identity.effective_language != source.effective_language
    ):
        raise SamplingRuleViolation("Task does not belong to the frozen Suite/SourceStratum")


def _failed_task_status(task: SamplingTask) -> SamplingTaskStatus:
    if len(task.attempt_ids) < task.max_attempts:
        return SamplingTaskStatus.RETRY_READY
    return SamplingTaskStatus.FAILED
