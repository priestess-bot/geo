"""Strict Recommendation generation request conversion and safe Job responses."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from geo_api.recommendation_contracts import (
    EnqueueRecommendationGenerationRequest,
    GenerationJobStatusValue,
    GenerationModelLineageResponse,
    GenerationModelSelectorContract,
    GenerationPromptLineageResponse,
    RecommendationGenerationJobResponse,
    RecommendationResponse,
)
from geo_api.recommendation_presenters import (
    selection_scope,
    selectors_from_contract,
    workflow_response,
)
from geo_core.recommendations.generation_admission import (
    GenerationModelSelector,
    RecommendationGenerationSelection,
)
from geo_core.recommendations.generation_contracts import (
    FrozenPromptBinding,
    GenerationExecution,
    RecommendationGenerationJob,
    RecommendationGenerationResult,
)
from geo_core.recommendations.models import RecommendationWorkflow


def generation_selection(
    project_id: UUID,
    item: EnqueueRecommendationGenerationRequest,
) -> RecommendationGenerationSelection:
    return RecommendationGenerationSelection(
        project_id=project_id,
        scope=selection_scope(project_id, item.scope),
        evidence_selectors=selectors_from_contract(item.evidence_selectors),
        prompt_binding_id=item.prompt_binding_id,
        model=_model_selector(item.model),
        valid_until=item.valid_until,
        minimum_real_observations=item.minimum_real_observations,
        arbiter_prompt_binding_id=item.arbiter_prompt_binding_id,
        arbiter_model=(_model_selector(item.arbiter_model) if item.arbiter_model else None),
    )


def generation_job_response(
    item: GenerationExecution | RecommendationGenerationJob,
) -> RecommendationGenerationJobResponse:
    execution = (
        item
        if isinstance(item, GenerationExecution)
        else GenerationExecution(item, result=None, replayed=False)
    )
    job = execution.job
    spec = job.spec
    return RecommendationGenerationJobResponse(
        id=job.id,
        project_id=spec.project_id,
        status=cast(GenerationJobStatusValue, job.status.value),
        version=job.version,
        input_hash=job.input_hash,
        evidence_input_hash=spec.evidence.input_hash,
        consumed_model_calls=job.consumed_model_calls,
        maximum_model_calls=spec.maximum_model_calls,
        cancel_requested=job.cancel_requested,
        error_code=job.error_code,
        valid_until=spec.valid_until,
        prompt=_prompt_lineage(spec.prompt_binding),
        model=GenerationModelLineageResponse(
            runtime_selection_id=spec.runtime_selection_id,
            runtime_manifest_id=spec.runtime_manifest_id,
            runtime_manifest_hash=spec.runtime_manifest_hash,
            runtime_option_id=spec.runtime_option_id,
            runtime_option_hash=spec.runtime_option_hash,
            provider=spec.route.provider,
            adapter_release_id=spec.route.adapter_release_id,
            adapter_release_hash=spec.route.adapter_release_hash,
            model_release_id=spec.route.model_release_id,
            model_release_hash=spec.route.model_release_hash,
            configured_model=spec.configured_model,
            policy_version_id=spec.model_policy.policy_version_id,
            policy_version_hash=spec.model_policy.policy_version_hash,
            capture_method=spec.capture_method.value,
            search_mode=spec.search_mode,
        ),
        arbiter_prompt=(
            _prompt_lineage(spec.arbiter_binding) if spec.arbiter_binding else None
        ),
        arbiter_model=(
            GenerationModelLineageResponse(
                runtime_selection_id=spec.arbiter_runtime_selection_id,
                runtime_manifest_id=spec.arbiter_runtime_manifest_id,
                runtime_manifest_hash=spec.arbiter_runtime_manifest_hash,
                runtime_option_id=spec.arbiter_runtime_option_id,
                runtime_option_hash=spec.arbiter_runtime_option_hash,
                provider=spec.arbiter_route.provider,
                adapter_release_id=spec.arbiter_route.adapter_release_id,
                adapter_release_hash=spec.arbiter_route.adapter_release_hash,
                model_release_id=spec.arbiter_route.model_release_id,
                model_release_hash=spec.arbiter_route.model_release_hash,
                configured_model=spec.arbiter_configured_model,
                policy_version_id=spec.arbiter_model_policy.policy_version_id,
                policy_version_hash=spec.arbiter_model_policy.policy_version_hash,
                capture_method=spec.arbiter_capture_method.value,
                search_mode=spec.arbiter_search_mode,
            )
            if spec.arbiter_binding
            and spec.arbiter_runtime_selection_id
            and spec.arbiter_runtime_manifest_id
            and spec.arbiter_runtime_manifest_hash
            and spec.arbiter_runtime_option_id
            and spec.arbiter_runtime_option_hash
            and spec.arbiter_route
            and spec.arbiter_configured_model
            and spec.arbiter_model_policy
            and spec.arbiter_capture_method
            else None
        ),
        result=_result_response(execution.result),
        model_call_ids=list(execution.result.model_call_ids) if execution.result else [],
        insufficient_reasons=(
            list(execution.result.insufficient_reasons) if execution.result else []
        ),
        replayed=execution.replayed,
    )


def _model_selector(item: GenerationModelSelectorContract) -> GenerationModelSelector:
    return GenerationModelSelector(
        runtime_selection_id=item.runtime_selection_id,
        search_mode=item.search_mode,
    )


def _prompt_lineage(item: FrozenPromptBinding) -> GenerationPromptLineageResponse:
    return GenerationPromptLineageResponse(
        binding_id=item.binding_id,
        binding_version=item.binding_version,
        frozen_state_id=item.frozen_state_id,
        frozen_state_version=item.frozen_state_version,
        release_id=item.release_id,
        release_version=item.release_version,
        release_hash=item.release_hash,
        program_kind=cast(
            Literal["recommendation", "arbiter"], item.program_kind.value
        ),
        purpose=item.purpose,
    )


def _result_response(
    item: RecommendationGenerationResult | None,
) -> RecommendationResponse | None:
    if item is None:
        return None
    workflow = RecommendationWorkflow(recommendation=item.recommendation, drafts=())
    return workflow_response(workflow).recommendation


__all__ = ["generation_job_response", "generation_selection"]
