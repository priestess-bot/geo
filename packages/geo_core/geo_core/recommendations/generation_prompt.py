"""Exact Prompt Program rendering for Recommendation model stages."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Protocol

from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.prompts.application_models import RuntimePromptProgram
from geo_core.prompts.program_rendering import render_program_release
from geo_core.recommendations.generation_contracts import (
    FrozenPromptBinding,
    RecommendationGenerationStale,
    ResolvedGenerationPrompt,
    canonical_hash,
)


class RuntimePromptProgramPort(Protocol):
    def resolve_runtime_binding(
        self, *, project_id, purpose: str
    ) -> RuntimePromptProgram: ...


class RecommendationPromptProgramResolver:
    """Re-resolve and render one frozen binding before every paid model call."""

    def __init__(self, application: RuntimePromptProgramPort) -> None:
        self._application = application

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
        runtime = self._runtime(binding)
        release = runtime.release
        if canonical_hash(release.schemas.output_schema) != canonical_hash(output_schema):
            raise RecommendationGenerationStale(
                "Prompt output schema changed from the Recommendation contract"
            )
        release_application_schema = getattr(
            release.schemas,
            "application_output_schema",
            None,
        )
        if (
            release_application_schema is None
            or canonical_hash(release_application_schema)
            != canonical_hash(application_output_schema)
        ):
            raise RecommendationGenerationStale(
                "Prompt application output schema changed from the Recommendation contract"
            )
        request_json = json.dumps(
            _json_value(structured_input),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        rendered = render_program_release(
            release=release,
            variables={"request_json": request_json},
        )
        structured_hash = canonical_hash(structured_input)
        bundle_hash = canonical_hash(
            {
                "binding_id": binding.binding_id,
                "binding_version": binding.binding_version,
                "release_id": binding.release_id,
                "release_hash": binding.release_hash,
                "structured_input_hash": structured_hash,
                "compiled_system_hash": rendered.compiled_system_hash,
                "compiled_user_hash": rendered.compiled_user_hash,
                "output_schema": output_schema,
                "application_output_schema": application_output_schema,
                "route": {
                    "provider": route.provider,
                    "adapter_release_id": route.adapter_release_id,
                    "adapter_release_hash": route.adapter_release_hash,
                    "model_release_id": route.model_release_id,
                    "model_release_hash": route.model_release_hash,
                },
                "policy_version_id": model_policy.policy_version_id,
                "policy_version_hash": model_policy.policy_version_hash,
            }
        )
        return ResolvedGenerationPrompt(
            binding=binding,
            route=route,
            configured_model=configured_model,
            capture_method=capture_method,
            search_mode=search_mode,
            prompt_bundle_hash=bundle_hash,
            messages=(
                {"role": "system", "content": rendered.compiled_system},
                {"role": "user", "content": rendered.compiled_user},
            ),
            output_schema=output_schema,
            application_output_schema=application_output_schema,
            policy=model_policy,
            structured_input_hash=structured_hash,
        )

    def _runtime(self, frozen: FrozenPromptBinding) -> RuntimePromptProgram:
        try:
            runtime = self._application.resolve_runtime_binding(
                project_id=frozen.project_id,
                purpose=frozen.purpose,
            )
        except Exception as error:
            raise RecommendationGenerationStale(
                "Prompt binding resolver rejected frozen lineage"
            ) from error
        release = runtime.release
        binding = runtime.binding
        observed = (
            release.project_id,
            binding.id,
            binding.binding_version,
            binding.frozen_state_id,
            runtime.state.version,
            release.id,
            release.version,
            release.release_hash,
            release.program_kind,
            release.purpose,
            runtime.state.id,
        )
        expected = (
            frozen.project_id,
            frozen.binding_id,
            frozen.binding_version,
            frozen.frozen_state_id,
            frozen.frozen_state_version,
            frozen.release_id,
            frozen.release_version,
            frozen.release_hash,
            frozen.program_kind,
            frozen.purpose,
            frozen.frozen_state_id,
        )
        if observed != expected:
            raise RecommendationGenerationStale(
                "Prompt binding or frozen Release identity changed"
            )
        return runtime


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise RecommendationGenerationStale(
        "Recommendation Prompt input is not canonical JSON"
    )


__all__ = ["RecommendationPromptProgramResolver", "RuntimePromptProgramPort"]
