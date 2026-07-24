from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
from typing import TypedDict
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from geo_core.synthetic_lab import (
    CorpusRole,
    CorpusVersion,
    ExperimentArm,
    FinalizationGuard,
    FrozenExperimentQuestion,
    OfflineExperimentPlan,
    OfflineSlotResult,
    ReviewRunStatus,
    ScenarioMode,
    SyntheticLabContractError,
    SyntheticLabScopeError,
    candidate_entry_from_resolution,
    corpus_candidate_set_hash,
    create_offline_experiment_plan,
    finalize_offline_experiment,
    freeze_corpus_version,
    make_slot_result,
    planned_experiment_slots,
)
from geo_core.synthetic_lab.revision import CandidateResolution


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _CorpusContext(TypedDict):
    project_id: UUID
    fact_snapshot_id: UUID
    fact_snapshot_hash: str
    profile_version_id: UUID
    profile_hash: str
    prompt_release_id: UUID
    prompt_release_hash: str


def _resolution(
    project_id: UUID,
    status: ReviewRunStatus,
    *,
    channel: str = "reddit",
    mode: ScenarioMode = ScenarioMode.AUTONOMOUS,
) -> CandidateResolution:
    candidate_id = uuid4()
    return CandidateResolution(
        id=uuid4(),
        project_id=project_id,
        review_run_id=uuid4(),
        review_case_id=uuid4(),
        candidate_id=candidate_id,
        candidate_output_hash=_hash(f"candidate-{candidate_id}"),
        evaluation_id=uuid4(),
        evaluation_evidence_hash=_hash(f"evaluation-{candidate_id}"),
        channel=channel,
        scenario_mode=mode,
        status=status,
        warning_codes=("derived_or_unknown", "minor_tone")
        if status == ReviewRunStatus.COMPLETED_WITH_WARNING
        else (),
        failure_code="unresolved_conflict" if status == ReviewRunStatus.FAILED else None,
    )


def _entry(
    resolution: CandidateResolution,
    *,
    competitor: bool = False,
    model_key: str = "generator-a",
    cluster: str = "comparison",
):
    return candidate_entry_from_resolution(
        resolution,
        competitor_scenario=competitor,
        model_key=model_key,
        model_identity_hash=_hash(f"model-{model_key}"),
        question_cluster_key=cluster,
    )


def _guard(
    *,
    project_id: UUID,
    resource_id: UUID,
    fact_snapshot_id: UUID,
    fact_snapshot_hash: str,
    **changes: object,
) -> FinalizationGuard:
    lease_id = uuid4()
    values: dict[str, object] = {
        "project_id": project_id,
        "resource_id": resource_id,
        "expected_lease_id": lease_id,
        "held_lease_id": lease_id,
        "expected_fencing_token": 7,
        "held_fencing_token": 7,
        "fact_snapshot_id": fact_snapshot_id,
        "fact_snapshot_hash": fact_snapshot_hash,
        "facts_current_approved": True,
        "cancelled": False,
    }
    values.update(changes)
    return FinalizationGuard(**values)  # type: ignore[arg-type]


def _freeze_corpus(
    *,
    project_id: UUID,
    role: CorpusRole,
    fact_snapshot_id: UUID,
    fact_snapshot_hash: str,
    profile_version_id: UUID,
    profile_hash: str,
    prompt_release_id: UUID,
    prompt_release_hash: str,
    candidates=(),
) -> CorpusVersion:
    version_id = uuid4()
    guard = _guard(
        project_id=project_id,
        resource_id=version_id,
        fact_snapshot_id=fact_snapshot_id,
        fact_snapshot_hash=fact_snapshot_hash,
    )
    return freeze_corpus_version(
        id=version_id,
        project_id=project_id,
        corpus_id=uuid4(),
        version_number=1,
        role=role,
        approved_fact_snapshot_id=fact_snapshot_id,
        approved_fact_snapshot_hash=fact_snapshot_hash,
        profile_version_id=profile_version_id,
        profile_hash=profile_hash,
        prompt_release_id=prompt_release_id,
        prompt_release_hash=prompt_release_hash,
        candidates=tuple(candidates),
        guard=guard,
    )


def _corpora(project_id: UUID):
    fact_id = uuid4()
    fact_hash = _hash("approved-facts-v1")
    profile_id = uuid4()
    profile_hash = _hash("profile-v1")
    prompt_id = uuid4()
    prompt_hash = _hash("corpus-prompt-v1")
    passed = _entry(_resolution(project_id, ReviewRunStatus.PASSED))
    warning = _entry(
        _resolution(
            project_id,
            ReviewRunStatus.COMPLETED_WITH_WARNING,
            channel="quora",
            mode=ScenarioMode.GUIDED,
        ),
        competitor=True,
        model_key="generator-b",
        cluster="competitor-comparison",
    )
    common: _CorpusContext = {
        "project_id": project_id,
        "fact_snapshot_id": fact_id,
        "fact_snapshot_hash": fact_hash,
        "profile_version_id": profile_id,
        "profile_hash": profile_hash,
        "prompt_release_id": prompt_id,
        "prompt_release_hash": prompt_hash,
    }
    baseline = _freeze_corpus(role=CorpusRole.NO_CORPUS_BASELINE, **common)
    current = _freeze_corpus(
        role=CorpusRole.CURRENT_APPROVED,
        candidates=(passed,),
        **common,
    )
    candidate = _freeze_corpus(
        role=CorpusRole.NEW_CANDIDATE,
        candidates=(passed, warning),
        **common,
    )
    return (baseline, current, candidate)


def _questions(project_id: UUID) -> tuple[FrozenExperimentQuestion, ...]:
    return tuple(
        FrozenExperimentQuestion(
            project_id=project_id,
            question_version_id=uuid5(NAMESPACE_URL, f"question-{ordinal}"),
            ordinal=ordinal,
            question_hash=_hash(f"question-{ordinal}"),
            question_cluster_key="comparison" if ordinal == 1 else "use-case",
        )
        for ordinal in range(1, 3)
    )


def _plan(
    project_id: UUID,
    corpora: tuple[CorpusVersion, ...],
    *,
    plan_id: UUID | None = None,
    minimum_valid_pair_ratio: float = 0.8,
    repetitions_per_question: int = 10,
) -> OfflineExperimentPlan:
    baseline = corpora[0]
    return create_offline_experiment_plan(
        id=plan_id or uuid4(),
        project_id=project_id,
        question_set_id=uuid5(NAMESPACE_URL, "question-set-v1"),
        question_set_hash=_hash("question-set-v1"),
        protocol_id=uuid5(NAMESPACE_URL, "offline-protocol-v1"),
        protocol_hash=_hash("offline-protocol-v1"),
        prompt_release_id=uuid5(NAMESPACE_URL, "experiment-prompt-v1"),
        prompt_release_hash=_hash("experiment-prompt-v1"),
        approved_fact_snapshot_id=baseline.approved_fact_snapshot_id,
        approved_fact_snapshot_hash=baseline.approved_fact_snapshot_hash,
        profile_version_id=baseline.profile_version_id,
        profile_hash=baseline.profile_hash,
        model_policy_hash=_hash("offline-model-policy-v1"),
        model_provider="test-provider",
        configured_model="offline-model-v1",
        reported_model="offline-model-v1-202607",
        model_identity_hash=_hash("offline-model-v1-202607"),
        metric_method_release="offline-metric-v1",
        metric_method_hash=_hash("offline-metric-v1"),
        seed_namespace_hash=_hash("offline-seed-namespace-v1"),
        questions=_questions(project_id),
        corpora=corpora,
        repetitions_per_question=repetitions_per_question,
        minimum_valid_pair_ratio=minimum_valid_pair_ratio,
    )


def _valid_result(slot, *, metric: float | None = None) -> OfflineSlotResult:
    value = metric
    if value is None:
        value = {
            ExperimentArm.NO_CORPUS_BASELINE: 0.2,
            ExperimentArm.CURRENT_APPROVED_CORPUS: 0.5,
            ExperimentArm.NEW_CANDIDATE_CORPUS: 0.7,
        }[slot.arm]
    return make_slot_result(
        slot,
        valid=True,
        metric_value=value,
        model_call_id=uuid5(NAMESPACE_URL, f"call-{slot.slot_id}"),
        request_hash=_hash(f"request-{slot.slot_id}"),
        response_hash=_hash(f"response-{slot.slot_id}"),
        answer_hash=_hash(f"answer-{slot.slot_id}"),
        citation_hash=_hash(f"citations-{slot.slot_id}"),
    )


def _invalid_result(slot) -> OfflineSlotResult:
    return make_slot_result(slot, valid=False, invalid_reason="provider_timeout")


def _experiment_guard(plan: OfflineExperimentPlan, **changes: object) -> FinalizationGuard:
    return _guard(
        project_id=plan.project_id,
        resource_id=plan.id,
        fact_snapshot_id=plan.approved_fact_snapshot_id,
        fact_snapshot_hash=plan.approved_fact_snapshot_hash,
        **changes,
    )


def test_corpus_roles_freeze_passed_warning_membership_and_all_warning_strata() -> None:
    project_id = uuid4()
    baseline, current, candidate = _corpora(project_id)

    assert baseline.role == CorpusRole.NO_CORPUS_BASELINE
    assert baseline.candidates == ()
    assert current.passed_count == 1
    assert candidate.passed_count == 1
    assert candidate.warning_count == 1
    assert candidate.warning_ratio == 0.5
    assert candidate.warning_by_code == {"derived_or_unknown": 1, "minor_tone": 1}
    assert candidate.warning_by_channel == {"quora": 1}
    assert candidate.warning_by_scenario_mode == {"guided_scenario": 1}
    assert candidate.warning_by_competitor == {"competitor": 1}
    assert candidate.warning_by_model == {"generator-b": 1}
    assert candidate.warning_by_question_cluster == {"competitor-comparison": 1}
    assert candidate.candidate_set_hash == corpus_candidate_set_hash(
        tuple(reversed(candidate.candidates))
    )
    with pytest.raises(FrozenInstanceError):
        candidate.warning_count = 0
    with pytest.raises(SyntheticLabContractError, match="failed Candidate"):
        _entry(_resolution(project_id, ReviewRunStatus.FAILED))


@pytest.mark.parametrize(
    ("guard_changes", "message"),
    [
        ({"cancelled": True}, "cancelled"),
        ({"facts_current_approved": False}, "retired Fact"),
        ({"held_lease_id": None}, "lost lease"),
        ({"held_fencing_token": 8}, "stale fencing"),
    ],
)
def test_corpus_finalize_rejects_cancelled_stale_lease_or_retired_fact(
    guard_changes: dict[str, object],
    message: str,
) -> None:
    project_id = uuid4()
    version_id = uuid4()
    fact_id = uuid4()
    fact_hash = _hash("facts")
    resolution = _resolution(project_id, ReviewRunStatus.PASSED)
    guard = _guard(
        project_id=project_id,
        resource_id=version_id,
        fact_snapshot_id=fact_id,
        fact_snapshot_hash=fact_hash,
        **guard_changes,
    )
    with pytest.raises(SyntheticLabContractError, match=message):
        freeze_corpus_version(
            id=version_id,
            project_id=project_id,
            corpus_id=uuid4(),
            version_number=1,
            role=CorpusRole.NEW_CANDIDATE,
            approved_fact_snapshot_id=fact_id,
            approved_fact_snapshot_hash=fact_hash,
            profile_version_id=uuid4(),
            profile_hash=_hash("profile"),
            prompt_release_id=uuid4(),
            prompt_release_hash=_hash("prompt"),
            candidates=(_entry(resolution),),
            guard=guard,
        )


def test_plan_builds_three_arms_ten_repetitions_and_shared_pair_seed() -> None:
    project_id = uuid4()
    corpora = _corpora(project_id)
    plan = _plan(project_id, corpora)
    slots = planned_experiment_slots(plan)

    assert len(slots) == 2 * 10 * 3
    pair_ids = {slot.pair_id for slot in slots}
    assert len(pair_ids) == 20
    for pair_id in pair_ids:
        paired = [slot for slot in slots if slot.pair_id == pair_id]
        assert {slot.arm for slot in paired} == set(ExperimentArm)
        assert len({slot.deterministic_seed for slot in paired}) == 1
        assert len({slot.input_hash for slot in paired}) == 3
    rebuilt = _plan(project_id, corpora, plan_id=uuid4())
    rebuilt_slots = planned_experiment_slots(rebuilt)
    assert rebuilt.input_hash == plan.input_hash
    assert [item.pair_id for item in rebuilt_slots] == [item.pair_id for item in slots]
    assert [item.slot_id for item in rebuilt_slots] == [item.slot_id for item in slots]
    with pytest.raises(SyntheticLabContractError, match="exactly 10"):
        _plan(project_id, corpora, repetitions_per_question=9)
    with pytest.raises(SyntheticLabContractError, match="frozen hash"):
        replace(plan, protocol_hash=_hash("changed-protocol"))


def test_slot_results_are_explicitly_valid_or_invalid_and_hash_stable() -> None:
    project_id = uuid4()
    slot = planned_experiment_slots(_plan(project_id, _corpora(project_id)))[0]
    valid = _valid_result(slot)
    invalid = _invalid_result(slot)

    assert valid.valid and valid.metric_value == 0.2
    assert not invalid.valid and invalid.invalid_reason == "provider_timeout"
    assert _valid_result(slot).result_hash == valid.result_hash
    with pytest.raises(SyntheticLabContractError, match="deterministic hash"):
        replace(valid, metric_value=0.9)
    with pytest.raises(SyntheticLabContractError, match="cannot enter"):
        replace(invalid, metric_value=0.1)


def test_finalize_combines_passed_warning_metrics_and_keeps_warning_layers() -> None:
    project_id = uuid4()
    plan = _plan(project_id, _corpora(project_id))
    results = tuple(_valid_result(slot) for slot in planned_experiment_slots(plan))
    finalized = finalize_offline_experiment(
        result_id=uuid4(),
        plan=plan,
        slot_results=results,
        guard=_experiment_guard(plan),
    )

    assert finalized.planned_pair_count == 20
    assert finalized.valid_pair_count == 20
    assert finalized.invalid_pair_count == 0
    assert finalized.completion_ratio == 1
    summaries = {summary.arm: summary for summary in finalized.arm_summaries}
    assert summaries[ExperimentArm.NO_CORPUS_BASELINE].overall_metric == pytest.approx(0.2)
    assert summaries[ExperimentArm.CURRENT_APPROVED_CORPUS].overall_metric == pytest.approx(0.5)
    candidate = summaries[ExperimentArm.NEW_CANDIDATE_CORPUS]
    assert candidate.overall_metric == pytest.approx(0.7)
    assert candidate.corpus_candidate_count == 2
    assert candidate.corpus_passed_count == 1
    assert candidate.corpus_warning_count == 1
    assert candidate.corpus_warning_ratio == 0.5
    assert candidate.warning_by_code == {"derived_or_unknown": 1, "minor_tone": 1}

    reordered = finalize_offline_experiment(
        result_id=uuid4(),
        plan=plan,
        slot_results=tuple(reversed(results)),
        guard=_experiment_guard(plan),
    )
    assert reordered.slot_membership_hash == finalized.slot_membership_hash
    assert reordered.result_hash == finalized.result_hash


def test_finalize_rejects_missing_or_unpaired_slots() -> None:
    project_id = uuid4()
    plan = _plan(project_id, _corpora(project_id))
    slots = planned_experiment_slots(plan)
    results = tuple(_valid_result(slot) for slot in slots)
    guard = _experiment_guard(plan)

    with pytest.raises(SyntheticLabContractError, match="every planned slot"):
        finalize_offline_experiment(
            result_id=uuid4(),
            plan=plan,
            slot_results=results[:-1],
            guard=guard,
        )
    first_pair = slots[0].pair_id
    unpaired = tuple(
        _invalid_result(slot)
        if slot.pair_id == first_pair and slot.arm == ExperimentArm.NO_CORPUS_BASELINE
        else result
        for slot, result in zip(slots, results, strict=True)
    )
    with pytest.raises(SyntheticLabContractError, match="cannot mix"):
        finalize_offline_experiment(
            result_id=uuid4(),
            plan=plan,
            slot_results=unpaired,
            guard=guard,
        )


def _results_with_invalid_pairs(plan: OfflineExperimentPlan, invalid_pair_count: int):
    slots = planned_experiment_slots(plan)
    invalid_pairs = sorted({slot.pair_id for slot in slots})[:invalid_pair_count]
    return tuple(
        _invalid_result(slot) if slot.pair_id in invalid_pairs else _valid_result(slot)
        for slot in slots
    )


def test_finalize_applies_frozen_completion_ratio_to_complete_paired_units() -> None:
    project_id = uuid4()
    plan = _plan(project_id, _corpora(project_id))
    guard = _experiment_guard(plan)

    accepted = finalize_offline_experiment(
        result_id=uuid4(),
        plan=plan,
        slot_results=_results_with_invalid_pairs(plan, 4),
        guard=guard,
    )
    assert accepted.valid_pair_count == 16
    assert accepted.invalid_pair_count == 4
    assert accepted.completion_ratio == 0.8
    assert all(summary.valid_slot_count == 16 for summary in accepted.arm_summaries)
    assert all(summary.invalid_slot_count == 4 for summary in accepted.arm_summaries)

    with pytest.raises(SyntheticLabContractError, match="below the frozen minimum"):
        finalize_offline_experiment(
            result_id=uuid4(),
            plan=plan,
            slot_results=_results_with_invalid_pairs(plan, 5),
            guard=guard,
        )


@pytest.mark.parametrize(
    ("guard_changes", "message"),
    [
        ({"cancelled": True}, "cancelled"),
        ({"facts_current_approved": False}, "retired Fact"),
        ({"held_lease_id": None}, "lost lease"),
        ({"held_fencing_token": 6}, "stale fencing"),
    ],
)
def test_experiment_finalize_fails_closed_on_guard_loss(
    guard_changes: dict[str, object],
    message: str,
) -> None:
    project_id = uuid4()
    plan = _plan(project_id, _corpora(project_id))
    results = tuple(_valid_result(slot) for slot in planned_experiment_slots(plan))
    with pytest.raises(SyntheticLabContractError, match=message):
        finalize_offline_experiment(
            result_id=uuid4(),
            plan=plan,
            slot_results=results,
            guard=_experiment_guard(plan, **guard_changes),
        )


def test_corpus_plan_slots_and_results_remain_synthetic_test_only_nonpublication() -> None:
    project_id = uuid4()
    corpora = _corpora(project_id)
    plan = _plan(project_id, corpora)
    slots = planned_experiment_slots(plan)
    slot_results = tuple(_valid_result(slot) for slot in slots)
    finalized = finalize_offline_experiment(
        result_id=uuid4(),
        plan=plan,
        slot_results=slot_results,
        guard=_experiment_guard(plan),
    )
    resources = (
        *corpora,
        *(item for corpus in corpora for item in corpus.candidates),
        plan,
        *plan.questions,
        *slots,
        *slot_results,
        finalized,
        *finalized.arm_summaries,
    )

    assert all(item.synthetic for item in resources)
    assert all(item.test_only for item in resources)
    assert not any(item.publication_eligible for item in resources)


def test_cross_project_corpus_cannot_enter_experiment() -> None:
    project_id = uuid4()
    corpora = list(_corpora(project_id))
    other_project_corpus = _corpora(uuid4())[0]
    with pytest.raises(SyntheticLabScopeError, match="different Projects"):
        _plan(project_id, tuple([other_project_corpus] + corpora[1:]))
