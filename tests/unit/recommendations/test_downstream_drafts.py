from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import inspect
from typing import Mapping, TypedDict, get_type_hints
from uuid import UUID, uuid4

import pytest

from geo_core.recommendations.downstream_contracts import (
    ConcreteDraftStatus,
    ContentBriefDraft,
    ExperimentPlanDraft,
    QuestionSetDraft,
    RecommendationDraft,
    SamplingPlanDraft,
)
from geo_core.recommendations.downstream_memory import (
    DownstreamDraftTransitionRejected,
    InMemoryConcreteDraftStorage,
    InMemorySourceRecommendations,
)
from geo_core.recommendations.downstream_ports import (
    ConcreteDraftStoragePort,
    ContentBriefDomainPort,
    ExperimentPlanDomainPort,
    QuestionSetDomainPort,
    SamplingPlanDomainPort,
)
from geo_core.recommendations.downstream_service import (
    ApprovalDraftAdapter,
    GuardedDraftDomainDispatcher,
    GovernedDownstreamDrafts,
    concrete_draft_from_approval,
    default_draft_kind,
)
from geo_core.recommendations.errors import (
    RecommendationConflict,
    RecommendationRuleViolation,
    RecommendationSourceStale,
)
from geo_core.recommendations.evidence import (
    ContentRef,
    FactRef,
    MetricComparisonRef,
    ModelCallRef,
    ObservationEvidenceClass,
    ObservationRef,
    PromptReleaseRef,
    QuestionRef,
    RecommendationDecision,
    RecommendationEvidenceGraph,
    RecommendationInputKind,
    RecommendationInputVersion,
    RecommendationScope,
    RuleRef,
    SurfaceRef,
)
from geo_core.recommendations.lifecycle import (
    approve_and_create_draft,
    reconcile_approved_inputs,
    submit_recommendation,
)
from geo_core.recommendations.models import (
    DownstreamDraftKind,
    InputChangeReason,
    Recommendation,
    RecommendationStatus,
    RecommendationType,
    RecommendationWorkflow,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
PROJECT_ID = UUID("20000000-0000-0000-0000-000000000002")


@pytest.mark.parametrize(
    ("recommendation_type", "kind", "concrete_type"),
    (
        (
            RecommendationType.HARD_BLOCKER,
            DownstreamDraftKind.CONTENT_BRIEF,
            ContentBriefDraft,
        ),
        (RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET, QuestionSetDraft),
        (
            RecommendationType.EXPERIMENT,
            DownstreamDraftKind.EXPERIMENT_PLAN,
            ExperimentPlanDraft,
        ),
        (
            RecommendationType.OPTIONAL,
            DownstreamDraftKind.CONTENT_BRIEF,
            ContentBriefDraft,
        ),
        (RecommendationType.NO_CHANGE, None, type(None)),
        (
            RecommendationType.INSUFFICIENT_EVIDENCE,
            DownstreamDraftKind.SAMPLING_PLAN,
            SamplingPlanDraft,
        ),
    ),
)
def test_all_recommendation_types_create_only_the_expected_concrete_draft(
    recommendation_type: RecommendationType,
    kind: DownstreamDraftKind | None,
    concrete_type: type[object],
) -> None:
    approved = _approved(recommendation_type, kind)
    storage = InMemoryConcreteDraftStorage()
    result = ApprovalDraftAdapter(storage).create_for_approval(approved)

    assert (
        default_draft_kind(recommendation_type)
        == {
            RecommendationType.HARD_BLOCKER: DownstreamDraftKind.CONTENT_BRIEF,
            RecommendationType.GAP: DownstreamDraftKind.QUESTION_SET,
            RecommendationType.EXPERIMENT: DownstreamDraftKind.EXPERIMENT_PLAN,
            RecommendationType.OPTIONAL: DownstreamDraftKind.CONTENT_BRIEF,
            RecommendationType.NO_CHANGE: None,
            RecommendationType.INSUFFICIENT_EVIDENCE: DownstreamDraftKind.SAMPLING_PLAN,
        }[recommendation_type]
    )
    if concrete_type is type(None):
        assert result is None
        assert approved.drafts == ()
        assert storage.all() == ()
        return
    assert isinstance(result, RecommendationDraft)
    linked = approved.drafts[0]
    approval = approved.recommendation.approval
    assert approval is not None
    assert result.id == linked.id
    assert result.idempotency_key == linked.idempotency_key
    assert result.status == ConcreteDraftStatus.DRAFT
    assert result.blocked_at is result.blocked_reason is None
    assert result.source.recommendation_version == approved.recommendation.version
    assert result.source.approval_id == approval.id
    assert result.source.evidence_graph_hash == approved.recommendation.evidence.graph_hash
    forbidden = {"started_at", "enqueued", "job_id", "executed", "published"}
    assert forbidden.isdisjoint(field.name for field in fields(result))
    assert isinstance(result, concrete_type)


def test_approval_retry_reuses_one_concrete_identity_and_idempotency_key() -> None:
    first = _approved(RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET)
    recommendation = first.recommendation
    approval = recommendation.approval
    assert approval is not None
    replay = approve_and_create_draft(
        first,
        expected_version=2,
        approval_id=approval.id,
        actor_id=approval.approved_by,
        current_inputs=recommendation.evidence.input_versions,
        occurred_at=approval.approved_at,
        draft_idempotency_key=first.drafts[0].idempotency_key,
    )
    storage = InMemoryConcreteDraftStorage()
    adapter = ApprovalDraftAdapter(storage)

    created = adapter.create_for_approval(first)
    repeated = adapter.create_for_approval(replay.workflow)

    assert replay.replayed is True
    assert created == repeated
    assert len(storage.all()) == 1


@pytest.mark.parametrize("tamper", ("version", "approval", "graph"))
def test_source_guard_blocks_tampered_immutable_lineage(tamper: str) -> None:
    approved = _approved(RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET)
    original = concrete_draft_from_approval(approved)
    assert isinstance(original, QuestionSetDraft)
    source = original.source
    if tamper == "version":
        source = replace(source, recommendation_version=source.recommendation_version - 1)
    elif tamper == "approval":
        source = replace(source, approval_id=uuid4())
    else:
        source = replace(source, evidence_graph_hash="f" * 64)
    tampered = replace(original, source=source)
    storage = InMemoryConcreteDraftStorage((tampered,))
    governed = GovernedDownstreamDrafts(
        storage,
        InMemorySourceRecommendations((approved,)),
    )

    checked = governed.read(
        draft_id=tampered.id,
        checked_at=NOW + timedelta(minutes=5),
    )

    assert checked.authorized is False
    assert checked.draft.status == ConcreteDraftStatus.BLOCKED_SOURCE_STALE
    assert storage.load_for_source_guard(draft_id=tampered.id) == checked.draft
    with pytest.raises(RecommendationSourceStale):
        governed.prepare_next_state(
            draft_id=tampered.id,
            checked_at=NOW + timedelta(minutes=6),
        )


def test_every_read_and_domain_entry_rechecks_current_inputs() -> None:
    approved = _approved(RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET)
    storage = InMemoryConcreteDraftStorage()
    draft = ApprovalDraftAdapter(storage).create_for_approval(approved)
    assert isinstance(draft, QuestionSetDraft)
    governed = GovernedDownstreamDrafts(
        storage,
        InMemorySourceRecommendations((approved,)),
    )

    valid = governed.read(
        draft_id=draft.id,
        checked_at=NOW + timedelta(minutes=5),
    )
    prepared = governed.prepare_question_set(
        draft_id=draft.id,
        checked_at=NOW + timedelta(minutes=6),
    )

    assert valid.authorized is prepared.authorized is True
    assert prepared.require_authorized() == draft
    assert isinstance(prepared.draft, QuestionSetDraft)


def test_stale_and_expired_sources_synchronize_blocked_status() -> None:
    approved = _approved(RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET)
    changed_inputs = _changed_inputs(approved.recommendation.evidence.input_versions)
    stale = reconcile_approved_inputs(
        approved,
        current_inputs=changed_inputs,
        change_reason=InputChangeReason.DATA_REFRESHED,
        actor_id="source-guard",
        occurred_at=NOW + timedelta(minutes=5),
    )
    stale_storage = InMemoryConcreteDraftStorage()
    stale_draft = ApprovalDraftAdapter(stale_storage).create_for_approval(approved)
    assert stale_draft is not None
    stale_sources = InMemorySourceRecommendations()
    stale_sources.put(stale, current_inputs=changed_inputs)
    stale_guarded = GovernedDownstreamDrafts(stale_storage, stale_sources)

    stale_result = stale_guarded.read(
        draft_id=stale_draft.id,
        checked_at=NOW + timedelta(minutes=6),
    )

    assert stale.recommendation.status == RecommendationStatus.STALE
    assert stale_result.draft.status == ConcreteDraftStatus.BLOCKED_SOURCE_STALE

    expired_storage = InMemoryConcreteDraftStorage()
    expired_draft = ApprovalDraftAdapter(expired_storage).create_for_approval(approved)
    assert expired_draft is not None
    expired_guarded = GovernedDownstreamDrafts(
        expired_storage,
        InMemorySourceRecommendations((approved,)),
    )
    expired_result = expired_guarded.read(
        draft_id=expired_draft.id,
        checked_at=approved.recommendation.valid_until,
    )

    assert expired_result.draft.status == ConcreteDraftStatus.BLOCKED_SOURCE_EXPIRED
    assert expired_storage.load_for_source_guard(draft_id=expired_draft.id) == expired_result.draft


def test_repository_rejects_direct_transition_and_non_draft_create() -> None:
    approved = _approved(RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET)
    storage = InMemoryConcreteDraftStorage()
    draft = ApprovalDraftAdapter(storage).create_for_approval(approved)
    assert draft is not None

    with pytest.raises(DownstreamDraftTransitionRejected, match="forbidden"):
        storage.transition(draft, "started")
    blocked = replace(
        draft,
        status=ConcreteDraftStatus.BLOCKED_SOURCE_STALE,
        blocked_at=NOW + timedelta(minutes=5),
        blocked_reason="attempted_bypass",
    )
    with pytest.raises(DownstreamDraftTransitionRejected, match="only create"):
        InMemoryConcreteDraftStorage().create_draft(blocked)


def test_ports_expose_guarded_create_only_contracts() -> None:
    storage_methods = {
        name
        for name, _ in inspect.getmembers(ConcreteDraftStoragePort, inspect.isfunction)
        if not name.startswith("_")
    }
    assert storage_methods == {
        "create_draft",
        "load_for_source_guard",
        "synchronize_blocked",
    }
    assert not any(
        token in name for name in storage_methods for token in ("execute", "enqueue", "publish")
    )
    question_hint = get_type_hints(QuestionSetDomainPort.create_question_set_draft)["permit"]
    content_hint = get_type_hints(ContentBriefDomainPort.create_content_brief_draft)["permit"]
    assert "GuardedDraftPermit" in str(question_hint)
    assert "GuardedDraftPermit" in str(content_hint)


@pytest.mark.parametrize(
    ("recommendation_type", "kind", "expected_method"),
    (
        (
            RecommendationType.EXPERIMENT,
            DownstreamDraftKind.EXPERIMENT_PLAN,
            "experiment",
        ),
        (RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET, "question"),
        (RecommendationType.OPTIONAL, DownstreamDraftKind.CONTENT_BRIEF, "content"),
        (
            RecommendationType.INSUFFICIENT_EVIDENCE,
            DownstreamDraftKind.SAMPLING_PLAN,
            "sampling",
        ),
    ),
)
def test_guarded_dispatcher_is_the_only_bridge_to_concrete_domain_shells(
    recommendation_type: RecommendationType,
    kind: DownstreamDraftKind,
    expected_method: str,
) -> None:
    approved = _approved(recommendation_type, kind)
    storage = InMemoryConcreteDraftStorage()
    draft = ApprovalDraftAdapter(storage).create_for_approval(approved)
    assert draft is not None
    domains = _DomainShells()
    dispatcher = GuardedDraftDomainDispatcher(
        GovernedDownstreamDrafts(
            storage,
            InMemorySourceRecommendations((approved,)),
        ),
        experiments=domains,
        questions=domains,
        content=domains,
        sampling=domains,
    )

    created_id = dispatcher.create_draft_shell(
        draft_id=draft.id,
        checked_at=NOW + timedelta(minutes=5),
    )

    assert created_id == draft.id
    assert domains.calls == [(expected_method, draft.id)]
    public_methods = {
        name
        for name, member in inspect.getmembers(dispatcher, inspect.ismethod)
        if not name.startswith("_")
    }
    assert public_methods == {"create_draft_shell"}


def test_guarded_dispatcher_never_calls_domain_adapter_for_stale_source() -> None:
    approved = _approved(RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET)
    changed = _changed_inputs(approved.recommendation.evidence.input_versions)
    stale = reconcile_approved_inputs(
        approved,
        current_inputs=changed,
        change_reason=InputChangeReason.DATA_REFRESHED,
        actor_id="source-guard",
        occurred_at=NOW + timedelta(minutes=5),
    )
    storage = InMemoryConcreteDraftStorage()
    draft = ApprovalDraftAdapter(storage).create_for_approval(approved)
    assert draft is not None
    sources = InMemorySourceRecommendations()
    sources.put(stale, current_inputs=changed)
    domains = _DomainShells()
    dispatcher = GuardedDraftDomainDispatcher(
        GovernedDownstreamDrafts(storage, sources),
        experiments=domains,
        questions=domains,
        content=domains,
        sampling=domains,
    )

    with pytest.raises(RecommendationSourceStale):
        dispatcher.create_draft_shell(
            draft_id=draft.id,
            checked_at=NOW + timedelta(minutes=6),
        )

    assert domains.calls == []
    blocked = storage.load_for_source_guard(draft_id=draft.id)
    assert blocked is not None
    assert blocked.status == ConcreteDraftStatus.BLOCKED_SOURCE_STALE


def test_adapter_requires_approved_source_and_exact_concrete_payload_type() -> None:
    draft_workflow = _workflow(RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET)
    with pytest.raises(RecommendationConflict, match="approved"):
        ApprovalDraftAdapter(InMemoryConcreteDraftStorage()).create_for_approval(draft_workflow)

    approved = _approved(RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET)
    concrete = concrete_draft_from_approval(approved)
    assert isinstance(concrete, QuestionSetDraft)
    with pytest.raises(RecommendationRuleViolation, match="requires QuestionSetPayload"):
        replace(concrete, payload=object())  # type: ignore[arg-type]


def _approved(
    recommendation_type: RecommendationType,
    draft_kind: DownstreamDraftKind | None,
) -> RecommendationWorkflow:
    submitted = submit_recommendation(
        _workflow(recommendation_type, draft_kind),
        expected_version=1,
        actor_id="creator",
        occurred_at=NOW + timedelta(minutes=1),
    )
    outcome = approve_and_create_draft(
        submitted,
        expected_version=2,
        approval_id=uuid4(),
        actor_id="approver",
        current_inputs=submitted.recommendation.evidence.input_versions,
        occurred_at=NOW + timedelta(minutes=2),
        draft_idempotency_key=None if draft_kind is None else "approval-command:downstream",
    )
    return outcome.workflow


def _workflow(
    recommendation_type: RecommendationType,
    draft_kind: DownstreamDraftKind | None,
) -> RecommendationWorkflow:
    recommendation = Recommendation(
        id=uuid4(),
        project_id=PROJECT_ID,
        recommendation_type=recommendation_type,
        evidence=_evidence(),
        proposed_draft_kind=draft_kind,
        valid_until=NOW + timedelta(days=30),
        created_by="creator",
        created_at=NOW,
        updated_at=NOW,
    )
    return RecommendationWorkflow(recommendation)


def _changed_inputs(
    values: tuple[RecommendationInputVersion, ...],
) -> tuple[RecommendationInputVersion, ...]:
    return tuple(
        replace(item, sha256="f" * 64) if item.kind == RecommendationInputKind.FACT else item
        for item in values
    )


def _evidence() -> RecommendationEvidenceGraph:
    question = QuestionRef(**_base("question:1"), active=True)
    surface = SurfaceRef(**_base("surface:google-aio:r1"), active=True)
    observation = ObservationRef(
        **_base("observation:1"),
        capture_method="automated_ui",
        evidence_class=ObservationEvidenceClass.REAL_OBSERVATION,
        question_resource_id=question.resource_id,
        surface_resource_id=surface.resource_id,
        eligible=True,
    )
    prompt = PromptReleaseRef(**_base("prompt:recommendation:r1"), approved=True, frozen=True)
    return RecommendationEvidenceGraph(
        scope=RecommendationScope(
            PROJECT_ID,
            "recommendation-contract-v1",
            question_or_cluster_ref=question.resource_id,
            surface_ref=surface.resource_id,
            content_asset_ref="content:1",
        ),
        decision=RecommendationDecision(
            impact_chain=("Observed omission", "Lower consideration"),
            risk="medium",
            effort="small",
            business_value="Protect qualified discovery",
            confidence=Decimal("0.82"),
            counterevidence=("One interval remains wide",),
            validation_plan=("Run a paired frozen experiment",),
            stale_conditions=("Any source input changes",),
        ),
        observations=(observation,),
        metric_comparisons=(
            MetricComparisonRef(
                **_base("comparison:1"),
                observation_resource_ids=(observation.resource_id,),
                method_version="comparison-method-v1",
                method_sha256=_digest("comparison-method-v1"),
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
                model_identity="provider/model@2026-07-23",
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


class _DomainShells(
    ExperimentPlanDomainPort,
    QuestionSetDomainPort,
    ContentBriefDomainPort,
    SamplingPlanDomainPort,
):
    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID]] = []

    def create_experiment_plan_draft(self, permit) -> UUID:
        return self._record("experiment", permit.require_authorized())

    def create_question_set_draft(self, permit) -> UUID:
        return self._record("question", permit.require_authorized())

    def create_content_brief_draft(self, permit) -> UUID:
        return self._record("content", permit.require_authorized())

    def create_sampling_plan_draft(self, permit) -> UUID:
        return self._record("sampling", permit.require_authorized())

    def _record(self, name: str, draft: RecommendationDraft[object]) -> UUID:
        self.calls.append((name, draft.id))
        return draft.id
