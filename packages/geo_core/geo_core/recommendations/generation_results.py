"""Pure projection from frozen generation inputs and model results to a draft."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from geo_core.model_gateway.contracts import ModelGatewayResult
from geo_core.recommendations.evidence import (
    ModelCallRef,
    PromptReleaseRef,
    RecommendationDecision,
    RecommendationEvidenceGraph,
    RecommendationScope,
)
from geo_core.recommendations.generation_contracts import (
    FrozenPromptBinding,
    RecommendationGenerationResult,
    RecommendationGenerationSpec,
)
from geo_core.recommendations.generation_ports import (
    ParsedRecommendationOutput,
    SelectedRecommendationRef,
)
from geo_core.recommendations.models import (
    DownstreamDraftKind,
    Recommendation,
    RecommendationType,
)


def build_evidence_graph(
    spec: RecommendationGenerationSpec,
    *,
    scope: RecommendationScope,
    decision: RecommendationDecision,
    selected: tuple[SelectedRecommendationRef, ...] | None,
    calls: tuple[ModelGatewayResult, ...],
    prompt_bindings: tuple[FrozenPromptBinding, ...],
) -> RecommendationEvidenceGraph:
    selected_ids = (
        None if selected is None else {(item.kind, item.resource_id) for item in selected}
    )
    evidence = spec.evidence
    prompts = tuple(_prompt_ref(binding) for binding in prompt_bindings)
    model_calls = tuple(
        _model_call_ref(spec.project_id, call, prompt)
        for call, prompt in zip(calls, prompts[: len(calls)], strict=True)
    )
    return RecommendationEvidenceGraph(
        scope=scope,
        decision=decision,
        observations=_selected(evidence.observations, selected_ids),
        metric_comparisons=_selected(evidence.metric_comparisons, selected_ids),
        facts=_selected(evidence.facts, selected_ids),
        rules=_selected(evidence.rules, selected_ids),
        prompt_releases=prompts,
        model_calls=model_calls,
        contents=evidence.contents,
        questions=evidence.questions,
        surfaces=evidence.surfaces,
        attributions=evidence.attributions,
    )


def build_draft_recommendation(
    spec: RecommendationGenerationSpec,
    *,
    recommendation_id: UUID,
    recommendation_type: RecommendationType,
    evidence: RecommendationEvidenceGraph,
    created_at: datetime,
) -> Recommendation:
    kind = {
        RecommendationType.HARD_BLOCKER: DownstreamDraftKind.CONTENT_BRIEF,
        RecommendationType.GAP: DownstreamDraftKind.QUESTION_SET,
        RecommendationType.EXPERIMENT: DownstreamDraftKind.EXPERIMENT_PLAN,
        RecommendationType.OPTIONAL: DownstreamDraftKind.CONTENT_BRIEF,
        RecommendationType.NO_CHANGE: None,
        RecommendationType.INSUFFICIENT_EVIDENCE: DownstreamDraftKind.SAMPLING_PLAN,
    }[recommendation_type]
    return Recommendation(
        id=recommendation_id,
        project_id=spec.project_id,
        recommendation_type=recommendation_type,
        evidence=evidence,
        proposed_draft_kind=kind,
        valid_until=spec.valid_until,
        created_by=spec.created_by,
        created_at=created_at,
        updated_at=created_at,
    )


def build_insufficient_result(
    spec: RecommendationGenerationSpec,
    reasons: tuple[str, ...],
    *,
    recommendation_id: UUID,
    created_at: datetime,
) -> RecommendationGenerationResult:
    decision = RecommendationDecision(
        impact_chain=("Evidence gate did not pass",),
        risk="Evidence is insufficient for a directional recommendation",
        effort="Collect the frozen Sampling Plan evidence",
        business_value="Avoid action based on unsupported evidence",
        confidence=Decimal("0"),
        counterevidence=reasons,
        validation_plan=("Complete the Sampling Plan and regenerate",),
        stale_conditions=("Any frozen evidence or Prompt identity changes",),
    )
    graph = build_evidence_graph(
        spec,
        scope=spec.evidence.scope,
        decision=decision,
        selected=None,
        calls=(),
        prompt_bindings=(spec.prompt_binding,),
    )
    recommendation = build_draft_recommendation(
        spec,
        recommendation_id=recommendation_id,
        recommendation_type=RecommendationType.INSUFFICIENT_EVIDENCE,
        evidence=graph,
        created_at=created_at,
    )
    return RecommendationGenerationResult(recommendation, (), reasons)


def build_model_result(
    spec: RecommendationGenerationSpec,
    parsed: ParsedRecommendationOutput,
    calls: tuple[ModelGatewayResult, ...],
    prompt_bindings: tuple[FrozenPromptBinding, ...],
    *,
    recommendation_id: UUID,
    created_at: datetime,
) -> RecommendationGenerationResult:
    graph = build_evidence_graph(
        spec,
        scope=parsed.scope,
        decision=parsed.decision,
        selected=parsed.selected_refs,
        calls=calls,
        prompt_bindings=prompt_bindings,
    )
    recommendation = build_draft_recommendation(
        spec,
        recommendation_id=recommendation_id,
        recommendation_type=parsed.recommendation_type,
        evidence=graph,
        created_at=created_at,
    )
    return RecommendationGenerationResult(
        recommendation,
        tuple(call.call_log_id for call in calls),
    )


def _prompt_ref(binding: FrozenPromptBinding) -> PromptReleaseRef:
    return PromptReleaseRef(
        project_id=binding.project_id,
        resource_id=str(binding.release_id),
        version=str(binding.release_version),
        sha256=binding.release_hash,
        locator={"binding_id": str(binding.binding_id), "release_id": str(binding.release_id)},
        valid=True,
        approved=True,
        frozen=True,
    )


def _model_call_ref(
    project_id: UUID,
    result: ModelGatewayResult,
    prompt: PromptReleaseRef,
) -> ModelCallRef:
    identity = "/".join(
        value or "missing"
        for value in (
            result.provider,
            result.adapter_release_id,
            result.model_release_id,
            result.configured_model,
        )
    )
    return ModelCallRef(
        project_id=project_id,
        resource_id=str(result.call_log_id),
        version=result.model_release_id or result.configured_model,
        sha256=result.response_hash,
        locator={"call_log_id": str(result.call_log_id)},
        valid=True,
        prompt_release_resource_id=prompt.resource_id,
        model_identity=identity,
        succeeded=True,
    )


def _selected(refs: tuple[object, ...], allowed: set[tuple[str, str]] | None) -> tuple:
    if allowed is None:
        return refs
    return tuple(ref for ref in refs if ref.identity in allowed)  # type: ignore[attr-defined]


__all__ = [
    "build_draft_recommendation",
    "build_evidence_graph",
    "build_insufficient_result",
    "build_model_result",
]
