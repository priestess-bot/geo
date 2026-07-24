"""Model Gateway executor for one immutable Prompt test fixture."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid5

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.application_support import ExecuteModelCall, ModelCallExecution
from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryPort,
    ProviderArtifactRecoveryRequest,
)
from geo_core.model_gateway.contracts import (
    ModelAudience,
    ModelGatewayError,
    ModelGatewayRequest,
    RetryableModelGatewayError,
)
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.model_gateway.ports import (
    ModelCallAttemptKind,
    ModelCallTerminalStatus,
)
from geo_core.model_gateway.prompt_admission import (
    ModelCallAdmissionMode,
    PromptAdmissionState,
    PromptReleaseAdmission,
)
from geo_core.model_gateway.runtime_execution import (
    AdmittedModelCallJob,
    LoadedModelCallRuntime,
    NewModelCallJobAdmissionRequest,
)
from geo_core.prompts.program import CompiledProgramPrompt
from geo_core.prompts.test_execution_contracts import (
    PROMPT_TEST_JOB_KIND,
    PromptTestCaseModelResult,
    PromptTestExecutionError,
    PromptTestRunTask,
    PromptTestStale,
)
from geo_core.prompts.test_runtime_selector import (
    PROMPT_TEST_MODEL_PURPOSE,
    PROMPT_TEST_SEARCH_MODE,
)


PROMPT_TEST_MAXIMUM_PAID_CALLS = 5
PROMPT_TEST_MAXIMUM_CONCURRENT_CALLS = 1


class PromptTestModelRuntime(Protocol):
    def load_or_admit_claimed_job(
        self, request: NewModelCallJobAdmissionRequest
    ) -> AdmittedModelCallJob: ...

    def load(self, *, project_id: UUID, job_id: UUID) -> LoadedModelCallRuntime: ...


class ModelGatewayPromptTestCaseExecutor:
    """Execute or recover a test case under one five-call audited Job budget."""

    def __init__(
        self,
        *,
        runtime: PromptTestModelRuntime,
        result_recovery: ProviderArtifactRecoveryPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._runtime = runtime
        self._result_recovery = result_recovery
        self._clock = clock

    def execute(
        self,
        *,
        lease: WorkerLease,
        task: PromptTestRunTask,
        prompt: CompiledProgramPrompt,
        fixture_id: str,
        fixture_hash: str,
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> PromptTestCaseModelResult:
        case_id = uuid5(task.test_set_id, f"{fixture_id}:{fixture_hash}")
        admission = self._admission_request(
            lease=lease,
            task=task,
            output_schema=output_schema,
            application_output_schema=application_output_schema,
        )
        admitted = self._runtime.load_or_admit_claimed_job(admission)
        _assert_job_matches_task(
            admitted.job,
            lease=lease,
            task=task,
            output_schema=output_schema,
            application_output_schema=application_output_schema,
        )
        loaded = self._runtime.load(project_id=task.project_id, job_id=task.job_id)
        _assert_job_matches_task(
            loaded.job,
            lease=lease,
            task=task,
            output_schema=output_schema,
            application_output_schema=application_output_schema,
        )
        request = ModelGatewayRequest(
            messages=(
                {"role": "system", "content": prompt.compiled_system},
                {"role": "user", "content": prompt.compiled_user},
            ),
            configured_model=task.model.configured_model,
            prompt_bundle_hash=task.input_hash,
            project_id=task.project_id,
            purpose=PROMPT_TEST_MODEL_PURPOSE,
            usage_audience=ModelAudience.INTERNAL_WORKER,
            temperature=0.0,
            max_output_tokens=4096,
            output_schema=output_schema,
            application_output_schema=application_output_schema,
            search_mode=PROMPT_TEST_SEARCH_MODE,
            capture_method=task.model.capture_method,
            provider_secret_handle=task.model.provider_secret_handle,
        )
        execution = loaded.application.execute(
            self._command(
                lease=lease,
                task=task,
                case_id=case_id,
                fixture_hash=fixture_hash,
                request=request,
                attempt_kind=ModelCallAttemptKind.INITIAL,
                attempt_index=1,
                parent_attempt_id=None,
                job_version=loaded.job.job_version,
            ),
            policy=loaded.policy,
        )
        retry_index = 2
        while (
            execution.result is None
            and execution.terminal_event.status is ModelCallTerminalStatus.FAILED
            and retry_index <= lease.attempt_count
        ):
            parent_attempt_id = execution.attempt.spec.id
            execution = loaded.application.execute(
                self._command(
                    lease=lease,
                    task=task,
                    case_id=case_id,
                    fixture_hash=fixture_hash,
                    request=request,
                    attempt_kind=ModelCallAttemptKind.RETRY,
                    attempt_index=retry_index,
                    parent_attempt_id=parent_attempt_id,
                    job_version=loaded.job.job_version,
                ),
                policy=loaded.policy,
            )
            retry_index += 1
        return self._result(
            execution=execution,
            lease=lease,
            task=task,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            output_schema=output_schema,
            application_output_schema=application_output_schema,
        )

    def _admission_request(
        self,
        *,
        lease: WorkerLease,
        task: PromptTestRunTask,
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> NewModelCallJobAdmissionRequest:
        return NewModelCallJobAdmissionRequest(
            project_id=task.project_id,
            job_id=task.job_id,
            job_kind=PROMPT_TEST_JOB_KIND,
            lease_token=lease.lease_token,
            fencing_generation=lease.fencing_generation,
            runtime_selection_id=task.model.runtime_selection_id,
            required_purpose=PROMPT_TEST_MODEL_PURPOSE,
            search_mode=PROMPT_TEST_SEARCH_MODE,
            usage_audience=ModelAudience.INTERNAL_WORKER,
            prompt=PromptReleaseAdmission(
                project_id=task.project_id,
                admission_mode=ModelCallAdmissionMode.PROMPT_RELEASE_TEST,
                binding_id=None,
                state_id=task.expected_state_id,
                state_version=task.expected_state_version,
                release_id=task.release_id,
                release_hash=task.release_hash,
                purpose=PROMPT_TEST_MODEL_PURPOSE,
                output_schema_hash=canonical_json_hash(output_schema),
                application_output_schema_hash=canonical_json_hash(
                    application_output_schema
                ),
                test_set_hash=task.test_set_hash,
                state_status=PromptAdmissionState.DRAFT,
                current=True,
            ),
            prompt_bundle_hash=task.input_hash,
            output_schema_hash=canonical_json_hash(output_schema),
            application_output_schema_hash=canonical_json_hash(
                application_output_schema
            ),
            maximum_paid_calls=PROMPT_TEST_MAXIMUM_PAID_CALLS,
            maximum_concurrent_calls=PROMPT_TEST_MAXIMUM_CONCURRENT_CALLS,
            admitted_by=task.requested_by,
            admitted_at=self._clock(),
        )

    @staticmethod
    def _command(
        *,
        lease: WorkerLease,
        task: PromptTestRunTask,
        case_id: UUID,
        fixture_hash: str,
        request: ModelGatewayRequest,
        attempt_kind: ModelCallAttemptKind,
        attempt_index: int,
        parent_attempt_id: UUID | None,
        job_version: int,
    ) -> ExecuteModelCall:
        return ExecuteModelCall(
            project_id=task.project_id,
            job_id=task.job_id,
            expected_job_version=job_version,
            lease_token=lease.lease_token,
            fencing_generation=lease.fencing_generation,
            route=task.model.route,
            runtime_manifest_id=task.model.runtime_manifest_id,
            runtime_manifest_hash=task.model.runtime_manifest_hash,
            runtime_option_id=task.model.runtime_selection_id,
            runtime_option_hash=task.model.runtime_selection_hash,
            prompt_binding_id=None,
            prompt_release_id=task.release_id,
            prompt_release_hash=task.release_hash,
            request=request,
            attempt_kind=attempt_kind,
            attempt_idempotency_key=(
                f"prompt-test:{task.job_id}:{case_id}:attempt:{attempt_index}"
            ),
            parent_attempt_id=parent_attempt_id,
            admission_mode=ModelCallAdmissionMode.PROMPT_RELEASE_TEST,
            prompt_state_id=task.expected_state_id,
            prompt_state_version=task.expected_state_version,
            prompt_test_set_hash=task.test_set_hash,
            prompt_test_case_id=case_id,
            prompt_test_case_hash=fixture_hash,
        )

    def _result(
        self,
        *,
        execution: ModelCallExecution,
        lease: WorkerLease,
        task: PromptTestRunTask,
        fixture_id: str,
        fixture_hash: str,
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> PromptTestCaseModelResult:
        event = execution.terminal_event
        if event.status is ModelCallTerminalStatus.FAILED:
            error_type = (
                RetryableModelGatewayError
                if event.error_retryable is True
                else ModelGatewayError
            )
            raise error_type(
                "Prompt test model attempt ended in a recorded failure",
                code=event.error_code,
                provider=task.model.route.provider,
            )
        if event.output_hash is None or event.response_hash is None:
            raise PromptTestExecutionError(
                "Successful Prompt test model call has incomplete hash lineage"
            )
        if execution.result is not None:
            output = execution.result.output
            if canonical_json_hash(output) != event.output_hash:
                raise PromptTestExecutionError(
                    "Prompt test model output differs from its terminal event"
                )
        else:
            recovered = self._result_recovery.recover_derived(
                ProviderArtifactRecoveryRequest(
                    project_id=task.project_id,
                    source_model_job_id=task.job_id,
                    recovery_job_id=task.job_id,
                    lease_token=lease.lease_token,
                    fencing_generation=lease.fencing_generation,
                    model_call_attempt_id=execution.attempt.spec.id,
                    expected_output_hash=event.output_hash,
                    output_schema=output_schema,
                    application_output_schema=application_output_schema,
                    purpose=PROMPT_TEST_MODEL_PURPOSE,
                )
            )
            if (
                recovered.model_call_attempt_id != execution.attempt.spec.id
                or recovered.output_hash != event.output_hash
            ):
                raise PromptTestExecutionError(
                    "Recovered Prompt test output differs from terminal lineage"
                )
            output = dict(recovered.output)
        return PromptTestCaseModelResult(
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            model_call_id=execution.attempt.spec.id,
            response_hash=event.response_hash,
            output=output,
        )


def _assert_job_matches_task(
    job: object,
    *,
    lease: WorkerLease,
    task: PromptTestRunTask,
    output_schema: Mapping[str, object],
    application_output_schema: Mapping[str, object],
) -> None:
    mismatches = (
        getattr(job, "project_id", None) != task.project_id,
        getattr(job, "job_id", None) != task.job_id,
        getattr(job, "job_kind", None) != PROMPT_TEST_JOB_KIND,
        getattr(job, "lease_token", None) != lease.lease_token,
        getattr(job, "fencing_generation", None) != lease.fencing_generation,
        getattr(job, "runtime_manifest_id", None) != task.model.runtime_manifest_id,
        getattr(job, "runtime_manifest_hash", None) != task.model.runtime_manifest_hash,
        getattr(job, "runtime_option_id", None) != task.model.runtime_selection_id,
        getattr(job, "runtime_option_hash", None) != task.model.runtime_selection_hash,
        getattr(job, "route", None) != task.model.route,
        getattr(job, "provider_secret_handle", None)
        != task.model.provider_secret_handle,
        getattr(job, "prompt_release_id", None) != task.release_id,
        getattr(job, "prompt_release_hash", None) != task.release_hash,
        getattr(job, "prompt_state_id", None) != task.expected_state_id,
        getattr(job, "prompt_state_version", None) != task.expected_state_version,
        getattr(job, "prompt_test_set_hash", None) != task.test_set_hash,
        getattr(job, "prompt_bundle_hash", None) != task.input_hash,
        getattr(job, "output_schema_hash", None) != canonical_json_hash(output_schema),
        getattr(job, "application_output_schema_hash", None)
        != canonical_json_hash(application_output_schema),
        getattr(job, "policy_version_id", None) != task.model.policy_version_id,
        getattr(job, "policy_version_hash", None) != task.model.policy_version_hash,
        getattr(job, "maximum_paid_calls", None)
        != PROMPT_TEST_MAXIMUM_PAID_CALLS,
        getattr(job, "maximum_concurrent_calls", None)
        != PROMPT_TEST_MAXIMUM_CONCURRENT_CALLS,
    )
    if any(mismatches):
        raise PromptTestStale(
            "Prompt test Model Gateway Job differs from its frozen task or active lease"
        )


__all__ = [
    "ModelGatewayPromptTestCaseExecutor",
    "PROMPT_TEST_MAXIMUM_CONCURRENT_CALLS",
    "PROMPT_TEST_MAXIMUM_PAID_CALLS",
    "PromptTestModelRuntime",
]
