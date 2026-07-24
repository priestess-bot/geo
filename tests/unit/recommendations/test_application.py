from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import inspect
from typing import Mapping, TypedDict
from uuid import UUID, uuid4

import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.recommendations import (
    ContentRef,
    CommandReceipt,
    DownstreamDraftKind,
    DownstreamDraftStatus,
    FactRef,
    InMemoryRecommendationStore,
    InputChangeReason,
    MetricComparisonRef,
    ModelCallRef,
    ObservationEvidenceClass,
    ObservationRef,
    PromptReleaseRef,
    QuestionRef,
    RecommendationApplication,
    RecommendationCommandIdentity,
    RecommendationCommandOperation,
    RecommendationDecision,
    RecommendationEvidenceSelector,
    RecommendationEvidenceGraph,
    RecommendationForbidden,
    RecommendationIdempotencyConflict,
    RecommendationInputKind,
    RecommendationNotFound,
    RecommendationPersistenceError,
    RecommendationReviewRequired,
    RecommendationScope,
    RecommendationSourceCheckRequired,
    RecommendationSourceStale,
    RecommendationStatus,
    RecommendationType,
    RecommendationVersionConflict,
    RecommendationWorkflow,
    ReviewedRecommendation,
    RuleRef,
    SurfaceRef,
    submit_recommendation,
)
from geo_core.recommendations.ports import RecommendationUnitOfWork


NOW = datetime(2026, 7, 23, 4, 0, tzinfo=UTC)
PROJECT_ID = UUID("40000000-0000-0000-0000-000000000001")
OTHER_PROJECT_ID = UUID("40000000-0000-0000-0000-000000000002")
TENANT_ID = UUID("40000000-0000-0000-0000-000000000003")


class _CreateValues(TypedDict):
    project_id: UUID
    recommendation_type: RecommendationType
    scope: RecommendationScope
    decision: RecommendationDecision
    evidence_selectors: tuple[RecommendationEvidenceSelector, ...]
    proposed_draft_kind: DownstreamDraftKind | None
    valid_until: datetime
    expected_version: int
    idempotency_key: str


class _RejectValues(TypedDict):
    project_id: UUID
    recommendation_id: UUID
    reason: str
    expected_version: int
    idempotency_key: str


class _SubmitValues(TypedDict):
    project_id: UUID
    recommendation_id: UUID
    expected_version: int
    idempotency_key: str


class _ReviewValues(_SubmitValues):
    notes: str


class _ReconcileValues(TypedDict):
    project_id: UUID
    recommendation_id: UUID
    change_reason: InputChangeReason
    expected_version: int
    idempotency_key: str


class _PrepareValues(_ReconcileValues):
    draft_id: UUID


def test_create_is_project_scoped_and_exactly_idempotent() -> None:
    app, store = _application()
    creator = _principal("analyst")
    evidence = _evidence()
    values = _create_values(evidence=evidence, idempotency_key="create:one")

    first = app.create_recommendation(creator, **values)
    replay = app.create_recommendation(creator, **values)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.value == first.value
    assert (
        store.workflow(
            project_id=PROJECT_ID,
            recommendation_id=first.value.recommendation.id,
        )
        == first.value
    )

    with pytest.raises(RecommendationIdempotencyConflict):
        changed_values = values.copy()
        changed_values["valid_until"] = NOW + timedelta(days=60)
        app.create_recommendation(
            creator,
            **changed_values,
        )
    with pytest.raises(RecommendationNotFound):
        app.create_recommendation(
            _principal("analyst", project_id=OTHER_PROJECT_ID),
            **values,
        )
    with pytest.raises(RecommendationForbidden):
        app.create_recommendation(_principal("viewer"), **values)


def test_review_and_approval_freeze_one_draft_without_runtime_side_effects() -> None:
    app, store = _application()
    creator = _principal("analyst")
    reviewer = _principal("owner")
    approver = _principal("admin")
    review = _create_submit_review(app, creator, reviewer)
    current = review.value.workflow

    approved = app.approve_recommendation(
        approver,
        project_id=PROJECT_ID,
        recommendation_id=current.recommendation.id,
        expected_version=2,
        idempotency_key="approve:one",
    )
    replay = app.approve_recommendation(
        approver,
        project_id=PROJECT_ID,
        recommendation_id=current.recommendation.id,
        expected_version=2,
        idempotency_key="approve:one",
    )

    assert approved.value.workflow.recommendation.status == RecommendationStatus.APPROVED
    assert approved.value.workflow.drafts[0].status == DownstreamDraftStatus.DRAFT
    assert approved.value.downstream_draft is not None
    assert approved.value.downstream_draft.status == "draft"
    assert approved.value.downstream_draft.enqueued is False
    assert approved.value.downstream_draft.executed is False
    assert approved.value.downstream_draft.published is False
    assert replay.replayed is True
    assert len(store.downstream_drafts(project_id=PROJECT_ID)) == 1


def test_approval_re_resolves_authoritative_state_not_only_version_fields() -> None:
    app, store = _application()
    review = _create_submit_review(app, _principal("analyst"), _principal("owner"))
    workflow = review.value.workflow
    fact = workflow.recommendation.evidence.facts[0]
    store.install_evidence(replace(fact, retired=True))

    with pytest.raises(RecommendationSourceStale, match="authoritative source"):
        app.approve_recommendation(
            _principal("admin"),
            project_id=PROJECT_ID,
            recommendation_id=workflow.recommendation.id,
            expected_version=workflow.recommendation.version,
            idempotency_key="approve:state-only-stale",
        )


def test_approval_requires_current_review_and_creator_separation() -> None:
    app, _ = _application()
    owner_creator = _principal("owner")
    admin = _principal("admin")
    created = app.create_recommendation(
        owner_creator,
        **_create_values(evidence=_evidence(), idempotency_key="create:owner"),
    ).value
    submitted = app.submit_recommendation(
        owner_creator,
        project_id=PROJECT_ID,
        recommendation_id=created.recommendation.id,
        expected_version=1,
        idempotency_key="submit:owner",
    ).value

    with pytest.raises(RecommendationReviewRequired):
        app.approve_recommendation(
            admin,
            project_id=PROJECT_ID,
            recommendation_id=submitted.recommendation.id,
            expected_version=2,
            idempotency_key="approve:no-review",
        )

    app.review_recommendation(
        admin,
        project_id=PROJECT_ID,
        recommendation_id=submitted.recommendation.id,
        notes="Reviewed against the frozen evidence graph.",
        expected_version=2,
        idempotency_key="review:owner-created",
    )
    with pytest.raises(RecommendationForbidden, match="self-approve"):
        app.approve_recommendation(
            owner_creator,
            project_id=PROJECT_ID,
            recommendation_id=submitted.recommendation.id,
            expected_version=2,
            idempotency_key="approve:self",
        )


def test_expected_version_and_command_hash_conflicts_are_enforced() -> None:
    app, _ = _application()
    creator = _principal("analyst")
    created = app.create_recommendation(
        creator,
        **_create_values(evidence=_evidence(), idempotency_key="create:cas"),
    ).value
    app.submit_recommendation(
        creator,
        project_id=PROJECT_ID,
        recommendation_id=created.recommendation.id,
        expected_version=1,
        idempotency_key="shared:key",
    )

    with pytest.raises(RecommendationVersionConflict):
        app.submit_recommendation(
            creator,
            project_id=PROJECT_ID,
            recommendation_id=created.recommendation.id,
            expected_version=1,
            idempotency_key="submit:stale-version",
        )
    with pytest.raises(RecommendationIdempotencyConflict):
        app.reject_recommendation(
            _principal("owner"),
            project_id=PROJECT_ID,
            recommendation_id=created.recommendation.id,
            reason="different operation with the same key",
            expected_version=2,
            idempotency_key="shared:key",
        )


def test_submit_and_review_replay_after_the_first_command_changed_state() -> None:
    app, _ = _application()
    creator = _principal("analyst")
    reviewer = _principal("owner")
    created = app.create_recommendation(
        creator,
        **_create_values(evidence=_evidence(), idempotency_key="create:replay-flow"),
    ).value
    submit_values: _SubmitValues = {
        "project_id": PROJECT_ID,
        "recommendation_id": created.recommendation.id,
        "expected_version": 1,
        "idempotency_key": "submit:replay-flow",
    }

    submitted = app.submit_recommendation(creator, **submit_values)
    submit_replay = app.submit_recommendation(creator, **submit_values)
    review_values: _ReviewValues = {
        "project_id": PROJECT_ID,
        "recommendation_id": submitted.value.recommendation.id,
        "notes": "Reviewed exact frozen inputs.",
        "expected_version": 2,
        "idempotency_key": "review:replay-flow",
    }
    reviewed = app.review_recommendation(reviewer, **review_values)
    review_replay = app.review_recommendation(reviewer, **review_values)

    assert submit_replay.replayed is True
    assert submit_replay.value == submitted.value
    assert review_replay.replayed is True
    assert review_replay.value == reviewed.value


def test_reject_command_replays_exact_result() -> None:
    app, _ = _application()
    creator = _principal("analyst")
    reviewer = _principal("owner")
    submitted = _create_submit(app, creator)
    values: _RejectValues = {
        "project_id": PROJECT_ID,
        "recommendation_id": submitted.recommendation.id,
        "reason": "Evidence does not justify action.",
        "expected_version": 2,
        "idempotency_key": "reject:one",
    }

    first = app.reject_recommendation(reviewer, **values)
    replay = app.reject_recommendation(reviewer, **values)

    assert first.value.recommendation.status == RecommendationStatus.REJECTED
    assert replay.replayed is True
    assert replay.value == first.value


def test_stale_reconciliation_blocks_draft_and_cancels_only_unpublished_outbox() -> None:
    app, store = _application()
    reconciler = _principal("analyst")
    approved = _approved_workflow(app)
    pending = store.seed_outbox(
        project_id=PROJECT_ID,
        recommendation_id=approved.recommendation.id,
    )
    delivered = store.seed_outbox(
        project_id=PROJECT_ID,
        recommendation_id=approved.recommendation.id,
        delivered=True,
    )
    _install_changed_reference(store, approved, RecommendationInputKind.FACT)
    values: _ReconcileValues = {
        "project_id": PROJECT_ID,
        "recommendation_id": approved.recommendation.id,
        "change_reason": InputChangeReason.FACT_RETIRED,
        "expected_version": 3,
        "idempotency_key": "stale:fact",
    }

    first = app.reconcile_stale(reconciler, **values)
    replay = app.reconcile_stale(reconciler, **values)

    assert first.value.workflow.recommendation.status == RecommendationStatus.STALE
    assert first.value.workflow.drafts[0].status == DownstreamDraftStatus.BLOCKED_SOURCE_STALE
    assert first.value.cancelled_outbox_ids == (pending.id,)
    assert store.outbox_message(pending.id).cancelled is True  # type: ignore[union-attr]
    assert store.outbox_message(delivered.id).cancelled is False  # type: ignore[union-attr]
    assert replay.replayed is True


def test_expiry_blocks_draft_and_cancels_pending_outbox_atomically() -> None:
    app, store = _application()
    owner = _principal("owner")
    approved = _approved_workflow(app)
    pending = store.seed_outbox(
        project_id=PROJECT_ID,
        recommendation_id=approved.recommendation.id,
    )
    values: _RejectValues = {
        "project_id": PROJECT_ID,
        "recommendation_id": approved.recommendation.id,
        "reason": "validity window closed",
        "expected_version": 3,
        "idempotency_key": "expire:one",
    }
    result = app.expire_recommendation(
        owner,
        **values,
    )
    replay = app.expire_recommendation(
        owner,
        **values,
    )

    assert result.value.workflow.recommendation.status == RecommendationStatus.EXPIRED
    assert result.value.workflow.drafts[0].status == DownstreamDraftStatus.BLOCKED_SOURCE_EXPIRED
    assert result.value.cancelled_outbox_ids == (pending.id,)
    assert replay.replayed is True


def test_prepare_action_rechecks_source_and_persists_failure_before_raising() -> None:
    app, store = _application()
    runner = _principal("analyst")
    approved = _approved_workflow(app)
    pending = store.seed_outbox(
        project_id=PROJECT_ID,
        recommendation_id=approved.recommendation.id,
    )
    _install_changed_reference(store, approved, RecommendationInputKind.FACT)
    values: _PrepareValues = {
        "project_id": PROJECT_ID,
        "recommendation_id": approved.recommendation.id,
        "draft_id": approved.drafts[0].id,
        "change_reason": InputChangeReason.FACT_RETIRED,
        "expected_version": 3,
        "idempotency_key": "prepare:stale",
    }

    with pytest.raises(RecommendationSourceStale):
        app.prepare_draft_action(runner, **values)
    with pytest.raises(RecommendationSourceStale):
        app.prepare_draft_action(runner, **values)

    persisted = store.workflow(
        project_id=PROJECT_ID,
        recommendation_id=approved.recommendation.id,
    )
    assert persisted is not None
    assert persisted.recommendation.status == RecommendationStatus.STALE
    assert persisted.drafts[0].status == DownstreamDraftStatus.BLOCKED_SOURCE_STALE
    assert store.outbox_message(pending.id).cancelled is True  # type: ignore[union-attr]


def test_prepare_action_authorizes_current_source_without_starting_it() -> None:
    app, _ = _application()
    approved = _approved_workflow(app)

    prepared = app.prepare_draft_action(
        _principal("analyst"),
        project_id=PROJECT_ID,
        recommendation_id=approved.recommendation.id,
        draft_id=approved.drafts[0].id,
        change_reason=InputChangeReason.DATA_REFRESHED,
        expected_version=3,
        idempotency_key="prepare:current",
    )

    assert prepared.value.check.authorized is True
    assert prepared.value.check.draft.status == DownstreamDraftStatus.DRAFT


def test_repository_cannot_directly_store_an_unchecked_started_draft() -> None:
    app, store = _application()
    approved = _approved_workflow(app)
    started = replace(
        approved.drafts[0],
        status=DownstreamDraftStatus.STARTED,
        started_at=NOW + timedelta(minutes=20),
    )
    candidate = RecommendationWorkflow(approved.recommendation, (started,))
    command = RecommendationCommandIdentity(
        PROJECT_ID,
        "a" * 64,
        RecommendationCommandOperation.PREPARE_DRAFT_ACTION,
        "b" * 64,
    )

    with store.unit_of_work_factory()(project_id=PROJECT_ID) as uow:
        with pytest.raises(RecommendationSourceCheckRequired):
            uow.recommendations.store_workflow(
                project_id=PROJECT_ID,
                workflow=candidate,
                expected_version=3,
                command=command,
                result=candidate,
            )

    signature = inspect.signature(RecommendationUnitOfWork.prepare_draft_action)
    assert "current_inputs" not in signature.parameters
    expected = signature.parameters["expected_recommendation_version"].default
    assert expected is inspect.Parameter.empty
    create_signature = inspect.signature(RecommendationApplication.create_recommendation)
    assert "evidence" not in create_signature.parameters
    for operation in (
        RecommendationApplication.review_recommendation,
        RecommendationApplication.approve_recommendation,
        RecommendationApplication.reconcile_stale,
        RecommendationApplication.prepare_draft_action,
    ):
        assert "current_inputs" not in inspect.signature(operation).parameters


def test_commit_failure_rolls_back_workflow_command_draft_and_outbox_changes() -> None:
    app, store = _application()
    approved = _approved_workflow(app)
    pending = store.seed_outbox(
        project_id=PROJECT_ID,
        recommendation_id=approved.recommendation.id,
    )
    store.fail_next_commit()

    with pytest.raises(RecommendationPersistenceError, match="simulated"):
        app.reconcile_stale(
            _principal("analyst"),
            project_id=PROJECT_ID,
            recommendation_id=approved.recommendation.id,
            change_reason=InputChangeReason.FACT_RETIRED,
            expected_version=3,
            idempotency_key="stale:rollback",
        )

    persisted = store.workflow(
        project_id=PROJECT_ID,
        recommendation_id=approved.recommendation.id,
    )
    assert persisted == approved
    assert store.outbox_message(pending.id).cancelled is False  # type: ignore[union-attr]


def test_memory_uow_detects_two_concurrent_writers_from_the_same_snapshot() -> None:
    app, store = _application()
    created = app.create_recommendation(
        _principal("analyst"),
        **_create_values(evidence=_evidence(), idempotency_key="create:concurrency"),
    ).value
    factory = store.unit_of_work_factory()
    first = factory(project_id=PROJECT_ID).__enter__()
    second = factory(project_id=PROJECT_ID).__enter__()
    try:
        first_current = first.recommendations.get_workflow(
            project_id=PROJECT_ID, recommendation_id=created.recommendation.id
        )
        second_current = second.recommendations.get_workflow(
            project_id=PROJECT_ID, recommendation_id=created.recommendation.id
        )
        assert first_current is not None and second_current is not None
        first_result = submit_recommendation(
            first_current,
            expected_version=1,
            actor_id="writer-1",
            occurred_at=NOW + timedelta(minutes=1),
        )
        second_result = submit_recommendation(
            second_current,
            expected_version=1,
            actor_id="writer-2",
            occurred_at=NOW + timedelta(minutes=1),
        )
        first.recommendations.store_workflow(
            project_id=PROJECT_ID,
            workflow=first_result,
            expected_version=1,
            command=_manual_command("c", "d"),
            result=first_result,
        )
        second.recommendations.store_workflow(
            project_id=PROJECT_ID,
            workflow=second_result,
            expected_version=1,
            command=_manual_command("e", "f"),
            result=second_result,
        )
        first.commit()
        with pytest.raises(RecommendationVersionConflict, match="concurrent"):
            second.commit()
    finally:
        first.__exit__(None, None, None)
        second.__exit__(None, None, None)


@pytest.mark.parametrize(
    ("recommendation_type", "draft_kind"),
    (
        (RecommendationType.EXPERIMENT, DownstreamDraftKind.EXPERIMENT_PLAN),
        (RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET),
        (RecommendationType.HARD_BLOCKER, DownstreamDraftKind.CONTENT_BRIEF),
        (RecommendationType.INSUFFICIENT_EVIDENCE, DownstreamDraftKind.SAMPLING_PLAN),
    ),
)
def test_each_downstream_adapter_only_creates_its_draft(
    recommendation_type: RecommendationType,
    draft_kind: DownstreamDraftKind,
) -> None:
    app, store = _application()
    approved = _approved_workflow(
        app,
        recommendation_type=recommendation_type,
        draft_kind=draft_kind,
    )
    records = store.downstream_drafts(project_id=PROJECT_ID)

    assert len(records) == 1
    assert records[0].kind == draft_kind
    assert records[0].status == "draft"
    assert (records[0].enqueued, records[0].executed, records[0].published) == (
        False,
        False,
        False,
    )
    assert approved.drafts[0].kind == draft_kind


def _application() -> tuple[RecommendationApplication, InMemoryRecommendationStore]:
    store = InMemoryRecommendationStore()
    store.install_evidence(*_evidence().all_refs)
    return (
        RecommendationApplication(
            store.unit_of_work_factory(),
            clock=lambda: NOW,
        ),
        store,
    )


def _principal(role: str, *, project_id: UUID = PROJECT_ID) -> AccessPrincipal:
    return AccessPrincipal(
        identity_id=uuid4(),
        actor_id=f"test-{role}",
        tenant_id=TENANT_ID,
        memberships=(MembershipRecord(project_id, TENANT_ID, role),),
        auth_method="test",
    )


def _create_values(
    *,
    evidence: RecommendationEvidenceGraph,
    idempotency_key: str,
    recommendation_type: RecommendationType = RecommendationType.HARD_BLOCKER,
    draft_kind: DownstreamDraftKind | None = DownstreamDraftKind.CONTENT_BRIEF,
) -> _CreateValues:
    from geo_core.recommendations import selectors_from_graph

    return {
        "project_id": PROJECT_ID,
        "recommendation_type": recommendation_type,
        "scope": evidence.scope,
        "decision": evidence.decision,
        "evidence_selectors": selectors_from_graph(evidence),
        "proposed_draft_kind": draft_kind,
        "valid_until": NOW + timedelta(days=30),
        "expected_version": 0,
        "idempotency_key": idempotency_key,
    }


def _create_submit(
    app: RecommendationApplication,
    creator: AccessPrincipal,
    *,
    recommendation_type: RecommendationType = RecommendationType.HARD_BLOCKER,
    draft_kind: DownstreamDraftKind = DownstreamDraftKind.CONTENT_BRIEF,
) -> RecommendationWorkflow:
    created = app.create_recommendation(
        creator,
        **_create_values(
            evidence=_evidence(),
            idempotency_key=f"create:{uuid4()}",
            recommendation_type=recommendation_type,
            draft_kind=draft_kind,
        ),
    ).value
    return app.submit_recommendation(
        creator,
        project_id=PROJECT_ID,
        recommendation_id=created.recommendation.id,
        expected_version=1,
        idempotency_key=f"submit:{uuid4()}",
    ).value


def _create_submit_review(
    app: RecommendationApplication,
    creator: AccessPrincipal,
    reviewer: AccessPrincipal,
    *,
    recommendation_type: RecommendationType = RecommendationType.HARD_BLOCKER,
    draft_kind: DownstreamDraftKind = DownstreamDraftKind.CONTENT_BRIEF,
) -> CommandReceipt[ReviewedRecommendation]:
    submitted = _create_submit(
        app,
        creator,
        recommendation_type=recommendation_type,
        draft_kind=draft_kind,
    )
    return app.review_recommendation(
        reviewer,
        project_id=PROJECT_ID,
        recommendation_id=submitted.recommendation.id,
        notes="Reviewed against exact evidence and input versions.",
        expected_version=2,
        idempotency_key=f"review:{uuid4()}",
    )


def _approved_workflow(
    app: RecommendationApplication,
    *,
    recommendation_type: RecommendationType = RecommendationType.HARD_BLOCKER,
    draft_kind: DownstreamDraftKind = DownstreamDraftKind.CONTENT_BRIEF,
) -> RecommendationWorkflow:
    review = _create_submit_review(
        app,
        _principal("analyst"),
        _principal("owner"),
        recommendation_type=recommendation_type,
        draft_kind=draft_kind,
    )
    return app.approve_recommendation(
        _principal("admin"),
        project_id=PROJECT_ID,
        recommendation_id=review.value.workflow.recommendation.id,
        expected_version=2,
        idempotency_key=f"approve:{uuid4()}",
    ).value.workflow


def _install_changed_reference(
    store: InMemoryRecommendationStore,
    workflow: RecommendationWorkflow,
    kind: RecommendationInputKind,
) -> None:
    reference = next(
        item for item in workflow.recommendation.evidence.all_refs if item.input_kind == kind
    )
    store.install_evidence(
        replace(
            reference,
            version="v2",
            sha256=_digest(f"{reference.resource_id}:v2"),
        )
    )


def _manual_command(key_char: str, request_char: str) -> RecommendationCommandIdentity:
    return RecommendationCommandIdentity(
        PROJECT_ID,
        key_char * 64,
        RecommendationCommandOperation.SUBMIT,
        request_char * 64,
    )


def _evidence() -> RecommendationEvidenceGraph:
    question = QuestionRef(**_base("question:1"), active=True)
    surface = SurfaceRef(**_base("surface:1"), active=True)
    observation = ObservationRef(
        **_base("observation:1"),
        capture_method="provider_api",
        evidence_class=ObservationEvidenceClass.REAL_OBSERVATION,
        question_resource_id=question.resource_id,
        surface_resource_id=surface.resource_id,
        eligible=True,
    )
    prompt = PromptReleaseRef(**_base("prompt:1"), approved=True, frozen=True)
    return RecommendationEvidenceGraph(
        scope=RecommendationScope(PROJECT_ID, "recommendation-v1"),
        decision=RecommendationDecision(
            impact_chain=("Observed gap", "Lost consideration"),
            risk="medium",
            effort="small",
            business_value="Protect qualified discovery",
            confidence=Decimal("0.8"),
            counterevidence=(),
            validation_plan=("Run paired experiment",),
            stale_conditions=("Any input version changes",),
        ),
        observations=(observation,),
        metric_comparisons=(
            MetricComparisonRef(
                **_base("comparison:1"),
                observation_resource_ids=(observation.resource_id,),
                method_version="method-v1",
                method_sha256=_digest("method-v1"),
                sufficient_evidence=True,
            ),
        ),
        facts=(FactRef(**_base("fact:1"), approved=True, retired=False),),
        rules=(RuleRef(**_base("rule:1"), active=True),),
        prompt_releases=(prompt,),
        model_calls=(
            ModelCallRef(
                **_base("model-call:1"),
                prompt_release_resource_id=prompt.resource_id,
                model_identity="provider/model@release",
                succeeded=True,
            ),
        ),
        contents=(ContentRef(**_base("content:1"), current=True),),
        questions=(question,),
        surfaces=(surface,),
    )


class _BaseRefArgs(TypedDict):
    project_id: UUID
    resource_id: str
    version: str
    sha256: str
    locator: Mapping[str, str]


def _base(resource_id: str) -> _BaseRefArgs:
    return {
        "project_id": PROJECT_ID,
        "resource_id": resource_id,
        "version": "v1",
        "sha256": _digest(f"{resource_id}:v1"),
        "locator": {"id": resource_id},
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
