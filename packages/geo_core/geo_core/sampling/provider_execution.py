"""Fenced Provider API execution joining Sampling Core to the Model Gateway."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
import hashlib
from typing import Callable
from uuid import UUID

from geo_core.jobs import JobStatus, LeaseConflict
from geo_core.model_gateway.application import ModelCallApplication
from geo_core.model_gateway.application_support import (
    ExecuteModelCall,
    ModelCallExecution,
    ModelCallUnknownOutcome,
)
from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryPort,
    ProviderArtifactRecoveryRequest,
    RecoveredProviderArtifact,
)
from geo_core.model_gateway.contracts import (
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.ports import ModelCallAttemptKind, ModelCallTerminalStatus
from geo_core.model_gateway.location import (
    EffectiveModelLocation,
    ModelLocationControl,
    RequestedModelLocation,
)
from geo_core.sampling.application import SamplingApplication
from geo_core.sampling.contracts import (
    CaptureMethod,
    EvidenceStatus,
    LocationControl,
    SamplingConflict,
    SamplingNotFound,
    SamplingRun,
    SamplingRunStatus,
    SamplingSuite,
    SamplingTask,
    SamplingTaskStatus,
)
from geo_core.sampling.execution import SamplingActualLocationLineage, SamplingAttempt
from geo_core.sampling.lifecycle import AttemptTransitionResult, ObservationCommitResult
from geo_core.sampling.ports import SamplingUnitOfWorkFactory
from geo_core.sampling.provider_execution_contracts import (
    ExecuteProviderSampling,
    ProviderAttemptObservationLineage,
    ProviderSamplingAdmissionError,
    ProviderSamplingPrompt,
)
from geo_core.sampling.provider_observation import (
    location_ineligibility,
    map_provider_success,
)


class ProviderSamplingUnknownOutcome(RuntimeError):
    """A paid call may have happened and must be reconciled before any retry."""

    def __init__(self, model_call_attempt_id: UUID) -> None:
        super().__init__(
            f"model-call attempt {model_call_attempt_id} requires manual reconciliation"
        )
        self.model_call_attempt_id = model_call_attempt_id


class ProviderSamplingFailureClass(StrEnum):
    INVALID_SCHEMA = "invalid_schema"
    REFUSAL = "refusal"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"
    QUOTA = "quota"
    TRANSIENT_PROVIDER = "transient_provider"
    CANCELLED = "cancelled"
    POLICY = "policy"
    RESULT_CONTRACT = "result_contract"
    CONFIGURATION = "configuration"
    BUDGET = "budget"


class ProviderSamplingFailure(RuntimeError):
    """A known classified failure whose Sampling Attempt was terminally recorded."""

    def __init__(
        self,
        *,
        classification: ProviderSamplingFailureClass,
        retryable: bool,
        provider_error_code: ModelGatewayErrorCode,
        transition: AttemptTransitionResult,
    ) -> None:
        super().__init__(f"provider sampling failed: {classification.value}")
        self.classification = classification
        self.retryable = retryable
        self.provider_error_code = provider_error_code
        self.transition = transition

    @property
    def automatic_retry_allowed(self) -> bool:
        return self.retryable and self.transition.task.status is SamplingTaskStatus.RETRY_READY


@dataclass(frozen=True)
class ProviderSamplingSuccess:
    sampling: ObservationCommitResult
    model_call: ModelCallExecution
    lineage: ProviderAttemptObservationLineage


@dataclass(frozen=True)
class _SamplingContext:
    suite: SamplingSuite
    run: SamplingRun
    task: SamplingTask
    attempt: SamplingAttempt


class ProviderSamplingExecutionService:
    """Execute one admitted API Attempt through exactly one frozen provider route."""

    def __init__(
        self,
        *,
        sampling_uow_factory: SamplingUnitOfWorkFactory,
        model_calls: ModelCallApplication,
        clock: Callable[[], datetime],
        result_recovery: ProviderArtifactRecoveryPort | None = None,
    ) -> None:
        self._sampling_uow_factory = sampling_uow_factory
        self._sampling = SamplingApplication(sampling_uow_factory)
        self._model_calls = model_calls
        self._clock = clock
        self._result_recovery = result_recovery

    def execute(
        self,
        command: ExecuteProviderSampling,
        *,
        policy: ModelPolicy,
    ) -> ProviderSamplingSuccess:
        context = self._load_context(command, now=self._clock())
        model_command = _build_model_command(command, context)
        try:
            model_call = self._model_calls.execute(model_command, policy=policy)
        except ModelCallUnknownOutcome as error:
            raise ProviderSamplingUnknownOutcome(error.attempt_id) from error
        except ModelGatewayError as error:
            raise self._record_known_failure(command, context, error) from error

        if model_call.result is None:
            model_call = self._recover_replayed_success(
                command,
                context,
                model_call,
            )
        assert model_call.result is not None
        try:
            lineage, evidence = map_provider_success(
                command, context.suite, context.attempt, model_call
            )
        except ProviderSamplingAdmissionError as error:
            contract_error = ModelGatewayError(
                str(error),
                code=ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION,
                provider=command.route.provider,
            )
            raise self._record_known_failure(command, context, contract_error) from error

        ineligible_reasons = location_ineligibility(context.suite, model_call.result)
        committed = self._sampling.finalize_observation(
            project_id=command.project_id,
            run_id=command.run_id,
            task_id=command.task_id,
            attempt_id=command.attempt_id,
            expected_task_version=context.task.version,
            expected_attempt_version=context.attempt.record_version,
            token=command.lease_token,
            generation=command.fencing_generation,
            now=self._clock(),
            evidence_status=(
                EvidenceStatus.INELIGIBLE
                if ineligible_reasons
                else EvidenceStatus.COMPLETE
            ),
            ineligible_reasons=ineligible_reasons,
            evidence=evidence,
            actual_location=SamplingActualLocationLineage(
                location_control=LocationControl(lineage.location_control),
                location_evidence_hash=lineage.location_evidence_hash,
                requested_country=lineage.requested_country,
                requested_region=lineage.requested_region,
                requested_locale=lineage.requested_locale,
                requested_language=lineage.requested_language,
                effective_country=lineage.effective_country,
                effective_region=lineage.effective_region,
                effective_locale=lineage.effective_locale,
                effective_language=lineage.effective_language,
            ),
        )
        return ProviderSamplingSuccess(committed, model_call, lineage)

    def _recover_replayed_success(
        self,
        command: ExecuteProviderSampling,
        context: _SamplingContext,
        execution: ModelCallExecution,
    ) -> ModelCallExecution:
        event = execution.terminal_event
        recovery = self._result_recovery
        if (
            recovery is None
            or not execution.replayed
            or event.status is not ModelCallTerminalStatus.SUCCEEDED
            or event.output_hash is None
        ):
            raise ProviderSamplingUnknownOutcome(execution.attempt.spec.id)
        try:
            recovered = recovery.recover_derived(
                ProviderArtifactRecoveryRequest(
                    project_id=command.project_id,
                    source_model_job_id=context.attempt.id,
                    recovery_job_id=context.attempt.id,
                    lease_token=command.lease_token,
                    fencing_generation=command.fencing_generation,
                    model_call_attempt_id=execution.attempt.spec.id,
                    expected_output_hash=event.output_hash,
                    output_schema=command.prompt.output_schema,
                    application_output_schema=(
                        command.prompt.application_output_schema
                    ),
                    purpose=context.run.purpose,
                )
            )
            result = _recovered_model_result(execution, recovered)
        except Exception as error:
            raise ProviderSamplingUnknownOutcome(execution.attempt.spec.id) from error
        return replace(execution, result=result)

    def _load_context(self, command: ExecuteProviderSampling, *, now: datetime) -> _SamplingContext:
        with self._sampling_uow_factory(project_id=command.project_id) as unit_of_work:
            repository = unit_of_work.sampling
            run = repository.get_run(project_id=command.project_id, run_id=command.run_id)
            task = repository.get_task(
                project_id=command.project_id,
                run_id=command.run_id,
                task_id=command.task_id,
            )
            attempt = repository.get_attempt(
                project_id=command.project_id,
                attempt_id=command.attempt_id,
            )
            if run is None or task is None or attempt is None:
                raise SamplingNotFound("Provider Sampling Run, Task, or Attempt does not exist")
            suite = repository.get_suite(
                project_id=command.project_id,
                suite_id=run.suite_id,
            )
            if suite is None:
                raise SamplingNotFound("Provider Sampling Suite does not exist")
        context = _SamplingContext(suite, run, task, attempt)
        _validate_context(command, context, now=now)
        return context

    def _record_known_failure(
        self,
        command: ExecuteProviderSampling,
        context: _SamplingContext,
        error: ModelGatewayError,
    ) -> ProviderSamplingFailure:
        classification = _classify_failure(error.code)
        transition = self._sampling.fail_attempt(
            project_id=command.project_id,
            run_id=command.run_id,
            task_id=command.task_id,
            attempt_id=command.attempt_id,
            expected_task_version=context.task.version,
            expected_attempt_version=context.attempt.record_version,
            token=command.lease_token,
            generation=command.fencing_generation,
            now=self._clock(),
            error_code=f"provider_sampling.{classification.value}",
        )
        return ProviderSamplingFailure(
            classification=classification,
            retryable=error.retryable,
            provider_error_code=error.code,
            transition=transition,
        )


def _validate_context(
    command: ExecuteProviderSampling,
    context: _SamplingContext,
    *,
    now: datetime,
) -> None:
    suite, run, task, attempt = (
        context.suite,
        context.run,
        context.task,
        context.attempt,
    )
    source = suite.source_stratum
    if run.status is not SamplingRunStatus.RUNNING or task.status is not SamplingTaskStatus.RUNNING:
        raise ProviderSamplingAdmissionError("Provider Sampling requires a running Run and Task")
    if (
        task.version != command.expected_task_version
        or attempt.record_version != command.expected_attempt_version
    ):
        raise SamplingConflict("Provider Sampling Task/Attempt optimistic version check failed")
    if (
        attempt.task_id != task.id
        or attempt.run_id != run.id
        or not task.attempt_ids
        or task.attempt_ids[-1] != attempt.id
    ):
        raise ProviderSamplingAdmissionError("Provider Sampling Attempt is not current")
    if source.capture_method not in {
        CaptureMethod.PROVIDER_API,
        CaptureMethod.PROXY_GROUNDED_API,
    }:
        raise ProviderSamplingAdmissionError(
            "Provider execution excludes manual_ui, automated_ui, Browser, and Egress"
        )
    if (
        task.identity.capture_method is not source.capture_method
        or task.identity.platform != source.platform
        or task.identity.adapter_release != source.adapter_release
        or task.identity.source_stratum_hash != source.stratum_hash
        or task.identity.region != source.region
        or task.identity.language != source.language
        or task.identity.location_control is not source.location_control
        or task.identity.location_evidence_hash != source.location_evidence_hash
        or task.identity.repetition > suite.repetitions
    ):
        raise ProviderSamplingAdmissionError("Task differs from its frozen SourceStratum")
    question = next(
        (
            item
            for item in suite.questions
            if item.question_id == task.identity.question_id
            and item.question_version == task.identity.question_version
        ),
        None,
    )
    if (
        question is None
        or hashlib.sha256(command.question_text.encode()).hexdigest() != question.text_hash
    ):
        raise ProviderSamplingAdmissionError("question text does not match its frozen hash")
    if (
        command.route.provider != source.platform
        or command.route.adapter_release_id != source.adapter_release
    ):
        raise ProviderSamplingAdmissionError("route differs from Task provider/Adapter Release")
    _validate_fence(command, attempt, now=now)


def _validate_fence(
    command: ExecuteProviderSampling,
    attempt: SamplingAttempt,
    *,
    now: datetime,
) -> None:
    job = attempt.job
    if (
        job.status is not JobStatus.RUNNING
        or job.spec.kind != "sampling.provider_execute"
        or job.lease_token != command.lease_token
        or job.fencing_generation != command.fencing_generation
        or job.lease_expires_at is None
        or job.lease_expires_at <= now
        or job.cancel_requested_at is not None
    ):
        raise LeaseConflict("Provider Sampling lease is absent, expired, cancelled, or fenced")


def _build_model_command(
    command: ExecuteProviderSampling,
    context: _SamplingContext,
) -> ExecuteModelCall:
    source = context.suite.source_stratum
    request = ModelGatewayRequest(
        messages=(
            {"role": "system", "content": command.prompt.system_message},
            {"role": "user", "content": command.question_text},
        ),
        configured_model=source.configured_model,
        prompt_bundle_hash=command.prompt.bundle_hash,
        project_id=command.project_id,
        purpose=context.run.purpose,
        temperature=command.prompt.temperature,
        max_output_tokens=command.prompt.max_output_tokens,
        output_schema=command.prompt.output_schema,
        application_output_schema=command.prompt.application_output_schema,
        seed=command.prompt.seed,
        tool_mode=command.prompt.tool_mode,
        search_mode=source.search_mode,
        deadline_at=command.deadline_at,
        capture_method=ModelCaptureMethod(source.capture_method.value),
        provider_secret_handle=command.provider_secret_handle,
        requested_location=RequestedModelLocation(
            country_code=source.requested_country,
            region_code=source.requested_region,
            locale=source.requested_locale,
            language=source.requested_language,
        ),
        expected_effective_location=EffectiveModelLocation(
            control=ModelLocationControl(source.location_control.value),
            country_code=source.effective_country,
            region_code=source.effective_region,
            locale=source.effective_locale,
            language=source.effective_language,
            evidence_hash=source.location_evidence_hash,
        ),
    )
    return ExecuteModelCall(
        project_id=command.project_id,
        job_id=context.attempt.id,
        expected_job_version=context.attempt.record_version,
        lease_token=command.lease_token,
        fencing_generation=command.fencing_generation,
        route=command.route,
        runtime_manifest_id=context.suite.runtime_manifest_id,
        runtime_manifest_hash=context.suite.runtime_manifest_hash,
        runtime_option_id=context.suite.runtime_option_id,
        runtime_option_hash=context.suite.runtime_option_hash,
        prompt_binding_id=command.prompt.binding_id,
        prompt_release_id=command.prompt.release_id,
        prompt_release_hash=command.prompt.release_hash,
        request=request,
        attempt_kind=ModelCallAttemptKind.INITIAL,
        attempt_idempotency_key=f"provider-sampling:{context.attempt.id}:initial",
    )


def _recovered_model_result(
    execution: ModelCallExecution,
    recovered: RecoveredProviderArtifact,
) -> ModelGatewayResult:
    """Rebuild only fields authenticated by call-log and artifact lineage."""
    attempt = execution.attempt.spec
    event = execution.terminal_event
    bundle = recovered.bundle_lineage
    if (
        bundle is None
        or recovered.model_call_attempt_id != attempt.id
        or event.attempt_id != attempt.id
        or event.status is not ModelCallTerminalStatus.SUCCEEDED
        or event.gateway_call_log_id is None
        or event.output_hash != recovered.output_hash
        or event.response_hash is None
        or event.provider_reported_model is None
        or event.lineage.capture_method is None
        or event.lineage.search_mode is None
        or attempt.requested_location is None
        or event.lineage.effective_location is None
        or bundle.derived_manifest_hash != recovered.manifest_hash
        or bundle.derived_content_hash != recovered.content_hash
    ):
        raise ProviderSamplingAdmissionError(
            "recovered Provider result has incomplete authenticated lineage"
        )
    route = attempt.route
    lineage = event.lineage
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
        raw_artifact_reference=bundle.raw_manifest_reference,
        raw_artifact_manifest_hash=bundle.raw_manifest_hash,
        raw_artifact_content_hash=bundle.raw_content_hash,
        raw_artifact_byte_size=bundle.raw_byte_size,
        derived_artifact_reference=bundle.derived_manifest_reference,
        derived_artifact_manifest_hash=bundle.derived_manifest_hash,
        derived_artifact_content_hash=bundle.derived_content_hash,
        derived_artifact_byte_size=bundle.derived_byte_size,
        raw_artifact_policy_hash=bundle.data_policy_hash,
        raw_artifact_storage_decision=bundle.storage_decision,
        raw_artifact_cache_decision=bundle.cache_decision,
        raw_artifact_display_decision=bundle.display_decision,
        raw_artifact_redistribution_decision=bundle.redistribution_decision,
        raw_artifact_retention_days=bundle.retention_days,
        usage_purpose=lineage.usage_purpose,
        usage_audience=lineage.usage_audience,
        capture_method=lineage.capture_method,
        search_mode=lineage.search_mode,
        requested_location=attempt.requested_location,
        effective_location=lineage.effective_location,
    )


def _classify_failure(code: ModelGatewayErrorCode) -> ProviderSamplingFailureClass:
    return {
        ModelGatewayErrorCode.SCHEMA_INVALID: ProviderSamplingFailureClass.INVALID_SCHEMA,
        ModelGatewayErrorCode.CONTENT_REFUSAL: ProviderSamplingFailureClass.REFUSAL,
        ModelGatewayErrorCode.RATE_LIMIT: ProviderSamplingFailureClass.RATE_LIMIT,
        ModelGatewayErrorCode.AUTH: ProviderSamplingFailureClass.AUTHENTICATION,
        ModelGatewayErrorCode.QUOTA: ProviderSamplingFailureClass.QUOTA,
        ModelGatewayErrorCode.TIMEOUT: ProviderSamplingFailureClass.TRANSIENT_PROVIDER,
        ModelGatewayErrorCode.PROVIDER_UNAVAILABLE: (
            ProviderSamplingFailureClass.TRANSIENT_PROVIDER
        ),
        ModelGatewayErrorCode.CANCELLED: ProviderSamplingFailureClass.CANCELLED,
        ModelGatewayErrorCode.POLICY: ProviderSamplingFailureClass.POLICY,
        ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION: (
            ProviderSamplingFailureClass.RESULT_CONTRACT
        ),
        ModelGatewayErrorCode.CONFIGURATION: ProviderSamplingFailureClass.CONFIGURATION,
        ModelGatewayErrorCode.BUDGET_EXCEEDED: ProviderSamplingFailureClass.BUDGET,
        ModelGatewayErrorCode.CONCURRENCY_LIMIT: ProviderSamplingFailureClass.BUDGET,
    }[code]


__all__ = [
    "ExecuteProviderSampling",
    "ProviderAttemptObservationLineage",
    "ProviderSamplingAdmissionError",
    "ProviderSamplingExecutionService",
    "ProviderSamplingFailure",
    "ProviderSamplingFailureClass",
    "ProviderSamplingPrompt",
    "ProviderSamplingSuccess",
    "ProviderSamplingUnknownOutcome",
]
