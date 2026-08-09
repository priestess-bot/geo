"""Pure admission, identity and event helpers for model-call execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from uuid import UUID

from geo_core.jobs.lifecycle import JobStatus
from geo_core.model_gateway.application_events import empty_lineage as empty_lineage
from geo_core.model_gateway.contracts import (
    ModelCallBudget,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelIdentityError,
    ModelPolicy,
    ProviderCapabilities,
    ProviderPolicyViolation,
)
from geo_core.model_gateway.ports import (
    ModelCallAttempt,
    ModelCallAttemptDraft,
    ModelCallAttemptKind,
    ModelCallJobAdmission,
    ModelCallRepository,
    ModelCallTerminalEvent,
    ModelCallTerminalStatus,
    PromptReleaseAdmission,
    canonical_json_hash,
    hash_secret_identifier,
)
from geo_core.model_gateway.prompt_admission import (
    ModelCallAdmissionMode,
    PromptAdmissionState,
)
from geo_core.model_gateway.releases import AdapterRelease, DataUseDecision, ModelRoute


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def maximum_paid_calls_per_attempt(provider: str) -> int:
    """Return the explicit Provider HTTP-call ceiling for one logical attempt."""

    return 2 if provider == "serpapi" else 1


class ModelCallAdmissionError(ModelGatewayError):
    """Frozen Job, Prompt, release, purpose, or schema lineage did not match."""

    default_code = ModelGatewayErrorCode.POLICY


class ModelCallUnknownOutcome(ModelGatewayError):
    """A reserved call cannot be retried until a human reconciles its outcome."""

    default_code = ModelGatewayErrorCode.CONFIGURATION

    def __init__(self, attempt_id: UUID, *, provider: str) -> None:
        super().__init__(
            f"model-call attempt {attempt_id} has an unknown outcome; manual reconciliation required",
            provider=provider,
        )
        self.attempt_id = attempt_id


@dataclass(frozen=True)
class ExecuteModelCall:
    project_id: UUID
    job_id: UUID
    expected_job_version: int
    lease_token: UUID
    fencing_generation: int
    route: ModelRoute
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    prompt_binding_id: UUID | None
    prompt_release_id: UUID
    prompt_release_hash: str
    request: ModelGatewayRequest
    attempt_kind: ModelCallAttemptKind
    attempt_idempotency_key: str
    parent_attempt_id: UUID | None = None
    admission_mode: ModelCallAdmissionMode = ModelCallAdmissionMode.RUNTIME_FROZEN
    prompt_state_id: UUID | None = None
    prompt_state_version: int | None = None
    prompt_test_set_hash: str | None = None
    prompt_test_case_id: UUID | None = None
    prompt_test_case_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_kind", ModelCallAttemptKind(self.attempt_kind))
        object.__setattr__(self, "admission_mode", ModelCallAdmissionMode(self.admission_mode))
        if self.expected_job_version < 1 or self.fencing_generation < 1:
            raise ValueError("model-call Job version and fencing generation must be positive")
        for value in (
            self.project_id,
            self.job_id,
            self.lease_token,
            self.runtime_manifest_id,
            self.runtime_option_id,
            self.prompt_release_id,
        ):
            if value.int == 0:
                raise ValueError("model-call command UUIDs cannot be zero")
        for digest in (self.runtime_manifest_hash, self.runtime_option_hash):
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("model-call runtime hashes must be lowercase SHA-256")
        if self.admission_mode is ModelCallAdmissionMode.RUNTIME_FROZEN:
            if self.prompt_binding_id is None:
                raise ValueError("runtime model calls require a Prompt binding")
            if any(
                value is not None
                for value in (
                    self.prompt_state_id,
                    self.prompt_state_version,
                    self.prompt_test_set_hash,
                    self.prompt_test_case_id,
                    self.prompt_test_case_hash,
                )
            ):
                raise ValueError("runtime model calls cannot carry Prompt test lineage")
            return
        if (
            self.prompt_binding_id is not None
            or self.request.purpose != "prompt_release_test"
            or self.prompt_state_id is None
            or self.prompt_state_id.int == 0
            or self.prompt_state_version is None
            or self.prompt_state_version < 1
            or self.prompt_test_set_hash is None
            or self.prompt_test_case_id is None
            or self.prompt_test_case_id.int == 0
            or self.prompt_test_case_hash is None
        ):
            raise ValueError("Prompt test model calls require exact draft/test-case lineage")
        for digest in (self.prompt_test_set_hash, self.prompt_test_case_hash):
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("Prompt test lineage hashes must be lowercase SHA-256")


@dataclass(frozen=True)
class ModelCallExecution:
    attempt: ModelCallAttempt
    terminal_event: ModelCallTerminalEvent
    result: ModelGatewayResult | None
    replayed: bool


@dataclass(frozen=True)
class RequestIdentity:
    key_hash: str
    portable_schema_hash: str
    application_schema_hash: str
    input_hash: str
    request_hash: str

    @property
    def schema_hash(self) -> str:
        return self.portable_schema_hash


def request_identity(command: ExecuteModelCall, *, policy: ModelPolicy) -> RequestIdentity:
    request = command.request
    schema_hash = canonical_json_hash(request.output_schema or {})
    application_schema_hash = canonical_json_hash(
        request.application_output_schema or {}
    )
    input_hash = canonical_json_hash({"messages": request.messages})
    key_hash = hash_secret_identifier(command.attempt_idempotency_key)
    request_hash = canonical_json_hash(
        {
            "project_id": command.project_id,
            "job_id": command.job_id,
            "route": {
                "provider": command.route.provider,
                "adapter_release_id": command.route.adapter_release_id,
                "adapter_release_hash": command.route.adapter_release_hash,
                "model_release_id": command.route.model_release_id,
                "model_release_hash": command.route.model_release_hash,
            },
            "runtime_manifest_id": command.runtime_manifest_id,
            "runtime_manifest_hash": command.runtime_manifest_hash,
            "runtime_option_id": command.runtime_option_id,
            "runtime_option_hash": command.runtime_option_hash,
            "prompt_binding_id": command.prompt_binding_id,
            "prompt_release_id": command.prompt_release_id,
            "prompt_release_hash": command.prompt_release_hash,
            "admission_mode": command.admission_mode,
            "prompt_state_id": command.prompt_state_id,
            "prompt_state_version": command.prompt_state_version,
            "prompt_test_set_hash": command.prompt_test_set_hash,
            "prompt_test_case_id": command.prompt_test_case_id,
            "prompt_test_case_hash": command.prompt_test_case_hash,
            "attempt_kind": command.attempt_kind,
            "parent_attempt_id": command.parent_attempt_id,
            "idempotency_key_hash": key_hash,
            "input_hash": input_hash,
            "purpose": request.purpose,
            "usage_audience": request.usage_audience,
            "configured_model": request.configured_model,
            "prompt_bundle_hash": request.prompt_bundle_hash,
            "portable_output_schema_hash": schema_hash,
            "application_schema_hash": application_schema_hash,
            "temperature": request.temperature,
            "max_output_tokens": request.max_output_tokens,
            "seed": request.seed,
            "tool_mode": request.tool_mode,
            "search_mode": request.search_mode,
            "capture_method": request.capture_method,
            "requested_location": (
                request.requested_location.canonical_value()
                if request.requested_location is not None
                else None
            ),
            "expected_effective_location": (
                request.expected_effective_location.canonical_value()
                if request.expected_effective_location is not None
                else None
            ),
            "provider_secret_handle_hash": (
                canonical_json_hash(request.provider_secret_handle.as_job_payload())
                if request.provider_secret_handle is not None
                else None
            ),
            "deadline_at": request.deadline_at,
            "policy_version_id": policy.policy_version_id,
            "policy_version_hash": policy.policy_version_hash,
        }
    )
    return RequestIdentity(
        key_hash,
        schema_hash,
        application_schema_hash,
        input_hash,
        request_hash,
    )


def validate_admission(
    command: ExecuteModelCall,
    *,
    identity: RequestIdentity,
    job: ModelCallJobAdmission,
    prompt: PromptReleaseAdmission,
    policy: ModelPolicy,
    adapter_release: AdapterRelease,
) -> None:
    request = command.request
    if (
        not policy.versioned
        or policy.policy_version_id is None
        or policy.policy_version_hash is None
        or policy.maximum_paid_calls is None
        or policy.maximum_concurrent_calls is None
    ):
        raise ModelCallAdmissionError(
            "model-call execution requires an immutable project policy version",
            provider=command.route.provider,
        )
    data_policy = adapter_release.data_policy
    mismatches = (
        job.project_id != command.project_id,
        job.job_id != command.job_id,
        job.job_version != command.expected_job_version,
        job.admission_mode is not command.admission_mode,
        job.status is not JobStatus.RUNNING,
        job.lease_token != command.lease_token,
        job.fencing_generation != command.fencing_generation,
        job.route != command.route,
        job.provider_secret_handle != request.provider_secret_handle,
        job.runtime_manifest_id != command.runtime_manifest_id,
        job.runtime_manifest_hash != command.runtime_manifest_hash,
        job.runtime_option_id != command.runtime_option_id,
        job.runtime_option_hash != command.runtime_option_hash,
        job.purpose != request.purpose,
        job.usage_audience is not request.usage_audience,
        job.prompt_binding_id != command.prompt_binding_id,
        job.prompt_release_id != command.prompt_release_id,
        job.prompt_release_hash != command.prompt_release_hash,
        job.prompt_state_id != prompt.state_id,
        job.prompt_state_version != prompt.state_version,
        job.prompt_test_set_hash != prompt.test_set_hash,
        command.prompt_state_id is not None and job.prompt_state_id != command.prompt_state_id,
        command.prompt_state_version is not None
        and job.prompt_state_version != command.prompt_state_version,
        command.prompt_test_set_hash is not None
        and job.prompt_test_set_hash != command.prompt_test_set_hash,
        job.prompt_bundle_hash != request.prompt_bundle_hash,
        job.output_schema_hash != identity.schema_hash,
        job.application_output_schema_hash != identity.application_schema_hash,
        job.policy_version_id != policy.policy_version_id,
        job.policy_version_hash != policy.policy_version_hash,
        job.maximum_paid_calls > policy.maximum_paid_calls,
        job.maximum_concurrent_calls > policy.maximum_concurrent_calls,
        job.raw_artifact_policy_hash != adapter_release.data_policy_hash,
        job.raw_artifact_storage_decision != data_policy.storage.value,
        job.raw_artifact_cache_decision != data_policy.cache.value,
        job.raw_artifact_display_decision != data_policy.display.value,
        job.raw_artifact_redistribution_decision != data_policy.redistribution.value,
        job.raw_artifact_retention_days != data_policy.retention_days,
        request.capture_method is not adapter_release.expected_capture_method,
        request.project_id != command.project_id,
        prompt.project_id != command.project_id,
        prompt.admission_mode is not command.admission_mode,
        prompt.binding_id != command.prompt_binding_id,
        prompt.release_id != command.prompt_release_id,
        prompt.release_hash != command.prompt_release_hash,
        prompt.purpose != request.purpose,
        prompt.output_schema_hash != identity.schema_hash,
        prompt.application_output_schema_hash != identity.application_schema_hash,
        not prompt.current,
    )
    if any(mismatches):
        raise ModelCallAdmissionError(
            "model call does not match the exact frozen Job and Prompt Release admission",
            provider=command.route.provider,
        )
    if command.admission_mode is ModelCallAdmissionMode.RUNTIME_FROZEN:
        if prompt.state_status is not PromptAdmissionState.FROZEN:
            raise ModelCallAdmissionError(
                "runtime model call requires an exact frozen Prompt binding",
                provider=command.route.provider,
            )
    elif (
        prompt.state_status is not PromptAdmissionState.DRAFT
        or command.prompt_test_case_id is None
        or command.prompt_test_case_hash is None
    ):
        raise ModelCallAdmissionError(
            "Prompt test model call requires current draft and test-case lineage",
            provider=command.route.provider,
        )


def validate_parent(
    repository: ModelCallRepository,
    command: ExecuteModelCall,
    *,
    job: ModelCallJobAdmission,
) -> None:
    if command.attempt_kind is ModelCallAttemptKind.INITIAL:
        if command.parent_attempt_id is not None:
            raise ModelCallAdmissionError("initial model calls cannot have a parent")
        return
    if command.parent_attempt_id is None:
        raise ModelCallAdmissionError("retry and repair model calls require a parent")
    parent = repository.get_attempt(
        project_id=command.project_id,
        attempt_id=command.parent_attempt_id,
    )
    terminal = repository.get_terminal_event(
        project_id=command.project_id,
        attempt_id=command.parent_attempt_id,
    )
    if (
        parent is None
        or terminal is None
        or parent.spec.job_id != command.job_id
        or parent.spec.admission_mode is not job.admission_mode
        or parent.spec.route != command.route
        or parent.spec.provider_secret_handle != job.provider_secret_handle
        or parent.spec.runtime_manifest_id != job.runtime_manifest_id
        or parent.spec.runtime_manifest_hash != job.runtime_manifest_hash
        or parent.spec.runtime_option_id != job.runtime_option_id
        or parent.spec.runtime_option_hash != job.runtime_option_hash
        or parent.spec.purpose != command.request.purpose
        or parent.spec.usage_audience is not command.request.usage_audience
        or parent.spec.prompt_binding_id != command.prompt_binding_id
        or parent.spec.prompt_release_id != command.prompt_release_id
        or parent.spec.prompt_release_hash != command.prompt_release_hash
        or parent.spec.prompt_state_id != job.prompt_state_id
        or parent.spec.prompt_state_version != job.prompt_state_version
        or parent.spec.prompt_test_set_hash != job.prompt_test_set_hash
        or parent.spec.prompt_test_case_id != command.prompt_test_case_id
        or parent.spec.prompt_test_case_hash != command.prompt_test_case_hash
        or parent.spec.prompt_bundle_hash != command.request.prompt_bundle_hash
        or parent.spec.output_schema_hash
        != canonical_json_hash(command.request.output_schema or {})
        or parent.spec.application_output_schema_hash
        != canonical_json_hash(command.request.application_output_schema or {})
        or parent.spec.configured_model != command.request.configured_model
        or parent.spec.search_mode != command.request.search_mode
        or parent.spec.capture_method != command.request.capture_method
        or parent.spec.requested_location != command.request.requested_location
        or parent.spec.expected_effective_location
        != command.request.expected_effective_location
        or parent.spec.policy_version_id != job.policy_version_id
        or parent.spec.policy_version_hash != job.policy_version_hash
        or parent.spec.raw_artifact_policy_hash != job.raw_artifact_policy_hash
        or parent.spec.raw_artifact_storage_decision != job.raw_artifact_storage_decision
        or parent.spec.raw_artifact_cache_decision != job.raw_artifact_cache_decision
        or parent.spec.raw_artifact_display_decision != job.raw_artifact_display_decision
        or parent.spec.raw_artifact_redistribution_decision
        != job.raw_artifact_redistribution_decision
        or parent.spec.raw_artifact_retention_days != job.raw_artifact_retention_days
        or terminal.status is not ModelCallTerminalStatus.FAILED
    ):
        raise ModelCallAdmissionError(
            "retry/repair requires a terminal failed parent with the same frozen lineage"
        )
    if command.attempt_kind is ModelCallAttemptKind.RETRY and terminal.error_retryable is not True:
        raise ModelCallAdmissionError("retry parent is not retryable")
    if (
        command.attempt_kind is ModelCallAttemptKind.RETRY
        and parent.spec.input_hash != canonical_json_hash({"messages": command.request.messages})
    ):
        raise ModelCallAdmissionError("retry must preserve the parent input hash")
    if (
        command.attempt_kind is ModelCallAttemptKind.REPAIR
        and terminal.error_code is not ModelGatewayErrorCode.SCHEMA_INVALID
    ):
        raise ModelCallAdmissionError("repair requires a structured-output failure parent")


def attempt_draft(
    command: ExecuteModelCall,
    *,
    identity: RequestIdentity,
    attempt_id: UUID,
    job: ModelCallJobAdmission,
) -> ModelCallAttemptDraft:
    request = command.request
    return ModelCallAttemptDraft(
        id=attempt_id,
        project_id=command.project_id,
        job_id=command.job_id,
        job_version=command.expected_job_version,
        admission_mode=job.admission_mode,
        lease_token=command.lease_token,
        fencing_generation=command.fencing_generation,
        kind=command.attempt_kind,
        parent_attempt_id=command.parent_attempt_id,
        idempotency_key_hash=identity.key_hash,
        request_hash=identity.request_hash,
        input_hash=identity.input_hash,
        purpose=request.purpose,
        usage_audience=request.usage_audience,
        route=command.route,
        provider_secret_handle=job.provider_secret_handle,
        runtime_manifest_id=job.runtime_manifest_id,
        runtime_manifest_hash=job.runtime_manifest_hash,
        runtime_option_id=job.runtime_option_id,
        runtime_option_hash=job.runtime_option_hash,
        prompt_binding_id=command.prompt_binding_id,
        prompt_release_id=command.prompt_release_id,
        prompt_release_hash=command.prompt_release_hash,
        prompt_state_id=job.prompt_state_id,
        prompt_state_version=job.prompt_state_version,
        prompt_test_set_hash=job.prompt_test_set_hash,
        prompt_test_case_id=command.prompt_test_case_id,
        prompt_test_case_hash=command.prompt_test_case_hash,
        prompt_bundle_hash=request.prompt_bundle_hash,
        output_schema_hash=identity.schema_hash,
        application_output_schema_hash=identity.application_schema_hash,
        policy_version_id=job.policy_version_id,
        policy_version_hash=job.policy_version_hash,
        raw_artifact_policy_hash=job.raw_artifact_policy_hash,
        raw_artifact_storage_decision=job.raw_artifact_storage_decision,
        raw_artifact_cache_decision=job.raw_artifact_cache_decision,
        raw_artifact_display_decision=job.raw_artifact_display_decision,
        raw_artifact_redistribution_decision=job.raw_artifact_redistribution_decision,
        raw_artifact_retention_days=job.raw_artifact_retention_days,
        configured_model=request.configured_model,
        search_mode=request.search_mode,
        capture_method=request.capture_method,
        requested_location=request.requested_location,
        expected_effective_location=request.expected_effective_location,
    )


def validate_capabilities(request: ModelGatewayRequest, capabilities: ProviderCapabilities) -> None:
    unsupported = (
        (request.seed is not None and not capabilities.supports_seed, "seed"),
        (request.tool_mode is not None and not capabilities.supports_tools, "tool mode"),
        (
            request.search_mode not in (None, "disabled") and not capabilities.supports_search,
            "search mode",
        ),
        (
            request.idempotency_key is not None and not capabilities.supports_idempotency,
            "provider idempotency",
        ),
    )
    for blocked, label in unsupported:
        if blocked:
            raise ProviderPolicyViolation(
                f"exact Adapter Release does not support {label}",
                provider=capabilities.provider,
            )


def validate_result_identity(result: ModelGatewayResult, *, command: ExecuteModelCall) -> None:
    route = command.route
    request = command.request
    if (
        result.provider != route.provider
        or result.adapter_release_id != route.adapter_release_id
        or result.adapter_release_hash != route.adapter_release_hash
        or result.model_release_id != route.model_release_id
        or result.model_release_hash != route.model_release_hash
        or result.configured_model != request.configured_model
        or result.search_mode != request.search_mode
        or result.capture_method != request.capture_method
    ):
        raise ModelIdentityError(
            "model result does not carry the exact admitted release and capture identity",
            provider=route.provider,
        )


def bind_result_artifact_policy(
    result: ModelGatewayResult,
    *,
    adapter_release: AdapterRelease,
    request: ModelGatewayRequest,
) -> ModelGatewayResult:
    data_policy = adapter_release.data_policy
    expected = (
        adapter_release.data_policy_hash,
        data_policy.storage.value,
        data_policy.cache.value,
        data_policy.display.value,
        data_policy.redistribution.value,
        data_policy.retention_days,
        request.purpose,
        request.usage_audience,
    )
    declared = (
        result.raw_artifact_policy_hash,
        result.raw_artifact_storage_decision,
        result.raw_artifact_cache_decision,
        result.raw_artifact_display_decision,
        result.raw_artifact_redistribution_decision,
        result.raw_artifact_retention_days,
        result.usage_purpose,
        result.usage_audience,
    )
    if any(value is not None for value in declared) and declared != expected:
        raise ModelIdentityError(
            "model result raw-artifact policy differs from the exact Adapter Release",
            provider=adapter_release.provider,
        )
    if (
        result.raw_artifact_reference is not None or result.derived_artifact_reference is not None
    ) and data_policy.storage is not DataUseDecision.ALLOWED:
        raise ProviderPolicyViolation(
            "exact Adapter Release prohibits raw-artifact storage",
            provider=adapter_release.provider,
        )
    return replace(
        result,
        raw_artifact_policy_hash=expected[0],
        raw_artifact_storage_decision=expected[1],
        raw_artifact_cache_decision=expected[2],
        raw_artifact_display_decision=expected[3],
        raw_artifact_redistribution_decision=expected[4],
        raw_artifact_retention_days=expected[5],
        usage_purpose=expected[6],
        usage_audience=expected[7],
    )


def provider_outcome_is_unknown(error: ModelGatewayError, paid_budget: ModelCallBudget) -> bool:
    return (
        paid_budget.consumed_calls > 0
        and error.status_code is None
        and error.code
        in {ModelGatewayErrorCode.TIMEOUT, ModelGatewayErrorCode.PROVIDER_UNAVAILABLE}
    )
