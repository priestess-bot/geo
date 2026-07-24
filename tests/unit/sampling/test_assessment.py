from __future__ import annotations

from dataclasses import replace

import pytest

from geo_core.sampling import (
    CaptureMethod,
    RunEvidenceStatus,
    SamplingRuleViolation,
    SamplingRunStatus,
    SamplingTaskStatus,
    assess_sampling_run,
    complete_sampling_run,
)

from tests.unit.sampling.factories import make_observation, make_run, make_source, make_suite


def test_eight_of_ten_valid_provider_slots_is_complete() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    observations = tuple(make_observation(suite, task) for task in tasks[:8])

    result = assess_sampling_run(suite, run, tasks=tasks, observations=observations)

    assert result.status is RunEvidenceStatus.COMPLETE
    assert result.planned_task_count == 10
    assert result.valid_task_count == 8
    assert result.missing_task_count == 2
    assert result.invalid_task_count == 0
    assert result.valid_completion_ratio.as_integer_ratio() == (4, 5)


def test_seven_of_ten_is_insufficient_and_failed_slots_remain_in_denominator() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    observations = tuple(make_observation(suite, task) for task in tasks[:7])

    result = assess_sampling_run(suite, run, tasks=tasks, observations=observations)

    assert result.status is RunEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert result.planned_task_count == 10
    assert result.valid_task_count == 7
    assert result.missing_task_count == 3


def test_ineligible_observation_does_not_count_as_valid_completion() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    observations = tuple(
        make_observation(suite, task, eligible=index < 7)
        for index, task in enumerate(tasks)
    )

    result = assess_sampling_run(suite, run, tasks=tasks, observations=observations)

    assert result.status is RunEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert result.valid_task_count == 7
    assert result.invalid_task_count == 3
    assert result.missing_task_count == 0


def test_each_question_must_meet_its_frozen_repeat_floor() -> None:
    suite = make_suite(question_count=2)
    _, run, tasks = make_run(suite)
    first_question = tuple(task for task in tasks if task.identity.question_id == "q-1")
    second_question = tuple(task for task in tasks if task.identity.question_id == "q-2")
    selected = (*first_question[:6], *second_question)
    observations = tuple(make_observation(suite, task) for task in selected)

    result = assess_sampling_run(suite, run, tasks=tasks, observations=observations)

    assert result.valid_task_count == 16
    assert result.valid_completion_ratio.as_integer_ratio() == (4, 5)
    assert result.sufficient_question_count == 1
    assert result.status is RunEvidenceStatus.INSUFFICIENT_EVIDENCE


def test_manual_three_repeat_floor_requires_all_three_valid() -> None:
    suite = make_suite(CaptureMethod.MANUAL_UI)
    _, run, tasks = make_run(suite)
    observations = tuple(make_observation(suite, task) for task in tasks[:2])

    result = assess_sampling_run(suite, run, tasks=tasks, observations=observations)

    assert result.status is RunEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert result.valid_task_count == 2
    assert result.planned_task_count == 3


def test_task_inventory_cannot_drop_a_failed_slot_to_raise_completion() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    observations = tuple(make_observation(suite, task) for task in tasks[:8])

    with pytest.raises(SamplingRuleViolation, match="inventory"):
        assess_sampling_run(
            suite,
            run,
            tasks=tasks[:8],
            observations=observations,
        )


def test_observations_from_another_capture_method_never_mix_denominators() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    manual_source = make_source(
        CaptureMethod.MANUAL_UI, adapter_release="manual-import@2026-07-23"
    )
    mixed = make_observation(suite, tasks[0], source=manual_source)

    with pytest.raises(SamplingRuleViolation, match="SourceStratum"):
        assess_sampling_run(suite, run, tasks=tasks, observations=(mixed,))


def test_denominator_hash_is_unchanged_by_observation_and_task_status() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    first = assess_sampling_run(suite, run, tasks=tasks, observations=())
    changed_tasks = tuple(replace(task, version=task.version + 1) for task in tasks)
    second = assess_sampling_run(
        suite,
        run,
        tasks=changed_tasks,
        observations=tuple(make_observation(suite, task) for task in tasks[:8]),
    )

    assert first.denominator_hash == second.denominator_hash
    assert first.planned_task_count == second.planned_task_count


def test_run_completion_requires_every_planned_task_to_be_terminal() -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)

    with pytest.raises(SamplingRuleViolation, match="planned Task is active"):
        complete_sampling_run(suite, run, tasks=tasks, observations=())

    failed_tasks = tuple(
        replace(
            task,
            status=SamplingTaskStatus.FAILED,
            version=task.version + 1,
        )
        for task in tasks
    )
    completed, assessment = complete_sampling_run(
        suite, run, tasks=failed_tasks, observations=()
    )

    assert completed.status is SamplingRunStatus.COMPLETED
    assert completed.version == run.version + 1
    assert assessment.status is RunEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert assessment.missing_task_count == suite.planned_task_count


@pytest.mark.parametrize(
    "status",
    (
        SamplingRunStatus.CANCEL_REQUESTED,
        SamplingRunStatus.CANCELLED,
        SamplingRunStatus.FAILED,
    ),
)
def test_cancelled_or_failed_run_cannot_be_completed(status: SamplingRunStatus) -> None:
    suite = make_suite()
    _, run, tasks = make_run(suite)
    terminal_tasks = tuple(
        replace(task, status=SamplingTaskStatus.CANCELLED, version=task.version + 1)
        for task in tasks
    )

    with pytest.raises(SamplingRuleViolation, match="cannot be completed"):
        complete_sampling_run(
            suite,
            replace(run, status=status, version=run.version + 1),
            tasks=terminal_tasks,
            observations=(),
        )
