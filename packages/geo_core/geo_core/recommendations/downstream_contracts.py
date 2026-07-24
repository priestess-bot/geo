"""Concrete, immutable draft-only contracts created from approved Recommendations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Generic, TypeVar
from uuid import UUID, uuid5

from geo_core.recommendations.evidence import (
    SHA256_PATTERN,
    RecommendationInputVersion,
    freeze_input_versions,
    input_fingerprint,
)
from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.models import (
    DownstreamDraftKind,
    normalise_idempotency_key,
    require_aware,
)


class ConcreteDraftStatus(StrEnum):
    """States owned by the Recommendation side of a downstream handoff."""

    DRAFT = "draft"
    BLOCKED_SOURCE_STALE = "blocked_source_stale"
    BLOCKED_SOURCE_EXPIRED = "blocked_source_expired"


@dataclass(frozen=True)
class SourceRecommendationReference:
    project_id: UUID
    recommendation_id: UUID
    recommendation_version: int
    approval_id: UUID
    evidence_graph_hash: str
    input_versions: tuple[RecommendationInputVersion, ...]
    input_fingerprint: str
    valid_until: datetime

    def __post_init__(self) -> None:
        if self.recommendation_version < 1:
            raise RecommendationRuleViolation("draft source version must be positive")
        if not SHA256_PATTERN.fullmatch(self.evidence_graph_hash):
            raise RecommendationRuleViolation("draft source graph hash must be lowercase SHA-256")
        frozen = freeze_input_versions(self.input_versions)
        if input_fingerprint(frozen) != self.input_fingerprint:
            raise RecommendationRuleViolation("draft source input fingerprint is inconsistent")
        require_aware(self.valid_until, "draft source validity time")
        object.__setattr__(self, "input_versions", frozen)


@dataclass(frozen=True)
class ExperimentPlanPayload:
    objective: str
    hypothesis: str
    validation_steps: tuple[str, ...]
    metric_comparison_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "objective", _required(self.objective, "experiment objective"))
        object.__setattr__(self, "hypothesis", _required(self.hypothesis, "experiment hypothesis"))
        object.__setattr__(
            self,
            "validation_steps",
            _references(self.validation_steps, "experiment validation steps"),
        )
        object.__setattr__(
            self,
            "metric_comparison_refs",
            _references(self.metric_comparison_refs, "experiment metric comparisons"),
        )


@dataclass(frozen=True)
class QuestionSetPayload:
    objective: str
    question_refs: tuple[str, ...]
    surface_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "objective", _required(self.objective, "question set objective"))
        object.__setattr__(
            self, "question_refs", _references(self.question_refs, "question set questions")
        )
        object.__setattr__(
            self, "surface_refs", _references(self.surface_refs, "question set surfaces")
        )


@dataclass(frozen=True)
class ContentBriefPayload:
    objective: str
    content_asset_ref: str
    question_refs: tuple[str, ...]
    approved_fact_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "objective", _required(self.objective, "content brief objective"))
        object.__setattr__(
            self,
            "content_asset_ref",
            _required(self.content_asset_ref, "content brief asset"),
        )
        object.__setattr__(
            self, "question_refs", _references(self.question_refs, "content brief questions")
        )
        object.__setattr__(
            self,
            "approved_fact_refs",
            _references(self.approved_fact_refs, "content brief facts"),
        )


@dataclass(frozen=True)
class SamplingPlanPayload:
    objective: str
    question_refs: tuple[str, ...]
    surface_refs: tuple[str, ...]
    repetitions_per_question: int = 10

    def __post_init__(self) -> None:
        object.__setattr__(self, "objective", _required(self.objective, "sampling objective"))
        object.__setattr__(
            self, "question_refs", _references(self.question_refs, "sampling questions")
        )
        object.__setattr__(
            self, "surface_refs", _references(self.surface_refs, "sampling surfaces")
        )
        if not 1 <= self.repetitions_per_question <= 100:
            raise RecommendationRuleViolation("sampling repetitions must be between 1 and 100")


_PayloadT = TypeVar("_PayloadT", covariant=True)


@dataclass(frozen=True, kw_only=True)
class RecommendationDraft(Generic[_PayloadT]):
    """A shell only; execution, queue and publication state are intentionally absent."""

    id: UUID
    source: SourceRecommendationReference
    idempotency_key: str
    payload: _PayloadT
    created_at: datetime
    status: ConcreteDraftStatus = ConcreteDraftStatus.DRAFT
    blocked_at: datetime | None = None
    blocked_reason: str | None = None

    kind: ClassVar[DownstreamDraftKind]
    payload_type: ClassVar[type[object]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ConcreteDraftStatus(self.status))
        key = normalise_idempotency_key(self.idempotency_key)
        expected_id = uuid5(
            self.source.recommendation_id,
            f"recommendation-draft:{key}",
        )
        if self.id != expected_id:
            raise RecommendationRuleViolation(
                "concrete draft identity must match its idempotency key"
            )
        if not isinstance(self.payload, self.payload_type):
            raise RecommendationRuleViolation(
                f"{self.kind.value} requires {self.payload_type.__name__}"
            )
        require_aware(self.created_at, "concrete draft creation time")
        blocked = self.status != ConcreteDraftStatus.DRAFT
        if blocked:
            if self.blocked_at is None or not (self.blocked_reason or "").strip():
                raise RecommendationRuleViolation("blocked concrete draft needs time and reason")
            require_aware(self.blocked_at, "concrete draft blocked time")
        elif self.blocked_at is not None or self.blocked_reason is not None:
            raise RecommendationRuleViolation("draft-only state cannot carry blocking details")
        object.__setattr__(self, "idempotency_key", key)


@dataclass(frozen=True, kw_only=True)
class ExperimentPlanDraft(RecommendationDraft[ExperimentPlanPayload]):
    kind: ClassVar[DownstreamDraftKind] = DownstreamDraftKind.EXPERIMENT_PLAN
    payload_type: ClassVar[type[object]] = ExperimentPlanPayload


@dataclass(frozen=True, kw_only=True)
class QuestionSetDraft(RecommendationDraft[QuestionSetPayload]):
    kind: ClassVar[DownstreamDraftKind] = DownstreamDraftKind.QUESTION_SET
    payload_type: ClassVar[type[object]] = QuestionSetPayload


@dataclass(frozen=True, kw_only=True)
class ContentBriefDraft(RecommendationDraft[ContentBriefPayload]):
    kind: ClassVar[DownstreamDraftKind] = DownstreamDraftKind.CONTENT_BRIEF
    payload_type: ClassVar[type[object]] = ContentBriefPayload


@dataclass(frozen=True, kw_only=True)
class SamplingPlanDraft(RecommendationDraft[SamplingPlanPayload]):
    kind: ClassVar[DownstreamDraftKind] = DownstreamDraftKind.SAMPLING_PLAN
    payload_type: ClassVar[type[object]] = SamplingPlanPayload


ConcreteRecommendationDraft = (
    ExperimentPlanDraft | QuestionSetDraft | ContentBriefDraft | SamplingPlanDraft
)

_DraftT = TypeVar("_DraftT", bound=RecommendationDraft[object])


def block_draft(
    draft: _DraftT,
    *,
    status: ConcreteDraftStatus,
    blocked_at: datetime,
    reason: str,
) -> _DraftT:
    if status == ConcreteDraftStatus.DRAFT:
        raise RecommendationRuleViolation("source guard cannot block a draft with draft status")
    return replace(
        draft,
        status=status,
        blocked_at=blocked_at,
        blocked_reason=_required(reason, "draft block reason"),
    )


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RecommendationRuleViolation(f"{label} is required")
    return normalized


def _references(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted({_required(value, label) for value in values}))
    if not normalized:
        raise RecommendationRuleViolation(f"{label} are required")
    return normalized
