"""Exact Prompt Program and ModelCallApplication adapters for Synthetic execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
from typing import Protocol
from uuid import UUID

from geo_core.model_gateway.application import ModelCallExecution
from geo_core.model_gateway.application_support import ExecuteModelCall
from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryPort,
    ProviderArtifactRecoveryRequest,
)
from geo_core.model_gateway.contracts import (
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.model_gateway.ports import ModelCallAttemptKind
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
from geo_core.prompts.application_models import RuntimePromptProgram
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.program_rendering import render_program_release
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.execution_contracts import (
    FrozenPromptRef,
    ResolvedSyntheticPrompt,
    SyntheticExecutionStale,
    SyntheticModelInvocation,
    SyntheticModelResult,
)


class RuntimePromptApplicationPort(Protocol):
    def resolve_runtime_binding(
        self, *, project_id, purpose: str
    ) -> RuntimePromptProgram: ...


class ModelCallApplicationPort(Protocol):
    def execute(
        self, command: ExecuteModelCall, *, policy: ModelPolicy
    ) -> ModelCallExecution: ...


class ModelResultReplayPort(Protocol):
    """Reload a governed structured result when an idempotent call is replayed."""

    def load(
        self,
        *,
        project_id,
        model_call_id,
        response_hash: str | None,
    ) -> ModelGatewayResult: ...


class SyntheticModelRuntimePort(Protocol):
    """The admission factory used only after the child Durable Job is claimed."""

    def load_or_admit_claimed_job(
        self, request: NewModelCallJobAdmissionRequest
    ) -> AdmittedModelCallJob: ...

    def load(self, *, project_id: UUID, job_id: UUID) -> LoadedModelCallRuntime: ...


class PromptProgramExecutionResolver:
    """Resolve and render exactly the frozen current Prompt binding."""

    def __init__(self, application: RuntimePromptApplicationPort) -> None:
        self._application = application

    def resolve(
        self,
        *,
        frozen: FrozenPromptRef,
        structured_input: Mapping[str, object],
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> ResolvedSyntheticPrompt:
        runtime = self._runtime(frozen)
        release = runtime.release
        spec = default_prompt_bootstrap_spec(frozen.program_kind)
        expected_hashes = (
            canonical_hash(spec.schemas.input_schema),
            canonical_hash(spec.schemas.output_schema),
            canonical_hash(spec.schemas.application_output_schema),
        )
        release_hashes = (
            canonical_hash(release.schemas.input_schema),
            canonical_hash(release.schemas.output_schema),
            canonical_hash(release.schemas.application_output_schema),
        )
        supplied_hashes = (
            expected_hashes[0],
            canonical_hash(output_schema),
            canonical_hash(application_output_schema),
        )
        if release_hashes != expected_hashes or supplied_hashes != expected_hashes:
            raise SyntheticExecutionStale(
                "Prompt input/output schema changed from the executable contract"
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
        prompt_bundle_hash = canonical_hash(
            {
                "frozen_prompt": frozen.identity_hash,
                "structured_input_hash": structured_hash,
                "compiled_system_hash": rendered.compiled_system_hash,
                "compiled_user_hash": rendered.compiled_user_hash,
                "output_schema": output_schema,
                "application_output_schema": application_output_schema,
            }
        )
        return ResolvedSyntheticPrompt(
            frozen=frozen,
            messages=(
                {"role": "system", "content": rendered.compiled_system},
                {"role": "user", "content": rendered.compiled_user},
            ),
            output_schema=output_schema,
            application_output_schema=application_output_schema,
            prompt_bundle_hash=prompt_bundle_hash,
            structured_input_hash=structured_hash,
        )

    def assert_current(self, frozen: FrozenPromptRef) -> None:
        self._runtime(frozen)

    def _runtime(self, frozen: FrozenPromptRef) -> RuntimePromptProgram:
        try:
            runtime = self._application.resolve_runtime_binding(
                project_id=frozen.project_id,
                purpose=frozen.purpose,
            )
        except Exception as error:
            raise SyntheticExecutionStale("Prompt binding resolver rejected frozen lineage") from error
        release = runtime.release
        state = runtime.state
        binding = runtime.binding
        observed = (
            release.project_id,
            binding.id,
            binding.binding_version,
            binding.frozen_state_id,
            release.id,
            release.version,
            release.release_hash,
            release.program_kind,
            release.purpose,
            release.model_policy.policy_hash,
            state.id,
            state.version,
        )
        expected = (
            frozen.project_id,
            frozen.binding_id,
            frozen.binding_version,
            frozen.frozen_state_id,
            frozen.release_id,
            frozen.release_version,
            frozen.release_hash,
            frozen.program_kind,
            frozen.purpose,
            frozen.model_policy_hash,
            frozen.frozen_state_id,
            frozen.frozen_state_version,
        )
        if observed != expected:
            raise SyntheticExecutionStale("Prompt binding, Release or policy identity changed")
        return runtime


class ModelCallExecutionAdapter:
    """Use the audited ModelCallApplication, including governed replay retrieval."""

    def __init__(
        self,
        application: ModelCallApplicationPort,
        *,
        replay: ModelResultReplayPort | None = None,
        capture_method: ModelCaptureMethod = ModelCaptureMethod.PROVIDER_API,
    ) -> None:
        self._application = application
        self._replay = replay
        self._capture_method = capture_method

    def execute(self, invocation: SyntheticModelInvocation) -> SyntheticModelResult:
        prompt = invocation.prompt
        frozen = prompt.frozen
        request = ModelGatewayRequest(
            messages=prompt.messages,
            configured_model=frozen.configured_model,
            prompt_bundle_hash=prompt.prompt_bundle_hash,
            project_id=invocation.lease.project_id,
            purpose=frozen.purpose,
            temperature=0,
            max_output_tokens=invocation.max_output_tokens,
            output_schema=prompt.output_schema,
            application_output_schema=prompt.application_output_schema,
            seed=invocation.deterministic_seed,
            idempotency_key=(
                f"synthetic:{invocation.lease.job_id}:{invocation.step_key}:"
                f"{prompt.structured_input_hash}"
            ),
            capture_method=self._capture_method,
        )
        execution = self._application.execute(
            ExecuteModelCall(
                project_id=invocation.lease.project_id,
                job_id=invocation.lease.job_id,
                expected_job_version=invocation.expected_job_version,
                lease_token=invocation.lease.lease_token,
                fencing_generation=invocation.lease.fencing_generation,
                route=frozen.route,
                runtime_manifest_id=frozen.runtime_manifest_id,
                runtime_manifest_hash=frozen.runtime_manifest_hash,
                runtime_option_id=frozen.runtime_option_id,
                runtime_option_hash=frozen.runtime_option_hash,
                prompt_binding_id=frozen.binding_id,
                prompt_release_id=frozen.release_id,
                prompt_release_hash=frozen.release_hash,
                request=request,
                attempt_kind=ModelCallAttemptKind.INITIAL,
                attempt_idempotency_key=request.idempotency_key or "",
            ),
            policy=frozen.model_policy,
        )
        result = execution.result
        if result is None:
            if self._replay is None:
                raise SyntheticExecutionStale(
                    "replayed model call has no governed structured-result loader"
                )
            result = self._replay.load(
                project_id=invocation.lease.project_id,
                model_call_id=execution.attempt.spec.id,
                response_hash=execution.terminal_event.response_hash,
            )
        return _model_result(invocation, result, model_attempt_id=execution.attempt.spec.id)


class GovernedSyntheticModelCallExecutor:
    """Admit and execute exactly one claimed Synthetic child model-call Job.

    The executor deliberately has no pre-built ``ModelCallApplication``.  A
    child Job first freezes a Model Gateway admission from the task artifact,
    then reloads that admission before any provider I/O.  This prevents a
    worker restart or a changed active runtime selection from silently
    changing the call's Prompt, route, Secret handle, or output schemas.
    """

    def __init__(
        self,
        *,
        runtime: SyntheticModelRuntimePort,
        result_recovery: ProviderArtifactRecoveryPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._runtime = runtime
        self._result_recovery = result_recovery
        self._clock = clock

    def execute(self, invocation: SyntheticModelInvocation) -> SyntheticModelResult:
        admission_request = self._admission_request(invocation)
        admitted = self._runtime.load_or_admit_claimed_job(admission_request)
        _assert_admitted_synthetic_lineage(invocation, admitted.job)
        loaded = self._runtime.load(
            project_id=invocation.lease.project_id,
            job_id=invocation.lease.job_id,
        )
        _assert_admitted_synthetic_lineage(invocation, loaded.job)
        capture_method = _capture_method(loaded)
        request = self._request(
            invocation=invocation,
            loaded=loaded,
            capture_method=capture_method,
        )
        execution = loaded.application.execute(
            ExecuteModelCall(
                project_id=invocation.lease.project_id,
                job_id=invocation.lease.job_id,
                expected_job_version=loaded.job.job_version,
                lease_token=invocation.lease.lease_token,
                fencing_generation=invocation.lease.fencing_generation,
                route=loaded.job.route,
                runtime_manifest_id=loaded.job.runtime_manifest_id,
                runtime_manifest_hash=loaded.job.runtime_manifest_hash,
                runtime_option_id=loaded.job.runtime_option_id,
                runtime_option_hash=loaded.job.runtime_option_hash,
                prompt_binding_id=invocation.prompt.frozen.binding_id,
                prompt_release_id=invocation.prompt.frozen.release_id,
                prompt_release_hash=invocation.prompt.frozen.release_hash,
                request=request,
                attempt_kind=ModelCallAttemptKind.INITIAL,
                attempt_idempotency_key=request.idempotency_key or "",
            ),
            policy=loaded.policy,
        )
        result = execution.result
        if result is None:
            result = self._recover_replayed_result(invocation, execution)
        return _model_result(invocation, result, model_attempt_id=execution.attempt.spec.id)

    def _admission_request(
        self, invocation: SyntheticModelInvocation,
    ) -> NewModelCallJobAdmissionRequest:
        frozen = invocation.prompt.frozen
        output_schema_hash = canonical_json_hash(invocation.prompt.output_schema)
        application_output_schema_hash = canonical_json_hash(
            invocation.prompt.application_output_schema
        )
        return NewModelCallJobAdmissionRequest(
            project_id=invocation.lease.project_id,
            job_id=invocation.lease.job_id,
            job_kind=invocation.lease.kind,
            lease_token=invocation.lease.lease_token,
            fencing_generation=invocation.lease.fencing_generation,
            runtime_selection_id=frozen.runtime_option_id,
            required_purpose=frozen.purpose,
            search_mode=None,
            usage_audience=ModelAudience.INTERNAL_WORKER,
            prompt=PromptReleaseAdmission(
                project_id=invocation.lease.project_id,
                admission_mode=ModelCallAdmissionMode.RUNTIME_FROZEN,
                binding_id=frozen.binding_id,
                state_id=frozen.frozen_state_id,
                state_version=frozen.frozen_state_version,
                release_id=frozen.release_id,
                release_hash=frozen.release_hash,
                purpose=frozen.purpose,
                output_schema_hash=output_schema_hash,
                application_output_schema_hash=application_output_schema_hash,
                test_set_hash=None,
                state_status=PromptAdmissionState.FROZEN,
                current=True,
            ),
            prompt_bundle_hash=invocation.prompt.prompt_bundle_hash,
            output_schema_hash=output_schema_hash,
            application_output_schema_hash=application_output_schema_hash,
            maximum_paid_calls=1,
            maximum_concurrent_calls=1,
            admitted_by=invocation.admitted_by,
            admitted_at=self._clock(),
        )

    @staticmethod
    def _request(
        *,
        invocation: SyntheticModelInvocation,
        loaded: LoadedModelCallRuntime,
        capture_method: ModelCaptureMethod,
    ) -> ModelGatewayRequest:
        frozen = invocation.prompt.frozen
        return ModelGatewayRequest(
            messages=invocation.prompt.messages,
            configured_model=frozen.configured_model,
            prompt_bundle_hash=invocation.prompt.prompt_bundle_hash,
            project_id=invocation.lease.project_id,
            purpose=frozen.purpose,
            usage_audience=ModelAudience.INTERNAL_WORKER,
            temperature=0,
            max_output_tokens=invocation.max_output_tokens,
            output_schema=invocation.prompt.output_schema,
            application_output_schema=invocation.prompt.application_output_schema,
            seed=invocation.deterministic_seed,
            idempotency_key=(
                f"synthetic:{invocation.lease.job_id}:{invocation.step_key}:"
                f"{invocation.prompt.structured_input_hash}"
            ),
            capture_method=capture_method,
            provider_secret_handle=loaded.job.provider_secret_handle,
        )

    def _recover_replayed_result(
        self,
        invocation: SyntheticModelInvocation,
        execution: ModelCallExecution,
    ) -> ModelGatewayResult:
        event = execution.terminal_event
        if (
            event.output_hash is None
            or event.response_hash is None
            or event.gateway_call_log_id is None
        ):
            raise SyntheticExecutionStale(
                "replayed Synthetic model call lacks complete governed output lineage"
            )
        recovered = self._result_recovery.recover_derived(
            ProviderArtifactRecoveryRequest(
                project_id=invocation.lease.project_id,
                source_model_job_id=invocation.lease.job_id,
                recovery_job_id=invocation.lease.job_id,
                lease_token=invocation.lease.lease_token,
                fencing_generation=invocation.lease.fencing_generation,
                model_call_attempt_id=execution.attempt.spec.id,
                expected_output_hash=event.output_hash,
                output_schema=invocation.prompt.output_schema,
                application_output_schema=invocation.prompt.application_output_schema,
                purpose=invocation.prompt.frozen.purpose,
            )
        )
        if (
            recovered.model_call_attempt_id != execution.attempt.spec.id
            or recovered.output_hash != event.output_hash
        ):
            raise SyntheticExecutionStale(
                "recovered Synthetic model output differs from governed terminal lineage"
            )
        route = invocation.prompt.frozen.route
        return ModelGatewayResult(
            output=dict(recovered.output),
            call_log_id=event.gateway_call_log_id,
            provider_request_id=event.provider_request_id,
            configured_model=event.configured_model,
            provider_reported_model=event.provider_reported_model,
            prompt_tokens=event.prompt_tokens,
            completion_tokens=event.completion_tokens,
            cost_usd=event.cost_usd,
            finish_reason=event.finish_reason,
            response_hash=event.response_hash,
            provider=route.provider,
            adapter_release_id=route.adapter_release_id,
            adapter_release_hash=route.adapter_release_hash,
            model_release_id=route.model_release_id,
            model_release_hash=route.model_release_hash,
        )


def _assert_admitted_synthetic_lineage(
    invocation: SyntheticModelInvocation,
    job: object,
) -> None:
    frozen = invocation.prompt.frozen
    mismatches = (
        getattr(job, "project_id", None) != invocation.lease.project_id,
        getattr(job, "job_id", None) != invocation.lease.job_id,
        getattr(job, "job_kind", None) != invocation.lease.kind,
        getattr(job, "lease_token", None) != invocation.lease.lease_token,
        getattr(job, "fencing_generation", None) != invocation.lease.fencing_generation,
        getattr(job, "runtime_manifest_id", None) != frozen.runtime_manifest_id,
        getattr(job, "runtime_manifest_hash", None) != frozen.runtime_manifest_hash,
        getattr(job, "runtime_option_id", None) != frozen.runtime_option_id,
        getattr(job, "runtime_option_hash", None) != frozen.runtime_option_hash,
        getattr(job, "route", None) != frozen.route,
        getattr(job, "prompt_binding_id", None) != frozen.binding_id,
        getattr(job, "prompt_release_id", None) != frozen.release_id,
        getattr(job, "prompt_release_hash", None) != frozen.release_hash,
        getattr(job, "prompt_state_id", None) != frozen.frozen_state_id,
        getattr(job, "prompt_state_version", None) != frozen.frozen_state_version,
        getattr(job, "purpose", None) != frozen.purpose,
        getattr(job, "usage_audience", None) is not ModelAudience.INTERNAL_WORKER,
        getattr(job, "prompt_bundle_hash", None) != invocation.prompt.prompt_bundle_hash,
        getattr(job, "output_schema_hash", None)
        != canonical_json_hash(invocation.prompt.output_schema),
        getattr(job, "application_output_schema_hash", None)
        != canonical_json_hash(invocation.prompt.application_output_schema),
        getattr(job, "maximum_paid_calls", None) != 1,
        getattr(job, "maximum_concurrent_calls", None) != 1,
    )
    if any(mismatches):
        raise SyntheticExecutionStale(
            "Model Gateway admission differs from the frozen Synthetic child task"
        )


def _capture_method(loaded: LoadedModelCallRuntime) -> ModelCaptureMethod:
    job = loaded.job
    adapter = loaded.composition.adapters.get(
        (job.route.provider, job.route.adapter_release_id)
    )
    runtime = getattr(adapter, "runtime", None)
    capture_method = getattr(runtime, "capture_method", None)
    if not isinstance(capture_method, ModelCaptureMethod):
        raise SyntheticExecutionStale(
            "Model Gateway runtime lacks the admitted adapter capture method"
        )
    return capture_method


def _model_result(
    invocation: SyntheticModelInvocation,
    result: ModelGatewayResult,
    *,
    model_attempt_id: UUID,
) -> SyntheticModelResult:
    frozen = invocation.prompt.frozen
    provider = result.provider or frozen.route.provider
    reported = result.provider_reported_model or result.configured_model
    identity_hash = canonical_hash(
        {
            "provider": provider,
            "adapter_release_id": result.adapter_release_id,
            "adapter_release_hash": result.adapter_release_hash,
            "model_release_id": result.model_release_id,
            "model_release_hash": result.model_release_hash,
            "configured_model": result.configured_model,
            "reported_model": reported,
        }
    )
    request_hash = canonical_hash(
        {
            "job_id": invocation.lease.job_id,
            "step_key": invocation.step_key,
            "prompt_bundle_hash": invocation.prompt.prompt_bundle_hash,
            "structured_input_hash": invocation.prompt.structured_input_hash,
            "seed": invocation.deterministic_seed,
        }
    )
    return SyntheticModelResult(
        model_attempt_id=model_attempt_id,
        model_call_id=result.call_log_id,
        output=result.output,
        provider=provider,
        configured_model=result.configured_model,
        reported_model=reported,
        model_identity_hash=identity_hash,
        request_hash=request_hash,
        response_hash=result.response_hash,
    )


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SyntheticExecutionStale("Prompt structured input is not canonical JSON")


__all__ = [
    "ModelCallApplicationPort",
    "ModelCallExecutionAdapter",
    "ModelResultReplayPort",
    "GovernedSyntheticModelCallExecutor",
    "PromptProgramExecutionResolver",
    "RuntimePromptApplicationPort",
    "SyntheticModelRuntimePort",
]
