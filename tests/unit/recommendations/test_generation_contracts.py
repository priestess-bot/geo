from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from geo_core.model_gateway.contracts import ModelCaptureMethod
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.recommendations import AttributionRef
from geo_core.recommendations.evidence import MetricComparisonConclusion
from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.generation_contracts import (
    EvidenceSummary,
    RecommendationGenerationOutputError,
)
from geo_core.recommendations.generation_evidence import (
    GENERATION_EVIDENCE_CONTRACT_V1,
)
from geo_core.recommendations.generation_ports import (
    RECOMMENDATION_DIFY_CONTEXT_MAX_BYTES,
    parse_recommendation_output,
    recommendation_context_size_bytes,
    require_arbiter_acceptance,
    structured_arbiter_input,
    structured_generation_input,
)
from geo_core.recommendations.models import RecommendationType
from geo_core.workflow_runtime.contracts import canonical_json_value
from tests.unit.recommendations.generation_test_support import (
    frozen_evidence,
    arbiter_output,
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
        "type_admission_json",
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
    assert payload["allowed_recommendation_types"] == ["gap"]
    admission = json.loads(str(payload["type_admission_json"]))
    assert admission["resolved_type"] == "gap"
    assert admission["reason_codes"] == ["comparison_loss"]
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
    evidence = frozen_evidence(recommendation_type=recommendation_type)
    parsed = parse_recommendation_output(
        model_output(recommendation_type, evidence=evidence),
        evidence=evidence,
    )

    assert parsed.recommendation_type.value == recommendation_type
    assert parsed.selected_refs
    assert parsed.scope.url_ref == "url:https://example.test/au"


def test_same_evidence_cannot_be_relabelled_as_another_recommendation_type() -> None:
    evidence = frozen_evidence(recommendation_type=RecommendationType.GAP)
    output = model_output("gap", evidence=evidence)
    output["recommendation_type"] = "hard_blocker"

    with pytest.raises(
        RecommendationGenerationOutputError,
        match="(deterministic evidence admission|frozen input allowlist)",
    ):
        parse_recommendation_output(output, evidence=evidence)


def test_legacy_v1_keeps_original_generation_and_arbiter_contracts() -> None:
    evidence = replace(
        frozen_evidence(recommendation_type=RecommendationType.GAP),
        contract_version=GENERATION_EVIDENCE_CONTRACT_V1,
    )
    generation_input = structured_generation_input(evidence)

    assert "type_admission_json" not in generation_input
    assert generation_input["allowed_recommendation_types"] == [
        item.value for item in RecommendationType
    ]

    candidate = model_output("gap", evidence=evidence)
    candidate["recommendation_type"] = "hard_blocker"
    parsed = parse_recommendation_output(candidate, evidence=evidence)
    assert parsed.recommendation_type is RecommendationType.HARD_BLOCKER

    arbiter_input = structured_arbiter_input(candidate, evidence=evidence)
    assert "candidate_payloads" not in arbiter_input
    assert "arbiter_context_json" not in arbiter_input
    evaluator_results = arbiter_input["evaluator_results"]
    assert isinstance(evaluator_results, list)
    assert [item["evaluator"] for item in evaluator_results] == [
        "recommendation_schema_validator",
        "recommendation_evidence_validator",
    ]

    arbiter = arbiter_output(candidate)
    arbiter["subject_id"] = generation_input["subject_id"]
    arbiter["considered_evaluators"] = [
        "recommendation_schema_validator",
        "recommendation_evidence_validator",
    ]
    refs = candidate["evidence_refs"]
    assert isinstance(refs, list)
    require_arbiter_acceptance(
        arbiter,
        evidence=evidence,
        candidate_id=str(arbiter_input["candidate_ids"][0]),
        evidence_refs=tuple(str(item) for item in refs),
    )

    decision = candidate["decision"]
    assert isinstance(decision, dict)
    decision["business_value"] = "Legacy output invents 12 percent"
    with pytest.raises(RecommendationGenerationOutputError, match="numeric claim"):
        parse_recommendation_output(candidate, evidence=evidence)


def test_recommendation_text_can_only_copy_numbers_from_selected_evidence() -> None:
    evidence = frozen_evidence()
    first = evidence.summaries[0]
    summary = "The selected observation reports 12.5% recommendation coverage."
    grounded_summary = replace(
        first,
        summary=summary,
        summary_hash=hashlib.sha256(summary.encode()).hexdigest(),
    )
    evidence = replace(evidence, summaries=(grounded_summary, *evidence.summaries[1:]))
    output = model_output(evidence=evidence)
    decision = output["decision"]
    assert isinstance(decision, dict)
    decision["impact_chain"] = ["Coverage is 12.5% in the selected observation."]

    parsed = parse_recommendation_output(output, evidence=evidence)
    assert parsed.decision.impact_chain == ("Coverage is 12.5% in the selected observation.",)

    decision["impact_chain"] = ["Coverage will become 13%."]
    with pytest.raises(
        RecommendationGenerationOutputError,
        match="numeric values must be copied verbatim",
    ):
        parse_recommendation_output(output, evidence=evidence)


@pytest.mark.parametrize(
    ("summary", "grounded_text", "invented_text"),
    (
        (
            "Attributed revenue is AUD 1,250 for the selected period.",
            "Attributed revenue is AUD1,250.",
            "Attributed revenue will be AUD 1,251.",
        ),
        (
            "The observation was captured on 2026-07-21.",
            "The capture date is 2026-07-21.",
            "The capture date is 2026-07-22.",
        ),
    ),
)
def test_recommendation_currency_and_date_claims_require_exact_selected_evidence(
    summary: str,
    grounded_text: str,
    invented_text: str,
) -> None:
    evidence = frozen_evidence()
    first = evidence.summaries[0]
    grounded_summary = replace(
        first,
        summary=summary,
        summary_hash=hashlib.sha256(summary.encode()).hexdigest(),
    )
    evidence = replace(evidence, summaries=(grounded_summary, *evidence.summaries[1:]))
    output = model_output(evidence=evidence)
    decision = output["decision"]
    assert isinstance(decision, dict)
    decision["business_value"] = grounded_text

    parse_recommendation_output(output, evidence=evidence)

    decision["business_value"] = invented_text
    with pytest.raises(
        RecommendationGenerationOutputError,
        match="numeric values must be copied verbatim",
    ):
        parse_recommendation_output(output, evidence=evidence)


def test_recommendation_context_size_counts_actual_utf8_json_bytes() -> None:
    payload = structured_generation_input(frozen_evidence())
    assert recommendation_context_size_bytes(payload) == len(
        json.dumps(
            canonical_json_value(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert recommendation_context_size_bytes(payload) < RECOMMENDATION_DIFY_CONTEXT_MAX_BYTES


def test_native_arbiter_receives_candidate_semantics_and_type_admission() -> None:
    evidence = frozen_evidence()
    candidate = model_output(evidence=evidence)
    payload = structured_arbiter_input(candidate, evidence=evidence)

    candidate_payloads = payload["candidate_payloads"]
    assert isinstance(candidate_payloads, list)
    candidate_payload = candidate_payloads[0]
    assert isinstance(candidate_payload, dict)
    assert json.loads(str(candidate_payload["payload_json"])) == candidate
    assert json.loads(str(payload["arbiter_context_json"]))["resolved_type"] == "gap"
    evaluators = payload["evaluator_results"]
    assert isinstance(evaluators, list)
    assert all(isinstance(item, dict) for item in evaluators)
    assert [item["evaluator"] for item in evaluators if isinstance(item, dict)] == [
        "recommendation_schema_validator",
        "recommendation_evidence_validator",
        "recommendation_type_validator",
    ]

    output = arbiter_output(candidate)
    considered = output["considered_evaluators"]
    assert isinstance(considered, list)
    output["considered_evaluators"] = considered[:-1]
    evidence_refs = candidate["evidence_refs"]
    assert isinstance(evidence_refs, list)
    with pytest.raises(
        RecommendationGenerationOutputError,
        match="evaluator coverage",
    ):
        require_arbiter_acceptance(
            output,
            evidence=evidence,
            candidate_id=str(candidate_payload["candidate_id"]),
            evidence_refs=tuple(str(item) for item in evidence_refs),
        )

    reordered = arbiter_output(candidate)
    considered = reordered["considered_evaluators"]
    assert isinstance(considered, list)
    reordered["considered_evaluators"] = list(reversed(considered))
    require_arbiter_acceptance(
        reordered,
        evidence=evidence,
        candidate_id=str(candidate_payload["candidate_id"]),
        evidence_refs=tuple(str(item) for item in evidence_refs),
    )


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
            replace(
                evidence.metric_comparisons[0],
                sufficient_evidence=False,
                conclusion=MetricComparisonConclusion.INSUFFICIENT_EVIDENCE,
            ),
        ),
    )

    assert underpowered.insufficiency_reasons(minimum_real_observations=3) == (
        "missing_sufficient_metric_comparison",
    )


def test_inconclusive_comparison_is_sufficient_and_admits_an_experiment() -> None:
    evidence = frozen_evidence(recommendation_type=RecommendationType.EXPERIMENT)

    assert evidence.insufficiency_reasons(minimum_real_observations=3) == ()
    payload = structured_generation_input(evidence)
    assert payload["allowed_recommendation_types"] == ["experiment"]


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
