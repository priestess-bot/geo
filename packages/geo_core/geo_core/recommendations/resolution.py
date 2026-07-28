"""Server-side evidence selection and graph resolution for Recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar
from uuid import UUID

from geo_core.recommendations.decision import RecommendationDecision
from geo_core.recommendations.errors import (
    RecommendationRuleViolation,
    RecommendationSourceStale,
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
    RecommendationEvidenceGraph,
    RecommendationScope,
    RuleRef,
    SurfaceRef,
)
from geo_core.recommendations.evidence_graph import EVIDENCE_GRAPH_CONTRACT_V2


MAX_RECOMMENDATION_EVIDENCE_SELECTORS = 100


class RecommendationEvidenceKind(StrEnum):
    OBSERVATION = "observation"
    METRIC_COMPARISON = "metric_comparison"
    FACT = "fact"
    RULE = "rule"
    PROMPT_RELEASE = "prompt_release"
    MODEL_CALL = "model_call"
    CONTENT = "content"
    QUESTION = "question"
    SURFACE = "surface"
    ATTRIBUTION = "attribution"


@dataclass(frozen=True, order=True)
class RecommendationEvidenceSelector:
    """Stable source identity supplied by a client; state and hashes are never supplied."""

    kind: RecommendationEvidenceKind
    resource_id: str

    def __post_init__(self) -> None:
        try:
            kind = RecommendationEvidenceKind(self.kind)
        except ValueError as error:
            raise RecommendationRuleViolation("Recommendation evidence kind is unsupported") from error
        resource_id = self.resource_id.strip()
        if not resource_id or len(resource_id) > 500:
            raise RecommendationRuleViolation(
                "Recommendation evidence resource identity is required and bounded"
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "resource_id", resource_id)

    @property
    def identity(self) -> tuple[str, str]:
        return (self.kind.value, self.resource_id)

    def canonical_value(self) -> dict[str, str]:
        return {"kind": self.kind.value, "resource_id": self.resource_id}


class RecommendationEvidenceResolverPort(Protocol):
    """Resolve current, project-scoped source truth inside the Recommendation UoW."""

    def resolve_current(
        self,
        *,
        project_id: UUID,
        selectors: tuple[RecommendationEvidenceSelector, ...],
    ) -> tuple[EvidenceRef, ...]: ...


def freeze_evidence_selectors(
    values: tuple[RecommendationEvidenceSelector, ...],
) -> tuple[RecommendationEvidenceSelector, ...]:
    selectors = tuple(sorted(values, key=lambda item: item.identity))
    identities = tuple(item.identity for item in selectors)
    if not selectors:
        raise RecommendationRuleViolation("Recommendation evidence selectors are required")
    if len(selectors) > MAX_RECOMMENDATION_EVIDENCE_SELECTORS:
        raise RecommendationRuleViolation(
            "Recommendation accepts at most 100 evidence selectors"
        )
    if len(set(identities)) != len(identities):
        raise RecommendationRuleViolation("Recommendation evidence selectors must be unique")
    return selectors


def selectors_from_graph(
    graph: RecommendationEvidenceGraph,
) -> tuple[RecommendationEvidenceSelector, ...]:
    return freeze_evidence_selectors(
        tuple(
            RecommendationEvidenceSelector(
                RecommendationEvidenceKind(reference.ref_kind),
                reference.resource_id,
            )
            for reference in graph.all_refs
        )
    )


def resolve_evidence_graph(
    resolver: RecommendationEvidenceResolverPort,
    *,
    project_id: UUID,
    scope: RecommendationScope,
    decision: RecommendationDecision,
    selectors: tuple[RecommendationEvidenceSelector, ...],
    contract_version: str = EVIDENCE_GRAPH_CONTRACT_V2,
) -> RecommendationEvidenceGraph:
    if scope.project_id != project_id:
        raise RecommendationRuleViolation("Recommendation scope belongs to another Project")
    frozen = freeze_evidence_selectors(selectors)
    resolved = tuple(resolver.resolve_current(project_id=project_id, selectors=frozen))
    by_identity = {(item.ref_kind, item.resource_id): item for item in resolved}
    expected = {item.identity for item in frozen}
    if len(by_identity) != len(resolved) or set(by_identity) != expected:
        raise RecommendationSourceStale(
            "Recommendation evidence resolution did not exactly cover its selectors"
        )
    if any(item.project_id != project_id for item in resolved):
        raise RecommendationSourceStale(
            "Recommendation evidence resolver returned another Project's source"
        )
    return RecommendationEvidenceGraph(
        scope=scope,
        decision=decision,
        observations=_typed(resolved, ObservationRef),
        metric_comparisons=_typed(resolved, MetricComparisonRef),
        facts=_typed(resolved, FactRef),
        rules=_typed(resolved, RuleRef),
        prompt_releases=_typed(resolved, PromptReleaseRef),
        model_calls=_typed(resolved, ModelCallRef),
        contents=_typed(resolved, ContentRef),
        questions=_typed(resolved, QuestionRef),
        surfaces=_typed(resolved, SurfaceRef),
        attributions=_typed(resolved, AttributionRef),
        contract_version=contract_version,
    )


def resolve_current_graph(
    resolver: RecommendationEvidenceResolverPort,
    graph: RecommendationEvidenceGraph,
) -> RecommendationEvidenceGraph:
    return resolve_evidence_graph(
        resolver,
        project_id=graph.scope.project_id,
        scope=graph.scope,
        decision=graph.decision,
        selectors=selectors_from_graph(graph),
        contract_version=graph.contract_version,
    )


def require_unchanged_evidence(
    frozen: RecommendationEvidenceGraph,
    current: RecommendationEvidenceGraph,
) -> None:
    if current.graph_hash != frozen.graph_hash:
        raise RecommendationSourceStale(
            "Recommendation evidence changed in its authoritative source repository"
        )


_EvidenceRefT = TypeVar("_EvidenceRefT", bound=EvidenceRef)


def _typed(
    values: tuple[EvidenceRef, ...], expected: type[_EvidenceRefT]
) -> tuple[_EvidenceRefT, ...]:
    return tuple(item for item in values if isinstance(item, expected))


__all__ = [
    "MAX_RECOMMENDATION_EVIDENCE_SELECTORS",
    "RecommendationEvidenceKind",
    "RecommendationEvidenceResolverPort",
    "RecommendationEvidenceSelector",
    "freeze_evidence_selectors",
    "require_unchanged_evidence",
    "resolve_current_graph",
    "resolve_evidence_graph",
    "selectors_from_graph",
]
