"""Graph-level Recommendation evidence validation and fingerprints."""

from __future__ import annotations

from dataclasses import dataclass

from geo_core.recommendations.decision import RecommendationDecision
from geo_core.recommendations.errors import (
    RecommendationEvidenceTampered,
    RecommendationRuleViolation,
)
from geo_core.recommendations.evidence import (
    AttributionRef,
    ContentRef,
    EvidenceRef,
    FactRef,
    MetricComparisonRef,
    ModelCallRef,
    ObservationRef,
    PromptReleaseRef,
    QuestionRef,
    RecommendationInputVersion,
    RecommendationScope,
    RuleRef,
    SurfaceRef,
    _canonical_hash,
    _require_hash,
)


@dataclass(frozen=True)
class RecommendationEvidenceGraph:
    scope: RecommendationScope
    decision: RecommendationDecision
    observations: tuple[ObservationRef, ...] = ()
    metric_comparisons: tuple[MetricComparisonRef, ...] = ()
    facts: tuple[FactRef, ...] = ()
    rules: tuple[RuleRef, ...] = ()
    prompt_releases: tuple[PromptReleaseRef, ...] = ()
    model_calls: tuple[ModelCallRef, ...] = ()
    contents: tuple[ContentRef, ...] = ()
    questions: tuple[QuestionRef, ...] = ()
    surfaces: tuple[SurfaceRef, ...] = ()
    attributions: tuple[AttributionRef, ...] = ()

    def __post_init__(self) -> None:
        fields = (
            ("observations", ObservationRef),
            ("metric_comparisons", MetricComparisonRef),
            ("facts", FactRef),
            ("rules", RuleRef),
            ("prompt_releases", PromptReleaseRef),
            ("model_calls", ModelCallRef),
            ("contents", ContentRef),
            ("questions", QuestionRef),
            ("surfaces", SurfaceRef),
            ("attributions", AttributionRef),
        )
        for field_name, expected_type in fields:
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, expected_type) for value in values):
                raise RecommendationRuleViolation(f"{field_name} contains the wrong reference type")
            ordered = tuple(sorted(values, key=lambda item: item.identity))
            if len({item.identity for item in ordered}) != len(ordered):
                raise RecommendationRuleViolation(f"{field_name} contains duplicate references")
            object.__setattr__(self, field_name, ordered)
        for reference in self.all_refs:
            if reference.project_id != self.scope.project_id:
                raise RecommendationRuleViolation(
                    f"{reference.ref_kind} evidence crosses the Recommendation project boundary"
                )

    @property
    def all_refs(self) -> tuple[EvidenceRef, ...]:
        return (
            *self.observations,
            *self.metric_comparisons,
            *self.facts,
            *self.rules,
            *self.prompt_releases,
            *self.model_calls,
            *self.contents,
            *self.questions,
            *self.surfaces,
            *self.attributions,
        )

    @property
    def input_versions(self) -> tuple[RecommendationInputVersion, ...]:
        return freeze_input_versions(
            tuple(version for reference in self.all_refs for version in reference.input_versions())
        )

    @property
    def input_fingerprint(self) -> str:
        return input_fingerprint(self.input_versions)

    @property
    def graph_hash(self) -> str:
        return _canonical_hash(self.canonical_value())

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract_version": "geo-recommendation-evidence-v1",
            "scope": self.scope.canonical_value(),
            "decision": self.decision.canonical_value(),
            "references": [reference.canonical_value() for reference in self.all_refs],
        }

    def verify_hash(self, expected_hash: str) -> None:
        _require_hash(expected_hash, "evidence graph hash")
        if expected_hash != self.graph_hash:
            raise RecommendationEvidenceTampered(
                "evidence graph hash does not match its canonical content"
            )

    def conclusive_failures(self) -> tuple[str, ...]:
        failures = [
            f"invalid_{reference.ref_kind}:{reference.resource_id}"
            for reference in self.all_refs
            if not reference.current_and_valid
            and not isinstance(reference, AttributionRef)
        ]
        questions = {item.resource_id for item in self.questions if item.current_and_valid}
        surfaces = {item.resource_id for item in self.surfaces if item.current_and_valid}
        real_observations = {
            item.resource_id
            for item in self.observations
            if item.is_real
            and item.question_resource_id in questions
            and item.surface_resource_id in surfaces
        }
        if not real_observations:
            failures.append("missing_real_observation")
        if not any(
            item.current_and_valid
            and real_observations.intersection(item.observation_resource_ids)
            for item in self.metric_comparisons
        ):
            failures.append("missing_valid_metric_comparison")
        if not any(item.current_and_valid for item in self.facts):
            failures.append("missing_current_approved_fact")
        if not any(item.current_and_valid for item in self.rules):
            failures.append("missing_active_rule")
        valid_prompts = {
            item.resource_id for item in self.prompt_releases if item.current_and_valid
        }
        if not valid_prompts:
            failures.append("missing_approved_frozen_prompt_release")
        if not any(
            item.current_and_valid and item.prompt_release_resource_id in valid_prompts
            for item in self.model_calls
        ):
            failures.append("missing_successful_model_call")
        failures.extend(
            f"attribution_unavailable:{item.reason}"
            for item in self.attributions
            if not item.current_and_valid
        )
        return tuple(dict.fromkeys(failures))


def freeze_input_versions(
    values: tuple[RecommendationInputVersion, ...],
) -> tuple[RecommendationInputVersion, ...]:
    frozen = tuple(sorted(values, key=lambda item: item.identity))
    identities = tuple(item.identity for item in frozen)
    if len(set(identities)) != len(identities):
        raise RecommendationRuleViolation("recommendation inputs must have unique identities")
    return frozen


def input_fingerprint(values: tuple[RecommendationInputVersion, ...]) -> str:
    payload = [
        {
            "kind": item.kind.value,
            "resource_id": item.resource_id,
            "version": item.version,
            "sha256": item.sha256,
        }
        for item in freeze_input_versions(values)
    ]
    return _canonical_hash(payload)


__all__ = [
    "RecommendationEvidenceGraph",
    "freeze_input_versions",
    "input_fingerprint",
]
