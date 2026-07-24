"""JSON codecs for frozen Recommendation generation specifications and results."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.recommendations.evidence import (
    AttributionRef,
    ContentRef,
    EvidenceRef,
    FactRef,
    MetricComparisonRef,
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
    RecommendationGenerationResult,
    RecommendationGenerationSpec,
    ScopeLocator,
)
from geo_core.recommendations.models import RecommendationWorkflow
from geo_core.recommendations.postgres.codec import (
    workflow_from_payload,
    workflow_payload,
)
from geo_core.recommendations.postgres.evidence import evidence_ref_from_payload


def generation_spec_payload(spec: RecommendationGenerationSpec) -> dict[str, object]:
    return {
        "contract_version": "recommendation-generation-spec-v3",
        "project_id": str(spec.project_id),
        "evidence": {
            "scope": spec.evidence.scope.canonical_value(),
            "refs": [item.canonical_value() for item in spec.evidence.all_refs],
            "summaries": [
                {
                    "ref_kind": item.ref_kind,
                    "resource_id": item.resource_id,
                    "summary": item.summary,
                    "summary_hash": item.summary_hash,
                }
                for item in spec.evidence.summaries
            ],
            "scope_locators": [
                {
                    "field_name": item.field_name,
                    "resource_id": item.resource_id,
                    "locator": dict(item.locator),
                }
                for item in spec.evidence.scope_locators
            ],
        },
        "prompt": _prompt_payload(spec.prompt_binding),
        "runtime_selection_id": str(spec.runtime_selection_id),
        "runtime_manifest_id": str(spec.runtime_manifest_id),
        "runtime_manifest_hash": spec.runtime_manifest_hash,
        "runtime_option_id": str(spec.runtime_option_id),
        "runtime_option_hash": spec.runtime_option_hash,
        "model": _model_payload(
            spec.route,
            spec.configured_model,
            spec.model_policy,
            spec.capture_method,
            spec.search_mode,
        ),
        "valid_until": spec.valid_until.isoformat(),
        "created_by": spec.created_by,
        "minimum_real_observations": spec.minimum_real_observations,
        "arbiter_prompt": (
            _prompt_payload(spec.arbiter_binding) if spec.arbiter_binding else None
        ),
        "arbiter_runtime_selection_id": (
            str(spec.arbiter_runtime_selection_id)
            if spec.arbiter_runtime_selection_id
            else None
        ),
        "arbiter_runtime_manifest_id": (
            str(spec.arbiter_runtime_manifest_id)
            if spec.arbiter_runtime_manifest_id
            else None
        ),
        "arbiter_runtime_manifest_hash": spec.arbiter_runtime_manifest_hash,
        "arbiter_runtime_option_id": (
            str(spec.arbiter_runtime_option_id) if spec.arbiter_runtime_option_id else None
        ),
        "arbiter_runtime_option_hash": spec.arbiter_runtime_option_hash,
        "arbiter_model": (
            _model_payload(
                spec.arbiter_route,
                spec.arbiter_configured_model,
                spec.arbiter_model_policy,
                spec.arbiter_capture_method,
                spec.arbiter_search_mode,
            )
            if spec.arbiter_route
            and spec.arbiter_configured_model
            and spec.arbiter_model_policy
            and spec.arbiter_capture_method
            else None
        ),
    }


def generation_spec_from_payload(value: object) -> RecommendationGenerationSpec:
    root = _mapping(value, "generation spec")
    project_id = UUID(_text(root, "project_id"))
    evidence = _evidence_from_payload(root.get("evidence"), project_id=project_id)
    prompt = _prompt_from_payload(root.get("prompt"), project_id=project_id)
    model = _mapping(root.get("model"), "generation model")
    route, configured, policy, capture, search = _model_from_payload(model)
    arbiter_prompt_value = root.get("arbiter_prompt")
    arbiter_model_value = root.get("arbiter_model")
    arbiter_prompt = (
        _prompt_from_payload(arbiter_prompt_value, project_id=project_id)
        if arbiter_prompt_value is not None
        else None
    )
    arbiter = (
        _model_from_payload(_mapping(arbiter_model_value, "arbiter model"))
        if arbiter_model_value is not None
        else None
    )
    return RecommendationGenerationSpec(
        project_id=project_id,
        evidence=evidence,
        prompt_binding=prompt,
        runtime_selection_id=UUID(_text(root, "runtime_selection_id")),
        runtime_manifest_id=UUID(_text(root, "runtime_manifest_id")),
        runtime_manifest_hash=_text(root, "runtime_manifest_hash"),
        runtime_option_id=UUID(_text(root, "runtime_option_id")),
        runtime_option_hash=_text(root, "runtime_option_hash"),
        route=route,
        configured_model=configured,
        model_policy=policy,
        capture_method=capture,
        search_mode=search,
        valid_until=datetime.fromisoformat(_text(root, "valid_until")),
        created_by=_text(root, "created_by"),
        minimum_real_observations=_integer(root, "minimum_real_observations"),
        arbiter_binding=arbiter_prompt,
        arbiter_runtime_selection_id=_optional_uuid(
            root.get("arbiter_runtime_selection_id")
        ),
        arbiter_runtime_manifest_id=_optional_uuid(
            root.get("arbiter_runtime_manifest_id")
        ),
        arbiter_runtime_manifest_hash=_optional_text(
            root.get("arbiter_runtime_manifest_hash")
        ),
        arbiter_runtime_option_id=_optional_uuid(root.get("arbiter_runtime_option_id")),
        arbiter_runtime_option_hash=_optional_text(root.get("arbiter_runtime_option_hash")),
        arbiter_route=arbiter[0] if arbiter else None,
        arbiter_configured_model=arbiter[1] if arbiter else None,
        arbiter_model_policy=arbiter[2] if arbiter else None,
        arbiter_capture_method=arbiter[3] if arbiter else None,
        arbiter_search_mode=arbiter[4] if arbiter else None,
    )


def generation_result_payload(
    result: RecommendationGenerationResult,
) -> dict[str, object]:
    return {
        "contract_version": "recommendation-generation-result-v1",
        "workflow": workflow_payload(RecommendationWorkflow(result.recommendation)),
        "model_call_ids": [str(value) for value in result.model_call_ids],
        "insufficient_reasons": list(result.insufficient_reasons),
    }


def generation_result_from_payload(value: object) -> RecommendationGenerationResult:
    root = _mapping(value, "generation result")
    workflow = workflow_from_payload(root.get("workflow"))
    return RecommendationGenerationResult(
        recommendation=workflow.recommendation,
        model_call_ids=tuple(
            UUID(str(item))
            for item in _sequence(root.get("model_call_ids"), "model call IDs")
        ),
        insufficient_reasons=tuple(
            str(item)
            for item in _sequence(root.get("insufficient_reasons"), "insufficient reasons")
        ),
    )


def _evidence_from_payload(
    value: object, *, project_id: UUID
) -> FrozenGenerationEvidence:
    root = _mapping(value, "generation evidence")
    scope_value = _mapping(root.get("scope"), "generation scope")
    scope = RecommendationScope(
        project_id=project_id,
        applicable_version=_text(scope_value, "applicable_version"),
        campaign_id=_optional_uuid(scope_value.get("campaign_id")),
        question_or_cluster_ref=_optional_text(scope_value.get("question_or_cluster_ref")),
        surface_ref=_optional_text(scope_value.get("surface_ref")),
        content_asset_ref=_optional_text(scope_value.get("content_asset_ref")),
        url_ref=_optional_text(scope_value.get("url_ref")),
    )
    refs = tuple(
        evidence_ref_from_payload(_mapping(item, "generation evidence ref"))
        for item in _sequence(root.get("refs"), "generation evidence refs")
    )
    summaries = tuple(
        EvidenceSummary(
            ref_kind=_text(item, "ref_kind"),
            resource_id=_text(item, "resource_id"),
            summary=_text(item, "summary"),
            summary_hash=_text(item, "summary_hash"),
        )
        for item in (
            _mapping(value, "generation summary")
            for value in _sequence(root.get("summaries"), "generation summaries")
        )
    )
    locators = tuple(
        ScopeLocator(
            field_name=_text(item, "field_name"),
            resource_id=_text(item, "resource_id"),
            locator=_string_mapping(item.get("locator")),
        )
        for item in (
            _mapping(value, "scope locator")
            for value in _sequence(root.get("scope_locators"), "scope locators")
        )
    )
    return FrozenGenerationEvidence(
        scope=scope,
        observations=_typed(refs, ObservationRef),
        metric_comparisons=_typed(refs, MetricComparisonRef),
        facts=_typed(refs, FactRef),
        rules=_typed(refs, RuleRef),
        questions=_typed(refs, QuestionRef),
        surfaces=_typed(refs, SurfaceRef),
        contents=_typed(refs, ContentRef),
        summaries=summaries,
        scope_locators=locators,
        attributions=_typed(refs, AttributionRef),
    )


def _prompt_payload(item: FrozenPromptBinding) -> dict[str, object]:
    return {
        "project_id": str(item.project_id),
        "binding_id": str(item.binding_id),
        "binding_version": item.binding_version,
        "frozen_state_id": str(item.frozen_state_id),
        "frozen_state_version": item.frozen_state_version,
        "release_id": str(item.release_id),
        "release_version": item.release_version,
        "release_hash": item.release_hash,
        "program_kind": item.program_kind.value,
        "purpose": item.purpose,
    }


def _prompt_from_payload(value: object, *, project_id: UUID) -> FrozenPromptBinding:
    item = _mapping(value, "generation Prompt")
    if UUID(_text(item, "project_id")) != project_id:
        raise ValueError("generation Prompt crosses Project scope")
    return FrozenPromptBinding(
        project_id=project_id,
        binding_id=UUID(_text(item, "binding_id")),
        binding_version=_integer(item, "binding_version"),
        frozen_state_id=UUID(_text(item, "frozen_state_id")),
        frozen_state_version=_integer(item, "frozen_state_version"),
        release_id=UUID(_text(item, "release_id")),
        release_version=_integer(item, "release_version"),
        release_hash=_text(item, "release_hash"),
        program_kind=ProgramKind(_text(item, "program_kind")),
        purpose=_text(item, "purpose"),
    )


def _model_payload(
    route: ModelRoute,
    configured_model: str,
    policy: ModelPolicy,
    capture_method: ModelCaptureMethod,
    search_mode: str | None,
) -> dict[str, object]:
    return {
        "provider": route.provider,
        "adapter_release_id": route.adapter_release_id,
        "adapter_release_hash": route.adapter_release_hash,
        "model_release_id": route.model_release_id,
        "model_release_hash": route.model_release_hash,
        "configured_model": configured_model,
        "policy": {
            **policy.canonical_value(),
            "policy_version_id": (
                str(policy.policy_version_id) if policy.policy_version_id else None
            ),
            "policy_version_hash": policy.policy_version_hash,
        },
        "capture_method": capture_method.value,
        "search_mode": search_mode,
    }


def _model_from_payload(
    item: Mapping[str, Any],
) -> tuple[ModelRoute, str, ModelPolicy, ModelCaptureMethod, str | None]:
    route = ModelRoute(
        provider=_text(item, "provider"),
        adapter_release_id=_text(item, "adapter_release_id"),
        adapter_release_hash=_text(item, "adapter_release_hash"),
        model_release_id=_text(item, "model_release_id"),
        model_release_hash=_text(item, "model_release_hash"),
    )
    policy_value = _mapping(item.get("policy"), "generation model policy")
    policy = ModelPolicy(
        external_training_allowed=_boolean(policy_value, "external_training_allowed"),
        structured_output_required=_boolean(policy_value, "structured_output_required"),
        allowed_providers=_optional_set(policy_value.get("allowed_providers")),
        allowed_adapter_release_ids=_optional_set(
            policy_value.get("allowed_adapter_release_ids")
        ),
        policy_version_id=_optional_uuid(policy_value.get("policy_version_id")),
        maximum_paid_calls=_optional_integer(policy_value.get("maximum_paid_calls")),
        maximum_concurrent_calls=_optional_integer(
            policy_value.get("maximum_concurrent_calls")
        ),
    )
    if policy.policy_version_hash != policy_value.get("policy_version_hash"):
        raise ValueError("generation model policy hash changed")
    return (
        route,
        _text(item, "configured_model"),
        policy,
        ModelCaptureMethod(_text(item, "capture_method")),
        _optional_text(item.get("search_mode")),
    )


_EvidenceT = TypeVar("_EvidenceT", bound=EvidenceRef)


def _typed(
    values: tuple[EvidenceRef, ...], expected: type[_EvidenceT]
) -> tuple[_EvidenceT, ...]:
    return tuple(item for item in values if isinstance(item, expected))


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be an array")
    return tuple(value)


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be text")
    return item.strip()


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{key} must be an integer")
    return item


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("optional integer is invalid")
    return value


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"{key} must be boolean")
    return item


def _optional_uuid(value: object) -> UUID | None:
    return UUID(str(value)) if value is not None else None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional text is invalid")
    return value


def _optional_set(value: object) -> frozenset[str] | None:
    if value is None:
        return None
    return frozenset(str(item) for item in _sequence(value, "model policy allowlist"))


def _string_mapping(value: object) -> dict[str, str]:
    item = _mapping(value, "locator")
    if not all(isinstance(key, str) and isinstance(entry, str) for key, entry in item.items()):
        raise ValueError("locator must contain text values")
    return {str(key): str(entry) for key, entry in item.items()}


__all__ = [
    "generation_result_from_payload",
    "generation_result_payload",
    "generation_spec_from_payload",
    "generation_spec_payload",
]
