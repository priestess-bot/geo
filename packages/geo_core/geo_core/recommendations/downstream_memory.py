"""In-memory draft-only adapters for the concrete downstream contracts."""

from __future__ import annotations

from threading import RLock
from uuid import UUID

from geo_core.recommendations.downstream_contracts import (
    ConcreteDraftStatus,
    ConcreteRecommendationDraft,
)
from geo_core.recommendations.errors import RecommendationConflict
from geo_core.recommendations.evidence import RecommendationInputVersion
from geo_core.recommendations.models import RecommendationWorkflow
from geo_core.recommendations.downstream_ports import ResolvedSourceRecommendation


class DownstreamDraftTransitionRejected(RecommendationConflict):
    """Raw repositories cannot advance a Recommendation-created draft."""


class InMemoryConcreteDraftStorage:
    def __init__(self, initial: tuple[ConcreteRecommendationDraft, ...] = ()) -> None:
        self._lock = RLock()
        self._drafts: dict[UUID, ConcreteRecommendationDraft] = {}
        self._idempotency: dict[tuple[UUID, str], UUID] = {}
        for draft in initial:
            self._insert_initial(draft)

    def create_draft(self, draft: ConcreteRecommendationDraft) -> ConcreteRecommendationDraft:
        if (
            draft.status != ConcreteDraftStatus.DRAFT
            or draft.blocked_at is not None
            or draft.blocked_reason is not None
        ):
            raise DownstreamDraftTransitionRejected(
                "approval adapter can only create a draft-only unstarted shell"
            )
        with self._lock:
            key = (draft.source.project_id, draft.idempotency_key)
            existing_id = self._idempotency.get(key)
            existing = self._drafts.get(draft.id)
            if existing_id is not None and existing_id != draft.id:
                raise RecommendationConflict("draft idempotency key owns another identity")
            if existing is not None:
                if existing != draft:
                    raise RecommendationConflict("draft identity already owns different content")
                return existing
            self._drafts[draft.id] = draft
            self._idempotency[key] = draft.id
            return draft

    def load_for_source_guard(self, *, draft_id: UUID) -> ConcreteRecommendationDraft | None:
        with self._lock:
            return self._drafts.get(draft_id)

    def synchronize_blocked(
        self, draft: ConcreteRecommendationDraft
    ) -> ConcreteRecommendationDraft:
        if draft.status == ConcreteDraftStatus.DRAFT:
            raise DownstreamDraftTransitionRejected("only Source Guard may persist blocked status")
        with self._lock:
            current = self._drafts.get(draft.id)
            if current is None:
                raise RecommendationConflict("cannot block an unknown concrete draft")
            if _immutable_value(current) != _immutable_value(draft):
                raise RecommendationConflict("Source Guard cannot change draft payload or lineage")
            if current.status != ConcreteDraftStatus.DRAFT:
                if current != draft:
                    raise RecommendationConflict("concrete draft already has another block result")
                return current
            self._drafts[draft.id] = draft
            return draft

    def transition(self, draft: ConcreteRecommendationDraft, target: str) -> None:
        del draft, target
        raise DownstreamDraftTransitionRejected(
            "repository transitions are forbidden; use GovernedDownstreamDrafts"
        )

    def all(self) -> tuple[ConcreteRecommendationDraft, ...]:
        with self._lock:
            return tuple(sorted(self._drafts.values(), key=lambda item: str(item.id)))

    def _insert_initial(self, draft: ConcreteRecommendationDraft) -> None:
        key = (draft.source.project_id, draft.idempotency_key)
        if draft.id in self._drafts or key in self._idempotency:
            raise RecommendationConflict("duplicate initial concrete draft")
        self._drafts[draft.id] = draft
        self._idempotency[key] = draft.id


class InMemorySourceRecommendations:
    def __init__(self, workflows: tuple[RecommendationWorkflow, ...] = ()) -> None:
        self._lock = RLock()
        self._workflows = {
            (workflow.recommendation.project_id, workflow.recommendation.id): (
                workflow,
                workflow.recommendation.evidence.input_versions,
            )
            for workflow in workflows
        }

    def put(
        self,
        workflow: RecommendationWorkflow,
        *,
        current_inputs: tuple[RecommendationInputVersion, ...] | None = None,
    ) -> None:
        with self._lock:
            self._workflows[(workflow.recommendation.project_id, workflow.recommendation.id)] = (
                workflow,
                current_inputs or workflow.recommendation.evidence.input_versions,
            )

    def resolve_source_recommendation(
        self, *, project_id: UUID, recommendation_id: UUID
    ) -> ResolvedSourceRecommendation:
        with self._lock:
            value = self._workflows.get((project_id, recommendation_id))
        if value is None:
            return ResolvedSourceRecommendation(None, ())
        return ResolvedSourceRecommendation(*value)


def _immutable_value(draft: ConcreteRecommendationDraft) -> tuple[object, ...]:
    return (
        type(draft),
        draft.id,
        draft.source,
        draft.idempotency_key,
        draft.payload,
        draft.created_at,
    )
