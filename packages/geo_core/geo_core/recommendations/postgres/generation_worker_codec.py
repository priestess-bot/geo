"""Strict JSON codecs for durable Recommendation model-child records."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from geo_core.model_gateway import (
    EffectiveModelLocation,
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayResult,
    ModelPolicy,
    RequestedModelLocation,
)
from geo_core.model_gateway.location import ModelLocationControl
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.recommendations.generation_contracts import (
    FrozenPromptBinding,
    ResolvedGenerationPrompt,
    canonical_hash,
)
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationExecutionBackend,
    RecommendationModelRole,
    RecommendationModelTask,
)


def model_task_payload(task: RecommendationModelTask) -> dict[str, object]:
    return {
        "contract_version": "recommendation-model-task-v3",
        "child_job_id": str(task.child_job_id),
        "parent_job_id": str(task.parent_job_id),
        "project_id": str(task.project_id),
        "parent_input_hash": task.parent_input_hash,
        "role": task.role.value,
        "execution_backend": task.execution_backend.value,
        "structured_input": dict(task.structured_input),
        "workflow_release_id": (
            str(task.workflow_release_id) if task.workflow_release_id is not None else None
        ),
        "workflow_release_hash": task.workflow_release_hash,
        "runtime_selection_id": str(task.runtime_selection_id),
        "runtime_manifest_id": str(task.runtime_manifest_id),
        "runtime_manifest_hash": task.runtime_manifest_hash,
        "runtime_option_id": str(task.runtime_option_id),
        "runtime_option_hash": task.runtime_option_hash,
        "prompt": resolved_prompt_payload(task.prompt),
        "admitted_by": str(task.admitted_by),
        "artifact_expires_at": task.artifact_expires_at.isoformat(),
    }


def model_task_from_payload(value: object) -> RecommendationModelTask:
    root = _mapping(value, "Recommendation model task")
    contract_version = root.get("contract_version")
    if contract_version not in {
        "recommendation-model-task-v2",
        "recommendation-model-task-v3",
    }:
        raise ValueError("unsupported Recommendation payload contract: recommendation-model-task-v3")
    legacy = contract_version == "recommendation-model-task-v2"
    return RecommendationModelTask(
        child_job_id=_uuid(root, "child_job_id"),
        parent_job_id=_uuid(root, "parent_job_id"),
        project_id=_uuid(root, "project_id"),
        parent_input_hash=_text(root, "parent_input_hash"),
        role=RecommendationModelRole(_text(root, "role")),
        execution_backend=(
            RecommendationExecutionBackend.MODEL_GATEWAY
            if legacy
            else RecommendationExecutionBackend(_text(root, "execution_backend"))
        ),
        structured_input=(
            {}
            if legacy
            else dict(_mapping(root.get("structured_input"), "structured input"))
        ),
        workflow_release_id=(
            None if legacy else _optional_uuid(root.get("workflow_release_id"))
        ),
        workflow_release_hash=(
            None if legacy else _optional_text(root.get("workflow_release_hash"))
        ),
        runtime_selection_id=_uuid(root, "runtime_selection_id"),
        runtime_manifest_id=_uuid(root, "runtime_manifest_id"),
        runtime_manifest_hash=_text(root, "runtime_manifest_hash"),
        runtime_option_id=_uuid(root, "runtime_option_id"),
        runtime_option_hash=_text(root, "runtime_option_hash"),
        prompt=resolved_prompt_from_payload(root.get("prompt")),
        admitted_by=_uuid(root, "admitted_by"),
        artifact_expires_at=datetime.fromisoformat(_text(root, "artifact_expires_at")),
    )


def resolved_prompt_payload(prompt: ResolvedGenerationPrompt) -> dict[str, object]:
    return {
        "contract_version": "recommendation-resolved-prompt-v2",
        "binding": _binding_payload(prompt.binding),
        "route": _route_payload(prompt.route),
        "configured_model": prompt.configured_model,
        "capture_method": prompt.capture_method.value,
        "search_mode": prompt.search_mode,
        "prompt_bundle_hash": prompt.prompt_bundle_hash,
        "messages": [dict(item) for item in prompt.messages],
        "output_schema": dict(prompt.output_schema),
        "application_output_schema": dict(prompt.application_output_schema),
        "policy": _policy_payload(prompt.policy),
        "structured_input_hash": prompt.structured_input_hash,
    }


def resolved_prompt_from_payload(value: object) -> ResolvedGenerationPrompt:
    root = _mapping(value, "resolved Recommendation Prompt")
    _contract(root, "recommendation-resolved-prompt-v2")
    messages_value = _sequence(root.get("messages"), "Prompt messages")
    messages: list[dict[str, str]] = []
    for value in messages_value:
        item = _mapping(value, "Prompt message")
        messages.append({"role": _text(item, "role"), "content": _text(item, "content")})
    schema = _mapping(root.get("output_schema"), "Prompt output schema")
    application_schema = _mapping(
        root.get("application_output_schema"),
        "Prompt application output schema",
    )
    return ResolvedGenerationPrompt(
        binding=_binding_from_payload(root.get("binding")),
        route=_route_from_payload(root.get("route")),
        configured_model=_text(root, "configured_model"),
        capture_method=ModelCaptureMethod(_text(root, "capture_method")),
        search_mode=_optional_text(root.get("search_mode")),
        prompt_bundle_hash=_text(root, "prompt_bundle_hash"),
        messages=tuple(messages),
        output_schema=schema,
        application_output_schema=application_schema,
        policy=_policy_from_payload(root.get("policy")),
        structured_input_hash=_text(root, "structured_input_hash"),
    )


def model_result_payload(result: ModelGatewayResult) -> dict[str, object]:
    return {
        "contract_version": "recommendation-model-result-v1",
        "output": dict(result.output),
        "call_log_id": str(result.call_log_id),
        "provider_request_id": result.provider_request_id,
        "configured_model": result.configured_model,
        "provider_reported_model": result.provider_reported_model,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
        "finish_reason": result.finish_reason,
        "response_hash": result.response_hash,
        "provider": result.provider,
        "adapter_release_id": result.adapter_release_id,
        "adapter_release_hash": result.adapter_release_hash,
        "model_release_id": result.model_release_id,
        "model_release_hash": result.model_release_hash,
        "latency_ms": result.latency_ms,
        "citations": [dict(item) for item in result.citations],
        "tool_events": [dict(item) for item in result.tool_events],
        "raw_artifact_reference": result.raw_artifact_reference,
        "raw_artifact_manifest_hash": result.raw_artifact_manifest_hash,
        "raw_artifact_content_hash": result.raw_artifact_content_hash,
        "raw_artifact_byte_size": result.raw_artifact_byte_size,
        "derived_artifact_reference": result.derived_artifact_reference,
        "derived_artifact_manifest_hash": result.derived_artifact_manifest_hash,
        "derived_artifact_content_hash": result.derived_artifact_content_hash,
        "derived_artifact_byte_size": result.derived_artifact_byte_size,
        "raw_artifact_policy_hash": result.raw_artifact_policy_hash,
        "raw_artifact_storage_decision": result.raw_artifact_storage_decision,
        "raw_artifact_cache_decision": result.raw_artifact_cache_decision,
        "raw_artifact_display_decision": result.raw_artifact_display_decision,
        "raw_artifact_redistribution_decision": result.raw_artifact_redistribution_decision,
        "raw_artifact_retention_days": result.raw_artifact_retention_days,
        "usage_purpose": result.usage_purpose,
        "usage_audience": result.usage_audience.value if result.usage_audience else None,
        "capture_method": result.capture_method.value if result.capture_method else None,
        "search_mode": result.search_mode,
        "usage_details": dict(result.usage_details) if result.usage_details else None,
        "requested_location": (
            result.requested_location.canonical_value()
            if result.requested_location is not None
            else None
        ),
        "effective_location": (
            result.effective_location.canonical_value()
            if result.effective_location is not None
            else None
        ),
    }


def model_result_from_payload(value: object) -> ModelGatewayResult:
    root = _mapping(value, "Recommendation model result")
    _contract(root, "recommendation-model-result-v1")
    output = _mapping(root.get("output"), "model output")
    return ModelGatewayResult(
        output=dict(output),
        call_log_id=_uuid(root, "call_log_id"),
        provider_request_id=_optional_text(root.get("provider_request_id")),
        configured_model=_text(root, "configured_model"),
        provider_reported_model=_optional_text(root.get("provider_reported_model")),
        prompt_tokens=_optional_integer(root.get("prompt_tokens")),
        completion_tokens=_optional_integer(root.get("completion_tokens")),
        cost_usd=_optional_decimal(root.get("cost_usd")),
        finish_reason=_optional_text(root.get("finish_reason")),
        response_hash=_text(root, "response_hash"),
        provider=_optional_text(root.get("provider")),
        adapter_release_id=_optional_text(root.get("adapter_release_id")),
        adapter_release_hash=_optional_text(root.get("adapter_release_hash")),
        model_release_id=_optional_text(root.get("model_release_id")),
        model_release_hash=_optional_text(root.get("model_release_hash")),
        latency_ms=_optional_integer(root.get("latency_ms")),
        citations=_mapping_sequence(root.get("citations"), "citations"),
        tool_events=_mapping_sequence(root.get("tool_events"), "tool events"),
        raw_artifact_reference=_optional_text(root.get("raw_artifact_reference")),
        raw_artifact_manifest_hash=_optional_text(root.get("raw_artifact_manifest_hash")),
        raw_artifact_content_hash=_optional_text(root.get("raw_artifact_content_hash")),
        raw_artifact_byte_size=_optional_integer(root.get("raw_artifact_byte_size")),
        derived_artifact_reference=_optional_text(root.get("derived_artifact_reference")),
        derived_artifact_manifest_hash=_optional_text(
            root.get("derived_artifact_manifest_hash")
        ),
        derived_artifact_content_hash=_optional_text(
            root.get("derived_artifact_content_hash")
        ),
        derived_artifact_byte_size=_optional_integer(root.get("derived_artifact_byte_size")),
        raw_artifact_policy_hash=_optional_text(root.get("raw_artifact_policy_hash")),
        raw_artifact_storage_decision=_optional_text(
            root.get("raw_artifact_storage_decision")
        ),
        raw_artifact_cache_decision=_optional_text(root.get("raw_artifact_cache_decision")),
        raw_artifact_display_decision=_optional_text(
            root.get("raw_artifact_display_decision")
        ),
        raw_artifact_redistribution_decision=_optional_text(
            root.get("raw_artifact_redistribution_decision")
        ),
        raw_artifact_retention_days=_optional_integer(
            root.get("raw_artifact_retention_days")
        ),
        usage_purpose=_optional_text(root.get("usage_purpose")),
        usage_audience=(
            ModelAudience(str(root["usage_audience"]))
            if root.get("usage_audience") is not None
            else None
        ),
        capture_method=(
            ModelCaptureMethod(str(root["capture_method"]))
            if root.get("capture_method") is not None
            else None
        ),
        search_mode=_optional_text(root.get("search_mode")),
        usage_details=(
            _mapping(root["usage_details"], "usage details")
            if root.get("usage_details") is not None
            else None
        ),
        requested_location=_requested_location(root.get("requested_location")),
        effective_location=_effective_location(root.get("effective_location")),
    )


def model_result_hash(result: ModelGatewayResult) -> str:
    return canonical_hash(model_result_payload(result))


def _binding_payload(value: FrozenPromptBinding) -> dict[str, object]:
    return {
        "project_id": str(value.project_id),
        "binding_id": str(value.binding_id),
        "binding_version": value.binding_version,
        "frozen_state_id": str(value.frozen_state_id),
        "frozen_state_version": value.frozen_state_version,
        "release_id": str(value.release_id),
        "release_version": value.release_version,
        "release_hash": value.release_hash,
        "program_kind": value.program_kind.value,
        "purpose": value.purpose,
    }


def _binding_from_payload(value: object) -> FrozenPromptBinding:
    item = _mapping(value, "Prompt binding")
    return FrozenPromptBinding(
        project_id=_uuid(item, "project_id"),
        binding_id=_uuid(item, "binding_id"),
        binding_version=_integer(item, "binding_version"),
        frozen_state_id=_uuid(item, "frozen_state_id"),
        frozen_state_version=_integer(item, "frozen_state_version"),
        release_id=_uuid(item, "release_id"),
        release_version=_integer(item, "release_version"),
        release_hash=_text(item, "release_hash"),
        program_kind=ProgramKind(_text(item, "program_kind")),
        purpose=_text(item, "purpose"),
    )


def _route_payload(value: ModelRoute) -> dict[str, str]:
    return {
        "provider": value.provider,
        "adapter_release_id": value.adapter_release_id,
        "adapter_release_hash": value.adapter_release_hash,
        "model_release_id": value.model_release_id,
        "model_release_hash": value.model_release_hash,
    }


def _route_from_payload(value: object) -> ModelRoute:
    item = _mapping(value, "model route")
    return ModelRoute(
        provider=_text(item, "provider"),
        adapter_release_id=_text(item, "adapter_release_id"),
        adapter_release_hash=_text(item, "adapter_release_hash"),
        model_release_id=_text(item, "model_release_id"),
        model_release_hash=_text(item, "model_release_hash"),
    )


def _policy_payload(value: ModelPolicy) -> dict[str, object]:
    return {
        **value.canonical_value(),
        "policy_version_id": str(value.policy_version_id) if value.policy_version_id else None,
        "policy_version_hash": value.policy_version_hash,
    }


def _policy_from_payload(value: object) -> ModelPolicy:
    item = _mapping(value, "model policy")
    policy = ModelPolicy(
        external_training_allowed=_boolean(item, "external_training_allowed"),
        structured_output_required=_boolean(item, "structured_output_required"),
        allowed_providers=_optional_set(item.get("allowed_providers")),
        allowed_adapter_release_ids=_optional_set(item.get("allowed_adapter_release_ids")),
        policy_version_id=_optional_uuid(item.get("policy_version_id")),
        maximum_paid_calls=_optional_integer(item.get("maximum_paid_calls")),
        maximum_concurrent_calls=_optional_integer(item.get("maximum_concurrent_calls")),
    )
    if policy.policy_version_hash != item.get("policy_version_hash"):
        raise ValueError("Recommendation model policy hash changed")
    return policy


def _requested_location(value: object) -> RequestedModelLocation | None:
    if value is None:
        return None
    item = _mapping(value, "requested location")
    return RequestedModelLocation(
        _optional_text(item.get("country_code")),
        _optional_text(item.get("region_code")),
        _text(item, "locale"),
        _text(item, "language"),
    )


def _effective_location(value: object) -> EffectiveModelLocation | None:
    if value is None:
        return None
    item = _mapping(value, "effective location")
    return EffectiveModelLocation(
        ModelLocationControl(_text(item, "control")),
        _optional_text(item.get("country_code")),
        _optional_text(item.get("region_code")),
        _optional_text(item.get("locale")),
        _optional_text(item.get("language")),
        _text(item, "evidence_hash"),
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be an array")
    return tuple(value)


def _mapping_sequence(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    return tuple(dict(_mapping(item, label)) for item in _sequence(value, label))


def _contract(value: Mapping[str, Any], expected: str) -> None:
    if value.get("contract_version") != expected:
        raise ValueError(f"unsupported Recommendation payload contract: {expected}")


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be non-empty text")
    return item


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional Recommendation text is invalid")
    return value


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{key} must be an integer")
    return item


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("optional Recommendation integer is invalid")
    return value


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"{key} must be boolean")
    return item


def _uuid(value: Mapping[str, Any], key: str) -> UUID:
    return UUID(_text(value, key))


def _optional_uuid(value: object) -> UUID | None:
    return UUID(str(value)) if value is not None else None


def _optional_decimal(value: object) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _optional_set(value: object) -> frozenset[str] | None:
    if value is None:
        return None
    return frozenset(str(item) for item in _sequence(value, "model policy allowlist"))


__all__ = [
    "model_result_from_payload",
    "model_result_hash",
    "model_result_payload",
    "model_task_from_payload",
    "model_task_payload",
    "resolved_prompt_from_payload",
    "resolved_prompt_payload",
]
