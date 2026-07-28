"""Fail-closed Dify routing for migrated Synthetic Lab workflow paths."""

from __future__ import annotations

from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_validation import validate_bootstrap_output
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.execution_contracts import (
    DIFY_SYNTHETIC_PROGRAM_KINDS,
    SyntheticExecutionBackend,
    SyntheticExecutionError,
    SyntheticExecutionResult,
    SyntheticModelCallPort,
    SyntheticModelInvocation,
    SyntheticWorkflowResult,
)
from geo_core.workflow_runtime import WorkflowExecutionRequest, WorkflowExecutor
from geo_core.workflow_runtime.errors import WorkflowContractError


class HybridSyntheticModelCallExecutor:
    """Route migrated Synthetic steps to Dify and all other steps to the native gateway."""

    def __init__(
        self, *, native: SyntheticModelCallPort, workflows: WorkflowExecutor | None
    ) -> None:
        self._native = native
        self._workflows = workflows

    def execute(self, invocation: SyntheticModelInvocation) -> SyntheticExecutionResult:
        kind = invocation.prompt.frozen.program_kind
        if invocation.execution_backend is SyntheticExecutionBackend.MODEL_GATEWAY:
            return self._native.execute(invocation)
        if kind not in DIFY_SYNTHETIC_PROGRAM_KINDS:
            raise SyntheticExecutionError(f"{kind.value} is not a migrated Dify purpose")
        if self._workflows is None:
            raise SyntheticExecutionError(
                f"Dify is required for migrated synthetic purpose {invocation.prompt.frozen.purpose}"
            )

        spec = default_prompt_bootstrap_spec(kind)
        request = WorkflowExecutionRequest(
            project_id=invocation.lease.project_id,
            purpose=invocation.prompt.frozen.purpose,
            context=invocation.structured_input,
            input_hash=canonical_hash(
                {
                    "parent_task_input_hash": invocation.parent_task_input_hash,
                    "step_key": invocation.step_key,
                    "prompt_bundle_hash": invocation.prompt.prompt_bundle_hash,
                    "structured_input_hash": invocation.prompt.structured_input_hash,
                }
            ),
            output_schema=invocation.prompt.application_output_schema,
        )

        def validate(output) -> None:
            try:
                validate_bootstrap_output(
                    spec,
                    input_value=invocation.structured_input,
                    output=output,
                )
            except Exception as exc:
                raise WorkflowContractError(
                    f"Dify synthetic output failed the frozen Prompt contract: {exc}",
                    code="dify_synthetic_contract_invalid",
                ) from exc

        if invocation.workflow_release_id is None or invocation.workflow_release_hash is None:
            raise SyntheticExecutionError("Dify child lacks its frozen Workflow Release")
        result = self._workflows.execute_frozen(
            invocation.lease,
            request,
            release_id=invocation.workflow_release_id,
            release_hash=invocation.workflow_release_hash,
            validate_output=validate,
        )
        frozen = invocation.prompt.frozen
        if (
            result.runtime_release_id != invocation.workflow_release_id
            or result.runtime_release_hash != invocation.workflow_release_hash
        ):
            raise SyntheticExecutionError("Dify changed the frozen Workflow Release")
        if result.configured_model != frozen.configured_model:
            raise SyntheticExecutionError("Dify changed the frozen configured model")
        if result.published_snapshot_id is None or result.published_snapshot_hash is None:
            raise SyntheticExecutionError("Dify success lacks its frozen published snapshot")
        reported_model = result.provider_reported_model or result.configured_model
        return SyntheticWorkflowResult(
            workflow_attempt_id=result.attempt_id,
            workflow_release_id=result.runtime_release_id,
            workflow_release_hash=result.runtime_release_hash,
            output=result.output,
            configured_model=result.configured_model,
            reported_model=reported_model,
            model_identity_hash=canonical_hash(
                {
                    "provider": "dify",
                    "runtime_release_id": result.runtime_release_id,
                    "runtime_release_hash": result.runtime_release_hash,
                    "published_snapshot_id": result.published_snapshot_id,
                    "published_snapshot_hash": result.published_snapshot_hash,
                    "configured_model": result.configured_model,
                    "reported_model": reported_model,
                }
            ),
            request_hash=request.input_hash,
            response_hash=result.response_hash,
            published_snapshot_id=result.published_snapshot_id,
            published_snapshot_hash=result.published_snapshot_hash,
        )


__all__ = ["DIFY_SYNTHETIC_PROGRAM_KINDS", "HybridSyntheticModelCallExecutor"]
