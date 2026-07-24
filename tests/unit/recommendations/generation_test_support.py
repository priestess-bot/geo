from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
from types import SimpleNamespace
from typing import Mapping, TypedDict, cast
from uuid import UUID, uuid4

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.application import ModelCallExecution
from geo_core.model_gateway.application_support import ExecuteModelCall
from geo_core.model_gateway.contracts import (
    ModelCaptureMethod,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.recommendations.evidence import (
    ContentRef,
    FactRef,
    MetricComparisonRef,
    ObservationEvidenceClass,
    ObservationRef,
    QuestionRef,
    RecommendationScope,
    RuleRef,
    SurfaceRef,
)
from geo_core.recommendations.generation_contracts import (
    EvidenceSummary,
    FrozenGenerationEvidence,
    FrozenPromptBinding,
    RecommendationGenerationSpec,
    ResolvedGenerationPrompt,
    ScopeLocator,
    canonical_hash,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
PROJECT_ID = UUID("20000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = UUID("30000000-0000-0000-0000-000000000003")


class MutableClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class PromptResolverStub:
    def __init__(
        self,
        *,
        stale_at: int | None = None,
        search_mode_tamper_at: int | None = None,
    ) -> None:
        self.stale_at = stale_at
        self.search_mode_tamper_at = search_mode_tamper_at
        self.calls: list[tuple[FrozenPromptBinding, Mapping[str, object]]] = []

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
    ) -> ResolvedGenerationPrompt:
        self.calls.append((binding, structured_input))
        resolved_binding = binding
        if self.stale_at is not None and len(self.calls) >= self.stale_at:
            resolved_binding = replace(binding, release_hash=_digest("stale-prompt"))
        return ResolvedGenerationPrompt(
            binding=resolved_binding,
            route=route,
            configured_model=configured_model,
            capture_method=capture_method,
            search_mode=(
                f"{search_mode}-tampered"
                if self.search_mode_tamper_at is not None
                and len(self.calls) >= self.search_mode_tamper_at
                else search_mode
            ),
            prompt_bundle_hash=_digest(
                f"{binding.release_hash}:{canonical_hash(structured_input)}"
            ),
            messages=(
                {"role": "system", "content": f"Run {binding.program_kind.value}."},
                {
                    "role": "user",
                    "content": json.dumps(structured_input, sort_keys=True, default=str),
                },
            ),
            output_schema=output_schema,
            application_output_schema=application_output_schema,
            policy=model_policy,
            structured_input_hash=canonical_hash(structured_input),
        )


class FactResolverStub:
    def __init__(self, *, stale_at: int | None = None) -> None:
        self.stale_at = stale_at
        self.calls = 0

    def current_facts(
        self,
        *,
        project_id: UUID,
        frozen_facts: tuple[FactRef, ...],
    ) -> tuple[FactRef, ...]:
        assert project_id == PROJECT_ID
        self.calls += 1
        if self.stale_at is not None and self.calls >= self.stale_at:
            return (replace(frozen_facts[0], retired=True), *frozen_facts[1:])
        return frozen_facts


class GatewayApplicationStub:
    def __init__(self, *outputs: Mapping[str, object] | Exception) -> None:
        self.outputs = list(outputs)
        self.commands: list[ExecuteModelCall] = []

    def execute(
        self,
        command: ExecuteModelCall,
        *,
        policy: ModelPolicy,
    ) -> ModelCallExecution:
        del policy
        self.commands.append(command)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        route = command.route
        result = ModelGatewayResult(
            output=dict(output),
            call_log_id=uuid4(),
            provider_request_id=f"request-{len(self.commands)}",
            configured_model=command.request.configured_model,
            provider_reported_model=command.request.configured_model,
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=None,
            finish_reason="stop",
            response_hash=_digest(json.dumps(output, sort_keys=True)),
            provider=route.provider,
            adapter_release_id=route.adapter_release_id,
            adapter_release_hash=route.adapter_release_hash,
            model_release_id=route.model_release_id,
            model_release_hash=route.model_release_hash,
        )
        return cast(ModelCallExecution, SimpleNamespace(result=result))


def generation_spec(
    *,
    real_observations: int = 3,
    minimum_real_observations: int = 3,
    with_arbiter: bool = False,
    same_arbiter_model: bool = False,
) -> RecommendationGenerationSpec:
    arbiter_binding = prompt_binding(ProgramKind.ARBITER, "arbiter") if with_arbiter else None
    arbiter_route = (
        route(
            "primary" if same_arbiter_model else "arbiter",
            provider="openai" if same_arbiter_model else "microsoft",
        )
        if with_arbiter
        else None
    )
    return RecommendationGenerationSpec(
        project_id=PROJECT_ID,
        evidence=frozen_evidence(real_observations=real_observations),
        prompt_binding=prompt_binding(ProgramKind.RECOMMENDATION, "recommendation"),
        runtime_selection_id=UUID("90000000-0000-0000-0000-000000000012"),
        runtime_manifest_id=UUID("90000000-0000-0000-0000-000000000011"),
        runtime_manifest_hash=_digest("runtime-manifest-primary"),
        runtime_option_id=UUID("90000000-0000-0000-0000-000000000012"),
        runtime_option_hash=_digest("runtime-option-primary"),
        route=route("primary", provider="openai"),
        configured_model="model-primary",
        model_policy=_policy("primary", "openai"),
        capture_method=ModelCaptureMethod.PROVIDER_API,
        search_mode="disabled",
        valid_until=NOW + timedelta(days=30),
        created_by="a0000000-0000-0000-0000-000000000001",
        minimum_real_observations=minimum_real_observations,
        arbiter_binding=arbiter_binding,
        arbiter_runtime_selection_id=(
            UUID("90000000-0000-0000-0000-000000000022") if with_arbiter else None
        ),
        arbiter_runtime_manifest_id=(
            UUID("90000000-0000-0000-0000-000000000021") if with_arbiter else None
        ),
        arbiter_runtime_manifest_hash=(
            _digest("runtime-manifest-arbiter") if with_arbiter else None
        ),
        arbiter_runtime_option_id=(
            UUID("90000000-0000-0000-0000-000000000022") if with_arbiter else None
        ),
        arbiter_runtime_option_hash=(
            _digest("runtime-option-arbiter") if with_arbiter else None
        ),
        arbiter_route=arbiter_route,
        arbiter_configured_model="model-arbiter" if with_arbiter else None,
        arbiter_model_policy=(
            _policy(
                "primary" if same_arbiter_model else "arbiter",
                "openai" if same_arbiter_model else "microsoft",
            )
            if with_arbiter
            else None
        ),
        arbiter_capture_method=(
            ModelCaptureMethod.PROVIDER_API
            if with_arbiter and same_arbiter_model
            else ModelCaptureMethod.PROXY_GROUNDED_API if with_arbiter else None
        ),
        arbiter_search_mode=(
            "disabled" if with_arbiter and same_arbiter_model else "bing_grounding"
            if with_arbiter
            else None
        ),
    )


def _policy(name: str, provider: str) -> ModelPolicy:
    return ModelPolicy(
        allowed_providers=frozenset({provider}),
        allowed_adapter_release_ids=frozenset({f"adapter-{name}"}),
    )


def frozen_evidence(*, real_observations: int = 3) -> FrozenGenerationEvidence:
    question = QuestionRef(**_base("question:1"), active=True)
    surface = SurfaceRef(**_base("surface:google-aio:r1"), active=True)
    observations = tuple(
        ObservationRef(
            **_base(f"observation:{index}"),
            capture_method="automated_ui",
            evidence_class=ObservationEvidenceClass.REAL_OBSERVATION,
            question_resource_id=question.resource_id,
            surface_resource_id=surface.resource_id,
            eligible=True,
        )
        for index in range(real_observations)
    )
    metric = MetricComparisonRef(
        **_base("comparison:1"),
        observation_resource_ids=tuple(item.resource_id for item in observations),
        method_version="comparison-method-v1",
        method_sha256=_digest("comparison-method-v1"),
        sufficient_evidence=True,
    )
    fact = FactRef(**_base("fact:1"), approved=True, retired=False)
    rule = RuleRef(**_base("rule:1"), active=True)
    core = (*observations, metric, fact, rule)
    return FrozenGenerationEvidence(
        scope=RecommendationScope(
            project_id=PROJECT_ID,
            applicable_version="recommendation-generation-v1",
            campaign_id=CAMPAIGN_ID,
            question_or_cluster_ref=question.resource_id,
            surface_ref=surface.resource_id,
            content_asset_ref="content:1",
            url_ref="url:https://example.test/au",
        ),
        observations=observations,
        metric_comparisons=(metric,),
        facts=(fact,),
        rules=(rule,),
        questions=(question,),
        surfaces=(surface,),
        contents=(ContentRef(**_base("content:1"), current=True),),
        summaries=tuple(
            EvidenceSummary(
                ref_kind=item.ref_kind,
                resource_id=item.resource_id,
                summary=f"Approved summary for {item.resource_id}",
                summary_hash=_digest(f"Approved summary for {item.resource_id}"),
            )
            for item in core
        ),
        scope_locators=tuple(
            ScopeLocator(field_name=name, resource_id=value, locator={"id": value})
            for name, value in (
                ("campaign_id", str(CAMPAIGN_ID)),
                ("question_or_cluster_ref", question.resource_id),
                ("surface_ref", surface.resource_id),
                ("content_asset_ref", "content:1"),
                ("url_ref", "url:https://example.test/au"),
            )
        ),
    )


def model_output(recommendation_type: str = "gap") -> dict[str, object]:
    evidence = frozen_evidence()
    selected = [
        {"kind": item.ref_kind, "resource_id": item.resource_id}
        for item in (
            *evidence.observations,
            *evidence.metric_comparisons,
            *evidence.facts,
            *evidence.rules,
        )
    ]
    evidence_refs = [
        f"{item['kind']}:{item['resource_id']}"
        for item in selected
    ]
    return {
        "subject_id": f"recommendation-scope:{evidence.input_hash}",
        "evidence_refs": evidence_refs,
        "citation_refs": [],
        "output_locale": "en-AU",
        "automatic_action_authorised": False,
        "injection_detected": False,
        "untrusted_instruction_followed": False,
        "recommendation_type": recommendation_type,
        "scope": evidence.scope.canonical_value(),
        "selected_evidence": selected,
        "decision": {
            "impact_chain": ["Observed omission lowers consideration"],
            "risk": "medium",
            "effort": "small",
            "business_value": "Protect qualified discovery",
            "confidence": 0.8,
            "counterevidence": ["Some uncertainty remains"],
            "validation_plan": ["Run a frozen paired experiment"],
            "stale_conditions": ["Any input identity changes"],
        },
    }


def arbiter_output(candidate: Mapping[str, object]) -> dict[str, object]:
    evidence = frozen_evidence()
    return {
        "subject_id": f"recommendation-scope:{evidence.input_hash}",
        "evidence_refs": list(cast(list[str], candidate["evidence_refs"])),
        "citation_refs": [],
        "output_locale": "en-AU",
        "automatic_action_authorised": False,
        "injection_detected": False,
        "untrusted_instruction_followed": False,
        "disposition": "pass",
        "selected_candidate_id": canonical_hash(candidate),
        "considered_evaluators": [
            "recommendation_schema_validator",
            "recommendation_evidence_validator",
        ],
        "issue_codes": [],
        "rationale": "The frozen schema and evidence checks passed.",
    }


def model_result(
    spec: RecommendationGenerationSpec,
    output: dict[str, object],
    *,
    arbiter: bool = False,
) -> ModelGatewayResult:
    selected_route = spec.arbiter_route if arbiter else spec.route
    model = spec.arbiter_configured_model if arbiter else spec.configured_model
    assert selected_route is not None and model is not None
    return ModelGatewayResult(
        output=output,
        call_log_id=uuid4(),
        provider_request_id="provider-request",
        configured_model=model,
        provider_reported_model=model,
        prompt_tokens=10,
        completion_tokens=10,
        cost_usd=None,
        finish_reason="stop",
        response_hash="f" * 64,
        provider=selected_route.provider,
        adapter_release_id=selected_route.adapter_release_id,
        adapter_release_hash=selected_route.adapter_release_hash,
        model_release_id=selected_route.model_release_id,
        model_release_hash=selected_route.model_release_hash,
        derived_artifact_reference="s3://model-artifacts/derived/manifest.json",
        derived_artifact_manifest_hash="a" * 64,
        derived_artifact_content_hash="b" * 64,
        derived_artifact_byte_size=512,
    )


def worker_lease(kind: str, *, job_id: UUID | None = None) -> WorkerLease:
    return WorkerLease(
        job_id or uuid4(),
        PROJECT_ID,
        kind,
        "recommendation-worker",
        uuid4(),
        1,
        1,
        3,
    )


def prompt_binding(kind: ProgramKind, suffix: str) -> FrozenPromptBinding:
    return FrozenPromptBinding(
        project_id=PROJECT_ID,
        binding_id=uuid4(),
        binding_version=1,
        frozen_state_id=uuid4(),
        frozen_state_version=4,
        release_id=uuid4(),
        release_version=1,
        release_hash=_digest(f"prompt:{suffix}"),
        program_kind=kind,
        purpose=(
            "synthetic_lab.arbiter"
            if kind is ProgramKind.ARBITER
            else "recommendations.recommendation"
        ),
    )


def route(suffix: str, *, provider: str) -> ModelRoute:
    return ModelRoute(
        provider=provider,
        adapter_release_id=f"adapter-{suffix}",
        adapter_release_hash=_digest(f"adapter:{suffix}"),
        model_release_id=f"model-{suffix}",
        model_release_hash=_digest(f"model:{suffix}"),
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
        "locator": {"id": resource_id},
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
