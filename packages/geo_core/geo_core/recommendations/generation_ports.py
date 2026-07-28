"""Persistence, Prompt, Fact and Model Gateway ports for generation Jobs."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import json
import re
from types import MappingProxyType
from geo_core.recommendations.decision import RecommendationDecision
from geo_core.recommendations.evidence import RecommendationScope
from geo_core.recommendations.generation_contracts import (
    EvidenceSummary,
    FrozenGenerationEvidence,
    RecommendationGenerationOutputError,
    canonical_hash,
)
from geo_core.recommendations.generation_evidence import (
    GENERATION_EVIDENCE_CONTRACT_V1,
)
from geo_core.recommendations.generation_interfaces import (
    ModelGatewayApplicationPort as ModelGatewayApplicationPort,
    ParsedRecommendationOutput,
    RecommendationFactResolverPort as RecommendationFactResolverPort,
    RecommendationGenerationRepositoryPort as RecommendationGenerationRepositoryPort,
    RecommendationPromptResolverPort as RecommendationPromptResolverPort,
    SelectedRecommendationRef,
)
from geo_core.recommendations.models import RecommendationType
from geo_core.recommendations.type_admission import resolve_recommendation_type
from geo_core.workflow_runtime.contracts import canonical_json_value
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_schemas import (
    bootstrap_application_output_schema,
    provider_portable_output_schema,
)
from geo_core.prompts.bootstrap_validation import validate_bootstrap_output
from geo_core.prompts.recommendation_numeric_grounding import (
    invented_recommendation_numeric_literals,
)
from geo_core.prompts.bootstrap_validation_errors import PromptOutputRuleViolation
from geo_core.prompts.program_contracts import ProgramKind


_CORE_KINDS = frozenset({"observation", "metric_comparison", "fact", "rule"})
_LEGACY_NUMERIC_CLAIM = re.compile(r"(?<![A-Za-z])\d")
RECOMMENDATION_DIFY_CONTEXT_MAX_BYTES = 100_000
_GOVERNANCE_OUTPUT_FIELDS = frozenset(
    {
        "subject_id",
        "evidence_refs",
        "citation_refs",
        "output_locale",
        "automatic_action_authorised",
        "injection_detected",
        "untrusted_instruction_followed",
    }
)


RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA: Mapping[str, object] = MappingProxyType(
    bootstrap_application_output_schema(ProgramKind.RECOMMENDATION)
)
RECOMMENDATION_OUTPUT_SCHEMA: Mapping[str, object] = MappingProxyType(
    provider_portable_output_schema(RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA)
)
ARBITER_APPLICATION_OUTPUT_SCHEMA: Mapping[str, object] = MappingProxyType(
    bootstrap_application_output_schema(ProgramKind.ARBITER)
)
ARBITER_OUTPUT_SCHEMA: Mapping[str, object] = MappingProxyType(
    provider_portable_output_schema(ARBITER_APPLICATION_OUTPUT_SCHEMA)
)


def structured_generation_input(
    evidence: FrozenGenerationEvidence,
    *,
    minimum_real_observations: int = 3,
) -> Mapping[str, object]:
    summaries = {item.identity: item for item in evidence.summaries}
    core = tuple(
        _common_evidence(ref, summary=summaries[ref.identity], evidence=evidence)
        for ref in (
            *evidence.observations,
            *evidence.metric_comparisons,
            *evidence.facts,
            *evidence.rules,
        )
    )
    context = tuple(
        _context_ref(ref) for ref in (*evidence.questions, *evidence.surfaces, *evidence.contents)
    )
    legacy = evidence.contract_version == GENERATION_EVIDENCE_CONTRACT_V1
    payload: dict[str, object] = {
        "subject_id": _subject_id(evidence),
        "allowed_subject_ids": [_subject_id(evidence)],
        "evidence": list(core),
        "output_locale": "en-AU",
        "untrusted_text": "",
        "prompt_injection_present": False,
        "scope": evidence.scope.canonical_value(),
        "context_refs": list(context),
        "allowed_recommendation_types": (
            [item.value for item in RecommendationType]
            if legacy
            else [
                resolve_recommendation_type(
                    evidence,
                    minimum_real_observations=minimum_real_observations,
                ).resolved_type.value
            ]
        ),
    }
    if not legacy:
        type_admission = resolve_recommendation_type(
            evidence,
            minimum_real_observations=minimum_real_observations,
        )
        payload["type_admission_json"] = _canonical_json(
            type_admission.canonical_value()
        )
    return payload


def recommendation_context_size_bytes(context: Mapping[str, object]) -> int:
    """Return the bytes sent in Dify's geo_context_json variable."""

    try:
        rendered = json.dumps(
            canonical_json_value(context),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise RecommendationGenerationOutputError(
            "Recommendation context is not valid JSON"
        ) from error
    return len(rendered.encode("utf-8"))


def parse_recommendation_output(
    output: Mapping[str, object],
    *,
    evidence: FrozenGenerationEvidence,
    minimum_real_observations: int = 3,
) -> ParsedRecommendationOutput:
    legacy = evidence.contract_version == GENERATION_EVIDENCE_CONTRACT_V1
    if not legacy:
        try:
            validate_bootstrap_output(
                default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION),
                input_value=structured_generation_input(
                    evidence,
                    minimum_real_observations=minimum_real_observations,
                ),
                output=output,
            )
        except PromptOutputRuleViolation as error:
            raise RecommendationGenerationOutputError(
                f"Recommendation output failed its frozen semantic contract: {error}"
            ) from error
    _exact_keys(
        output,
        {
            *_GOVERNANCE_OUTPUT_FIELDS,
            "recommendation_type",
            "selected_evidence",
            "scope",
            "decision",
        },
        "output",
    )
    evidence_refs = _governance_output(output, evidence=evidence)
    try:
        raw_type = output["recommendation_type"]
        if not isinstance(raw_type, str):
            raise TypeError
        recommendation_type = RecommendationType(raw_type)
    except (KeyError, ValueError, TypeError) as error:
        raise RecommendationGenerationOutputError("unknown recommendation type") from error
    if not legacy:
        type_admission = resolve_recommendation_type(
            evidence,
            minimum_real_observations=minimum_real_observations,
        )
        if recommendation_type is not type_admission.resolved_type:
            raise RecommendationGenerationOutputError(
                "recommendation type differs from deterministic evidence admission"
            )
    selected = _parse_refs(output.get("selected_evidence"), evidence)
    selected_tokens = tuple(_selected_token(item) for item in selected)
    if selected_tokens != evidence_refs:
        raise RecommendationGenerationOutputError(
            "selected evidence differs from common evidence_refs"
        )
    selected_identities = {(item.kind, item.resource_id) for item in selected}
    grounded_numeric_summaries = tuple(
        item.summary
        for item in evidence.summaries
        if item.identity in selected_identities
    )
    return ParsedRecommendationOutput(
        recommendation_type,
        _parse_scope(output.get("scope"), evidence),
        selected,
        _parse_decision(
            output.get("decision"),
            reject_all_numeric=legacy,
            grounded_numeric_summaries=(
                None if legacy else grounded_numeric_summaries
            ),
        ),
    )


def structured_arbiter_input(
    candidate: Mapping[str, object],
    *,
    evidence: FrozenGenerationEvidence,
    minimum_real_observations: int = 3,
) -> Mapping[str, object]:
    parse_recommendation_output(
        candidate,
        evidence=evidence,
        minimum_real_observations=minimum_real_observations,
    )
    selected = _output_evidence_refs(candidate, evidence=evidence)
    legacy = evidence.contract_version == GENERATION_EVIDENCE_CONTRACT_V1
    evaluators = (
        (
            "recommendation_schema_validator",
            "recommendation_evidence_validator",
        )
        if legacy
        else (
            "recommendation_schema_validator",
            "recommendation_evidence_validator",
            "recommendation_type_validator",
        )
    )
    summaries = {item.identity: item for item in evidence.summaries}
    by_token = {
        _evidence_token(item.ref_kind, item.resource_id): item
        for item in (
            *evidence.observations,
            *evidence.metric_comparisons,
            *evidence.facts,
            *evidence.rules,
        )
    }
    candidate_id = canonical_hash(candidate)
    payload: dict[str, object] = {
        "subject_id": _subject_id(evidence),
        "allowed_subject_ids": [_subject_id(evidence)],
        "evidence": [
            _common_evidence(
                by_token[token],
                summary=summaries[by_token[token].identity],
                evidence=evidence,
            )
            for token in selected
        ],
        "output_locale": "en-AU",
        "untrusted_text": "",
        "prompt_injection_present": False,
        "candidate_ids": [candidate_id],
        "evaluator_results": [
            {
                "evaluator": evaluator,
                "candidate_id": candidate_id,
                "disposition": "pass",
                "issue_codes": [],
                "evidence_refs": list(selected),
            }
            for evaluator in evaluators
        ],
    }
    if not legacy:
        type_admission = resolve_recommendation_type(
            evidence,
            minimum_real_observations=minimum_real_observations,
        )
        payload["candidate_payloads"] = [
            {
                "candidate_id": candidate_id,
                "payload_json": _canonical_json(candidate),
            }
        ]
        payload["arbiter_context_json"] = _canonical_json(
            type_admission.canonical_value()
        )
    return payload


def validated_recommendation_evidence_refs(
    output: Mapping[str, object],
    *,
    evidence: FrozenGenerationEvidence,
) -> tuple[str, ...]:
    """Expose the already-governed composite refs for arbiter lineage."""

    return _output_evidence_refs(output, evidence=evidence)


def require_arbiter_acceptance(
    output: Mapping[str, object],
    *,
    evidence: FrozenGenerationEvidence,
    candidate_id: str,
    evidence_refs: tuple[str, ...],
) -> None:
    _exact_keys(
        output,
        {
            *_GOVERNANCE_OUTPUT_FIELDS,
            "disposition",
            "selected_candidate_id",
            "considered_evaluators",
            "issue_codes",
            "rationale",
        },
        "arbiter output",
    )
    observed_refs = _governance_output(output, evidence=evidence)
    if observed_refs != evidence_refs:
        raise RecommendationGenerationOutputError("arbiter evidence lineage changed")
    if output.get("selected_candidate_id") != candidate_id:
        raise RecommendationGenerationOutputError("arbiter selected another candidate")
    considered = _strings(
        output.get("considered_evaluators"),
        "considered evaluators",
        required=True,
    )
    legacy = evidence.contract_version == GENERATION_EVIDENCE_CONTRACT_V1
    expected_evaluators = (
        (
            "recommendation_schema_validator",
            "recommendation_evidence_validator",
        )
        if legacy
        else (
            "recommendation_schema_validator",
            "recommendation_evidence_validator",
            "recommendation_type_validator",
        )
    )
    coverage_changed = (
        considered != expected_evaluators
        if legacy
        else len(considered) != len(expected_evaluators)
        or set(considered) != set(expected_evaluators)
    )
    if coverage_changed:
        raise RecommendationGenerationOutputError("arbiter evaluator coverage changed")
    _strings(output.get("issue_codes"), "arbiter issue codes")
    _string(output.get("rationale"), "arbiter rationale")
    if output.get("disposition") not in {"pass", "warning"}:
        raise RecommendationGenerationOutputError("arbiter rejected Recommendation output")


def _parse_scope(value: object, evidence: FrozenGenerationEvidence) -> RecommendationScope:
    if not isinstance(value, Mapping):
        raise RecommendationGenerationOutputError("model scope must be an object")
    expected = evidence.scope.canonical_value()
    _exact_keys(value, set(expected), "scope")
    if dict(value) != expected:
        raise RecommendationGenerationOutputError("model scope differs from frozen scope")
    return evidence.scope


def _parse_refs(
    value: object,
    evidence: FrozenGenerationEvidence,
) -> tuple[SelectedRecommendationRef, ...]:
    if not isinstance(value, list) or not value:
        raise RecommendationGenerationOutputError("selected_evidence must be a non-empty list")
    allowed = {
        item.identity
        for item in (
            *evidence.observations,
            *evidence.metric_comparisons,
            *evidence.facts,
            *evidence.rules,
        )
        if item.locator
    }
    selected: list[SelectedRecommendationRef] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise RecommendationGenerationOutputError("selected evidence must be an object")
        _exact_keys(raw, {"kind", "resource_id"}, "evidence ref")
        kind, resource_id = raw["kind"], raw["resource_id"]
        if not isinstance(kind, str) or not isinstance(resource_id, str):
            raise RecommendationGenerationOutputError("selected evidence identity is invalid")
        if kind not in _CORE_KINDS or (kind, resource_id) not in allowed:
            raise RecommendationGenerationOutputError("model invented an evidence ref")
        selected.append(SelectedRecommendationRef(kind, resource_id))
    result = tuple(selected)
    if len({(item.kind, item.resource_id) for item in result}) != len(result):
        raise RecommendationGenerationOutputError("model repeated an evidence ref")
    return result


def _parse_decision(
    value: object,
    *,
    reject_all_numeric: bool = False,
    grounded_numeric_summaries: tuple[str, ...] | None = None,
) -> RecommendationDecision:
    if not isinstance(value, Mapping):
        raise RecommendationGenerationOutputError("model decision must be an object")
    fields = {
        "impact_chain",
        "risk",
        "effort",
        "business_value",
        "confidence",
        "counterevidence",
        "validation_plan",
        "stale_conditions",
    }
    _exact_keys(value, fields, "decision")
    texts = {
        "impact_chain": _strings(value["impact_chain"], "impact_chain", required=True),
        "counterevidence": _strings(value["counterevidence"], "counterevidence"),
        "validation_plan": _strings(value["validation_plan"], "validation_plan", required=True),
        "stale_conditions": _strings(value["stale_conditions"], "stale_conditions", required=True),
    }
    scalar = {name: _string(value[name], name) for name in ("risk", "effort", "business_value")}
    if reject_all_numeric:
        for item in (*texts.values(), *scalar.values()):
            values = item if isinstance(item, tuple) else (item,)
            if any(_LEGACY_NUMERIC_CLAIM.search(text) for text in values):
                raise RecommendationGenerationOutputError("model invented a numeric claim")
    elif grounded_numeric_summaries is not None:
        decision_texts = tuple(
            text
            for item in (*texts.values(), *scalar.values())
            for text in (item if isinstance(item, tuple) else (item,))
        )
        if invented_recommendation_numeric_literals(
            evidence_texts=grounded_numeric_summaries,
            decision_texts=decision_texts,
        ):
            raise RecommendationGenerationOutputError(
                "recommendation numeric values must be copied verbatim from selected evidence"
            )
    try:
        if isinstance(value["confidence"], bool):
            raise InvalidOperation
        confidence = Decimal(str(value["confidence"]))
    except (InvalidOperation, ValueError) as error:
        raise RecommendationGenerationOutputError("model confidence is invalid") from error
    return RecommendationDecision(
        impact_chain=texts["impact_chain"],
        risk=scalar["risk"],
        effort=scalar["effort"],
        business_value=scalar["business_value"],
        confidence=confidence,
        counterevidence=texts["counterevidence"],
        validation_plan=texts["validation_plan"],
        stale_conditions=texts["stale_conditions"],
    )


def _context_ref(ref: object) -> Mapping[str, object]:
    value = ref.canonical_value()  # type: ignore[attr-defined]
    return {
        "kind": value["kind"],
        "resource_id": value["resource_id"],
        "version": value["version"],
        "hash": value["sha256"],
    }


def _common_evidence(
    ref: object,
    *,
    summary: EvidenceSummary,
    evidence: FrozenGenerationEvidence,
) -> Mapping[str, object]:
    value = ref.canonical_value()  # type: ignore[attr-defined]
    return {
        "ref": _evidence_token(str(value["kind"]), str(value["resource_id"])),
        "subject_id": _subject_id(evidence),
        "evidence_scope": "primary_subject",
        "summary": summary.summary[:4000],
    }


def _governance_output(
    output: Mapping[str, object],
    *,
    evidence: FrozenGenerationEvidence,
) -> tuple[str, ...]:
    if output.get("subject_id") != _subject_id(evidence):
        raise RecommendationGenerationOutputError("model subject differs from frozen scope")
    if output.get("output_locale") != "en-AU":
        raise RecommendationGenerationOutputError("model output locale changed")
    for field_name in (
        "automatic_action_authorised",
        "injection_detected",
        "untrusted_instruction_followed",
    ):
        if output.get(field_name) is not False:
            raise RecommendationGenerationOutputError(
                f"model governance field {field_name} must be false"
            )
    refs = _output_evidence_refs(output, evidence=evidence)
    citations = _strings(output.get("citation_refs"), "citation refs")
    if len(set(citations)) != len(citations) or not set(citations).issubset(refs):
        raise RecommendationGenerationOutputError(
            "model citation refs differ from selected evidence"
        )
    return refs


def _output_evidence_refs(
    output: Mapping[str, object],
    *,
    evidence: FrozenGenerationEvidence,
) -> tuple[str, ...]:
    refs = _strings(output.get("evidence_refs"), "evidence refs", required=True)
    allowed = {
        _evidence_token(item.ref_kind, item.resource_id)
        for item in (
            *evidence.observations,
            *evidence.metric_comparisons,
            *evidence.facts,
            *evidence.rules,
        )
        if item.locator
    }
    if len(set(refs)) != len(refs) or not set(refs).issubset(allowed):
        raise RecommendationGenerationOutputError("model invented an evidence ref")
    return refs


def _selected_token(value: SelectedRecommendationRef) -> str:
    return _evidence_token(value.kind, value.resource_id)


def _evidence_token(kind: str, resource_id: str) -> str:
    token = f"{kind}:{resource_id}"
    if len(token) > 500:
        raise RecommendationGenerationOutputError("evidence ref token is too long")
    return token


def _subject_id(evidence: FrozenGenerationEvidence) -> str:
    return f"recommendation-scope:{evidence.input_hash}"


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise RecommendationGenerationOutputError(
            "Recommendation payload is not canonical JSON"
        ) from error


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise RecommendationGenerationOutputError(f"{label} fields do not match schema")


def _strings(value: object, label: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RecommendationGenerationOutputError(f"{label} must be a string list")
    result = tuple(_string(item, label) for item in value)
    if required and not result:
        raise RecommendationGenerationOutputError(f"{label} is required")
    return result


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecommendationGenerationOutputError(f"{label} must be non-empty text")
    return value.strip()
