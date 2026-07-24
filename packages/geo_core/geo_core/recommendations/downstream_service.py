"""Approval-time draft creation and mandatory source-guard application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypedDict, TypeVar, cast
from uuid import UUID

from geo_core.recommendations.downstream_contracts import (
    ConcreteDraftStatus,
    ConcreteRecommendationDraft,
    ContentBriefDraft,
    ContentBriefPayload,
    ExperimentPlanDraft,
    ExperimentPlanPayload,
    QuestionSetDraft,
    QuestionSetPayload,
    RecommendationDraft,
    SamplingPlanDraft,
    SamplingPlanPayload,
    SourceRecommendationReference,
    block_draft,
)
from geo_core.recommendations.downstream_ports import (
    ContentBriefDomainPort,
    ConcreteDraftStoragePort,
    ExperimentPlanDomainPort,
    QuestionSetDomainPort,
    SamplingPlanDomainPort,
    SourceRecommendationPort,
)
from geo_core.recommendations.errors import (
    SOURCE_STALE_PROBLEM_CODE,
    RecommendationConflict,
    RecommendationRuleViolation,
    RecommendationSourceStale,
)
from geo_core.recommendations.evidence import (
    RecommendationInputVersion,
    freeze_input_versions,
    input_fingerprint,
)
from geo_core.recommendations.models import (
    DownstreamDraftKind,
    DownstreamDraftStatus,
    RecommendationStatus,
    RecommendationType,
    RecommendationWorkflow,
    require_aware,
)


_DraftT = TypeVar("_DraftT", bound=RecommendationDraft[object])


@dataclass(frozen=True)
class SourceGuardPermit(Generic[_DraftT]):
    draft: _DraftT
    authorized: bool
    problem_code: str | None = None
    detail: str | None = None

    def require_authorized(self) -> _DraftT:
        if not self.authorized:
            raise RecommendationSourceStale(self.detail or SOURCE_STALE_PROBLEM_CODE)
        return self.draft


class ApprovalDraftAdapter:
    """Create one concrete shell inside the caller-owned approval transaction."""

    def __init__(self, storage: ConcreteDraftStoragePort) -> None:
        self._storage = storage

    def create_for_approval(
        self,
        workflow: RecommendationWorkflow,
    ) -> ConcreteRecommendationDraft | None:
        draft = concrete_draft_from_approval(workflow)
        if draft is None:
            return None
        return self._storage.create_draft(draft)


class SourceRecommendationGuard:
    def inspect(
        self,
        draft: _DraftT,
        source: RecommendationWorkflow | None,
        *,
        current_inputs: tuple[RecommendationInputVersion, ...],
        checked_at: datetime,
    ) -> SourceGuardPermit[_DraftT]:
        require_aware(checked_at, "draft source guard time")
        if draft.status != ConcreteDraftStatus.DRAFT:
            return SourceGuardPermit(
                draft,
                False,
                SOURCE_STALE_PROBLEM_CODE,
                "draft source was already blocked",
            )
        if source is None:
            return self._blocked(
                draft,
                ConcreteDraftStatus.BLOCKED_SOURCE_STALE,
                checked_at,
                "source_recommendation_missing",
            )
        recommendation = source.recommendation
        reference = draft.source
        if (
            recommendation.status == RecommendationStatus.EXPIRED
            or checked_at >= reference.valid_until
        ):
            return self._blocked(
                draft,
                ConcreteDraftStatus.BLOCKED_SOURCE_EXPIRED,
                checked_at,
                "source_recommendation_expired",
            )
        approval = recommendation.approval
        inputs = freeze_input_versions(current_inputs)
        exact_source = (
            recommendation.status == RecommendationStatus.APPROVED
            and recommendation.project_id == reference.project_id
            and recommendation.id == reference.recommendation_id
            and recommendation.version == reference.recommendation_version
            and recommendation.evidence.graph_hash == reference.evidence_graph_hash
            and input_fingerprint(inputs) == reference.input_fingerprint
            and inputs == reference.input_versions
            and approval is not None
            and approval.id == reference.approval_id
            and approval.recommendation_version == reference.recommendation_version
            and approval.frozen_evidence_graph_hash == reference.evidence_graph_hash
            and approval.frozen_input_versions == reference.input_versions
            and approval.valid_until == reference.valid_until
        )
        if not exact_source:
            return self._blocked(
                draft,
                ConcreteDraftStatus.BLOCKED_SOURCE_STALE,
                checked_at,
                "source_recommendation_changed",
            )
        return SourceGuardPermit(draft, True)

    @staticmethod
    def _blocked(
        draft: _DraftT,
        status: ConcreteDraftStatus,
        checked_at: datetime,
        reason: str,
    ) -> SourceGuardPermit[_DraftT]:
        blocked = block_draft(draft, status=status, blocked_at=checked_at, reason=reason)
        return SourceGuardPermit(
            blocked,
            False,
            SOURCE_STALE_PROBLEM_CODE,
            "source Recommendation is no longer the exact approved snapshot",
        )


class GovernedDownstreamDrafts:
    """The only read/next-state entrypoint exposed to downstream domain adapters."""

    def __init__(
        self,
        storage: ConcreteDraftStoragePort,
        sources: SourceRecommendationPort,
        *,
        guard: SourceRecommendationGuard | None = None,
    ) -> None:
        self._storage = storage
        self._sources = sources
        self._guard = guard or SourceRecommendationGuard()

    def read(
        self,
        *,
        draft_id: UUID,
        checked_at: datetime,
    ) -> SourceGuardPermit[RecommendationDraft[object]]:
        loaded = self._storage.load_for_source_guard(draft_id=draft_id)
        if loaded is None:
            raise RecommendationConflict("concrete Recommendation draft does not exist")
        draft: RecommendationDraft[object] = loaded
        source = self._sources.resolve_source_recommendation(
            project_id=draft.source.project_id,
            recommendation_id=draft.source.recommendation_id,
        )
        permit: SourceGuardPermit[RecommendationDraft[object]] = self._guard.inspect(
            draft,
            source.workflow,
            current_inputs=source.current_inputs,
            checked_at=checked_at,
        )
        if permit.draft != draft:
            synchronized: RecommendationDraft[object] = self._storage.synchronize_blocked(
                cast(ConcreteRecommendationDraft, permit.draft)
            )
            return SourceGuardPermit(
                synchronized,
                permit.authorized,
                permit.problem_code,
                permit.detail,
            )
        return permit

    def prepare_next_state(
        self,
        *,
        draft_id: UUID,
        checked_at: datetime,
    ) -> SourceGuardPermit[RecommendationDraft[object]]:
        permit = self.read(
            draft_id=draft_id,
            checked_at=checked_at,
        )
        permit.require_authorized()
        return permit

    def prepare_experiment_plan(
        self,
        *,
        draft_id: UUID,
        checked_at: datetime,
    ) -> SourceGuardPermit[ExperimentPlanDraft]:
        return _typed_permit(
            self.prepare_next_state(
                draft_id=draft_id,
                checked_at=checked_at,
            ),
            ExperimentPlanDraft,
        )

    def prepare_question_set(
        self,
        *,
        draft_id: UUID,
        checked_at: datetime,
    ) -> SourceGuardPermit[QuestionSetDraft]:
        return _typed_permit(
            self.prepare_next_state(
                draft_id=draft_id,
                checked_at=checked_at,
            ),
            QuestionSetDraft,
        )

    def prepare_content_brief(
        self,
        *,
        draft_id: UUID,
        checked_at: datetime,
    ) -> SourceGuardPermit[ContentBriefDraft]:
        return _typed_permit(
            self.prepare_next_state(
                draft_id=draft_id,
                checked_at=checked_at,
            ),
            ContentBriefDraft,
        )

    def prepare_sampling_plan(
        self,
        *,
        draft_id: UUID,
        checked_at: datetime,
    ) -> SourceGuardPermit[SamplingPlanDraft]:
        return _typed_permit(
            self.prepare_next_state(
                draft_id=draft_id,
                checked_at=checked_at,
            ),
            SamplingPlanDraft,
        )


class GuardedDraftDomainDispatcher:
    """The sole bridge from a Recommendation draft into concrete domain shells."""

    def __init__(
        self,
        governed: GovernedDownstreamDrafts,
        *,
        experiments: ExperimentPlanDomainPort,
        questions: QuestionSetDomainPort,
        content: ContentBriefDomainPort,
        sampling: SamplingPlanDomainPort,
    ) -> None:
        self._governed = governed
        self._experiments = experiments
        self._questions = questions
        self._content = content
        self._sampling = sampling

    def create_draft_shell(self, *, draft_id: UUID, checked_at: datetime) -> UUID:
        permit = self._governed.prepare_next_state(
            draft_id=draft_id,
            checked_at=checked_at,
        )
        draft = permit.require_authorized()
        if isinstance(draft, ExperimentPlanDraft):
            return self._experiments.create_experiment_plan_draft(
                _typed_permit(permit, ExperimentPlanDraft)
            )
        if isinstance(draft, QuestionSetDraft):
            return self._questions.create_question_set_draft(
                _typed_permit(permit, QuestionSetDraft)
            )
        if isinstance(draft, ContentBriefDraft):
            return self._content.create_content_brief_draft(
                _typed_permit(permit, ContentBriefDraft)
            )
        if isinstance(draft, SamplingPlanDraft):
            return self._sampling.create_sampling_plan_draft(
                _typed_permit(permit, SamplingPlanDraft)
            )
        raise RecommendationConflict("unsupported guarded Recommendation draft type")


def default_draft_kind(recommendation_type: RecommendationType) -> DownstreamDraftKind | None:
    return {
        RecommendationType.HARD_BLOCKER: DownstreamDraftKind.CONTENT_BRIEF,
        RecommendationType.GAP: DownstreamDraftKind.QUESTION_SET,
        RecommendationType.EXPERIMENT: DownstreamDraftKind.EXPERIMENT_PLAN,
        RecommendationType.OPTIONAL: DownstreamDraftKind.CONTENT_BRIEF,
        RecommendationType.NO_CHANGE: None,
        RecommendationType.INSUFFICIENT_EVIDENCE: DownstreamDraftKind.SAMPLING_PLAN,
    }[RecommendationType(recommendation_type)]


def concrete_draft_from_approval(
    workflow: RecommendationWorkflow,
) -> ConcreteRecommendationDraft | None:
    recommendation = workflow.recommendation
    if recommendation.status != RecommendationStatus.APPROVED or recommendation.approval is None:
        raise RecommendationConflict("concrete drafts require an approved Recommendation")
    kind = recommendation.proposed_draft_kind
    expected_default = default_draft_kind(recommendation.recommendation_type)
    if recommendation.recommendation_type == RecommendationType.NO_CHANGE:
        if kind is not None or workflow.drafts:
            raise RecommendationConflict("no_change cannot create a concrete draft")
        return None
    if recommendation.recommendation_type == RecommendationType.INSUFFICIENT_EVIDENCE:
        kind = kind or expected_default
        if kind != DownstreamDraftKind.SAMPLING_PLAN:
            raise RecommendationConflict("insufficient evidence requires a Sampling Plan draft")
    if kind is None or len(workflow.drafts) != 1:
        raise RecommendationConflict("approved actionable Recommendation needs one linked draft")
    linked = workflow.drafts[0]
    if linked.kind != kind or linked.status != DownstreamDraftStatus.DRAFT:
        raise RecommendationConflict("approval adapter only accepts an unstarted linked draft")
    approval = recommendation.approval
    source = SourceRecommendationReference(
        project_id=recommendation.project_id,
        recommendation_id=recommendation.id,
        recommendation_version=recommendation.version,
        approval_id=approval.id,
        evidence_graph_hash=recommendation.evidence.graph_hash,
        input_versions=approval.frozen_input_versions,
        input_fingerprint=approval.frozen_input_fingerprint,
        valid_until=approval.valid_until,
    )
    common: _CommonDraftValues = {
        "id": linked.id,
        "source": source,
        "idempotency_key": linked.idempotency_key,
        "created_at": linked.created_at,
    }
    evidence = recommendation.evidence
    objective = evidence.decision.business_value
    question_refs = _refs(
        *(item.resource_id for item in evidence.questions),
        evidence.scope.question_or_cluster_ref,
    )
    surface_refs = _refs(
        *(item.resource_id for item in evidence.surfaces),
        evidence.scope.surface_ref,
    )
    if kind == DownstreamDraftKind.EXPERIMENT_PLAN:
        return ExperimentPlanDraft(
            **common,
            payload=ExperimentPlanPayload(
                objective=objective,
                hypothesis=evidence.decision.impact_chain[0],
                validation_steps=evidence.decision.validation_plan,
                metric_comparison_refs=_refs(
                    *(item.resource_id for item in evidence.metric_comparisons)
                ),
            ),
        )
    if kind == DownstreamDraftKind.QUESTION_SET:
        return QuestionSetDraft(
            **common,
            payload=QuestionSetPayload(
                objective=objective,
                question_refs=question_refs,
                surface_refs=surface_refs,
            ),
        )
    if kind == DownstreamDraftKind.CONTENT_BRIEF:
        content_ref = (
            evidence.scope.content_asset_ref
            or next(
                (item.resource_id for item in evidence.contents),
                "",
            )
            or ""
        )
        return ContentBriefDraft(
            **common,
            payload=ContentBriefPayload(
                objective=objective,
                content_asset_ref=content_ref,
                question_refs=question_refs,
                approved_fact_refs=_refs(
                    *(item.resource_id for item in evidence.facts if item.approved)
                ),
            ),
        )
    if kind == DownstreamDraftKind.SAMPLING_PLAN:
        return SamplingPlanDraft(
            **common,
            payload=SamplingPlanPayload(
                objective=objective,
                question_refs=question_refs,
                surface_refs=surface_refs,
            ),
        )
    raise RecommendationRuleViolation("unsupported concrete draft kind")


def _refs(*values: str | None) -> tuple[str, ...]:
    return tuple(sorted({value.strip() for value in values if value and value.strip()}))


class _CommonDraftValues(TypedDict):
    id: UUID
    source: SourceRecommendationReference
    idempotency_key: str
    created_at: datetime


def _typed_permit(
    permit: SourceGuardPermit[RecommendationDraft[object]],
    expected: type[_DraftT],
) -> SourceGuardPermit[_DraftT]:
    if not isinstance(permit.draft, expected):
        raise RecommendationConflict(f"draft is not a {expected.__name__}")
    return cast(SourceGuardPermit[_DraftT], permit)
