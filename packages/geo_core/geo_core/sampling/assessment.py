"""Frozen-denominator completion assessment for Sampling Runs."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from decimal import Decimal

from geo_core.sampling.contracts import (
    RunEvidenceStatus,
    SamplingRuleViolation,
    SamplingRun,
    SamplingRunAssessment,
    SamplingRunStatus,
    SamplingSuite,
    SamplingTask,
    SamplingTaskStatus,
    canonical_hash,
)
from geo_core.sampling.execution import SamplingObservation


TERMINAL_TASK_STATUSES = frozenset(
    {
        SamplingTaskStatus.SUCCEEDED,
        SamplingTaskStatus.FAILED,
        SamplingTaskStatus.CANCELLED,
    }
)


def assess_sampling_run(
    suite: SamplingSuite,
    run: SamplingRun,
    *,
    tasks: tuple[SamplingTask, ...],
    observations: tuple[SamplingObservation, ...],
) -> SamplingRunAssessment:
    """Assess evidence without removing failed, cancelled, or missing planned slots."""
    _validate_run(suite, run)
    task_by_key = _validate_tasks(suite, run, tasks)
    observation_by_key = _validate_observations(suite, run, task_by_key, observations)

    valid_keys = {
        key for key, observation in observation_by_key.items() if observation.included_in_metrics
    }
    invalid_count = len(observation_by_key) - len(valid_keys)
    missing_count = len(run.planned_task_keys) - len(observation_by_key)
    valid_by_question = Counter(task_by_key[key].identity.question_id for key in valid_keys)
    sufficient_questions = sum(
        valid_by_question[question.question_id] >= suite.minimum_valid_repeats
        for question in suite.questions
    )
    planned_count = len(run.planned_task_keys)
    valid_count = len(valid_keys)
    completion_ratio = Decimal(valid_count) / Decimal(planned_count)
    globally_sufficient = valid_count * 5 >= planned_count * 4
    status = (
        RunEvidenceStatus.COMPLETE
        if globally_sufficient and sufficient_questions == len(suite.questions)
        else RunEvidenceStatus.INSUFFICIENT_EVIDENCE
    )
    return SamplingRunAssessment(
        run_id=run.id,
        planned_task_count=planned_count,
        valid_task_count=valid_count,
        invalid_task_count=invalid_count,
        missing_task_count=missing_count,
        valid_completion_ratio=completion_ratio,
        sufficient_question_count=sufficient_questions,
        question_count=len(suite.questions),
        status=status,
        denominator_hash=canonical_hash(list(run.planned_task_keys)),
    )


def complete_sampling_run(
    suite: SamplingSuite,
    run: SamplingRun,
    *,
    tasks: tuple[SamplingTask, ...],
    observations: tuple[SamplingObservation, ...],
) -> tuple[SamplingRun, SamplingRunAssessment]:
    assessment = assess_sampling_run(suite, run, tasks=tasks, observations=observations)
    if run.status in {
        SamplingRunStatus.CANCEL_REQUESTED,
        SamplingRunStatus.CANCELLED,
        SamplingRunStatus.FAILED,
    }:
        raise SamplingRuleViolation("A cancelled or failed Run cannot be completed")
    if any(task.status not in TERMINAL_TASK_STATUSES for task in tasks):
        raise SamplingRuleViolation("Run cannot complete while a planned Task is active")
    if run.status is SamplingRunStatus.COMPLETED:
        return run, assessment
    return (
        replace(
            run,
            status=SamplingRunStatus.COMPLETED,
            version=run.version + 1,
        ),
        assessment,
    )


def _validate_run(suite: SamplingSuite, run: SamplingRun) -> None:
    if (
        run.project_id != suite.project_id
        or run.suite_id != suite.id
        or run.suite_hash != suite.suite_hash
        or len(run.planned_task_keys) != suite.planned_task_count
    ):
        raise SamplingRuleViolation("Run does not match its frozen Sampling Suite")


def _validate_tasks(
    suite: SamplingSuite,
    run: SamplingRun,
    tasks: tuple[SamplingTask, ...],
) -> dict[str, SamplingTask]:
    task_by_key: dict[str, SamplingTask] = {}
    question_versions = {
        question.question_id: question.question_version for question in suite.questions
    }
    source = suite.source_stratum
    for task in tasks:
        key = task.identity.task_key
        if key in task_by_key:
            raise SamplingRuleViolation("Run contains duplicate Task identities")
        if (
            task.project_id != run.project_id
            or task.run_id != run.id
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
            or question_versions.get(task.identity.question_id) != task.identity.question_version
            or task.identity.repetition > suite.repetitions
        ):
            raise SamplingRuleViolation("Task escaped the frozen Run SourceStratum")
        task_by_key[key] = task
    if set(task_by_key) != set(run.planned_task_keys):
        raise SamplingRuleViolation("Task inventory differs from the planned denominator")
    return task_by_key


def _validate_observations(
    suite: SamplingSuite,
    run: SamplingRun,
    task_by_key: dict[str, SamplingTask],
    observations: tuple[SamplingObservation, ...],
) -> dict[str, SamplingObservation]:
    observation_by_key: dict[str, SamplingObservation] = {}
    for observation in observations:
        key = observation.task_key
        task = task_by_key.get(key)
        if task is None or key in observation_by_key:
            raise SamplingRuleViolation("Observation is duplicate or outside the Run denominator")
        if (
            observation.project_id != run.project_id
            or observation.run_id != run.id
            or observation.task_id != task.id
            or observation.source_stratum != suite.source_stratum
            or observation.source_stratum_hash != suite.source_stratum.stratum_hash
        ):
            raise SamplingRuleViolation("Observation escaped the frozen SourceStratum")
        observation_by_key[key] = observation
    return observation_by_key
