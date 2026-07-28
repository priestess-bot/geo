"""Deterministic Recommendation classification from frozen producer evidence."""

from __future__ import annotations

from dataclasses import dataclass

from geo_core.recommendations.evidence import (
    MetricComparisonConclusion,
    RecommendationRuleSeverity,
)
from geo_core.recommendations.generation_evidence import FrozenGenerationEvidence
from geo_core.recommendations.generation_hashing import canonical_hash
from geo_core.recommendations.models import RecommendationType


@dataclass(frozen=True)
class RecommendationTypeAdmission:
    resolved_type: RecommendationType
    reason_codes: tuple[str, ...]
    comparison_conclusions: tuple[MetricComparisonConclusion, ...]
    triggered_rule_refs: tuple[str, ...]

    @property
    def admission_hash(self) -> str:
        return canonical_hash(self.canonical_value())

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract_version": "recommendation-type-admission-v1",
            "resolved_type": self.resolved_type.value,
            "reason_codes": list(self.reason_codes),
            "comparison_conclusions": [
                item.value for item in self.comparison_conclusions
            ],
            "triggered_rule_refs": list(self.triggered_rule_refs),
        }


def resolve_recommendation_type(
    evidence: FrozenGenerationEvidence,
    *,
    minimum_real_observations: int,
) -> RecommendationTypeAdmission:
    """Resolve one type before a model runs; prose never decides classification."""

    insufficiency = evidence.insufficiency_reasons(
        minimum_real_observations=minimum_real_observations
    )
    comparisons = tuple(
        sorted(
            (
                item.conclusion
                for item in evidence.metric_comparisons
                if item.valid and item.conclusion is not None
            ),
            key=lambda item: item.value,
        )
    )
    triggered = tuple(
        sorted(
            (item for item in evidence.rules if item.triggered),
            key=lambda item: item.identity,
        )
    )
    triggered_refs = tuple(f"rule:{item.resource_id}" for item in triggered)
    if insufficiency:
        return RecommendationTypeAdmission(
            RecommendationType.INSUFFICIENT_EVIDENCE,
            insufficiency,
            comparisons,
            triggered_refs,
        )

    if any(item.severity is RecommendationRuleSeverity.CRITICAL for item in triggered):
        resolved = RecommendationType.HARD_BLOCKER
        reasons = ("triggered_critical_rule",)
    elif (
        MetricComparisonConclusion.LOSS in comparisons
        or any(item.severity is RecommendationRuleSeverity.WARNING for item in triggered)
    ):
        resolved = RecommendationType.GAP
        reasons = (
            "comparison_loss"
            if MetricComparisonConclusion.LOSS in comparisons
            else "triggered_warning_rule",
        )
    elif MetricComparisonConclusion.INCONCLUSIVE in comparisons:
        resolved = RecommendationType.EXPERIMENT
        reasons = ("comparison_inconclusive",)
    elif any(item.severity is RecommendationRuleSeverity.INFO for item in triggered):
        resolved = RecommendationType.OPTIONAL
        reasons = ("triggered_info_rule",)
    else:
        resolved = RecommendationType.NO_CHANGE
        reasons = ("no_negative_or_uncertain_signal",)
    return RecommendationTypeAdmission(resolved, reasons, comparisons, triggered_refs)


__all__ = ["RecommendationTypeAdmission", "resolve_recommendation_type"]
