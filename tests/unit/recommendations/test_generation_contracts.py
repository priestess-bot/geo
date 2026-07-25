from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from geo_core.model_gateway.contracts import ModelCaptureMethod
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.recommendations import AttributionRef
from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.generation_contracts import (
    EvidenceSummary,
    RecommendationGenerationOutputError,
)
from geo_core.recommendations.generation_ports import (
    parse_recommendation_output,
    structured_generation_input,
)
from geo_core.recommendations.models import RecommendationType
from tests.unit.recommendations.generation_test_support import (
    frozen_evidence,
    generation_spec,
    model_output,
    prompt_binding,
    route,
)


def test_structured_request_contains_only_frozen_safe_evidence_fields() -> None:
    evidence = frozen_evidence()
    payload = structured_generation_input(evidence)

    assert set(payload) == {
        "subject_id",
        "allowed_subject_ids",
        "evidence",
        "output_locale",
        "untrusted_text",
        "prompt_injection_present",
        "scope",
        "context_refs",
        "allowed_recommendation_types",
    }
    assert payload["subject_id"] == f"recommendation-scope:{evidence.input_hash}"
    core_refs = payload["evidence"]
    context_refs = payload["context_refs"]
    assert isinstance(core_refs, list) and isinstance(context_refs, list)
    for item in core_refs:
        assert isinstance(item, dict)
        assert set(item) == {
            "ref",
            "subject_id",
            "evidence_scope",
            "summary",
        }
    for item in context_refs:
        assert isinstance(item, dict)
        assert set(item) == {"kind", "resource_id", "version", "hash"}
    serialized = str(payload)
    for forbidden in (
        "eligible",
        "approved",
        "retired",
        "automatic_action_authorised",
        "raw",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize("recommendation_type", tuple(item.value for item in RecommendationType))
def test_output_schema_accepts_all_six_recommendation_types(
    recommendation_type: str,
) -> None:
    parsed = parse_recommendation_output(
        model_output(recommendation_type),
        evidence=frozen_evidence(),
    )

    assert parsed.recommendation_type.value == recommendation_type
    assert parsed.selected_refs
    assert parsed.scope.url_ref == "url:https://example.test/au"


@pytest.mark.parametrize("hallucination", ("ref", "scope", "number", "extra"))
def test_output_rejects_hallucinated_refs_scope_numbers_and_fields(
    hallucination: str,
) -> None:
    output = deepcopy(model_output())
    if hallucination == "ref":
        output["evidence_refs"].append(
            {"kind": "observation", "resource_id": "observation:invented"}
        )
    elif hallucination == "scope":
        output["scope"]["surface_ref"] = "surface:invented"
    elif hallucination == "number":
        output["decision"]["business_value"] = "Increase visibility by 20 percent"
    else:
        output["invented_fact"] = "not frozen"

    with pytest.raises(RecommendationGenerationOutputError):
        parse_recommendation_output(output, evidence=frozen_evidence())


def test_summary_hash_and_exact_summary_coverage_are_frozen() -> None:
    evidence = frozen_evidence()
    first = evidence.summaries[0]
    with pytest.raises(RecommendationRuleViolation, match="hash"):
        EvidenceSummary(first.ref_kind, first.resource_id, first.summary, "f" * 64)
    with pytest.raises(RecommendationRuleViolation, match="exactly cover"):
        replace(evidence, summaries=evidence.summaries[1:])


def test_generation_freezes_unavailable_attribution_as_an_insufficient_reason() -> None:
    evidence = frozen_evidence()
    frozen = replace(
        evidence,
        attributions=(
            AttributionRef(
                project_id=evidence.scope.project_id,
                resource_id="attribution:unavailable",
                version="connector-boundary-v1",
                sha256="a" * 64,
                locator={"boundary": "connector-attribution"},
                valid=False,
                available=False,
                reason="connector_attribution_excluded_from_this_phase",
            ),
        ),
    )

    assert frozen.insufficiency_reasons(minimum_real_observations=3) == (
        "attribution_unavailable:connector_attribution_excluded_from_this_phase",
    )
    assert frozen.input_hash != evidence.input_hash


def test_valid_but_underpowered_comparison_remains_insufficient_not_stale() -> None:
    evidence = frozen_evidence()
    underpowered = replace(
        evidence,
        metric_comparisons=(
            replace(evidence.metric_comparisons[0], sufficient_evidence=False),
        ),
    )

    assert underpowered.insufficiency_reasons(minimum_real_observations=3) == (
        "missing_sufficient_metric_comparison",
    )


def test_spec_input_hash_is_stable_and_arbiter_must_use_another_model() -> None:
    first = generation_spec()
    second = replace(first)
    assert first.input_hash == second.input_hash
    assert first.maximum_model_calls == 1

    with pytest.raises(RecommendationRuleViolation, match="cannot use the generation model"):
        generation_spec(with_arbiter=True, same_arbiter_model=True)

    arbiter = generation_spec(with_arbiter=True)
    assert arbiter.maximum_model_calls == 2
    assert arbiter.capture_method is ModelCaptureMethod.PROVIDER_API
    assert arbiter.arbiter_capture_method is ModelCaptureMethod.PROXY_GROUNDED_API
    assert arbiter.search_mode == "disabled"
    assert arbiter.arbiter_search_mode == "bing_grounding"


@pytest.mark.parametrize(
    ("kind", "purpose"),
    (
        (ProgramKind.RECOMMENDATION, "foo.recommendations.recommendation"),
        (ProgramKind.RECOMMENDATION, "recommendations.recommendation.evil"),
        (ProgramKind.ARBITER, "foo.synthetic_lab.arbiter"),
        (ProgramKind.ARBITER, "synthetic_lab.arbiterish"),
    ),
)
def test_prompt_binding_rejects_noncanonical_purpose_aliases(
    kind: ProgramKind,
    purpose: str,
) -> None:
    binding = prompt_binding(kind, kind.value)

    with pytest.raises(RecommendationRuleViolation, match="kind and purpose"):
        replace(binding, purpose=purpose)


def test_spec_hash_freezes_search_mode_and_rejects_cross_route_capture_method() -> None:
    spec = generation_spec()

    search_changed = replace(spec, search_mode="web")
    assert search_changed.input_hash != spec.input_hash
    capture_tampered = replace(spec)
    object.__setattr__(
        capture_tampered,
        "capture_method",
        ModelCaptureMethod.PROXY_GROUNDED_API,
    )
    assert capture_tampered.input_hash != spec.input_hash

    microsoft_route = route("primary", provider="microsoft")
    with pytest.raises(RecommendationRuleViolation, match="frozen Model route"):
        replace(spec, route=microsoft_route)

    microsoft_spec = replace(
        spec,
        route=microsoft_route,
        capture_method=ModelCaptureMethod.PROXY_GROUNDED_API,
        search_mode="bing_grounding",
    )
    assert microsoft_spec.input_hash != spec.input_hash
    with pytest.raises(RecommendationRuleViolation, match="frozen Model route"):
        replace(microsoft_spec, capture_method=ModelCaptureMethod.PROVIDER_API)
