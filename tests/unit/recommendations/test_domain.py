from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
from uuid import UUID, uuid4

import pytest

from geo_core.recommendations import domain as domain_facade
from geo_core.recommendations import (
    ApprovalOutcome,
    ContentRef,
    DownstreamDraftKind,
    DownstreamDraftStatus,
    FactRef,
    InputChangeReason,
    MetricComparisonRef,
    ModelCallRef,
    ObservationEvidenceClass,
    ObservationRef,
    PromptReleaseRef,
    QuestionRef,
    Recommendation,
    RecommendationDecision,
    RecommendationConflict,
    RecommendationEvidenceGraph,
    RecommendationInputKind,
    RecommendationInputVersion,
    RecommendationRuleViolation,
    RecommendationScope,
    RecommendationSourceStale,
    RecommendationStatus,
    RecommendationType,
    RecommendationWorkflow,
    RuleRef,
    SurfaceRef,
    approve_and_create_draft,
    expire_recommendation,
    mark_draft_started,
    prepare_draft_action,
    reconcile_approved_inputs,
    reject_recommendation,
    submit_recommendation,
)


NOW = datetime(2026, 7, 23, 1, 0, tzinfo=UTC)
PROJECT_ID = UUID("10000000-0000-0000-0000-000000000001")
APPROVAL_ID = UUID("20000000-0000-0000-0000-000000000001")


def test_domain_facade_preserves_established_model_and_operation_imports() -> None:
    assert domain_facade.Recommendation is Recommendation
    assert domain_facade.RecommendationWorkflow is RecommendationWorkflow
    assert domain_facade.ApprovalOutcome is ApprovalOutcome
    assert domain_facade.submit_recommendation is submit_recommendation
    assert domain_facade.approve_and_create_draft is approve_and_create_draft
    assert domain_facade.prepare_draft_action is prepare_draft_action
    assert domain_facade.mark_draft_started is mark_draft_started


def test_all_six_recommendation_types_are_normal_approvable_outcomes() -> None:
    cases = (
        (RecommendationType.HARD_BLOCKER, DownstreamDraftKind.CONTENT_BRIEF),
        (RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET),
        (RecommendationType.EXPERIMENT, DownstreamDraftKind.EXPERIMENT_PLAN),
        (RecommendationType.OPTIONAL, DownstreamDraftKind.CONTENT_BRIEF),
        (RecommendationType.NO_CHANGE, None),
        (RecommendationType.INSUFFICIENT_EVIDENCE, DownstreamDraftKind.SAMPLING_PLAN),
    )

    assert {item.value for item in RecommendationType} == {
        "hard_blocker",
        "gap",
        "experiment",
        "optional",
        "no_change",
        "insufficient_evidence",
    }
    for recommendation_type, draft_kind in cases:
        outcome = _approve(
            _workflow(recommendation_type=recommendation_type, draft_kind=draft_kind)
        )

        assert outcome.workflow.recommendation.status == RecommendationStatus.APPROVED
        assert (outcome.draft.kind if outcome.draft else None) == draft_kind


def test_approval_freezes_exact_inputs_and_only_creates_an_unstarted_draft() -> None:
    outcome = _approve(_workflow())
    recommendation = outcome.workflow.recommendation

    assert recommendation.version == 3
    assert recommendation.approval is not None
    assert recommendation.approval.recommendation_version == recommendation.version
    assert recommendation.approval.frozen_input_versions == recommendation.evidence.input_versions
    assert recommendation.approval.frozen_evidence_graph_hash == recommendation.evidence.graph_hash
    assert outcome.draft is not None
    assert outcome.draft.status == DownstreamDraftStatus.DRAFT
    assert outcome.draft.started_at is None
    assert outcome.draft.frozen_input_versions == recommendation.approval.frozen_input_versions
    assert outcome.draft.frozen_evidence_graph_hash == recommendation.evidence.graph_hash
    assert [event.to_status for event in recommendation.transitions] == [
        RecommendationStatus.IN_REVIEW,
        RecommendationStatus.APPROVED,
    ]


def test_approval_rejects_an_input_that_changed_after_review_started() -> None:
    review = _submit(_workflow())
    changed = _changed_inputs(review, RecommendationInputKind.FACT)

    with pytest.raises(RecommendationSourceStale, match="changed before approval"):
        approve_and_create_draft(
            review,
            expected_version=2,
            approval_id=APPROVAL_ID,
            actor_id="operator-1",
            current_inputs=changed,
            occurred_at=NOW + timedelta(minutes=2),
            draft_idempotency_key="approve:one",
        )


def test_approval_retry_replays_the_one_deterministic_draft() -> None:
    review = _submit(_workflow())
    first = _approve_review(review)
    replay = approve_and_create_draft(
        first.workflow,
        expected_version=2,
        approval_id=APPROVAL_ID,
        actor_id="operator-1",
        current_inputs=review.recommendation.evidence.input_versions,
        occurred_at=NOW + timedelta(minutes=3),
        draft_idempotency_key="approve:one",
    )

    assert replay.replayed is True
    assert replay.workflow == first.workflow
    assert replay.draft == first.draft
    assert len(replay.workflow.drafts) == 1

    with pytest.raises(RecommendationConflict, match="different approval"):
        approve_and_create_draft(
            first.workflow,
            expected_version=2,
            approval_id=uuid4(),
            actor_id="operator-2",
            current_inputs=review.recommendation.evidence.input_versions,
            occurred_at=NOW + timedelta(minutes=3),
            draft_idempotency_key="approve:two",
        )


def test_no_change_approval_is_terminal_without_inventing_a_work_draft() -> None:
    review = _submit(
        _workflow(
            recommendation_type=RecommendationType.NO_CHANGE,
            draft_kind=None,
        )
    )
    first = approve_and_create_draft(
        review,
        expected_version=2,
        approval_id=APPROVAL_ID,
        actor_id="operator-1",
        current_inputs=review.recommendation.evidence.input_versions,
        occurred_at=NOW + timedelta(minutes=2),
    )
    replay = approve_and_create_draft(
        first.workflow,
        expected_version=2,
        approval_id=APPROVAL_ID,
        actor_id="operator-1",
        current_inputs=review.recommendation.evidence.input_versions,
        occurred_at=NOW + timedelta(minutes=3),
    )

    assert first.workflow.recommendation.status == RecommendationStatus.APPROVED
    assert first.draft is None
    assert first.workflow.drafts == ()
    assert replay.replayed is True


@pytest.mark.parametrize("from_review", [False, True])
def test_reject_is_only_available_before_approval(from_review: bool) -> None:
    workflow = _submit(_workflow()) if from_review else _workflow()
    rejected = reject_recommendation(
        workflow,
        expected_version=workflow.recommendation.version,
        actor_id="reviewer-1",
        reason="does not justify a business action",
        occurred_at=NOW + timedelta(minutes=2),
    )

    assert rejected.recommendation.status == RecommendationStatus.REJECTED
    with pytest.raises(RecommendationConflict, match="terminal state"):
        expire_recommendation(
            rejected,
            expected_version=rejected.recommendation.version,
            actor_id="reviewer-1",
            reason="late expiry attempt",
            occurred_at=NOW + timedelta(minutes=3),
        )


def test_expiring_an_approved_recommendation_blocks_its_unstarted_draft() -> None:
    approved = _approve(_workflow()).workflow
    expired = expire_recommendation(
        approved,
        expected_version=approved.recommendation.version,
        actor_id="system-expiry",
        reason="validity_window_elapsed",
        occurred_at=NOW + timedelta(days=31),
    )

    assert expired.recommendation.status == RecommendationStatus.EXPIRED
    assert expired.drafts[0].status == DownstreamDraftStatus.BLOCKED_SOURCE_EXPIRED
    assert expired.drafts[0].blocked_reason == "validity_window_elapsed"
    assert (
        expire_recommendation(
            expired,
            expected_version=expired.recommendation.version,
            actor_id="system-expiry",
            reason="retry",
            occurred_at=NOW + timedelta(days=32),
        )
        == expired
    )


@pytest.mark.parametrize(
    ("input_kind", "reason"),
    (
        (RecommendationInputKind.FACT, InputChangeReason.FACT_RETIRED),
        (RecommendationInputKind.OBSERVATION, InputChangeReason.DATA_REFRESHED),
        (RecommendationInputKind.METHOD_VERSION, InputChangeReason.METHOD_REPLACED),
        (
            RecommendationInputKind.CONTENT_VERSION,
            InputChangeReason.CONTENT_VERSION_CHANGED,
        ),
    ),
)
def test_approved_input_changes_persist_stale_and_block_draft(
    input_kind: RecommendationInputKind,
    reason: InputChangeReason,
) -> None:
    approved = _approve(_workflow()).workflow
    changed = reconcile_approved_inputs(
        approved,
        current_inputs=_changed_inputs(approved, input_kind),
        change_reason=reason,
        actor_id="lineage-reconciler",
        occurred_at=NOW + timedelta(minutes=3),
    )

    assert changed.recommendation.status == RecommendationStatus.STALE
    assert changed.recommendation.transitions[-1].reason == reason.value
    assert changed.drafts[0].status == DownstreamDraftStatus.BLOCKED_SOURCE_STALE
    assert changed.drafts[0].blocked_reason == reason.value
    assert (
        reconcile_approved_inputs(
            changed,
            current_inputs=_changed_inputs(approved, input_kind),
            change_reason=reason,
            actor_id="lineage-reconciler",
            occurred_at=NOW + timedelta(minutes=4),
        )
        == changed
    )


def test_unchanged_inputs_do_not_churn_the_approved_version() -> None:
    approved = _approve(_workflow()).workflow

    reconciled = reconcile_approved_inputs(
        approved,
        current_inputs=tuple(reversed(approved.recommendation.evidence.input_versions)),
        change_reason=InputChangeReason.DATA_REFRESHED,
        actor_id="lineage-reconciler",
        occurred_at=NOW + timedelta(minutes=3),
    )

    assert reconciled == approved


def test_draft_action_requires_the_same_approved_version_and_current_inputs() -> None:
    approved = _approve(_workflow()).workflow
    draft = approved.drafts[0]
    current = approved.recommendation.evidence.input_versions
    allowed = prepare_draft_action(
        approved,
        draft_id=draft.id,
        expected_recommendation_version=approved.recommendation.version,
        current_inputs=current,
        current_evidence_graph_hash=approved.recommendation.evidence.graph_hash,
        occurred_at=NOW + timedelta(minutes=3),
        actor_id="draft-runner",
    )

    assert allowed.authorized is True
    started = mark_draft_started(allowed, started_at=NOW + timedelta(minutes=4))
    assert started.drafts[0].status == DownstreamDraftStatus.STARTED

    wrong_version = prepare_draft_action(
        approved,
        draft_id=draft.id,
        expected_recommendation_version=approved.recommendation.version - 1,
        current_inputs=current,
        current_evidence_graph_hash=approved.recommendation.evidence.graph_hash,
        occurred_at=NOW + timedelta(minutes=3),
        actor_id="draft-runner",
    )
    assert wrong_version.authorized is False
    assert wrong_version.problem_code == "recommendation_source_stale"
    with pytest.raises(RecommendationSourceStale) as error:
        wrong_version.require_authorized()
    assert error.value.problem_code == "recommendation_source_stale"


def test_action_recheck_persists_source_stale_before_refusing_execution() -> None:
    approved = _approve(_workflow()).workflow
    check = prepare_draft_action(
        approved,
        draft_id=approved.drafts[0].id,
        expected_recommendation_version=approved.recommendation.version,
        current_inputs=_changed_inputs(approved, RecommendationInputKind.FACT),
        current_evidence_graph_hash="f" * 64,
        occurred_at=NOW + timedelta(minutes=3),
        actor_id="draft-runner",
        change_reason=InputChangeReason.FACT_RETIRED,
    )

    assert check.authorized is False
    assert check.workflow.recommendation.status == RecommendationStatus.STALE
    assert check.workflow.drafts[0].status == DownstreamDraftStatus.BLOCKED_SOURCE_STALE
    with pytest.raises(RecommendationSourceStale):
        mark_draft_started(check, started_at=NOW + timedelta(minutes=4))


def test_action_recheck_expires_the_source_and_blocks_the_draft() -> None:
    approved = _approve(_workflow()).workflow
    check = prepare_draft_action(
        approved,
        draft_id=approved.drafts[0].id,
        expected_recommendation_version=approved.recommendation.version,
        current_inputs=approved.recommendation.evidence.input_versions,
        current_evidence_graph_hash=approved.recommendation.evidence.graph_hash,
        occurred_at=NOW + timedelta(days=31),
        actor_id="draft-runner",
    )

    assert check.authorized is False
    assert check.workflow.recommendation.status == RecommendationStatus.EXPIRED
    assert check.workflow.drafts[0].status == DownstreamDraftStatus.BLOCKED_SOURCE_EXPIRED


def test_stale_propagation_does_not_relabel_an_already_started_draft() -> None:
    approved = _approve(_workflow()).workflow
    check = prepare_draft_action(
        approved,
        draft_id=approved.drafts[0].id,
        expected_recommendation_version=approved.recommendation.version,
        current_inputs=approved.recommendation.evidence.input_versions,
        current_evidence_graph_hash=approved.recommendation.evidence.graph_hash,
        occurred_at=NOW + timedelta(minutes=3),
        actor_id="draft-runner",
    )
    started = mark_draft_started(check, started_at=NOW + timedelta(minutes=4))
    stale = reconcile_approved_inputs(
        started,
        current_inputs=_changed_inputs(started, RecommendationInputKind.CONTENT_VERSION),
        change_reason=InputChangeReason.CONTENT_VERSION_CHANGED,
        actor_id="lineage-reconciler",
        occurred_at=NOW + timedelta(minutes=5),
    )

    assert stale.recommendation.status == RecommendationStatus.STALE
    assert stale.drafts[0].status == DownstreamDraftStatus.STARTED


def test_terminal_workflow_rejects_the_wrong_draft_block_reason() -> None:
    expired = expire_recommendation(
        _approve(_workflow()).workflow,
        expected_version=3,
        actor_id="system-expiry",
        reason="validity_window_elapsed",
        occurred_at=NOW + timedelta(days=31),
    )
    wrong_block = replace(
        expired.drafts[0],
        status=DownstreamDraftStatus.BLOCKED_SOURCE_STALE,
    )

    with pytest.raises(RecommendationRuleViolation, match="block every unstarted draft"):
        RecommendationWorkflow(expired.recommendation, (wrong_block,))


def _workflow(
    *,
    recommendation_type: RecommendationType = RecommendationType.HARD_BLOCKER,
    draft_kind: DownstreamDraftKind | None = DownstreamDraftKind.CONTENT_BRIEF,
) -> RecommendationWorkflow:
    scope = RecommendationScope(
        project_id=PROJECT_ID,
        campaign_id=UUID("10000000-0000-0000-0000-000000000002"),
        question_or_cluster_ref="question-cluster:commercial",
        surface_ref="surface:google-ai-overviews:release-1",
        content_asset_ref="package-version:12",
        url_ref="verified-url:8",
        applicable_version="recommendation-contract-v1",
    )
    recommendation = Recommendation(
        id=uuid4(),
        project_id=PROJECT_ID,
        recommendation_type=recommendation_type,
        evidence=_evidence(scope),
        proposed_draft_kind=draft_kind,
        valid_until=NOW + timedelta(days=30),
        created_by="recommendation-engine",
        created_at=NOW,
        updated_at=NOW,
    )
    return RecommendationWorkflow(recommendation)


def _submit(workflow: RecommendationWorkflow) -> RecommendationWorkflow:
    return submit_recommendation(
        workflow,
        expected_version=1,
        actor_id="operator-1",
        occurred_at=NOW + timedelta(minutes=1),
    )


def _approve(workflow: RecommendationWorkflow) -> ApprovalOutcome:
    return _approve_review(_submit(workflow))


def _approve_review(workflow: RecommendationWorkflow) -> ApprovalOutcome:
    key = None if workflow.recommendation.proposed_draft_kind is None else "approve:one"
    return approve_and_create_draft(
        workflow,
        expected_version=2,
        approval_id=APPROVAL_ID,
        actor_id="operator-1",
        current_inputs=workflow.recommendation.evidence.input_versions,
        occurred_at=NOW + timedelta(minutes=2),
        draft_idempotency_key=key,
    )


def _evidence(scope: RecommendationScope) -> RecommendationEvidenceGraph:
    question = QuestionRef(
        project_id=PROJECT_ID,
        resource_id="question:commercial",
        version="v1",
        sha256=_digest("question:v1"),
        locator={"table": "monitoring_queries", "id": "question:commercial"},
        active=True,
    )
    surface = SurfaceRef(
        project_id=PROJECT_ID,
        resource_id="surface:google-aio:r1",
        version="r1",
        sha256=_digest("surface:r1"),
        locator={"registry": "surface_releases", "id": "google-aio:r1"},
        active=True,
    )
    observation = ObservationRef(
        project_id=PROJECT_ID,
        resource_id="observation:1",
        version="v1",
        sha256=_digest("observation:v1"),
        locator={"artifact": "s3://geo/observations/1.json", "row": "1"},
        capture_method="automated_ui",
        evidence_class=ObservationEvidenceClass.REAL_OBSERVATION,
        question_resource_id=question.resource_id,
        surface_resource_id=surface.resource_id,
        eligible=True,
    )
    prompt = PromptReleaseRef(
        project_id=PROJECT_ID,
        resource_id="prompt:recommendation:r1",
        version="r1",
        sha256=_digest("prompt:r1"),
        locator={"table": "prompt_releases", "id": "recommendation:r1"},
        approved=True,
        frozen=True,
    )
    return RecommendationEvidenceGraph(
        scope=scope,
        decision=RecommendationDecision(
            impact_chain=("Observed answer gap", "Lost qualified consideration"),
            risk="medium",
            effort="small",
            business_value="Protect high-intent discovery",
            confidence=Decimal("0.82"),
            counterevidence=("One comparison interval remains wide",),
            validation_plan=("Run the frozen paired experiment",),
            stale_conditions=("Fact retires", "Observation or method version changes"),
        ),
        observations=(observation,),
        metric_comparisons=(
            MetricComparisonRef(
                project_id=PROJECT_ID,
                resource_id="comparison:1",
                version="v1",
                sha256=_digest("comparison:v1"),
                locator={"table": "metric_comparisons", "id": "comparison:1"},
                observation_resource_ids=(observation.resource_id,),
                method_version="paired-bootstrap-v1",
                method_sha256=_digest("paired-bootstrap-v1"),
                sufficient_evidence=True,
            ),
        ),
        facts=(
            FactRef(
                project_id=PROJECT_ID,
                resource_id="fact:1",
                version="v1",
                sha256=_digest("fact:v1"),
                locator={"table": "facts", "id": "fact:1"},
                approved=True,
                retired=False,
            ),
        ),
        rules=(
            RuleRef(
                project_id=PROJECT_ID,
                resource_id="rule:recommendation:v1",
                version="v1",
                sha256=_digest("rule:v1"),
                locator={"registry": "recommendation_rules", "id": "v1"},
                active=True,
            ),
        ),
        prompt_releases=(prompt,),
        model_calls=(
            ModelCallRef(
                project_id=PROJECT_ID,
                resource_id="model-call:1",
                version="v1",
                sha256=_digest("model-call:v1"),
                locator={"table": "model_call_logs", "id": "model-call:1"},
                prompt_release_resource_id=prompt.resource_id,
                model_identity="provider/model@2026-07-23",
                succeeded=True,
            ),
        ),
        contents=(
            ContentRef(
                project_id=PROJECT_ID,
                resource_id="content:package:12",
                version="v12",
                sha256=_digest("content:v12"),
                locator={"table": "package_versions", "id": "12"},
                current=True,
            ),
        ),
        questions=(question,),
        surfaces=(surface,),
    )


def _input(kind: RecommendationInputKind, version: str) -> RecommendationInputVersion:
    payload = f"{kind.value}:{version}"
    return RecommendationInputVersion(
        kind=kind,
        resource_id=f"{kind.value}:primary",
        version=version,
        sha256=hashlib.sha256(payload.encode()).hexdigest(),
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _changed_inputs(
    workflow: RecommendationWorkflow,
    kind: RecommendationInputKind,
) -> tuple[RecommendationInputVersion, ...]:
    return tuple(
        _input(item.kind, "v2") if item.kind == kind else replace(item)
        for item in workflow.recommendation.evidence.input_versions
    )
