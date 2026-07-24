from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest

from geo_core.synthetic_lab import (
    CandidateEvaluation,
    CandidateResolution,
    CandidateRevision,
    ClaimAssessment,
    EvaluationDisposition,
    FactStatus,
    FrozenCallLineage,
    GeneratedCandidate,
    GenerationBatch,
    GenerationBatchKind,
    ReviewCase,
    ReviewRunResult,
    ReviewRunStatus,
    RevisedCandidate,
    ScenarioMode,
    SyntheticLabContractError,
    SyntheticLabScopeError,
    WorkflowAction,
    assert_evaluation_for_candidate,
    assert_fact_snapshot_current,
    assert_generation_batch_for_case,
    assert_generation_history,
    assert_revision_chain,
    decide_next_step,
    resolution_from_decision,
    review_case_content_hash,
    revision_issue_set_hash,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _case(
    *,
    project_id: UUID | None = None,
    suite_version_id: UUID | None = None,
    ordinal: int = 1,
    mode: ScenarioMode = ScenarioMode.AUTONOMOUS,
) -> ReviewCase:
    values: dict[str, object] = {
        "id": uuid4(),
        "project_id": project_id or uuid4(),
        "review_suite_version_id": suite_version_id or uuid4(),
        "review_suite_version_number": 1,
        "case_key": f"reddit-case-{ordinal}",
        "ordinal": ordinal,
        "mode": mode,
        "channel": "reddit",
        "persona": "Australian home workshop owner",
        "use_case": "compare two compact pressure washers",
        "subject": "Acme PW-20",
        "question_set_version_id": uuid4(),
        "question_set_hash": _hash("question-set-v1"),
        "fact_snapshot_id": uuid4(),
        "fact_snapshot_hash": _hash("facts-v1"),
        "profile_version_id": uuid4(),
        "profile_hash": _hash("reddit-profile-v1"),
        "competitor_scenario": True,
        "expected_risks": ("subject_mixup", "explicit_conflict"),
        "creative_reference": "Keep the scenario in a small garage."
        if mode == ScenarioMode.GUIDED
        else None,
    }
    hash_values = {
        key: values[key]
        for key in (
            "case_key",
            "ordinal",
            "mode",
            "channel",
            "persona",
            "use_case",
            "subject",
            "question_set_version_id",
            "question_set_hash",
            "fact_snapshot_id",
            "fact_snapshot_hash",
            "profile_version_id",
            "profile_hash",
            "competitor_scenario",
            "expected_risks",
            "creative_reference",
        )
    }
    values["content_hash"] = review_case_content_hash(**hash_values)  # type: ignore[arg-type]
    return ReviewCase(**values)  # type: ignore[arg-type]


def _lineage(
    case: ReviewCase,
    review_run_id: UUID,
    *,
    program_kind: str = "generation",
    **changes: object,
) -> FrozenCallLineage:
    values: dict[str, object] = {
        "project_id": case.project_id,
        "review_run_id": review_run_id,
        "review_suite_version_id": case.review_suite_version_id,
        "review_suite_hash": _hash("suite-v1"),
        "review_case_id": case.id,
        "review_case_hash": case.content_hash,
        "program_kind": program_kind,
        "prompt_release_id": uuid4(),
        "prompt_release_hash": _hash(f"{program_kind}-prompt-v1"),
        "profile_version_id": case.profile_version_id,
        "profile_hash": case.profile_hash,
        "fact_snapshot_id": case.fact_snapshot_id,
        "fact_snapshot_hash": case.fact_snapshot_hash,
        "model_policy_hash": _hash("model-policy-v1"),
        "model_call_id": uuid4(),
        "provider": "test-provider",
        "configured_model": "judge-v1",
        "reported_model": "judge-v1-202607",
        "model_identity_hash": _hash("judge-v1-202607"),
        "request_hash": _hash(f"request-{uuid4()}"),
        "response_hash": _hash(f"response-{uuid4()}"),
    }
    values.update(changes)
    return FrozenCallLineage(**values)  # type: ignore[arg-type]


def _batch(
    case: ReviewCase,
    review_run_id: UUID,
    *,
    kind: GenerationBatchKind = GenerationBatchKind.INITIAL,
    lineage_changes: dict[str, object] | None = None,
) -> GenerationBatch:
    batch_id = uuid4()
    batch_number = 1 if kind == GenerationBatchKind.INITIAL else 2
    candidates = tuple(
        GeneratedCandidate(
            id=uuid4(),
            project_id=case.project_id,
            review_run_id=review_run_id,
            review_case_id=case.id,
            generation_batch_id=batch_id,
            batch_number=batch_number,
            ordinal=ordinal,
            output_hash=_hash(f"{batch_id}-candidate-{ordinal}"),
            artifact_hash=_hash(f"{batch_id}-artifact-{ordinal}"),
        )
        for ordinal in range(1, 5)
    )
    lineage = _lineage(case, review_run_id)
    if lineage_changes:
        lineage = replace(lineage, **lineage_changes)  # type: ignore[arg-type]
    return GenerationBatch(
        id=batch_id,
        project_id=case.project_id,
        review_run_id=review_run_id,
        review_case_id=case.id,
        batch_number=batch_number,
        kind=kind,
        scenario_mode=case.mode,
        creative_reference=case.creative_reference,
        call_lineage=lineage,
        candidates=candidates,
    )


def _assessment(status: FactStatus) -> ClaimAssessment:
    claim_hash = _hash(f"claim-{status.value}-{uuid4()}")
    if status in {FactStatus.CURRENT_APPROVED, FactStatus.EXPLICIT_CONFLICT}:
        return ClaimAssessment(
            claim_hash=claim_hash,
            status=status,
            fact_id=uuid4(),
            fact_hash=_hash("approved-fact"),
        )
    if status == FactStatus.DERIVED_OR_UNKNOWN:
        return ClaimAssessment(
            claim_hash=claim_hash,
            status=status,
            output_annotation=FactStatus.DERIVED_OR_UNKNOWN.value,
        )
    return ClaimAssessment(
        claim_hash=claim_hash,
        status=status,
        expected_subject_id=uuid4(),
        observed_subject_id=uuid4(),
    )


def _evaluation(
    batch: GenerationBatch,
    candidate: GeneratedCandidate | RevisedCandidate,
    *,
    statuses: tuple[FactStatus, ...] = (FactStatus.CURRENT_APPROVED,),
    style_passed: bool = True,
    correctable: tuple[str, ...] = (),
    soft: tuple[str, ...] = (),
) -> CandidateEvaluation:
    call = replace(
        batch.call_lineage,
        program_kind="conflict_check",
        prompt_release_id=uuid4(),
        prompt_release_hash=_hash("conflict-prompt-v1"),
        model_call_id=uuid4(),
        request_hash=_hash(f"evaluation-request-{uuid4()}"),
        response_hash=_hash(f"evaluation-response-{uuid4()}"),
    )
    return CandidateEvaluation(
        id=uuid4(),
        project_id=batch.project_id,
        review_run_id=batch.review_run_id,
        review_case_id=batch.review_case_id,
        generation_batch_id=batch.id,
        candidate_id=candidate.id,
        candidate_output_hash=candidate.output_hash,
        call_lineage=call,
        evaluator_release="synthetic-evaluator-v1",
        evaluator_hash=_hash("synthetic-evaluator-v1"),
        evidence_artifact_hash=_hash(f"evaluation-evidence-{uuid4()}"),
        claim_assessments=tuple(_assessment(status) for status in statuses),
        style_score=4.5 if style_passed else 3.0,
        style_passed=style_passed,
        correctable_issue_codes=correctable,
        soft_issue_codes=soft,
    )


def _revision(
    batch: GenerationBatch,
    parent: GeneratedCandidate | RevisedCandidate,
    round_number: int,
) -> CandidateRevision:
    revision_id = uuid4()
    issues = ("explicit_conflict",)
    revised = RevisedCandidate(
        id=uuid4(),
        project_id=batch.project_id,
        review_run_id=batch.review_run_id,
        review_case_id=batch.review_case_id,
        generation_batch_id=batch.id,
        batch_number=batch.batch_number,
        revision_id=revision_id,
        revision_round=round_number,
        parent_candidate_id=parent.id,
        parent_output_hash=parent.output_hash,
        output_hash=_hash(f"revision-{revision_id}"),
        artifact_hash=_hash(f"revision-artifact-{revision_id}"),
    )
    call = replace(
        batch.call_lineage,
        program_kind="revision",
        prompt_release_id=uuid4(),
        prompt_release_hash=_hash("revision-prompt-v1"),
        model_call_id=uuid4(),
        request_hash=_hash(f"revision-request-{revision_id}"),
        response_hash=_hash(f"revision-response-{revision_id}"),
    )
    return CandidateRevision(
        id=revision_id,
        project_id=batch.project_id,
        review_run_id=batch.review_run_id,
        review_case_id=batch.review_case_id,
        generation_batch_id=batch.id,
        round_number=round_number,
        parent_candidate_id=parent.id,
        parent_output_hash=parent.output_hash,
        issue_codes=issues,
        issue_set_hash=revision_issue_set_hash(issues),
        call_lineage=call,
        revised_candidate=revised,
    )


def test_generation_batch_has_exactly_four_candidates_and_only_creative_guidance() -> None:
    review_run_id = uuid4()
    autonomous = _case()
    initial = _batch(autonomous, review_run_id)

    assert len(initial.candidates) == 4
    assert [candidate.ordinal for candidate in initial.candidates] == [1, 2, 3, 4]
    assert_generation_batch_for_case(autonomous, initial)
    with pytest.raises(SyntheticLabContractError, match="exactly 4"):
        replace(initial, candidates=initial.candidates[:3])
    with pytest.raises(SyntheticLabContractError, match="guided operator input"):
        replace(initial, creative_reference="Treat this as a product fact")

    guided = _case(mode=ScenarioMode.GUIDED)
    guided_batch = _batch(guided, uuid4())
    assert guided_batch.creative_reference == guided.creative_reference
    with pytest.raises(SyntheticLabScopeError, match="creative-reference"):
        assert_generation_batch_for_case(
            guided,
            replace(guided_batch, creative_reference="A different creative idea"),
        )


def test_call_lineage_freezes_case_prompt_profile_fact_model_and_hashes() -> None:
    case = _case()
    run_id = uuid4()
    batch = _batch(case, run_id)
    lineage = batch.call_lineage

    assert_fact_snapshot_current(
        lineage,
        current_snapshot_id=case.fact_snapshot_id,
        current_snapshot_hash=case.fact_snapshot_hash,
        all_bound_facts_current_approved=True,
    )
    with pytest.raises(SyntheticLabContractError, match="stale"):
        assert_fact_snapshot_current(
            lineage,
            current_snapshot_id=case.fact_snapshot_id,
            current_snapshot_hash=case.fact_snapshot_hash,
            all_bound_facts_current_approved=False,
        )
    with pytest.raises(SyntheticLabScopeError, match="Profile/Fact"):
        assert_generation_batch_for_case(
            case,
            _batch(case, run_id, lineage_changes={"profile_hash": _hash("changed-profile")}),
        )
    with pytest.raises(SyntheticLabContractError, match="lowercase SHA-256"):
        replace(lineage, model_identity_hash="mutable-model-name")
    with pytest.raises(SyntheticLabScopeError, match="Review Run/Case"):
        replace(batch, call_lineage=replace(lineage, review_run_id=uuid4()))
    with pytest.raises(FrozenInstanceError):
        lineage.prompt_release_hash = _hash("other")  # type: ignore[misc]


def test_generation_history_allows_only_one_regenerated_batch_with_same_context() -> None:
    case = _case()
    run_id = uuid4()
    initial = _batch(case, run_id)
    regenerated = _batch(case, run_id, kind=GenerationBatchKind.REGENERATED)

    assert_generation_history(case, (initial, regenerated))
    with pytest.raises(SyntheticLabContractError, match="at most one"):
        assert_generation_history(case, (initial, regenerated, regenerated))
    changed_fact = _batch(
        case,
        run_id,
        kind=GenerationBatchKind.REGENERATED,
        lineage_changes={"fact_snapshot_hash": _hash("silently-changed-fact")},
    )
    with pytest.raises(SyntheticLabScopeError, match="Review Case/Profile/Fact"):
        assert_generation_history(case, (initial, changed_fact))


@pytest.mark.parametrize(
    ("statuses", "style_passed", "correctable", "soft", "disposition", "allowed"),
    [
        ((FactStatus.CURRENT_APPROVED,), True, (), (), EvaluationDisposition.PASS, True),
        (
            (FactStatus.DERIVED_OR_UNKNOWN,),
            True,
            (),
            (),
            EvaluationDisposition.WARNING,
            True,
        ),
        (
            (FactStatus.EXPLICIT_CONFLICT,),
            True,
            (),
            (),
            EvaluationDisposition.REVISE,
            False,
        ),
        (
            (FactStatus.SUBJECT_MIXUP,),
            True,
            (),
            (),
            EvaluationDisposition.REVISE,
            False,
        ),
        (
            (FactStatus.CURRENT_APPROVED,),
            False,
            ("style_mismatch",),
            (),
            EvaluationDisposition.REVISE,
            False,
        ),
        (
            (FactStatus.CURRENT_APPROVED,),
            True,
            (),
            ("minor_tone",),
            EvaluationDisposition.WARNING,
            True,
        ),
    ],
)
def test_fact_and_style_semantics_map_deterministically_to_output_or_revision(
    statuses: tuple[FactStatus, ...],
    style_passed: bool,
    correctable: tuple[str, ...],
    soft: tuple[str, ...],
    disposition: EvaluationDisposition,
    allowed: bool,
) -> None:
    case = _case()
    batch = _batch(case, uuid4())
    candidate = batch.candidates[0]
    evaluation = _evaluation(
        batch,
        candidate,
        statuses=statuses,
        style_passed=style_passed,
        correctable=correctable,
        soft=soft,
    )

    assert_evaluation_for_candidate(batch, candidate, evaluation)
    assert evaluation.disposition == disposition
    assert evaluation.output_allowed is allowed
    if FactStatus.DERIVED_OR_UNKNOWN in statuses:
        assert "derived_or_unknown" in evaluation.warning_codes


def test_fact_assessments_cannot_drop_derived_marker_or_fake_fact_subject_lineage() -> None:
    with pytest.raises(SyntheticLabContractError, match="explicit annotation"):
        ClaimAssessment(
            claim_hash=_hash("derived"),
            status=FactStatus.DERIVED_OR_UNKNOWN,
        )
    with pytest.raises(SyntheticLabContractError, match="frozen Fact lineage"):
        ClaimAssessment(
            claim_hash=_hash("conflict"),
            status=FactStatus.EXPLICIT_CONFLICT,
        )
    subject_id = uuid4()
    with pytest.raises(SyntheticLabContractError, match="actually differ"):
        ClaimAssessment(
            claim_hash=_hash("mixup"),
            status=FactStatus.SUBJECT_MIXUP,
            expected_subject_id=subject_id,
            observed_subject_id=subject_id,
        )


def test_two_revision_rounds_then_one_regeneration_then_terminal_failure() -> None:
    case = _case()
    run_id = uuid4()
    initial = _batch(case, run_id)
    candidate = initial.candidates[0]

    first_decision = decide_next_step(
        initial,
        candidate,
        (),
        _evaluation(initial, candidate, statuses=(FactStatus.EXPLICIT_CONFLICT,)),
    )
    assert first_decision.action == WorkflowAction.REVISE
    assert first_decision.next_revision_round == 1

    revision_one = _revision(initial, candidate, 1)
    second_decision = decide_next_step(
        initial,
        candidate,
        (revision_one,),
        _evaluation(
            initial,
            revision_one.revised_candidate,
            statuses=(FactStatus.EXPLICIT_CONFLICT,),
        ),
    )
    assert second_decision.action == WorkflowAction.REVISE
    assert second_decision.next_revision_round == 2

    revision_two = _revision(initial, revision_one.revised_candidate, 2)
    regenerate = decide_next_step(
        initial,
        candidate,
        (revision_one, revision_two),
        _evaluation(
            initial,
            revision_two.revised_candidate,
            statuses=(FactStatus.SUBJECT_MIXUP,),
        ),
    )
    assert regenerate.action == WorkflowAction.REGENERATE
    assert_revision_chain(initial, candidate, (revision_one, revision_two))

    regenerated = _batch(case, run_id, kind=GenerationBatchKind.REGENERATED)
    regenerated_candidate = regenerated.candidates[0]
    final_evaluation = _evaluation(
        regenerated,
        regenerated_candidate,
        statuses=(FactStatus.EXPLICIT_CONFLICT,),
    )
    failed = decide_next_step(regenerated, regenerated_candidate, (), final_evaluation)
    assert failed.action == WorkflowAction.FAIL
    assert failed.final_status == ReviewRunStatus.FAILED


def test_revision_chain_rejects_skipped_rounds_and_changed_fact_context() -> None:
    case = _case()
    batch = _batch(case, uuid4())
    candidate = batch.candidates[0]
    first = _revision(batch, candidate, 1)
    second = _revision(batch, first.revised_candidate, 2)

    with pytest.raises(SyntheticLabContractError, match="contiguous"):
        assert_revision_chain(batch, candidate, (second,))
    stale_lineage = replace(second.call_lineage, fact_snapshot_hash=_hash("stale-facts"))
    with pytest.raises(SyntheticLabScopeError, match="frozen Case/Profile/Fact"):
        assert_revision_chain(
            batch,
            candidate,
            (first, replace(second, call_lineage=stale_lineage)),
        )


def test_pass_and_warning_complete_without_revision_and_warning_remains_offline_eligible() -> None:
    case = _case(mode=ScenarioMode.GUIDED)
    batch = _batch(case, uuid4())
    candidate = batch.candidates[0]
    warning_evaluation = _evaluation(
        batch,
        candidate,
        statuses=(FactStatus.DERIVED_OR_UNKNOWN,),
        soft=("minor_tone",),
    )
    decision = decide_next_step(batch, candidate, (), warning_evaluation)
    resolution = resolution_from_decision(
        resolution_id=uuid4(),
        decision=decision,
        evaluation=warning_evaluation,
        channel="reddit",
        scenario_mode=ScenarioMode.GUIDED,
    )

    assert decision.action == WorkflowAction.COMPLETE
    assert decision.final_status == ReviewRunStatus.COMPLETED_WITH_WARNING
    assert resolution.offline_experiment_eligible
    assert resolution.included_in_overall_metrics
    assert resolution.warning_codes == ("derived_or_unknown", "minor_tone")
    with pytest.raises(SyntheticLabContractError, match="complete decision"):
        replace(decision, final_status=ReviewRunStatus.FAILED)
    forged_pass = replace(decision, final_status=ReviewRunStatus.PASSED)
    with pytest.raises(SyntheticLabContractError, match="Evaluation disposition"):
        resolution_from_decision(
            resolution_id=uuid4(),
            decision=forged_pass,
            evaluation=warning_evaluation,
            channel="reddit",
            scenario_mode=ScenarioMode.GUIDED,
        )
    with pytest.raises(SyntheticLabScopeError, match="different Projects"):
        resolution_from_decision(
            resolution_id=uuid4(),
            decision=replace(decision, project_id=uuid4()),
            evaluation=warning_evaluation,
            channel="reddit",
            scenario_mode=ScenarioMode.GUIDED,
        )


def _resolution(
    *,
    project_id: UUID,
    review_run_id: UUID,
    case_id: UUID,
    status: ReviewRunStatus,
    channel: str = "reddit",
    mode: ScenarioMode = ScenarioMode.AUTONOMOUS,
) -> CandidateResolution:
    return CandidateResolution(
        id=uuid4(),
        project_id=project_id,
        review_run_id=review_run_id,
        review_case_id=case_id,
        candidate_id=uuid4(),
        candidate_output_hash=_hash(f"candidate-{case_id}"),
        evaluation_id=uuid4(),
        evaluation_evidence_hash=_hash(f"evaluation-{case_id}"),
        channel=channel,
        scenario_mode=mode,
        status=status,
        warning_codes=("derived_or_unknown",)
        if status == ReviewRunStatus.COMPLETED_WITH_WARNING
        else (),
        failure_code="unresolved_conflict" if status == ReviewRunStatus.FAILED else None,
    )


def test_review_run_result_exposes_warning_ratio_and_independent_strata() -> None:
    project_id = uuid4()
    run_id = uuid4()
    passed = _resolution(
        project_id=project_id,
        review_run_id=run_id,
        case_id=uuid4(),
        status=ReviewRunStatus.PASSED,
    )
    warning = _resolution(
        project_id=project_id,
        review_run_id=run_id,
        case_id=uuid4(),
        status=ReviewRunStatus.COMPLETED_WITH_WARNING,
        channel="quora",
        mode=ScenarioMode.GUIDED,
    )
    failed = _resolution(
        project_id=project_id,
        review_run_id=run_id,
        case_id=uuid4(),
        status=ReviewRunStatus.FAILED,
    )
    result = ReviewRunResult(
        id=uuid4(),
        project_id=project_id,
        review_run_id=run_id,
        resolutions=(passed, warning, failed),
    )

    assert result.status == ReviewRunStatus.FAILED
    assert (result.passed_count, result.warning_count, result.failed_count) == (1, 1, 1)
    assert result.offline_eligible_count == 2
    assert result.warning_ratio == pytest.approx(1 / 3)
    assert result.warning_by_code == {"derived_or_unknown": 1}
    assert result.warning_by_channel == {"quora": 1}
    assert result.warning_by_scenario_mode == {"guided_scenario": 1}
    assert warning.offline_experiment_eligible
    assert not failed.offline_experiment_eligible
    assert isinstance(result.warning_by_code, MappingProxyType)
    with pytest.raises(TypeError):
        result.warning_by_code["hidden"] = 1  # type: ignore[index]


def test_every_generation_evaluation_revision_and_result_is_synthetic_only() -> None:
    case = _case()
    batch = _batch(case, uuid4())
    candidate = batch.candidates[0]
    evaluation = _evaluation(batch, candidate)
    revision = _revision(batch, candidate, 1)
    decision = decide_next_step(batch, candidate, (), evaluation)
    resolution = resolution_from_decision(
        resolution_id=uuid4(),
        decision=decision,
        evaluation=evaluation,
        channel="reddit",
        scenario_mode=ScenarioMode.AUTONOMOUS,
    )
    result = ReviewRunResult(
        id=uuid4(),
        project_id=case.project_id,
        review_run_id=batch.review_run_id,
        resolutions=(resolution,),
    )
    resources = (
        batch.call_lineage,
        batch,
        *batch.candidates,
        evaluation,
        *evaluation.claim_assessments,
        revision,
        revision.revised_candidate,
        decision,
        resolution,
        result,
    )

    assert all(resource.synthetic for resource in resources)
    assert all(resource.test_only for resource in resources)
    assert not any(resource.publication_eligible for resource in resources)
