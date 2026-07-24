from __future__ import annotations

from collections.abc import Mapping
import json
from types import MappingProxyType

import pytest

from geo_core.prompts.bootstrap_catalog import (
    BOOTSTRAP_SPEC_VERSION,
    default_prompt_bootstrap_spec,
    default_prompt_bootstrap_specs,
    prompt_bootstrap_catalog_hash,
)
from geo_core.prompts.bootstrap_contracts import (
    BOOTSTRAP_CATALOG_VERSION,
    EvalScenario,
    PromptBootstrapRuleViolation,
    thaw_mapping,
)
from geo_core.prompts.bootstrap_evaluation import (
    evaluate_prompt_output,
    evaluate_prompt_test_set,
)
from geo_core.prompts.bootstrap_validation import (
    PromptOutputRuleViolation,
    assert_bootstrap_spec,
    evaluate_fixture,
    validate_bootstrap_output,
    validate_portable_output_schema,
)
from geo_core.prompts.program import (
    AUXILIARY_PROGRAM_KINDS,
    CORE_FIRST_PHASE_PROGRAM_KINDS,
    FIRST_PHASE_PROGRAM_KINDS,
    ProgramKind,
    ProgramReleaseStatus,
    render_program_release,
)
from tests.unit.prompts.prompt_bootstrap_catalog_test_support import (
    AUXILIARY_SYNTHETIC_OUTPUT_FIELDS,
    CATALOG_HASH,
    OWNER_ID,
    PROJECT_ID,
    assert_every_object_is_closed_and_fully_required as _assert_every_object_is_closed_and_fully_required,
    fixture_for as _fixture,
)


def test_catalog_delivers_eight_core_and_two_auxiliary_first_phase_drafts() -> None:
    specs = default_prompt_bootstrap_specs()

    assert tuple(spec.program_kind for spec in specs) == FIRST_PHASE_PROGRAM_KINDS
    assert len(specs) == 10
    assert CORE_FIRST_PHASE_PROGRAM_KINDS == FIRST_PHASE_PROGRAM_KINDS[:8]
    assert AUXILIARY_PROGRAM_KINDS == FIRST_PHASE_PROGRAM_KINDS[8:]
    assert ProgramKind.REFERENCE_TRANSLATION not in {spec.program_kind for spec in specs}
    assert all(spec.catalog_version == BOOTSTRAP_CATALOG_VERSION for spec in specs)
    assert all(spec.spec_version == BOOTSTRAP_SPEC_VERSION for spec in specs)
    assert all(spec.minimum_score == 95 for spec in specs)
    with pytest.raises(PromptBootstrapRuleViolation, match="reserved"):
        default_prompt_bootstrap_spec(ProgramKind.REFERENCE_TRANSLATION)


def test_first_phase_business_purposes_are_exact_and_reference_translation_is_reserved() -> None:
    assert {
        spec.program_kind: spec.purpose for spec in default_prompt_bootstrap_specs()
    } == {
        ProgramKind.GENERATION: "synthetic_lab.generation",
        ProgramKind.CLAIM_EXTRACTION: "synthetic_lab.claim_extraction",
        ProgramKind.CONFLICT_CHECK: "synthetic_lab.conflict_check",
        ProgramKind.REVISION: "synthetic_lab.revision",
        ProgramKind.STYLE_JUDGE: "synthetic_lab.style_judge",
        ProgramKind.ARBITER: "synthetic_lab.arbiter",
        ProgramKind.METRIC_JUDGE: "monitoring.metric_judge",
        ProgramKind.RECOMMENDATION: "recommendations.recommendation",
        ProgramKind.STYLE_PROFILE: "synthetic_lab.style_profile",
        ProgramKind.OFFLINE_ANSWER: "synthetic_lab.offline_answer",
    }


def test_catalog_and_spec_hashes_are_stable_across_rebuilds() -> None:
    first = default_prompt_bootstrap_specs()
    first_values = tuple((spec.spec_hash, spec.test_set_hash) for spec in first)

    default_prompt_bootstrap_specs.cache_clear()
    second = default_prompt_bootstrap_specs()

    assert prompt_bootstrap_catalog_hash() == CATALOG_HASH
    assert tuple((spec.spec_hash, spec.test_set_hash) for spec in second) == first_values
    assert all(len(spec.spec_hash) == 64 for spec in second)
    assert all(len(spec.test_set_hash) == 64 for spec in second)
    assert all(len({fixture.fixture_hash for fixture in spec.fixtures}) == 5 for spec in second)


@pytest.mark.parametrize("kind", FIRST_PHASE_PROGRAM_KINDS)
def test_each_spec_compiles_an_existing_prompt_program_draft_only(kind: ProgramKind) -> None:
    spec = default_prompt_bootstrap_spec(kind)

    first = spec.compile_draft(project_id=PROJECT_ID, owner_id=OWNER_ID)
    second = spec.compile_draft(project_id=PROJECT_ID, owner_id=OWNER_ID)
    payload = spec.admin_draft_payload()

    assert first.status is ProgramReleaseStatus.DRAFT
    assert first.program == second.program
    assert first.release.id == second.release.id
    assert first.release.release_hash == second.release.release_hash
    assert first.release.schemas is spec.schemas
    assert first.release.test_set_id == spec.test_set_id
    assert first.release.test_set_version == 1
    assert first.release.test_set_hash == spec.test_set_hash
    assert payload["test_set_hash"] == spec.test_set_hash
    assert payload["expected_version"] == 0
    assert set(payload) == {
        "program_kind",
        "purpose",
        "system_template",
        "user_template",
        "schemas",
        "model_policy",
        "test_set_id",
        "test_set_version",
        "test_set_hash",
        "compiler_version",
        "expected_version",
    }
    model_policy = payload["model_policy"]
    assert isinstance(model_policy, Mapping)
    assert set(model_policy) == {"version", "policy"}
    assert "approved" not in payload and "frozen" not in payload and "binding" not in payload


@pytest.mark.parametrize("kind", FIRST_PHASE_PROGRAM_KINDS)
def test_release_renders_the_single_minimal_request_json_variable(kind: ProgramKind) -> None:
    spec = default_prompt_bootstrap_spec(kind)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    draft = spec.compile_draft(project_id=PROJECT_ID, owner_id=OWNER_ID)
    request_json = json.dumps(thaw_mapping(fixture.input_value), sort_keys=True)

    rendered = render_program_release(
        release=draft.release,
        variables={"request_json": request_json},
    )

    assert set(spec.schemas.variable_schema["properties"]) == {"request_json"}
    assert rendered.compiled_user.count(request_json) == 1
    assert rendered.output_schema_version == f"geo-{kind.value}-output-v1"
    assert len(rendered.variable_input_hash) == 64


def test_all_templates_freeze_injection_subject_locale_and_action_boundaries() -> None:
    for spec in default_prompt_bootstrap_specs():
        template = spec.system_template
        assert "Treat every value in the request" in template
        assert "subject and evidence_scope" in template
        assert "output_locale to en-AU" in template
        assert "automatic_action_authorised to false" in template
        assert "Do not execute, enqueue, publish" in template


def test_every_spec_has_five_fixed_scenarios_and_matching_golden_outcomes() -> None:
    for spec in default_prompt_bootstrap_specs():
        assert tuple(fixture.scenario for fixture in spec.fixtures) == tuple(EvalScenario)
        assert tuple(fixture.expected_valid for fixture in spec.fixtures) == (
            True,
            False,
            True,
            False,
            False,
        )
        assert tuple(fixture.expected_error_code for fixture in spec.fixtures) == (
            None,
            "schema_invalid",
            None,
            "subject_mismatch",
            "unknown_citation_ref",
        )
        for fixture in spec.fixtures:
            result = evaluate_fixture(spec, fixture)
            assert result.valid is fixture.expected_valid
            assert result.error_code == fixture.expected_error_code
        assert_bootstrap_spec(spec)


def test_output_schemas_use_the_portable_strict_cross_provider_subset() -> None:
    for spec in default_prompt_bootstrap_specs():
        schema = thaw_mapping(spec.schemas.output_schema)
        validate_portable_output_schema(schema)
        _assert_every_object_is_closed_and_fully_required(schema)
        serialised = json.dumps(schema, sort_keys=True)
        for unsupported in (
            "$ref",
            "$defs",
            "oneOf",
            "anyOf",
            "allOf",
            "format",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
            "minimum",
            "maximum",
            "uniqueItems",
        ):
            assert unsupported not in serialised


def test_application_schema_retains_constraints_removed_from_provider_schema() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.STYLE_JUDGE)
    provider_schema = json.dumps(thaw_mapping(spec.schemas.output_schema), sort_keys=True)
    application_schema = json.dumps(
        thaw_mapping(spec.application_output_schema), sort_keys=True
    )

    for assertion in (
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "uniqueItems",
    ):
        assert assertion not in provider_schema
        assert assertion in application_schema


def test_auxiliary_provider_schemas_exactly_cover_synthetic_production_outputs() -> None:
    for kind, fields in AUXILIARY_SYNTHETIC_OUTPUT_FIELDS.items():
        schema = thaw_mapping(default_prompt_bootstrap_spec(kind).schemas.output_schema)
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields


def test_style_profile_freezes_manifest_and_noncontradictory_patterns() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.STYLE_PROFILE)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    output = thaw_mapping(fixture.expected_output)
    output["sample_manifest_hash"] = "0" * 64
    with pytest.raises(PromptOutputRuleViolation) as manifest:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)
    assert manifest.value.code == "semantic_rule_failed"

    output = thaw_mapping(fixture.expected_output)
    output["avoid_patterns"] = ["plain-spoken"]
    with pytest.raises(PromptOutputRuleViolation) as contradiction:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)
    assert contradiction.value.code == "semantic_rule_failed"


def test_offline_answer_requires_exact_corpus_evidence_and_bounded_metric() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.OFFLINE_ANSWER)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    output = thaw_mapping(fixture.expected_output)
    output["metric_value"] = 1.01
    with pytest.raises(PromptOutputRuleViolation) as metric:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)
    assert metric.value.code == "schema_invalid"

    output = thaw_mapping(fixture.expected_output)
    output["evidence_refs"] = ["evidence-fact-001"]
    output["citation_refs"] = []
    with pytest.raises(PromptOutputRuleViolation) as evidence:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)
    assert evidence.value.code == "unknown_evidence_ref"


@pytest.mark.parametrize(
    ("kind", "mutate"),
    (
        (
            ProgramKind.RECOMMENDATION,
            lambda output: output.update(
                {"evidence_refs": [output["evidence_refs"][0]] * 2}
            ),
        ),
        (
            ProgramKind.RECOMMENDATION,
            lambda output: output.update({"evidence_refs": [f"ref-{i}" for i in range(101)]}),
        ),
        (
            ProgramKind.RECOMMENDATION,
            lambda output: output["decision"].update({"risk": "x" * 4_001}),
        ),
        (
            ProgramKind.STYLE_JUDGE,
            lambda output: output.update({"score": 5.01}),
        ),
        (
            ProgramKind.METRIC_JUDGE,
            lambda output: output["results"][0].update({"value": 1.01}),
        ),
    ),
)
def test_application_schema_rejects_constraints_omitted_from_provider_schema(
    kind: ProgramKind,
    mutate,
) -> None:
    spec = default_prompt_bootstrap_spec(kind)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    output = thaw_mapping(fixture.expected_output)
    mutate(output)

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)

    assert captured.value.code == "schema_invalid"


@pytest.mark.parametrize("kind", FIRST_PHASE_PROGRAM_KINDS)
def test_every_output_freezes_australian_locale_and_forbids_automatic_action(
    kind: ProgramKind,
) -> None:
    spec = default_prompt_bootstrap_spec(kind)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    output = thaw_mapping(fixture.expected_output)
    output["output_locale"] = "en-US"
    with pytest.raises(PromptOutputRuleViolation) as locale:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)
    assert locale.value.code == "schema_invalid"

    output = thaw_mapping(fixture.expected_output)
    output["automatic_action_authorised"] = True
    with pytest.raises(PromptOutputRuleViolation) as action:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)
    assert action.value.code == "automatic_action_forbidden"


def test_recommendation_input_allows_only_the_six_frozen_types() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    input_value = thaw_mapping(fixture.input_value)
    input_value["allowed_recommendation_types"] = ["publish_now"]

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(
            spec,
            input_value=input_value,
            output=fixture.expected_output,
        )

    assert captured.value.code == "input_schema_invalid"


@pytest.mark.parametrize(
    "schema",
    (
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": True,
        },
        {"type": "string", "oneOf": [{"const": "a"}, {"const": "b"}]},
    ),
)
def test_portable_schema_profile_fails_closed(schema: dict[str, object]) -> None:
    with pytest.raises(PromptBootstrapRuleViolation, match="portable output"):
        validate_portable_output_schema(schema)


@pytest.mark.parametrize("kind", (ProgramKind.GENERATION, ProgramKind.REVISION))
def test_guided_input_can_never_be_reported_as_evidence(kind: ProgramKind) -> None:
    spec = default_prompt_bootstrap_spec(kind)
    fixture = _fixture(spec.fixtures, EvalScenario.PROMPT_INJECTION)
    output = thaw_mapping(fixture.expected_output)
    output["guidance_used_as_evidence"] = True

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(
            spec,
            input_value=thaw_mapping(fixture.input_value),
            output=output,
        )

    assert captured.value.code == "guided_input_as_evidence"


def test_injection_must_be_detected_and_must_never_be_followed() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.GENERATION)
    fixture = _fixture(spec.fixtures, EvalScenario.PROMPT_INJECTION)
    output = thaw_mapping(fixture.expected_output)
    output["untrusted_instruction_followed"] = True

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(
            spec,
            input_value=thaw_mapping(fixture.input_value),
            output=output,
        )

    assert captured.value.code == "prompt_injection_followed"


def test_subject_validation_reaches_nested_generated_candidates() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.GENERATION)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    output = thaw_mapping(fixture.expected_output)
    candidates = output["candidates"]
    assert isinstance(candidates, list) and isinstance(candidates[0], dict)
    candidates[0]["subject_id"] = "subject-placeholder-other"

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(
            spec,
            input_value=thaw_mapping(fixture.input_value),
            output=output,
        )

    assert captured.value.code == "subject_mismatch"


def test_input_evidence_subject_must_be_in_the_explicit_allowlist() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    input_value = thaw_mapping(fixture.input_value)
    evidence = input_value["evidence"]
    assert isinstance(evidence, list) and isinstance(evidence[0], dict)
    evidence[0]["subject_id"] = "subject-not-allowed"
    evidence[0]["evidence_scope"] = "competitor_subject"

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(
            spec,
            input_value=input_value,
            output=fixture.expected_output,
        )

    assert captured.value.code == "input_evidence_invalid"


def test_competitor_evidence_is_legal_when_subject_and_scope_are_explicit() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.CLAIM_EXTRACTION)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    input_value = thaw_mapping(fixture.input_value)
    output = thaw_mapping(fixture.expected_output)
    competitor_ref = "evidence-competitor-001"
    evidence = input_value["evidence"]
    claims = output["claims"]
    assert isinstance(evidence, list)
    assert isinstance(claims, list)
    evidence.append(
        {
            "ref": competitor_ref,
            "subject_id": "subject-placeholder-other",
            "evidence_scope": "competitor_subject",
            "summary": "Approved fictional Fact for the explicit comparison subject.",
        }
    )
    claims.append(
        {
            "claim_id": "claim-competitor-001",
            "text": "The explicit comparison subject has a fictional attribute.",
            "subject_id": "subject-placeholder-other",
            "evidence_refs": [competitor_ref],
            "classification": "fact",
        }
    )
    output["evidence_refs"] = ["evidence-fact-001", competitor_ref]

    validate_bootstrap_output(spec, input_value=input_value, output=output)


def test_competitor_fact_cannot_silently_assess_a_primary_subject_claim() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.CONFLICT_CHECK)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    input_value = thaw_mapping(fixture.input_value)
    output = thaw_mapping(fixture.expected_output)
    competitor_ref = "evidence-competitor-001"
    evidence = input_value["evidence"]
    assessments = output["assessments"]
    assert isinstance(evidence, list)
    assert isinstance(assessments, list) and isinstance(assessments[0], dict)
    evidence.append(
        {
            "ref": competitor_ref,
            "subject_id": "subject-placeholder-other",
            "evidence_scope": "competitor_subject",
            "summary": "Approved fictional Fact for the explicit comparison subject.",
        }
    )
    assessments[0]["fact_ref"] = competitor_ref

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(spec, input_value=input_value, output=output)

    assert captured.value.code == "semantic_rule_failed"


def test_recommendation_cannot_escape_input_evidence_or_authorise_execution() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    input_value = thaw_mapping(fixture.input_value)
    output = thaw_mapping(fixture.expected_output)
    output["automatic_action_authorised"] = True

    with pytest.raises(PromptOutputRuleViolation) as automatic:
        validate_bootstrap_output(spec, input_value=input_value, output=output)
    assert automatic.value.code == "automatic_action_forbidden"

    output = thaw_mapping(fixture.expected_output)
    output["evidence_refs"] = ["evidence-not-in-input"]
    output["citation_refs"] = []
    with pytest.raises(PromptOutputRuleViolation) as evidence:
        validate_bootstrap_output(spec, input_value=input_value, output=output)
    assert evidence.value.code == "unknown_evidence_ref"


def test_kind_specific_outputs_cannot_expand_frozen_fact_issue_or_type_scope() -> None:
    conflict = default_prompt_bootstrap_spec(ProgramKind.CONFLICT_CHECK)
    conflict_fixture = _fixture(conflict.fixtures, EvalScenario.POSITIVE)
    conflict_output = thaw_mapping(conflict_fixture.expected_output)
    assessments = conflict_output["assessments"]
    assert isinstance(assessments, list) and isinstance(assessments[0], dict)
    assessments[0]["fact_ref"] = "evidence-not-in-input"
    with pytest.raises(PromptOutputRuleViolation) as fact:
        validate_bootstrap_output(
            conflict,
            input_value=conflict_fixture.input_value,
            output=conflict_output,
        )
    assert fact.value.code == "semantic_rule_failed"

    revision = default_prompt_bootstrap_spec(ProgramKind.REVISION)
    revision_fixture = _fixture(revision.fixtures, EvalScenario.POSITIVE)
    revision_output = thaw_mapping(revision_fixture.expected_output)
    revision_output["remaining_warning_codes"] = ["invented_issue"]
    with pytest.raises(PromptOutputRuleViolation) as issue:
        validate_bootstrap_output(
            revision,
            input_value=revision_fixture.input_value,
            output=revision_output,
        )
    assert issue.value.code == "semantic_rule_failed"

    recommendation = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    recommendation_fixture = _fixture(recommendation.fixtures, EvalScenario.POSITIVE)
    recommendation_input = thaw_mapping(recommendation_fixture.input_value)
    recommendation_input["allowed_recommendation_types"] = ["gap"]
    with pytest.raises(PromptOutputRuleViolation) as recommendation_type:
        validate_bootstrap_output(
            recommendation,
            input_value=recommendation_input,
            output=recommendation_fixture.expected_output,
        )
    assert recommendation_type.value.code == "semantic_rule_failed"


def test_claim_extraction_rejects_duplicate_claim_ids() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.CLAIM_EXTRACTION)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    output = thaw_mapping(fixture.expected_output)
    claims = output["claims"]
    assert isinstance(claims, list) and isinstance(claims[0], dict)
    claims.append(dict(claims[0]))

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)

    assert captured.value.code == "semantic_rule_failed"


@pytest.mark.parametrize("failure", ("missing", "duplicate"))
def test_conflict_check_requires_one_unique_assessment_per_input_claim(
    failure: str,
) -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.CONFLICT_CHECK)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    input_value = thaw_mapping(fixture.input_value)
    output = thaw_mapping(fixture.expected_output)
    claims = input_value["claims"]
    assessments = output["assessments"]
    assert isinstance(claims, list) and isinstance(claims[0], dict)
    assert isinstance(assessments, list) and isinstance(assessments[0], dict)
    if failure == "missing":
        second_claim = dict(claims[0])
        second_claim["claim_id"] = "claim-002"
        claims.append(second_claim)
    else:
        assessments.append(dict(assessments[0]))

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(spec, input_value=input_value, output=output)

    assert captured.value.code == "semantic_rule_failed"


def test_revision_cannot_omit_a_frozen_issue() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.REVISION)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    input_value = thaw_mapping(fixture.input_value)
    issue_codes = input_value["issue_codes"]
    assert isinstance(issue_codes, list)
    issue_codes.append("unsupported_claim")

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(
            spec,
            input_value=input_value,
            output=fixture.expected_output,
        )

    assert captured.value.code == "semantic_rule_failed"


def test_arbiter_cannot_omit_or_duplicate_a_frozen_evaluator() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.ARBITER)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    output = thaw_mapping(fixture.expected_output)
    output["considered_evaluators"] = ["evaluator-a", "evaluator-a"]

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)

    assert captured.value.code == "schema_invalid"


@pytest.mark.parametrize(
    ("locators", "expected_code"),
    (
        ([], "schema_invalid"),
        (
            [
                {
                    "kind": "answer_span",
                    "reference_id": "evidence-observation-001",
                    "version": "observation-v1",
                    "content_hash": "d" * 64,
                    "start": 0,
                    "end": 9999,
                    "redacted_quote_hash": None,
                }
            ],
            "semantic_rule_failed",
        ),
        (
            [
                {
                    "kind": "fact",
                    "reference_id": "evidence-not-in-input",
                    "version": "approved-fact-v7",
                    "content_hash": None,
                    "start": None,
                    "end": None,
                    "redacted_quote_hash": None,
                }
            ],
            "semantic_rule_failed",
        ),
    ),
)
def test_metric_judge_requires_valid_frozen_evidence_locators(
    locators: list[object],
    expected_code: str,
) -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.METRIC_JUDGE)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    output = thaw_mapping(fixture.expected_output)
    results = output["results"]
    assert isinstance(results, list) and isinstance(results[0], dict)
    results[0]["evidence_locators"] = locators

    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)

    assert captured.value.code == expected_code


def test_metric_judge_fact_locator_requires_the_exact_versioned_evidence_reference() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.METRIC_JUDGE)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)
    output = thaw_mapping(fixture.expected_output)

    validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)

    results = output["results"]
    assert isinstance(results, list) and isinstance(results[1], dict)
    locators = results[1]["evidence_locators"]
    assert isinstance(locators, list) and isinstance(locators[0], dict)
    locators[0]["version"] = "approved-fact-v8"
    with pytest.raises(PromptOutputRuleViolation) as captured:
        validate_bootstrap_output(spec, input_value=fixture.input_value, output=output)

    assert captured.value.code == "semantic_rule_failed"


def test_rubrics_are_complete_blocking_and_total_one_hundred() -> None:
    for spec in default_prompt_bootstrap_specs():
        assert sum(item.weight for item in spec.rubric) == 100
        assert all(item.blocking for item in spec.rubric)
        assert {item.code for item in spec.rubric} >= {
            "schema.portable_strict",
            "identity.subject_exact",
            "lineage.evidence_allowlist",
            "safety.untrusted_input",
            f"semantics.{spec.program_kind.value}",
        }


def test_rubric_evaluator_maps_failures_and_freezes_a_test_set_receipt() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    positive_output = thaw_mapping(
        _fixture(spec.fixtures, EvalScenario.POSITIVE).expected_output
    )
    valid_outputs = {
        fixture.fixture_id: (
            thaw_mapping(fixture.expected_output)
            if fixture.scenario is EvalScenario.PROMPT_INJECTION
            else positive_output
        )
        for fixture in spec.fixtures
    }
    first = evaluate_prompt_test_set(spec, valid_outputs)
    second = evaluate_prompt_test_set(spec, valid_outputs)

    assert first.passed is True
    assert first.score == 100
    assert first.result_hash == second.result_hash
    assert len(first.result_hash) == 64
    assert all(item.score == 100 and item.passed for item in first.case_results)

    subject_fixture = _fixture(spec.fixtures, EvalScenario.SUBJECT_MIXUP)
    subject_result = evaluate_prompt_output(
        spec,
        fixture=subject_fixture,
        output=thaw_mapping(subject_fixture.expected_output),
    )
    assert subject_result.passed is False
    assert subject_result.blocking_failure is True
    assert subject_result.failed_criteria == ("identity.subject_exact",)
    assert subject_result.score == 80


def test_test_set_evaluator_rejects_missing_or_unfrozen_fixture_ids() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.METRIC_JUDGE)

    with pytest.raises(PromptBootstrapRuleViolation, match="missing="):
        evaluate_prompt_test_set(spec, {})


def test_catalog_contains_only_synthetic_placeholders_and_no_secret_fields() -> None:
    payload = json.dumps(
        [spec.canonical_value() for spec in default_prompt_bootstrap_specs()],
        sort_keys=True,
    ).casefold()

    assert "fictional" in payload and "placeholder" in payload
    for forbidden in (
        "api_key",
        "access_token",
        "secret_reference",
        "authorization:",
        "automatically publish",
    ):
        assert forbidden not in payload


def test_specs_and_fixtures_are_deeply_immutable() -> None:
    spec = default_prompt_bootstrap_spec(ProgramKind.GENERATION)
    fixture = _fixture(spec.fixtures, EvalScenario.POSITIVE)

    assert isinstance(spec.schemas.output_schema, MappingProxyType)
    assert isinstance(fixture.input_value, MappingProxyType)
    with pytest.raises(TypeError):
        spec.schemas.output_schema["type"] = "array"  # type: ignore[index]
    with pytest.raises(TypeError):
        fixture.input_value["subject_id"] = "changed"  # type: ignore[index]
