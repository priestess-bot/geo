from __future__ import annotations

from dataclasses import replace

import pytest

from geo_core.semantic_metrics import (
    METRIC_JUDGE_MAX_RESULTS,
    MetricJudgeCandidate,
    MetricJudgePlan,
    MetricJudgePlanBatch,
    MetricJudgeKind,
    SelectedMetricJudgeBatch,
    SemanticMetricRuleViolation,
    apply_metric_judge_output,
    merge_selected_metric_judge_batches,
    plan_metric_judge_batches,
    resolve_metric_judge_arbiter,
    resolve_metric_judge_candidates,
)
from geo_core.semantic_metrics.program_output import (
    ParsedArbiterProgramOutput,
    ParsedMetricJudgeProgramOutput,
)


def test_metric_judge_plan_binds_versioned_fact_evidence_and_never_drops_results(
    metric_input_set,
    metric_suite,
) -> None:
    observation = metric_input_set.observations[0]
    batches = plan_metric_judge_batches(
        input_set=metric_input_set,
        suite=metric_suite,
        observation=observation,
    )

    assert len(batches) == 1
    batch = batches[0]
    assert batch.ordinal == 1
    assert [item.metric_id for item in batch.plans] == [
        "recommendation",
        "sentiment",
        "fact:fact:battery@fact-v1",
        "fact:fact:warranty@fact-v1",
        "citation:citation-1",
        "citation:citation-2",
        "approved_corpus_absorption",
    ]
    prompt_input = batch.program_input(input_set=metric_input_set)
    evidence = prompt_input["evidence"]
    assert isinstance(evidence, list)
    assert "fact:battery@fact-v1" in {item["ref"] for item in evidence}
    locator_sources = prompt_input["locator_sources"]
    assert isinstance(locator_sources, list)
    assert {
        (item["reference_id"], item["version"])
        for item in locator_sources
        if item["kind"] == "fact"
    } == {("fact:battery", "fact-v1"), ("fact:warranty", "fact-v1")}


def test_metric_judge_batch_rejects_an_unbounded_prompt_result_set(metric_input_set) -> None:
    observation = metric_input_set.observations[0]
    plans = tuple(
        MetricJudgePlan(
            metric_id=f"fact:fixture-{ordinal}",
            metric_kind=MetricJudgeKind.FACT,
            definition="Bounded fixture fact judgement.",
            allowed_evidence_refs=(str(observation.id),),
        )
        for ordinal in range(METRIC_JUDGE_MAX_RESULTS + 1)
    )

    with pytest.raises(SemanticMetricRuleViolation, match="plan count"):
        MetricJudgePlanBatch.create(
            observation=observation,
            ordinal=1,
            plans=plans,
        )


def test_candidate_agreement_skips_arbiter_and_disagreement_requires_exact_selection(
    metric_input_set,
) -> None:
    observation = metric_input_set.observations[0]
    selected_output = replace(
        observation.judge_outputs[0],
        metric_id="recommendation",
    )
    agreed = ParsedMetricJudgeProgramOutput(
        results=(selected_output,),
        overall_status="pass",
        output_locale="en-AU",
    )
    candidate_a = MetricJudgeCandidate.create(
        candidate_id="candidate-a",
        evaluator_id="evaluator-a",
        output=agreed,
    )
    candidate_b = MetricJudgeCandidate.create(
        candidate_id="candidate-b",
        evaluator_id="evaluator-b",
        output=agreed,
    )

    agreement = resolve_metric_judge_candidates((candidate_b, candidate_a))

    assert agreement.arbiter_required is False
    assert agreement.selected_candidate_id == "candidate-a"
    with pytest.raises(SemanticMetricRuleViolation, match="arbiter is forbidden"):
        resolve_metric_judge_arbiter(
            agreement,
            ParsedArbiterProgramOutput(
                disposition="pass",
                selected_candidate_id="candidate-a",
                considered_evaluators=("evaluator-a", "evaluator-b"),
                issue_codes=(),
            ),
        )

    disagreeing = ParsedMetricJudgeProgramOutput(
        results=(replace(selected_output, label="no"),),
        overall_status="warning",
        output_locale="en-AU",
    )
    candidate_c = MetricJudgeCandidate.create(
        candidate_id="candidate-c",
        evaluator_id="evaluator-b",
        output=disagreeing,
    )
    disagreement = resolve_metric_judge_candidates((candidate_a, candidate_c))
    selected = resolve_metric_judge_arbiter(
        disagreement,
        ParsedArbiterProgramOutput(
            disposition="warning",
            selected_candidate_id="candidate-c",
            considered_evaluators=("evaluator-a", "evaluator-b"),
            issue_codes=("judge_disagreement",),
        ),
    )

    assert disagreement.arbiter_required is True
    assert selected.candidate_id == "candidate-c"
    with_output = apply_metric_judge_output(observation, selected)
    with pytest.raises(SemanticMetricRuleViolation, match="duplicate a metric ID"):
        apply_metric_judge_output(with_output, selected)


def test_metric_parent_merge_requires_every_current_frozen_batch(
    metric_input_set, metric_suite
) -> None:
    selected = tuple(
        SelectedMetricJudgeBatch(batch=batch, candidate=_candidate_for(batch))
        for observation in metric_input_set.observations
        for batch in plan_metric_judge_batches(
            input_set=metric_input_set,
            suite=metric_suite,
            observation=observation,
        )
    )

    merged = merge_selected_metric_judge_batches(
        input_set=metric_input_set,
        suite=metric_suite,
        selected_batches=selected,
    )

    assert all(
        {item.metric_id for item in observation.judge_outputs if item.metric_id is not None}
        for observation in merged.observations
    )
    with pytest.raises(SemanticMetricRuleViolation, match="incomplete"):
        merge_selected_metric_judge_batches(
            input_set=metric_input_set,
            suite=metric_suite,
            selected_batches=selected[:-1],
        )


def test_metric_parent_merge_rejects_a_valid_result_rebound_to_the_wrong_plan(
    metric_input_set, metric_suite
) -> None:
    selected = tuple(
        SelectedMetricJudgeBatch(batch=batch, candidate=_candidate_for(batch))
        for observation in metric_input_set.observations
        for batch in plan_metric_judge_batches(
            input_set=metric_input_set,
            suite=metric_suite,
            observation=observation,
        )
    )
    first = selected[0]
    wrong_kind = replace(
        first.batch.observation.judge_outputs[-1],
        metric_id=first.batch.plans[0].metric_id,
    )
    rebound = MetricJudgeCandidate.create(
        candidate_id=first.candidate.candidate_id,
        evaluator_id=first.candidate.evaluator_id,
        output=ParsedMetricJudgeProgramOutput(
            results=(wrong_kind, *first.candidate.output.results[1:]),
            overall_status="pass",
            output_locale="en-AU",
        ),
    )
    tampered = (SelectedMetricJudgeBatch(batch=first.batch, candidate=rebound), *selected[1:])

    with pytest.raises(SemanticMetricRuleViolation, match="result kind changed"):
        merge_selected_metric_judge_batches(
            input_set=metric_input_set,
            suite=metric_suite,
            selected_batches=tampered,
        )


def _candidate_for(batch: MetricJudgePlanBatch) -> MetricJudgeCandidate:
    outputs = tuple(
        replace(_output_for_plan(batch, plan), metric_id=plan.metric_id)
        for plan in batch.plans
    )
    parsed = ParsedMetricJudgeProgramOutput(
        results=outputs,
        overall_status="pass",
        output_locale="en-AU",
    )
    return MetricJudgeCandidate.create(
        candidate_id=f"candidate:{batch.observation.id}:{batch.ordinal}",
        evaluator_id=f"judge:{batch.observation.id}:{batch.ordinal}",
        output=parsed,
    )


def _output_for_plan(batch: MetricJudgePlanBatch, plan: MetricJudgePlan):
    if plan.metric_kind is MetricJudgeKind.FACT:
        reference = plan.metric_id.removeprefix("fact:")
        return next(
            output
            for output in batch.observation.judge_outputs
            if output.kind.value == plan.metric_kind.value
            and any(
                f"{locator.reference_id}@{locator.version}" == reference
                for locator in output.locators
                if locator.kind.value == "fact"
            )
        )
    if plan.metric_kind is MetricJudgeKind.CITATION_ENTAILMENT:
        reference = plan.metric_id.removeprefix("citation:")
        return next(
            output
            for output in batch.observation.judge_outputs
            if output.kind.value == plan.metric_kind.value
            and any(
                locator.reference_id == reference
                for locator in output.locators
                if locator.kind.value == "citation"
            )
        )
    return next(
        output
        for output in batch.observation.judge_outputs
        if output.kind.value == plan.metric_kind.value
    )
