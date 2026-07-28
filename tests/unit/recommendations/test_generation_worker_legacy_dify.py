from __future__ import annotations

from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

import pytest

from geo_core.recommendations.evidence_graph import EVIDENCE_GRAPH_CONTRACT_V1
from geo_core.recommendations.generation_evidence import GENERATION_EVIDENCE_CONTRACT_V1
from geo_core.recommendations.generation_ports import (
    ARBITER_APPLICATION_OUTPUT_SCHEMA,
    ARBITER_OUTPUT_SCHEMA,
    structured_arbiter_input,
)
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationChildStatus,
    RecommendationDifyResultRef,
    RecommendationExecutionBackend,
    RecommendationModelOutcome,
    RecommendationModelRole,
    RecommendationModelTask,
    RecommendationParentClaim,
)
from geo_core.recommendations.models import RecommendationType
from geo_core.workflow_runtime.errors import UnknownWorkflowOutcomeError

from .generation_test_support import (
    PromptResolverStub,
    generation_spec,
    model_output,
    model_result,
)
from .test_generation_worker import _dify_child_runtime, _parent_runtime


def test_legacy_v3_queued_parent_stages_native_with_original_input_shape() -> None:
    current = generation_spec()
    spec = replace(
        current,
        evidence=replace(
            current.evidence,
            contract_version=GENERATION_EVIDENCE_CONTRACT_V1,
        ),
    )
    store, repository, handler, parent = _parent_runtime(spec)

    outcome = handler.handle(parent)

    assert outcome["status"] == "retry_wait"
    task = repository.staged[0]
    assert task.execution_backend is RecommendationExecutionBackend.MODEL_GATEWAY
    assert task.workflow_release_id is None
    assert task.workflow_release_hash is None
    assert "type_admission_json" not in task.structured_input
    assert task.structured_input["allowed_recommendation_types"] == [
        item.value for item in RecommendationType
    ]
    assert store.deferred[0][0] == "waiting_primary"


def test_legacy_v3_successful_primary_resumes_with_original_parser_and_graph() -> None:
    current = generation_spec()
    spec = replace(
        current,
        evidence=replace(
            current.evidence,
            contract_version=GENERATION_EVIDENCE_CONTRACT_V1,
        ),
    )
    output = model_output("gap", evidence=spec.evidence)
    output["recommendation_type"] = "hard_blocker"
    result = model_result(spec, output)
    primary = RecommendationModelOutcome(
        child_job_id=uuid4(),
        role=RecommendationModelRole.PRIMARY,
        status=RecommendationChildStatus.SUCCEEDED,
        result=result,
    )
    store, repository, handler, parent = _parent_runtime(
        spec,
        claim=RecommendationParentClaim(spec, primary=primary),
    )

    outcome = handler.handle(parent)

    assert outcome["status"] == "succeeded"
    recommendation = repository.finalized[0].recommendation
    assert recommendation.recommendation_type is RecommendationType.HARD_BLOCKER
    assert recommendation.evidence.contract_version == EVIDENCE_GRAPH_CONTRACT_V1
    assert store.completed[0][0].startswith("recommendation:")


def test_dify_primary_uses_only_the_frozen_release_and_wakes_parent() -> None:
    runtime, workflows = _dify_child_runtime()

    outcome = runtime.handler.handle(runtime.lease)

    assert outcome["status"] == "succeeded"
    assert workflows.frozen_calls == [
        (
            runtime.task.workflow_release_id,
            runtime.task.workflow_release_hash,
            workflows.frozen_calls[0][2],
        )
    ]
    assert not runtime.admitter.requests
    assert not runtime.application.commands
    assert isinstance(runtime.repository.successes[0][1], RecommendationDifyResultRef)
    assert runtime.store.completed[0][0].startswith("dify-workflow://attempt/")
    assert runtime.repository.woken == [runtime.task.parent_job_id]


def test_dify_unknown_outcome_is_terminal_and_invalid_output_never_succeeds() -> None:
    unknown, _ = _dify_child_runtime(
        action=UnknownWorkflowOutcomeError(
            "read timed out after provider acceptance", code="dify_unknown_outcome"
        )
    )

    outcome = unknown.handler.handle(unknown.lease)

    assert outcome["status"] == "failed"
    assert unknown.store.transaction_failures == [("failed", "dify_unknown_outcome", None)]
    assert unknown.repository.woken == [unknown.task.parent_job_id]

    invalid, _ = _dify_child_runtime(output={"recommendation_type": "gap"})
    invalid_outcome = invalid.handler.handle(invalid.lease)
    assert invalid_outcome["status"] == "failed"
    assert invalid.store.transaction_failures[0][1].startswith("recommendation_dify_")
    assert not invalid.repository.successes

    invented_number = model_output()
    decision = invented_number["decision"]
    assert isinstance(decision, dict)
    decision["business_value"] = "Increase qualified discovery by 99%"
    numeric, _ = _dify_child_runtime(output=invented_number)
    numeric_outcome = numeric.handler.handle(numeric.lease)
    assert numeric_outcome["status"] == "failed"
    assert numeric.store.transaction_failures[0][1].startswith("recommendation_dify_")
    assert not numeric.repository.successes


def test_model_task_rejects_dify_arbiter_even_with_frozen_release() -> None:
    spec = generation_spec(with_arbiter=True)
    structured_input = structured_arbiter_input(model_output(), evidence=spec.evidence)
    prompt = PromptResolverStub().resolve(
        binding=spec.arbiter_binding,
        route=spec.arbiter_route,
        configured_model=spec.arbiter_configured_model,
        model_policy=spec.arbiter_model_policy,
        capture_method=spec.arbiter_capture_method,
        search_mode=spec.arbiter_search_mode,
        structured_input=structured_input,
        output_schema=ARBITER_OUTPUT_SCHEMA,
        application_output_schema=ARBITER_APPLICATION_OUTPUT_SCHEMA,
    )
    with pytest.raises(ValueError, match="arbiter must remain"):
        RecommendationModelTask(
            child_job_id=uuid4(),
            parent_job_id=uuid4(),
            project_id=spec.project_id,
            parent_input_hash=spec.input_hash,
            role=RecommendationModelRole.ARBITER,
            runtime_selection_id=cast(UUID, spec.arbiter_runtime_selection_id),
            runtime_manifest_id=cast(UUID, spec.arbiter_runtime_manifest_id),
            runtime_manifest_hash=cast(str, spec.arbiter_runtime_manifest_hash),
            runtime_option_id=cast(UUID, spec.arbiter_runtime_option_id),
            runtime_option_hash=cast(str, spec.arbiter_runtime_option_hash),
            prompt=prompt,
            admitted_by=uuid4(),
            artifact_expires_at=spec.valid_until,
            execution_backend=RecommendationExecutionBackend.DIFY,
            structured_input=structured_input,
            workflow_release_id=uuid4(),
            workflow_release_hash="8" * 64,
        )
