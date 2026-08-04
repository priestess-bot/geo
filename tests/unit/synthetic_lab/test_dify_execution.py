from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

import pytest

from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_contracts import thaw_mapping
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.dify_execution import (
    DIFY_SYNTHETIC_PROGRAM_KINDS,
    HybridSyntheticModelCallExecutor,
)
from geo_core.synthetic_lab.execution_contracts import (
    SyntheticExecutionBackend,
    SyntheticExecutionError,
    StyleProfileBuildOutput,
    SyntheticModelInvocation,
    SyntheticModelResult,
    SyntheticWorkflowResult,
)
from geo_core.synthetic_lab.execution_gateway import PromptProgramExecutionResolver
from geo_core.workflow_runtime import WorkflowExecutionRequest, WorkflowExecutionResult
from geo_core.workflow_runtime.contracts import canonical_json_hash as workflow_output_hash
from geo_core.workflow_runtime.errors import RetryableWorkflowExecutionError
from tests.unit.synthetic_lab.test_execution_prompt_contracts import (
    _RuntimeApplication,
    _hash,
    _lease,
    _runtime,
    _runtime_inputs,
)


@pytest.mark.parametrize(
    "kind",
    (
        ProgramKind.STYLE_PROFILE,
        ProgramKind.GENERATION,
        ProgramKind.CLAIM_EXTRACTION,
        ProgramKind.CONFLICT_CHECK,
        ProgramKind.REVISION,
    ),
)
def test_hybrid_executor_routes_migrated_step_to_dify_without_native_fallback(
    kind: ProgramKind,
) -> None:
    runtime, frozen = _runtime(kind)
    spec = default_prompt_bootstrap_spec(kind)
    fixture = next(item for item in spec.fixtures if item.expected_valid)
    structured_input = thaw_mapping(fixture.input_value)
    prompt = PromptProgramExecutionResolver(_RuntimeApplication(runtime)).resolve(
        frozen=frozen,
        structured_input=structured_input,
        output_schema=spec.schemas.output_schema,
        application_output_schema=spec.schemas.application_output_schema,
    )

    class Native:
        def execute(self, invocation: object) -> None:
            del invocation
            raise AssertionError("migrated synthetic step fell back to native")

    class Workflows:
        request: WorkflowExecutionRequest | None = None
        release_id = uuid4()
        release_hash = _hash("dify-release")
        snapshot_id = uuid4()
        snapshot_hash = _hash("dify-snapshot")

        def execute_frozen(
            self,
            lease: object,
            request: WorkflowExecutionRequest,
            *,
            release_id,
            release_hash,
            validate_output=None,
        ) -> WorkflowExecutionResult:
            del lease
            assert release_id == self.release_id
            assert release_hash == self.release_hash
            self.request = request
            output: Mapping[str, object] = thaw_mapping(fixture.expected_output)
            assert validate_output is not None
            validate_output(output)
            return WorkflowExecutionResult(
                output=output,
                attempt_id=uuid4(),
                runtime_release_id=self.release_id,
                runtime_release_hash=self.release_hash,
                dify_task_id="task",
                dify_run_id="run",
                configured_model=frozen.configured_model,
                provider_reported_model=frozen.configured_model,
                prompt_tokens=1,
                completion_tokens=1,
                total_steps=3,
                elapsed_seconds=None,
                response_hash=workflow_output_hash(output),
                published_snapshot_id=self.snapshot_id,
                published_snapshot_hash=self.snapshot_hash,
            )

    workflows = Workflows()
    result = HybridSyntheticModelCallExecutor(native=Native(), workflows=workflows).execute(
        SyntheticModelInvocation(
            lease=_lease(uuid4(), "synthetic.model.call"),
            expected_job_version=1,
            parent_task_input_hash=_hash("parent-task"),
            runtime_inputs=_runtime_inputs(frozen, profile_id=uuid4()),
            prompt=prompt,
            admitted_by=uuid4(),
            step_key="evaluate:c1:claims",
            structured_input=structured_input,
            execution_backend=SyntheticExecutionBackend.DIFY,
            workflow_release_id=workflows.release_id,
            workflow_release_hash=workflows.release_hash,
        )
    )

    assert isinstance(result, SyntheticWorkflowResult)
    assert result.provider == "dify"
    assert not hasattr(result, "model_attempt_id")
    assert not hasattr(result, "model_call_id")
    assert result.published_snapshot_id == workflows.snapshot_id
    assert result.published_snapshot_hash == workflows.snapshot_hash
    assert workflows.request is not None
    assert workflows.request.purpose == spec.purpose
    assert workflows.request.input_hash == canonical_hash(
        {
            "parent_task_input_hash": _hash("parent-task"),
            "step_key": "evaluate:c1:claims",
            "prompt_bundle_hash": prompt.prompt_bundle_hash,
            "structured_input_hash": prompt.structured_input_hash,
        }
    )


def test_hybrid_executor_fails_closed_when_dify_executor_is_unavailable() -> None:
    runtime, frozen = _runtime(ProgramKind.STYLE_PROFILE)
    spec = default_prompt_bootstrap_spec(ProgramKind.STYLE_PROFILE)
    fixture = next(item for item in spec.fixtures if item.expected_valid)
    structured_input = thaw_mapping(fixture.input_value)
    prompt = PromptProgramExecutionResolver(_RuntimeApplication(runtime)).resolve(
        frozen=frozen,
        structured_input=structured_input,
        output_schema=spec.schemas.output_schema,
        application_output_schema=spec.schemas.application_output_schema,
    )

    class Native:
        def execute(self, invocation: object) -> None:
            del invocation
            raise AssertionError("migrated Style Profile fell back to native")

    with pytest.raises(SyntheticExecutionError, match="Dify is required"):
        HybridSyntheticModelCallExecutor(native=Native(), workflows=None).execute(
            SyntheticModelInvocation(
                lease=_lease(uuid4(), "synthetic.model.call"),
                expected_job_version=1,
                parent_task_input_hash=_hash("parent-task"),
                runtime_inputs=_runtime_inputs(frozen, profile_id=uuid4()),
                prompt=prompt,
                admitted_by=uuid4(),
                step_key="style-profile:build:v1",
                structured_input=structured_input,
                execution_backend=SyntheticExecutionBackend.DIFY,
                workflow_release_id=uuid4(),
                workflow_release_hash=_hash("frozen-workflow"),
            )
        )


def test_dify_model_semantic_contract_failure_is_bounded_retryable() -> None:
    runtime, frozen = _runtime(ProgramKind.CLAIM_EXTRACTION)
    spec = default_prompt_bootstrap_spec(ProgramKind.CLAIM_EXTRACTION)
    fixture = next(item for item in spec.fixtures if item.expected_valid)
    structured_input = thaw_mapping(fixture.input_value)
    prompt = PromptProgramExecutionResolver(_RuntimeApplication(runtime)).resolve(
        frozen=frozen,
        structured_input=structured_input,
        output_schema=spec.schemas.output_schema,
        application_output_schema=spec.schemas.application_output_schema,
    )

    class Native:
        def execute(self, invocation: object) -> None:
            del invocation
            raise AssertionError("migrated claim extraction fell back to native")

    class Workflows:
        release_id = uuid4()
        release_hash = _hash("dify-release")

        def execute_frozen(
            self,
            lease: object,
            request: WorkflowExecutionRequest,
            *,
            release_id,
            release_hash,
            validate_output=None,
        ) -> None:
            del lease, request
            assert release_id == self.release_id
            assert release_hash == self.release_hash
            output = thaw_mapping(fixture.expected_output)
            output["claims"][0]["classification"] = "derived_or_unknown"
            output["claims"][0]["evidence_refs"] = [
                structured_input["evidence"][0]["ref"]
            ]
            assert validate_output is not None
            validate_output(output)

    workflows = Workflows()
    invocation = SyntheticModelInvocation(
        lease=_lease(uuid4(), "synthetic.model.call"),
        expected_job_version=1,
        parent_task_input_hash=_hash("parent-task"),
        runtime_inputs=_runtime_inputs(frozen, profile_id=uuid4()),
        prompt=prompt,
        admitted_by=uuid4(),
        step_key="evaluate:candidate:claims",
        structured_input=structured_input,
        execution_backend=SyntheticExecutionBackend.DIFY,
        workflow_release_id=workflows.release_id,
        workflow_release_hash=workflows.release_hash,
    )

    with pytest.raises(RetryableWorkflowExecutionError) as captured:
        HybridSyntheticModelCallExecutor(native=Native(), workflows=workflows).execute(
            invocation
        )

    assert captured.value.code == "synthetic_output_invalid"
    assert captured.value.retryable is True


def test_hybrid_executor_keeps_offline_answer_on_native_runtime() -> None:
    runtime, frozen = _runtime(ProgramKind.OFFLINE_ANSWER)
    spec = default_prompt_bootstrap_spec(ProgramKind.OFFLINE_ANSWER)
    fixture = next(item for item in spec.fixtures if item.expected_valid)
    structured_input = thaw_mapping(fixture.input_value)
    prompt = PromptProgramExecutionResolver(_RuntimeApplication(runtime)).resolve(
        frozen=frozen,
        structured_input=structured_input,
        output_schema=spec.schemas.output_schema,
        application_output_schema=spec.schemas.application_output_schema,
    )
    expected = SyntheticModelResult(
        model_attempt_id=uuid4(),
        model_call_id=uuid4(),
        output=thaw_mapping(fixture.expected_output),
        provider="native-test",
        configured_model=frozen.configured_model,
        reported_model=frozen.configured_model,
        model_identity_hash=_hash("native-model"),
        request_hash=_hash("native-request"),
        response_hash=_hash("native-response"),
    )

    class Native:
        invocation: SyntheticModelInvocation | None = None

        def execute(self, invocation: SyntheticModelInvocation) -> SyntheticModelResult:
            self.invocation = invocation
            return expected

    class Workflows:
        def execute_optional(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise AssertionError("native Offline Answer was sent to Dify")

    invocation = SyntheticModelInvocation(
        lease=_lease(uuid4(), "synthetic.model.call"),
        expected_job_version=1,
        parent_task_input_hash=_hash("parent-task"),
        runtime_inputs=_runtime_inputs(frozen, profile_id=uuid4()),
        prompt=prompt,
        admitted_by=uuid4(),
        step_key="offline-slot:test",
        structured_input=structured_input,
    )
    native = Native()

    result = HybridSyntheticModelCallExecutor(native=native, workflows=Workflows()).execute(
        invocation
    )

    assert ProgramKind.OFFLINE_ANSWER not in DIFY_SYNTHETIC_PROGRAM_KINDS
    assert result is expected
    assert native.invocation is invocation


def test_style_profile_output_keeps_workflow_lineage_out_of_model_calls() -> None:
    workflow_attempt_id = uuid4()

    output = StyleProfileBuildOutput(
        project_id=uuid4(),
        profile_version_id=uuid4(),
        profile_hash=_hash("profile"),
        artifact_hash=_hash("artifact"),
        model_call_ids=(),
        workflow_attempt_ids=(workflow_attempt_id,),
    )

    assert output.model_call_ids == ()
    assert output.workflow_attempt_ids == (workflow_attempt_id,)
