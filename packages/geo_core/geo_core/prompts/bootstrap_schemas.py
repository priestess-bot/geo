"""Full application and provider-portable schemas for the Prompt draft catalog."""

from __future__ import annotations

from collections.abc import Mapping

from geo_core.prompts.bootstrap_limits import STYLE_PROFILE_SUMMARY_MAX_CHARACTERS
from geo_core.prompts.program_contracts import (
    ProgramKind,
    provider_portable_output_schema,
)


def bootstrap_variable_schema() -> dict[str, object]:
    return _strict_object(
        {
            "request_json": _string(minimum=2, maximum=100_000),
        }
    )


def bootstrap_input_schema(kind: ProgramKind) -> dict[str, object]:
    properties = {
        "subject_id": _string(maximum=200),
        "allowed_subject_ids": _string_array(minimum=1, maximum=50),
        "evidence": _array(_evidence_item_schema(), minimum=1, maximum=100),
        "output_locale": _enum("en-AU"),
        "untrusted_text": _string(minimum=0, maximum=10_000),
        "prompt_injection_present": {"type": "boolean"},
        **_input_properties(kind),
    }
    schema = _strict_object(properties)
    if kind is ProgramKind.ARBITER:
        required = schema["required"]
        assert isinstance(required, list)
        required.remove("candidate_payloads")
        required.remove("arbiter_context_json")
    return schema


def bootstrap_output_schema(kind: ProgramKind) -> dict[str, object]:
    return provider_portable_output_schema(bootstrap_application_output_schema(kind))


def bootstrap_application_output_schema(kind: ProgramKind) -> dict[str, object]:
    """Return the complete schema enforced after every provider response."""

    properties = {
        "subject_id": _string(maximum=200),
        "evidence_refs": _string_array(minimum=1, maximum=100),
        "citation_refs": _string_array(minimum=0, maximum=100),
        "output_locale": _enum("en-AU"),
        "automatic_action_authorised": {"type": "boolean"},
        "injection_detected": {"type": "boolean"},
        "untrusted_instruction_followed": {"type": "boolean"},
        **_output_properties(kind),
    }
    return _strict_object(properties)


def _input_properties(kind: ProgramKind) -> Mapping[str, object]:
    if kind is ProgramKind.GENERATION:
        return {
            "scenario_mode": _enum("autonomous_scenario", "guided_scenario"),
            "guided_idea": _string(minimum=0, maximum=4000),
            "channel": _string(maximum=100),
            "scenario": _string(maximum=4000),
            "style_profile": _string(maximum=STYLE_PROFILE_SUMMARY_MAX_CHARACTERS),
            "approved_facts": _string_array(minimum=1, maximum=100),
        }
    if kind is ProgramKind.CLAIM_EXTRACTION:
        return {"candidate_text": _string(maximum=20_000)}
    if kind is ProgramKind.CONFLICT_CHECK:
        return {
            "claims": _array(
                _strict_object(
                    {
                        "claim_id": _string(maximum=200),
                        "text": _string(maximum=4000),
                        "subject_id": _string(maximum=200),
                        "evidence_refs": _string_array(minimum=0, maximum=100),
                    }
                ),
                minimum=1,
                maximum=100,
            )
        }
    if kind is ProgramKind.REVISION:
        return {
            "candidate_text": _string(maximum=20_000),
            "issue_codes": _string_array(minimum=1, maximum=100),
            "scenario_mode": _enum("autonomous_scenario", "guided_scenario"),
            "guided_idea": _string(minimum=0, maximum=4000),
        }
    if kind is ProgramKind.STYLE_JUDGE:
        return {
            "candidate_text": _string(maximum=20_000),
            "style_profile": _string(maximum=STYLE_PROFILE_SUMMARY_MAX_CHARACTERS),
            "pass_threshold": {"type": "number", "minimum": 0, "maximum": 5},
        }
    if kind is ProgramKind.ARBITER:
        return {
            "candidate_ids": _string_array(minimum=1, maximum=20),
            "candidate_payloads": _array(
                _strict_object(
                    {
                        "candidate_id": _string(maximum=200),
                        "payload_json": _string(maximum=100_000),
                    }
                ),
                minimum=1,
                maximum=20,
            ),
            "arbiter_context_json": _string(maximum=4_000),
            "evaluator_results": _array(
                _strict_object(
                    {
                        "evaluator": _string(maximum=200),
                        "candidate_id": _string(maximum=200),
                        "disposition": _enum("pass", "warning", "revise"),
                        "issue_codes": _string_array(minimum=0, maximum=100),
                        "evidence_refs": _string_array(minimum=1, maximum=100),
                    }
                ),
                minimum=2,
                maximum=20,
            ),
        }
    if kind is ProgramKind.METRIC_JUDGE:
        return {
            "answer_text": _string(maximum=50_000),
            "locator_sources": _array(
                _strict_object(
                    {
                        "kind": _enum("answer_span", "citation", "fact"),
                        "reference_id": _string(maximum=500),
                        "version": _nullable_string(maximum=200),
                        "content_hash": _nullable_sha256(),
                    }
                ),
                minimum=1,
                maximum=200,
            ),
            "metrics": _array(
                _strict_object(
                    {
                        "metric_id": _string(maximum=200),
                        "kind": _enum(
                            "recommendation",
                            "sentiment",
                            "fact",
                            "citation_entailment",
                            "corpus_absorption",
                        ),
                        "definition": _string(maximum=4000),
                        "evidence_refs": _string_array(minimum=1, maximum=100),
                    }
                ),
                minimum=1,
                maximum=50,
            ),
        }
    if kind is ProgramKind.RECOMMENDATION:
        return {
            "scope": _recommendation_scope_schema(),
            "context_refs": _array(_context_ref_schema(), minimum=0, maximum=100),
            "allowed_recommendation_types": _enum_array(
                "hard_blocker",
                "gap",
                "experiment",
                "optional",
                "no_change",
                "insufficient_evidence",
            ),
            "type_admission_json": _string(maximum=4_000),
        }
    if kind is ProgramKind.STYLE_PROFILE:
        return {
            "channel": _string(maximum=100),
            "locale": _enum("en-AU"),
            "corpus_hash": _sha256(),
            "approved_sample_count": _integer(minimum=200, maximum=1_000_000),
            "sample_manifest_hash": _sha256(),
        }
    if kind is ProgramKind.OFFLINE_ANSWER:
        return {
            "experiment_input_hash": _sha256(),
            "slot_id": _sha256(),
            "pair_id": _sha256(),
            "question_version_id": _string(maximum=200),
            "question_hash": _sha256(),
            "question_text": _string(maximum=20_000),
            "question_cluster_key": _string(maximum=500),
            "repetition": _integer(minimum=1, maximum=10),
            "arm": _enum(
                "no_corpus_baseline",
                "current_approved_corpus",
                "new_candidate_corpus",
            ),
            "corpus_version_id": _string(maximum=200),
            "corpus_hash": _sha256(),
            "corpus_context": _string(maximum=100_000),
        }
    if kind is ProgramKind.QUESTION_GENERATION:
        return {
            "dimensions": _string_array(minimum=1, maximum=50),
            "facts": _string_array(minimum=1, maximum=100),
            "entities": _string_array(minimum=1, maximum=50),
            "parent_candidates": _string_array(minimum=0, maximum=50),
        }
    if kind is ProgramKind.RAG_GROUNDING:
        return {
            "question": _string(maximum=4_000),
            "facts": _string_array(minimum=1, maximum=100),
            "entities": _string_array(minimum=1, maximum=50),
        }
    if kind in {ProgramKind.PLACEMENT_GENERATION, ProgramKind.PLACEMENT_SIMULATION}:
        return {
            "brief": _string(maximum=20_000),
            "destination_policy": _string(maximum=8_000),
        }
    raise ValueError(f"unsupported bootstrap Program kind: {kind.value}")


def _output_properties(kind: ProgramKind) -> Mapping[str, object]:
    if kind is ProgramKind.GENERATION:
        candidate = _strict_object(
            {
                "candidate_id": _string(maximum=200),
                "subject_id": _string(maximum=200),
                "text": _string(maximum=20_000),
                "evidence_refs": _string_array(minimum=1, maximum=100),
                "derived_or_unknown_claims": _string_array(minimum=0, maximum=100),
            }
        )
        return {
            "guidance_used_as_evidence": {"type": "boolean"},
            "candidates": _array(candidate, minimum=4, maximum=4),
        }
    if kind is ProgramKind.CLAIM_EXTRACTION:
        return {
            "claims": _array(
                _strict_object(
                    {
                        "claim_id": _string(maximum=200),
                        "text": _string(maximum=4000),
                        "subject_id": _string(maximum=200),
                        "evidence_refs": _string_array(minimum=0, maximum=100),
                        "classification": _enum("fact", "experience", "derived_or_unknown"),
                    }
                ),
                minimum=1,
                maximum=100,
            )
        }
    if kind is ProgramKind.CONFLICT_CHECK:
        return {
            "assessments": _array(
                _strict_object(
                    {
                        "claim_id": _string(maximum=200),
                        "status": _enum(
                            "current_approved",
                            "derived_or_unknown",
                            "explicit_conflict",
                            "subject_mixup",
                        ),
                        "fact_ref": _string(minimum=0, maximum=200),
                        "expected_subject_id": _string(minimum=0, maximum=200),
                        "observed_subject_id": _string(minimum=0, maximum=200),
                    }
                ),
                minimum=1,
                maximum=100,
            ),
            "requires_revision": {"type": "boolean"},
        }
    if kind is ProgramKind.REVISION:
        return {
            "revised_text": _string(maximum=20_000),
            "resolved_issue_codes": _string_array(minimum=1, maximum=100),
            "remaining_warning_codes": _string_array(minimum=0, maximum=100),
            "guidance_used_as_evidence": {"type": "boolean"},
        }
    if kind is ProgramKind.STYLE_JUDGE:
        return {
            "score": {"type": "number", "minimum": 0, "maximum": 5},
            "passed": {"type": "boolean"},
            "issue_codes": _string_array(minimum=0, maximum=100),
            "rationale": _string(maximum=4000),
        }
    if kind is ProgramKind.ARBITER:
        return {
            "disposition": _enum("pass", "warning", "revise"),
            "selected_candidate_id": _string(maximum=200),
            "considered_evaluators": _string_array(minimum=2, maximum=20),
            "issue_codes": _string_array(minimum=0, maximum=100),
            "rationale": _string(maximum=4000),
        }
    if kind is ProgramKind.METRIC_JUDGE:
        return {
            "results": _array(
                _strict_object(
                    {
                        "metric_id": _string(maximum=200),
                        "kind": _enum(
                            "recommendation",
                            "sentiment",
                            "fact",
                            "citation_entailment",
                            "corpus_absorption",
                        ),
                        "label": _enum(
                            "yes",
                            "no",
                            "positive",
                            "neutral",
                            "negative",
                            "accurate",
                            "conflict",
                            "omission",
                            "unknown",
                            "entailed",
                            "not_entailed",
                            "absorbed",
                            "not_absorbed",
                        ),
                        "score": {
                            "type": ["number", "null"],
                            "minimum": -1,
                            "maximum": 1,
                        },
                        "reason_codes": _string_array(minimum=0, maximum=100),
                        "evidence_refs": _string_array(minimum=1, maximum=100),
                        "evidence_locators": _array(
                            _metric_locator_schema(),
                            minimum=1,
                            maximum=100,
                        ),
                    }
                ),
                minimum=1,
                maximum=50,
            ),
            "overall_status": _enum("pass", "warning", "fail"),
        }
    if kind is ProgramKind.RECOMMENDATION:
        return {
            "recommendation_type": _enum(
                "hard_blocker",
                "gap",
                "experiment",
                "optional",
                "no_change",
                "insufficient_evidence",
            ),
            "selected_evidence": _array(
                _strict_object(
                    {
                        "kind": _enum(
                            "observation",
                            "metric_comparison",
                            "fact",
                            "rule",
                        ),
                        "resource_id": _string(maximum=500),
                    }
                ),
                minimum=1,
                maximum=100,
            ),
            "scope": _recommendation_scope_schema(),
            "decision": _recommendation_decision_schema(),
        }
    if kind is ProgramKind.STYLE_PROFILE:
        return {
            "sample_manifest_hash": _sha256(),
            "voice_traits": _string_array(
                minimum=1, maximum=12, item_maximum=200
            ),
            "lexical_patterns": _string_array(
                minimum=1, maximum=12, item_maximum=200
            ),
            "structure_patterns": _string_array(
                minimum=1, maximum=12, item_maximum=200
            ),
            "avoid_patterns": _string_array(
                minimum=0, maximum=12, item_maximum=200
            ),
        }
    if kind is ProgramKind.OFFLINE_ANSWER:
        return {
            "answer_text": _string(maximum=50_000),
            "metric_value": {"type": "number", "minimum": 0, "maximum": 1},
        }
    if kind is ProgramKind.QUESTION_GENERATION:
        return {
            "questions": _array(
                _strict_object(
                    {
                        "question_id": _string(maximum=200),
                        "text": _string(maximum=4_000),
                        "evidence_refs": _string_array(minimum=1, maximum=100),
                    }
                ),
                minimum=1,
                maximum=20,
            )
        }
    if kind is ProgramKind.RAG_GROUNDING:
        return {
            "grounded_question": _string(maximum=4_000),
            "supporting_fact_refs": _string_array(minimum=1, maximum=100),
            "unsupported_premises": _string_array(minimum=0, maximum=20),
        }
    if kind is ProgramKind.PLACEMENT_GENERATION:
        return {
            "content": _string(maximum=50_000),
            "destination_policy_applied": {"type": "boolean"},
            "destination_summary": _string(maximum=4_000),
        }
    if kind is ProgramKind.PLACEMENT_SIMULATION:
        return {
            "rendered_prompt": _string(maximum=50_000),
            "output_preview": _string(maximum=50_000),
            "warning_codes": _string_array(minimum=0, maximum=50),
        }
    raise ValueError(f"unsupported bootstrap Program kind: {kind.value}")


def _evidence_item_schema() -> dict[str, object]:
    return _strict_object(
        {
            "ref": _string(maximum=500),
            "subject_id": _string(maximum=200),
            "evidence_scope": _enum(
                "primary_subject",
                "competitor_subject",
                "cross_subject_observation",
            ),
            "summary": _string(maximum=4000),
        }
    )


def _metric_locator_schema() -> dict[str, object]:
    return _strict_object(
        {
            "kind": _enum("answer_span", "citation", "fact"),
            "reference_id": _string(maximum=500),
            "version": _nullable_string(maximum=200),
            "content_hash": _nullable_sha256(),
            "start": {"type": ["integer", "null"], "minimum": 0},
            "end": {"type": ["integer", "null"], "minimum": 1},
            "redacted_quote_hash": _nullable_sha256(),
        }
    )


def _recommendation_scope_schema() -> dict[str, object]:
    return _strict_object(
        {
            "project_id": _string(maximum=200),
            "campaign_id": _nullable_string(maximum=200),
            "question_or_cluster_ref": _nullable_string(maximum=500),
            "surface_ref": _nullable_string(maximum=500),
            "content_asset_ref": _nullable_string(maximum=500),
            "url_ref": _nullable_string(maximum=4_000),
            "applicable_version": _string(maximum=200),
        }
    )


def _context_ref_schema() -> dict[str, object]:
    return _strict_object(
        {
            "kind": _enum("question", "surface", "content"),
            "resource_id": _string(maximum=500),
            "version": _string(maximum=200),
            "hash": _sha256(),
        }
    )


def _recommendation_decision_schema() -> dict[str, object]:
    return _strict_object(
        {
            "impact_chain": _string_array(minimum=1, maximum=100),
            "risk": _string(maximum=4_000),
            "effort": _string(maximum=4_000),
            "business_value": _string(maximum=4_000),
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "counterevidence": _string_array(minimum=0, maximum=100),
            "validation_plan": _string_array(minimum=1, maximum=100),
            "stale_conditions": _string_array(minimum=1, maximum=100),
        }
    )


def _strict_object(properties: Mapping[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties),
        "additionalProperties": False,
    }


def _array(
    items: Mapping[str, object], *, minimum: int, maximum: int
) -> dict[str, object]:
    return {
        "type": "array",
        "items": dict(items),
        "minItems": minimum,
        "maxItems": maximum,
    }


def _string(*, minimum: int = 1, maximum: int) -> dict[str, object]:
    return {"type": "string", "minLength": minimum, "maxLength": maximum}


def _sha256() -> dict[str, object]:
    return {
        "type": "string",
        "minLength": 64,
        "maxLength": 64,
        "pattern": "^[0-9a-f]{64}$",
    }


def _nullable_sha256() -> dict[str, object]:
    return {
        "type": ["string", "null"],
        "minLength": 64,
        "maxLength": 64,
        "pattern": "^[0-9a-f]{64}$",
    }


def _nullable_string(*, maximum: int) -> dict[str, object]:
    return {"type": ["string", "null"], "minLength": 1, "maxLength": maximum}


def _integer(*, minimum: int, maximum: int) -> dict[str, object]:
    return {
        "type": "integer",
        "minimum": minimum,
        "maximum": maximum,
    }


def _string_array(
    *, minimum: int, maximum: int, item_maximum: int = 500
) -> dict[str, object]:
    schema = _array(
        _string(maximum=item_maximum), minimum=minimum, maximum=maximum
    )
    schema["uniqueItems"] = True
    return schema


def _enum_array(*values: str) -> dict[str, object]:
    schema = _array(_enum(*values), minimum=1, maximum=len(values))
    schema["uniqueItems"] = True
    return schema


def _enum(*values: str) -> dict[str, object]:
    return {"type": "string", "enum": list(values)}
