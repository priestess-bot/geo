from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
from collections.abc import Callable
from typing import Any, Mapping, TypedDict, cast
from uuid import UUID, uuid4

import pytest

from geo_core.recommendations import (
    AttributionRef,
    ContentRef,
    DownstreamDraftKind,
    FactRef,
    MetricComparisonRef,
    ModelCallRef,
    ObservationEvidenceClass,
    ObservationRef,
    PromptReleaseRef,
    QuestionRef,
    Recommendation,
    RecommendationDecision,
    RecommendationEvidenceGraph,
    RecommendationEvidenceTampered,
    RecommendationInputKind,
    RecommendationRuleViolation,
    RecommendationScope,
    RecommendationType,
    RuleRef,
    SurfaceRef,
)
from geo_core.recommendations.evidence_graph import EVIDENCE_GRAPH_CONTRACT_V1
from geo_core.recommendations.resolution import (
    RecommendationEvidenceKind,
    RecommendationEvidenceSelector,
    freeze_evidence_selectors,
    resolve_current_graph,
)


NOW = datetime(2026, 7, 23, 2, 0, tzinfo=UTC)
PROJECT_ID = UUID("30000000-0000-0000-0000-000000000001")
OTHER_PROJECT_ID = UUID("30000000-0000-0000-0000-000000000002")


def test_graph_contains_all_typed_refs_and_no_attribution_placeholder() -> None:
    graph = _graph()

    assert {type(reference) for reference in graph.all_refs} == {
        ObservationRef,
        MetricComparisonRef,
        FactRef,
        RuleRef,
        PromptReleaseRef,
        ModelCallRef,
        ContentRef,
        QuestionRef,
        SurfaceRef,
    }
    for reference in graph.all_refs:
        assert reference.project_id == PROJECT_ID
        assert reference.version
        assert len(reference.sha256) == 64
        assert reference.locator
    assert "attribution_snapshot" not in {kind.value for kind in RecommendationInputKind}
    assert graph.conclusive_failures() == ()


def test_explicit_attribution_unavailability_is_frozen_and_requires_insufficient_evidence() -> None:
    graph = replace(
        _graph(),
        attributions=(
            AttributionRef(
                project_id=PROJECT_ID,
                resource_id="attribution:unavailable",
                version="connector-boundary-v1",
                sha256=_digest("connector-boundary-v1"),
                locator={"boundary": "connector-attribution"},
                valid=False,
                available=False,
                reason="connector_attribution_excluded_from_this_phase",
            ),
        ),
    )

    assert graph.conclusive_failures() == (
        "attribution_unavailable:connector_attribution_excluded_from_this_phase",
    )
    assert RecommendationInputKind.ATTRIBUTION_AVAILABILITY in {
        item.kind for item in graph.input_versions
    }
    assert graph.graph_hash != _graph().graph_hash


def test_locator_is_defensively_copied_and_immutable() -> None:
    locator = {"table": "facts", "id": "fact:1"}
    reference = FactRef(
        project_id=PROJECT_ID,
        resource_id="fact:1",
        version="v1",
        sha256=_digest("fact:1:v1"),
        locator=locator,
        approved=True,
        retired=False,
    )
    locator["id"] = "tampered"

    assert reference.locator["id"] == "fact:1"
    with pytest.raises(TypeError):
        reference.locator["id"] = "tampered"  # type: ignore[index]


def test_graph_hash_is_canonical_and_detects_decision_tampering() -> None:
    graph = _graph()
    equivalent_confidence = replace(graph.decision, confidence=Decimal("0.8200"))
    equivalent = replace(
        graph,
        decision=equivalent_confidence,
        facts=tuple(reversed(graph.facts)),
    )

    assert equivalent.graph_hash == graph.graph_hash
    graph.verify_hash(graph.graph_hash)

    changed = replace(
        graph,
        decision=replace(graph.decision, business_value="A materially different value claim"),
    )
    assert changed.graph_hash != graph.graph_hash
    with pytest.raises(RecommendationEvidenceTampered, match="canonical content"):
        changed.verify_hash(graph.graph_hash)


def test_current_resolution_preserves_legacy_graph_hash_contract() -> None:
    legacy = replace(_graph(), contract_version=EVIDENCE_GRAPH_CONTRACT_V1)

    class Resolver:
        def resolve_current(self, **_: object) -> tuple[object, ...]:
            return legacy.all_refs

    current = resolve_current_graph(cast(Any, Resolver()), legacy)

    assert current.contract_version == EVIDENCE_GRAPH_CONTRACT_V1
    assert current.graph_hash == legacy.graph_hash


@pytest.mark.parametrize(
    "field_name",
    (
        "observations",
        "metric_comparisons",
        "facts",
        "rules",
        "prompt_releases",
        "model_calls",
    ),
)
def test_action_recommendations_fail_closed_when_required_lineage_is_missing(
    field_name: str,
) -> None:
    graph = replace(_graph(), **cast(Any, {field_name: ()}))

    with pytest.raises(RecommendationRuleViolation, match="use insufficient_evidence"):
        _recommendation(graph, RecommendationType.HARD_BLOCKER)


def test_no_change_requires_the_same_complete_evidence_as_an_action() -> None:
    graph = replace(_graph(), facts=())

    with pytest.raises(RecommendationRuleViolation, match="missing_current_approved_fact"):
        _recommendation(graph, RecommendationType.NO_CHANGE)


def test_synthetic_only_cannot_masquerade_as_real_observation() -> None:
    graph = _graph()
    synthetic = replace(
        graph.observations[0],
        evidence_class=ObservationEvidenceClass.SYNTHETIC,
    )
    synthetic_only = replace(graph, observations=(synthetic,))

    assert "missing_real_observation" in synthetic_only.conclusive_failures()
    with pytest.raises(RecommendationRuleViolation, match="missing_real_observation"):
        _recommendation(synthetic_only, RecommendationType.GAP)

    sampling = _recommendation(synthetic_only, RecommendationType.INSUFFICIENT_EVIDENCE)
    assert sampling.proposed_draft_kind == DownstreamDraftKind.SAMPLING_PLAN


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("facts", lambda graph: replace(graph.facts[0], retired=True)),
        ("rules", lambda graph: replace(graph.rules[0], active=False)),
        ("prompt_releases", lambda graph: replace(graph.prompt_releases[0], frozen=False)),
        ("model_calls", lambda graph: replace(graph.model_calls[0], succeeded=False)),
    ),
)
def test_invalid_refs_cannot_support_a_conclusive_recommendation(
    field_name: str,
    replacement: Callable[[RecommendationEvidenceGraph], object],
) -> None:
    graph = _graph()
    changed_ref = replacement(graph)
    invalid = replace(graph, **cast(Any, {field_name: (changed_ref,)}))

    with pytest.raises(RecommendationRuleViolation, match=f"invalid_{field_name.rstrip('s')}"):
        _recommendation(invalid, RecommendationType.OPTIONAL)


def test_metric_must_reach_a_real_observation_in_the_same_graph() -> None:
    graph = _graph()
    detached = replace(
        graph.metric_comparisons[0],
        observation_resource_ids=("observation:not-in-graph",),
    )
    broken = replace(graph, metric_comparisons=(detached,))

    assert "missing_valid_metric_comparison" in broken.conclusive_failures()
    with pytest.raises(RecommendationRuleViolation, match="missing_valid_metric_comparison"):
        _recommendation(broken, RecommendationType.EXPERIMENT)


@pytest.mark.parametrize(
    "field_name",
    (
        "observations",
        "metric_comparisons",
        "facts",
        "rules",
        "prompt_releases",
        "model_calls",
        "contents",
        "questions",
        "surfaces",
    ),
)
def test_every_typed_ref_is_project_scoped(field_name: str) -> None:
    graph = _graph()
    crossed = replace(getattr(graph, field_name)[0], project_id=OTHER_PROJECT_ID)

    with pytest.raises(RecommendationRuleViolation, match="crosses.*project boundary"):
        replace(graph, **cast(Any, {field_name: (crossed,)}))


def test_incomplete_evidence_is_only_storable_as_a_sampling_recommendation() -> None:
    empty = RecommendationEvidenceGraph(
        scope=_scope(),
        decision=_decision(),
    )

    recommendation = _recommendation(empty, RecommendationType.INSUFFICIENT_EVIDENCE)
    assert recommendation.evidence.input_versions == ()
    assert recommendation.proposed_draft_kind == DownstreamDraftKind.SAMPLING_PLAN
    with pytest.raises(RecommendationRuleViolation, match="use insufficient_evidence"):
        _recommendation(empty, RecommendationType.HARD_BLOCKER)


def test_evidence_selector_boundary_is_bounded_before_resolution() -> None:
    selectors = tuple(
        RecommendationEvidenceSelector(
            RecommendationEvidenceKind.FACT,
            f"fact:{index}",
        )
        for index in range(101)
    )

    with pytest.raises(RecommendationRuleViolation, match="at most 100"):
        freeze_evidence_selectors(selectors)


def _recommendation(
    graph: RecommendationEvidenceGraph,
    recommendation_type: RecommendationType,
) -> Recommendation:
    draft_kind = {
        RecommendationType.NO_CHANGE: None,
        RecommendationType.EXPERIMENT: DownstreamDraftKind.EXPERIMENT_PLAN,
        RecommendationType.INSUFFICIENT_EVIDENCE: DownstreamDraftKind.SAMPLING_PLAN,
    }.get(recommendation_type, DownstreamDraftKind.CONTENT_BRIEF)
    return Recommendation(
        id=uuid4(),
        project_id=PROJECT_ID,
        recommendation_type=recommendation_type,
        evidence=graph,
        proposed_draft_kind=draft_kind,
        valid_until=NOW + timedelta(days=30),
        created_by="recommendation-engine",
        created_at=NOW,
        updated_at=NOW,
    )


def _graph() -> RecommendationEvidenceGraph:
    question = QuestionRef(
        **_base("question:1"),
        active=True,
    )
    surface = SurfaceRef(
        **_base("surface:google-aio:r1"),
        active=True,
    )
    observation = ObservationRef(
        **_base("observation:1"),
        capture_method="automated_ui",
        evidence_class=ObservationEvidenceClass.REAL_OBSERVATION,
        question_resource_id=question.resource_id,
        surface_resource_id=surface.resource_id,
        eligible=True,
    )
    prompt = PromptReleaseRef(
        **_base("prompt:recommendation:r1"),
        approved=True,
        frozen=True,
    )
    return RecommendationEvidenceGraph(
        scope=_scope(),
        decision=_decision(),
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
        facts=(
            FactRef(
                **_base("fact:1"),
                approved=True,
                retired=False,
            ),
        ),
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


def _scope() -> RecommendationScope:
    return RecommendationScope(
        project_id=PROJECT_ID,
        applicable_version="recommendation-contract-v1",
        campaign_id=UUID("30000000-0000-0000-0000-000000000003"),
        question_or_cluster_ref="question:1",
        surface_ref="surface:google-aio:r1",
        content_asset_ref="content:1",
        url_ref="verified-url:1",
    )


def _decision() -> RecommendationDecision:
    return RecommendationDecision(
        impact_chain=("Observed omission", "Lower qualified consideration"),
        risk="medium",
        effort="small",
        business_value="Protect discovery",
        confidence=Decimal("0.82"),
        counterevidence=("One interval remains wide",),
        validation_plan=("Run a paired frozen experiment",),
        stale_conditions=("Fact retires", "Observation or method changes"),
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
        "locator": {"kind": resource_id.split(":", 1)[0], "id": resource_id},
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
