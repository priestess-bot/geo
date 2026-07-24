"""Frozen evidence contracts consumed by Recommendation generation Jobs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.evidence import (
    AttributionRef,
    ContentRef,
    EvidenceRef,
    FactRef,
    MetricComparisonRef,
    ObservationRef,
    QuestionRef,
    RecommendationScope,
    RuleRef,
    SurfaceRef,
)
from geo_core.recommendations.generation_hashing import (
    canonical_hash,
    locator as _locator,
    required as _required,
    text_hash as _text_hash,
)


@dataclass(frozen=True)
class EvidenceSummary:
    ref_kind: str
    resource_id: str
    summary: str
    summary_hash: str

    def __post_init__(self) -> None:
        if self.ref_kind not in {"observation", "metric_comparison", "fact", "rule"}:
            raise RecommendationRuleViolation("generation summary has an unsupported ref kind")
        object.__setattr__(self, "resource_id", _required(self.resource_id, "summary resource"))
        summary = _required(self.summary, "evidence summary")
        if _text_hash(summary) != self.summary_hash:
            raise RecommendationRuleViolation("evidence summary hash is inconsistent")
        object.__setattr__(self, "summary", summary)

    @property
    def identity(self) -> tuple[str, str]:
        return (self.ref_kind, self.resource_id)


@dataclass(frozen=True)
class ScopeLocator:
    field_name: str
    resource_id: str
    locator: Mapping[str, str]

    def __post_init__(self) -> None:
        allowed = {
            "campaign_id",
            "question_or_cluster_ref",
            "surface_ref",
            "content_asset_ref",
            "url_ref",
        }
        if self.field_name not in allowed:
            raise RecommendationRuleViolation("generation scope locator field is unsupported")
        object.__setattr__(self, "resource_id", _required(self.resource_id, "scope resource"))
        object.__setattr__(self, "locator", _locator(self.locator, "scope resource"))


@dataclass(frozen=True)
class FrozenGenerationEvidence:
    scope: RecommendationScope
    observations: tuple[ObservationRef, ...]
    metric_comparisons: tuple[MetricComparisonRef, ...]
    facts: tuple[FactRef, ...]
    rules: tuple[RuleRef, ...]
    questions: tuple[QuestionRef, ...]
    surfaces: tuple[SurfaceRef, ...]
    contents: tuple[ContentRef, ...]
    summaries: tuple[EvidenceSummary, ...]
    scope_locators: tuple[ScopeLocator, ...]
    attributions: tuple[AttributionRef, ...] = ()

    def __post_init__(self) -> None:
        typed_fields = (
            ("observations", ObservationRef),
            ("metric_comparisons", MetricComparisonRef),
            ("facts", FactRef),
            ("rules", RuleRef),
            ("questions", QuestionRef),
            ("surfaces", SurfaceRef),
            ("contents", ContentRef),
            ("attributions", AttributionRef),
        )
        for field_name, expected in typed_fields:
            values = tuple(sorted(getattr(self, field_name), key=lambda item: item.identity))
            if any(not isinstance(item, expected) for item in values):
                raise RecommendationRuleViolation(f"{field_name} contains the wrong ref type")
            identities = tuple(item.identity for item in values)
            if len(set(identities)) != len(identities):
                raise RecommendationRuleViolation(f"{field_name} contains duplicate refs")
            if any(item.project_id != self.scope.project_id for item in values):
                raise RecommendationRuleViolation("generation evidence crosses Project scope")
            object.__setattr__(self, field_name, values)
        summaries = tuple(sorted(self.summaries, key=lambda item: item.identity))
        expected_summaries = {
            item.identity
            for item in (
                *self.observations,
                *self.metric_comparisons,
                *self.facts,
                *self.rules,
            )
        }
        if {item.identity for item in summaries} != expected_summaries:
            raise RecommendationRuleViolation("summaries must exactly cover frozen core evidence")
        if len({item.identity for item in summaries}) != len(summaries):
            raise RecommendationRuleViolation("generation summaries contain duplicates")
        object.__setattr__(self, "summaries", summaries)
        locators = tuple(sorted(self.scope_locators, key=lambda item: item.field_name))
        if len({item.field_name for item in locators}) != len(locators):
            raise RecommendationRuleViolation("generation scope locators contain duplicates")
        expected_scope = {
            field_name: str(value) if isinstance(value, UUID) else value
            for field_name in (
                "campaign_id",
                "question_or_cluster_ref",
                "surface_ref",
                "content_asset_ref",
                "url_ref",
            )
            if (value := getattr(self.scope, field_name)) is not None
        }
        if {item.field_name: item.resource_id for item in locators} != expected_scope:
            raise RecommendationRuleViolation("scope locators must cover every frozen scope ref")
        object.__setattr__(self, "scope_locators", locators)

    @property
    def all_refs(self) -> tuple[EvidenceRef, ...]:
        return (
            *self.observations,
            *self.metric_comparisons,
            *self.facts,
            *self.rules,
            *self.questions,
            *self.surfaces,
            *self.contents,
            *self.attributions,
        )

    @property
    def input_hash(self) -> str:
        return canonical_hash(self.canonical_value())

    def canonical_value(self) -> Mapping[str, object]:
        return {
            "scope": self.scope.canonical_value(),
            "refs": [item.canonical_value() for item in self.all_refs],
            "summaries": [
                {
                    "kind": item.ref_kind,
                    "resource_id": item.resource_id,
                    "summary": item.summary,
                    "summary_hash": item.summary_hash,
                }
                for item in self.summaries
            ],
            "scope_locators": [
                {
                    "field": item.field_name,
                    "resource_id": item.resource_id,
                    "locator": dict(item.locator),
                }
                for item in self.scope_locators
            ],
        }

    def insufficiency_reasons(self, *, minimum_real_observations: int) -> tuple[str, ...]:
        real = {
            item.resource_id
            for item in self.observations
            if item.is_real and item.current_and_valid
        }
        reasons: list[str] = []
        if len(real) < minimum_real_observations:
            reasons.append("insufficient_real_observation_count")
        if not any(
            item.current_and_valid and real.intersection(item.observation_resource_ids)
            for item in self.metric_comparisons
        ):
            reasons.append("missing_sufficient_metric_comparison")
        if not self.questions or not self.surfaces:
            reasons.append("missing_question_or_surface_lineage")
        if not self.facts or not all(item.current_and_valid for item in self.facts):
            reasons.append("missing_current_approved_fact")
        if not self.rules or not all(item.current_and_valid for item in self.rules):
            reasons.append("missing_active_rule")
        reasons.extend(
            f"attribution_unavailable:{item.reason}"
            for item in self.attributions
            if not item.current_and_valid
        )
        return tuple(reasons)


__all__ = ["EvidenceSummary", "FrozenGenerationEvidence", "ScopeLocator"]
