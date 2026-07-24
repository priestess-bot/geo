"""Ports that preserve the source guard between Recommendations and draft domains."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar
from uuid import UUID

from geo_core.recommendations.downstream_contracts import (
    ConcreteRecommendationDraft,
    ContentBriefDraft,
    ExperimentPlanDraft,
    QuestionSetDraft,
    RecommendationDraft,
    SamplingPlanDraft,
)
from geo_core.recommendations.models import RecommendationWorkflow
from geo_core.recommendations.evidence import RecommendationInputVersion


class ConcreteDraftStoragePort(Protocol):
    """Persistence has create and guard-block operations, but no start operation."""

    def create_draft(self, draft: ConcreteRecommendationDraft) -> ConcreteRecommendationDraft: ...

    def load_for_source_guard(self, *, draft_id: UUID) -> ConcreteRecommendationDraft | None: ...

    def synchronize_blocked(
        self, draft: ConcreteRecommendationDraft
    ) -> ConcreteRecommendationDraft: ...


@dataclass(frozen=True)
class ResolvedSourceRecommendation:
    """Current server-resolved source state; never assembled by an API caller."""

    workflow: RecommendationWorkflow | None
    current_inputs: tuple[RecommendationInputVersion, ...]


class SourceRecommendationPort(Protocol):
    def resolve_source_recommendation(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> ResolvedSourceRecommendation: ...


_DraftT = TypeVar("_DraftT", bound=RecommendationDraft[object], covariant=True)


class GuardedDraftPermit(Generic[_DraftT], Protocol):
    @property
    def draft(self) -> _DraftT: ...

    def require_authorized(self) -> _DraftT: ...


class ExperimentPlanDomainPort(Protocol):
    def create_experiment_plan_draft(
        self, permit: GuardedDraftPermit[ExperimentPlanDraft]
    ) -> UUID: ...


class QuestionSetDomainPort(Protocol):
    """Implementable by the existing QuestionSet application without a raw-draft bypass."""

    def create_question_set_draft(self, permit: GuardedDraftPermit[QuestionSetDraft]) -> UUID: ...


class ContentBriefDomainPort(Protocol):
    """Implementable by Content while retaining the Recommendation guard receipt."""

    def create_content_brief_draft(self, permit: GuardedDraftPermit[ContentBriefDraft]) -> UUID: ...


class SamplingPlanDomainPort(Protocol):
    def create_sampling_plan_draft(self, permit: GuardedDraftPermit[SamplingPlanDraft]) -> UUID: ...
