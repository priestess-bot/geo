"""Persistence, Prompt, Fact and Model Gateway ports for generation Jobs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from geo_core.model_gateway.application import ModelCallExecution
from geo_core.model_gateway.application_support import ExecuteModelCall
from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.recommendations.decision import RecommendationDecision
from geo_core.recommendations.evidence import FactRef
from geo_core.recommendations.generation_contracts import (
    EvidenceSummary,
    FrozenGenerationEvidence,
    FrozenPromptBinding,
    GenerationJobOwnership,
    GenerationJobStatus,
    RecommendationGenerationJob,
    RecommendationGenerationOutputError,
    RecommendationGenerationResult,
    RecommendationGenerationSpec,
    ResolvedGenerationPrompt,
    canonical_hash,
)
from geo_core.recommendations.models import RecommendationType
from geo_core.recommendations.evidence import RecommendationScope
from geo_core.prompts.bootstrap_schemas import (
    bootstrap_application_output_schema,
    provider_portable_output_schema,
)
from geo_core.prompts.program_contracts import ProgramKind


_NUMERIC_CLAIM = re.compile(r"(?<![A-Za-z])\d")
_CORE_KINDS = frozenset({"observation", "metric_comparison", "fact", "rule"})
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


@dataclass(frozen=True)
class SelectedRecommendationRef:
    kind: str
    resource_id: str


@dataclass(frozen=True)
class ParsedRecommendationOutput:
    recommendation_type: RecommendationType
    scope: RecommendationScope
    selected_refs: tuple[SelectedRecommendationRef, ...]
    decision: RecommendationDecision


class RecommendationPromptResolverPort(Protocol):
    """Render one exact current binding; stale bindings must fail closed."""

    def resolve(
        self,
        *,
        binding: FrozenPromptBinding,
        route: ModelRoute,
        configured_model: str,
        model_policy: ModelPolicy,
        capture_method: ModelCaptureMethod,
        search_mode: str | None,
        structured_input: Mapping[str, object],
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> ResolvedGenerationPrompt: ...


class RecommendationFactResolverPort(Protocol):
    def current_facts(
        self,
        *,
        project_id: UUID,
        frozen_facts: tuple[FactRef, ...],
    ) -> tuple[FactRef, ...]: ...


class ModelGatewayApplicationPort(Protocol):
    """Structural match for ModelCallApplication; no raw provider adapter is accepted."""

    def execute(
        self,
        command: ExecuteModelCall,
        *,
        policy: ModelPolicy,
    ) -> ModelCallExecution: ...


class RecommendationGenerationRepositoryPort(Protocol):
    def create_job(
        self,
        *,
        job_id: UUID,
        spec: RecommendationGenerationSpec,
        idempotency_key_hash: str,
    ) -> tuple[RecommendationGenerationJob, bool]: ...

    def claim_job(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> RecommendationGenerationJob: ...

    def get_job(
        self, *, project_id: UUID, job_id: UUID
    ) -> RecommendationGenerationJob: ...

    def request_cancel(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        expected_version: int | None = None,
        idempotency_key_hash: str | None = None,
    ) -> RecommendationGenerationJob: ...

    def require_owned(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
        now: datetime,
    ) -> RecommendationGenerationJob: ...

    def reserve_model_call(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
        now: datetime,
    ) -> RecommendationGenerationJob: ...

    def finish_job(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
        now: datetime,
        status: GenerationJobStatus,
        expected_input_hash: str,
        result: RecommendationGenerationResult | None,
        error_code: str | None,
    ) -> RecommendationGenerationJob: ...

    def result(
        self, *, project_id: UUID, job_id: UUID
    ) -> RecommendationGenerationResult | None: ...


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


def structured_generation_input(evidence: FrozenGenerationEvidence) -> Mapping[str, object]:
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
        _context_ref(ref)
        for ref in (*evidence.questions, *evidence.surfaces, *evidence.contents)
    )
    return {
        "subject_id": _subject_id(evidence),
        "allowed_subject_ids": [_subject_id(evidence)],
        "evidence": list(core),
        "output_locale": "en-AU",
        "untrusted_text": "",
        "prompt_injection_present": False,
        "scope": evidence.scope.canonical_value(),
        "context_refs": list(context),
        "allowed_recommendation_types": [item.value for item in RecommendationType],
    }


def parse_recommendation_output(
    output: Mapping[str, object],
    *,
    evidence: FrozenGenerationEvidence,
) -> ParsedRecommendationOutput:
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
    selected = _parse_refs(output.get("selected_evidence"), evidence)
    selected_tokens = tuple(_selected_token(item) for item in selected)
    if selected_tokens != evidence_refs:
        raise RecommendationGenerationOutputError(
            "selected evidence differs from common evidence_refs"
        )
    return ParsedRecommendationOutput(
        recommendation_type,
        _parse_scope(output.get("scope"), evidence),
        selected,
        _parse_decision(output.get("decision")),
    )


def structured_arbiter_input(
    candidate: Mapping[str, object],
    *,
    evidence: FrozenGenerationEvidence,
) -> Mapping[str, object]:
    selected = _output_evidence_refs(candidate, evidence=evidence)
    evaluators = ("recommendation_schema_validator", "recommendation_evidence_validator")
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
    return {
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
    if considered != (
        "recommendation_schema_validator",
        "recommendation_evidence_validator",
    ):
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


def _parse_decision(value: object) -> RecommendationDecision:
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
    for item in (*texts.values(), *scalar.values()):
        values = item if isinstance(item, tuple) else (item,)
        if any(_NUMERIC_CLAIM.search(text) for text in values):
            raise RecommendationGenerationOutputError("model invented a numeric claim")
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
