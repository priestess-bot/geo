"""Fenced PostgreSQL operations for the two non-browser Workflow C samplers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from geo_core.jobs.postgres import LeaseHeartbeat, PostgresDurableJobStore, WorkerLease
from geo_core.model_gateway import (
    ExecuteModelCall,
    ModelAudience,
    ModelCallAdmissionMode,
    ModelCallAttemptKind,
    ModelCallTerminalStatus,
    ModelCallUnknownOutcome,
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayRequest,
    PromptAdmissionState,
    PromptReleaseAdmission,
    RequestedModelLocation,
)
from geo_core.model_gateway.application_support import (
    ModelCallExecution,
    maximum_paid_calls_per_attempt,
)
from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryPort,
    ProviderArtifactRecoveryRequest,
)
from geo_core.model_gateway.location import EffectiveModelLocation, ModelLocationControl
from geo_core.model_gateway.runtime_execution import (
    LoadedModelCallRuntime,
    NewModelCallJobAdmissionRequest,
)
from geo_core.sampling.postgres_worker_contracts import (
    ManualSamplingWorkerSpec,
    ProviderSamplingWorkerSpec,
    parse_manual_sampling_spec,
    parse_provider_sampling_spec,
)
from geo_core.sampling.provider_sources import gateway_provider_for_source
from geo_core.sampling.postgres_worker_evidence import (
    build_manual_commit,
    build_provider_commit,
)
from geo_core.sampling.postgres_worker_repository import (
    ManualSamplingExecutionState,
    PostgresWorkflowCSamplingRepository,
    SamplingExecutionState,
    WorkflowCSamplingWorkerError,
)
from geo_core.sampling.provider_model_retries import (
    execute_provider_model_attempt_chain,
)
from geo_core.workflow_c_artifacts.reader import (
    PostgresWorkflowCManualArtifactReader,
    WorkflowCManualArtifactReadRequest,
)
from geo_core.workflow_c_job_specs import (
    PostgresWorkflowCJobSpecRepository,
    WorkflowCJobSpec,
)
PROVIDER_EXECUTE_KIND = "sampling.provider_execute"
MANUAL_IMPORT_KIND = "sampling.manual_import"
class ModelRuntimePort(Protocol):
    def load_or_admit_claimed_job(
        self, request: NewModelCallJobAdmissionRequest
    ) -> object: ...

    def load(self, *, project_id: UUID, job_id: UUID) -> LoadedModelCallRuntime: ...


class PostgresProviderSamplingOperation:
    """Execute one governed Provider API attempt under a durable fenced lease."""

    kind = PROVIDER_EXECUTE_KIND

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        specs: PostgresWorkflowCJobSpecRepository,
        repository: PostgresWorkflowCSamplingRepository,
        model_runtime: ModelRuntimePort,
        result_recovery: ProviderArtifactRecoveryPort,
        lease_for: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _validate_lease(lease_for)
        self._store = store
        self._specs = specs
        self._repository = repository
        self._model_runtime = model_runtime
        self._result_recovery = result_recovery
        self._lease_for = lease_for
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        if lease.kind != self.kind:
            raise WorkflowCSamplingWorkerError("provider sampling Worker kind is invalid")
        job_spec = self._specs.load(lease)
        spec = parse_provider_sampling_spec(job_spec.payload)
        state = self._repository.provider_state(project_id=lease.project_id, spec=spec)
        _assert_lease_job(lease, state)
        # Claiming the Durable Job atomically moves the aggregate to running and
        # increments its fenced versions.  The immutable spec remains the
        # admission baseline; terminal writes use the claimed aggregate version.
        spec = replace(
            spec,
            task_version=state.task_version,
            attempt_version=state.attempt_version,
        )
        try:
            execution = self._execute_model(lease, spec, state)
            result = _result_from_execution(
                execution,
                project_id=lease.project_id,
                job_id=lease.job_id,
                lease=lease,
                output_schema=spec.prompt.output_schema,
                application_output_schema=spec.prompt.application_output_schema,
                purpose=state.run_purpose,
                recovery=self._result_recovery,
            )
            output_hash = execution.terminal_event.output_hash
            if output_hash is None:
                raise WorkflowCSamplingWorkerError("provider model output hash is unavailable")
            commit = build_provider_commit(
                project_id=lease.project_id,
                spec=spec,
                task_key=state.task_key,
                question_id=state.question_id,
                question_version=state.question_version,
                source=state.source,
                result=result,
                model_attempt_id=execution.attempt.spec.id,
                output_hash=output_hash,
                observed_at=self._clock(),
            )
        except ModelCallUnknownOutcome:
            # The durable dispatcher must reconcile an ambiguous paid call.
            raise
        except ModelGatewayError as error:
            return self._terminal_failure(
                lease,
                job_spec,
                state,
                spec,
                f"provider_{error.code.value}",
                error.retryable,
            )
        except (WorkflowCSamplingWorkerError, ValueError):
            return self._terminal_failure(
                lease, job_spec, state, spec, "provider_contract_invalid", False
            )
        with self._store.fenced_transaction(lease) as connection:
            self._repository.commit_provider(
                connection=connection,
                lease=lease,
                spec_hash=job_spec.spec_hash,
                state=state,
                spec=spec,
                commit=commit,
            )
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"workflow-c-observation:{commit.observation_id}",
                details={
                    "observation_id": str(commit.observation_id),
                    "evidence_status": commit.evidence_status,
                },
            )
        return {
            "status": "succeeded",
            "job_id": str(lease.job_id),
            "observation_id": str(commit.observation_id),
            "evidence_status": commit.evidence_status,
        }

    def _execute_model(
        self,
        lease: WorkerLease,
        spec: ProviderSamplingWorkerSpec,
        state: SamplingExecutionState,
    ) -> ModelCallExecution:
        prompt = spec.prompt.as_provider_prompt()
        source = state.source.source
        expected_provider = gateway_provider_for_source(
            platform=source.platform,
            surface=source.surface,
            capture_method=source.capture_method,
        )
        admission = PromptReleaseAdmission(
            project_id=lease.project_id,
            admission_mode=ModelCallAdmissionMode.RUNTIME_FROZEN,
            binding_id=prompt.binding_id,
            state_id=spec.prompt.state_id,
            state_version=spec.prompt.state_version,
            release_id=prompt.release_id,
            release_hash=prompt.release_hash,
            purpose=spec.prompt.purpose,
            output_schema_hash=prompt.output_schema_hash,
            application_output_schema_hash=prompt.application_output_schema_hash,
            test_set_hash=None,
            state_status=PromptAdmissionState.FROZEN,
        )
        paid_calls_per_attempt = maximum_paid_calls_per_attempt(expected_provider)
        self._model_runtime.load_or_admit_claimed_job(
            NewModelCallJobAdmissionRequest(
                project_id=lease.project_id,
                job_id=lease.job_id,
                job_kind=lease.kind,
                lease_token=lease.lease_token,
                fencing_generation=lease.fencing_generation,
                runtime_selection_id=spec.runtime_selection_id,
                required_purpose=spec.prompt.purpose,
                search_mode=spec.search_mode,
                usage_audience=ModelAudience.INTERNAL_WORKER,
                prompt=admission,
                prompt_bundle_hash=prompt.bundle_hash,
                output_schema_hash=prompt.output_schema_hash,
                application_output_schema_hash=prompt.application_output_schema_hash,
                maximum_paid_calls=paid_calls_per_attempt * lease.max_attempts,
                maximum_concurrent_calls=1,
                admitted_by=spec.admitted_by,
                admitted_at=spec.admitted_at,
            )
        )
        runtime = self._model_runtime.load(project_id=lease.project_id, job_id=lease.job_id)
        if (
            runtime.job.runtime_option_id != spec.runtime_selection_id
            or runtime.job.route.provider != expected_provider
            or runtime.job.purpose != state.run_purpose
            or runtime.job.purpose != spec.prompt.purpose
            or runtime.job.prompt_binding_id != prompt.binding_id
            or runtime.job.prompt_release_id != prompt.release_id
            or runtime.job.prompt_release_hash != prompt.release_hash
        ):
            raise WorkflowCSamplingWorkerError("frozen model admission differs from sampling Job")
        idempotency_prefix = f"workflow-c-provider:{spec.attempt_id}"
        initial_idempotency_key = f"{idempotency_prefix}:initial"
        request = ModelGatewayRequest(
            messages=(
                {"role": "system", "content": prompt.system_message},
                {"role": "user", "content": spec.question_text},
            ),
            configured_model=source.configured_model,
            prompt_bundle_hash=prompt.bundle_hash,
            project_id=lease.project_id,
            purpose=state.run_purpose,
            usage_audience=ModelAudience.INTERNAL_WORKER,
            temperature=prompt.temperature,
            max_output_tokens=prompt.max_output_tokens,
            output_schema=prompt.output_schema,
            application_output_schema=prompt.application_output_schema,
            seed=prompt.seed,
            tool_mode=prompt.tool_mode,
            search_mode=source.search_mode,
            deadline_at=spec.deadline_at,
            idempotency_key=initial_idempotency_key,
            capture_method=ModelCaptureMethod(source.capture_method.value),
            provider_secret_handle=runtime.job.provider_secret_handle,
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
        command = ExecuteModelCall(
            project_id=lease.project_id,
            job_id=lease.job_id,
            expected_job_version=runtime.job.job_version,
            lease_token=lease.lease_token,
            fencing_generation=lease.fencing_generation,
            route=runtime.job.route,
            runtime_manifest_id=runtime.job.runtime_manifest_id,
            runtime_manifest_hash=runtime.job.runtime_manifest_hash,
            runtime_option_id=runtime.job.runtime_option_id,
            runtime_option_hash=runtime.job.runtime_option_hash,
            prompt_binding_id=prompt.binding_id,
            prompt_release_id=prompt.release_id,
            prompt_release_hash=prompt.release_hash,
            request=request,
            attempt_kind=ModelCallAttemptKind.INITIAL,
            attempt_idempotency_key=request.idempotency_key or "",
        )
        with LeaseHeartbeat(
            self._store,
            lease,
            lease_for=self._lease_for,
            interval=min(self._lease_for / 3, timedelta(seconds=30)),
        ) as heartbeat:
            execution = execute_provider_model_attempt_chain(
                application=runtime.application,
                initial_command=command,
                policy=runtime.policy,
                durable_attempt_count=lease.attempt_count,
                idempotency_prefix=idempotency_prefix,
            )
            heartbeat.raise_if_stopped()
        return execution

    def _terminal_failure(
        self,
        lease: WorkerLease,
        job_spec: WorkflowCJobSpec,
        state: SamplingExecutionState,
        spec: ProviderSamplingWorkerSpec,
        error_code: str,
        retryable: bool,
    ) -> Mapping[str, object]:
        with self._store.fenced_transaction(lease) as connection:
            self._repository.record_failure(
                connection=connection,
                lease=lease,
                spec_hash=job_spec.spec_hash,
                state=state,
                task_version=spec.task_version,
                attempt_version=spec.attempt_version,
                error_code=error_code,
                retryable=retryable,
                occurred_at=self._clock(),
            )
            if retryable:
                job_status = self._store.fail_with_retry_in_transaction(
                    connection,
                    lease,
                    error_code=error_code,
                    details={"sampling_status": "retry_ready"},
                    retry_delay=timedelta(seconds=60),
                )
            else:
                self._store.fail_in_transaction(
                    connection,
                    lease,
                    error_code=error_code,
                    details={"sampling_status": "failed"},
                )
                job_status = "failed"
        return {
            "status": job_status,
            "job_id": str(lease.job_id),
            "sampling_status": "retry_ready" if retryable else "failed",
            "error_code": error_code,
        }


class PostgresManualSamplingOperation:
    """Commit a previously approved, encrypted manual evidence artifact."""

    kind = MANUAL_IMPORT_KIND

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        specs: PostgresWorkflowCJobSpecRepository,
        repository: PostgresWorkflowCSamplingRepository,
        artifacts: PostgresWorkflowCManualArtifactReader,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._specs = specs
        self._repository = repository
        self._artifacts = artifacts
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        if lease.kind != self.kind:
            raise WorkflowCSamplingWorkerError("manual sampling Worker kind is invalid")
        job_spec = self._specs.load(lease)
        spec = parse_manual_sampling_spec(job_spec.payload)
        state = self._repository.manual_state(project_id=lease.project_id, spec=spec)
        _assert_lease_job(lease, state.sampling)
        spec = replace(
            spec,
            task_version=state.sampling.task_version,
            attempt_version=state.sampling.attempt_version,
        )
        try:
            recovered = self._artifacts.load(
                WorkflowCManualArtifactReadRequest(
                    project_id=lease.project_id,
                    artifact_id=state.artifact_manifest_id,
                    expected_manifest_hash=state.artifact_manifest_hash,
                    expected_content_hash=state.artifact_content_hash,
                )
            )
            try:
                if (
                    recovered.artifact_id != state.artifact_manifest_id
                    or recovered.manifest_hash != state.artifact_manifest_hash
                    or recovered.content_hash != state.artifact_content_hash
                    or recovered.evidence_kind != state.evidence_kind
                    or recovered.persisted_content_type != state.persisted_content_type
                ):
                    raise WorkflowCSamplingWorkerError("manual artifact recovery lineage changed")
                commit = build_manual_commit(
                    project_id=lease.project_id,
                    spec=spec,
                    task_key=state.sampling.task_key,
                    source=state.sampling.source,
                    manifest_uri=state.manifest_uri,
                    surface_parse=state.surface_parse,
                    observed_at=self._clock(),
                )
            finally:
                recovered.wipe()
        except (WorkflowCSamplingWorkerError, ValueError):
            return self._terminal_failure(lease, job_spec, state, spec)
        with self._store.fenced_transaction(lease) as connection:
            self._repository.commit_manual(
                connection=connection,
                lease=lease,
                spec_hash=job_spec.spec_hash,
                state=state,
                spec=spec,
                commit=commit,
            )
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"workflow-c-observation:{commit.observation_id}",
                details={
                    "observation_id": str(commit.observation_id),
                    "evidence_status": commit.evidence_status,
                },
            )
        return {
            "status": "succeeded",
            "job_id": str(lease.job_id),
            "observation_id": str(commit.observation_id),
            "evidence_status": commit.evidence_status,
        }

    def _terminal_failure(
        self,
        lease: WorkerLease,
        job_spec: WorkflowCJobSpec,
        state: ManualSamplingExecutionState,
        spec: ManualSamplingWorkerSpec,
    ) -> Mapping[str, object]:
        with self._store.fenced_transaction(lease) as connection:
            self._repository.record_failure(
                connection=connection,
                lease=lease,
                spec_hash=job_spec.spec_hash,
                state=state.sampling,
                task_version=spec.task_version,
                attempt_version=spec.attempt_version,
                error_code="manual_artifact_invalid",
                retryable=False,
                occurred_at=self._clock(),
            )
            self._store.fail_in_transaction(
                connection,
                lease,
                error_code="manual_artifact_invalid",
                details={"sampling_status": "failed"},
            )
        return {
            "status": "failed",
            "job_id": str(lease.job_id),
            "sampling_status": "failed",
            "error_code": "manual_artifact_invalid",
        }


def _result_from_execution(
    execution: ModelCallExecution,
    *,
    project_id: UUID,
    job_id: UUID,
    lease: WorkerLease,
    output_schema: Mapping[str, object],
    application_output_schema: Mapping[str, object],
    purpose: str,
    recovery: ProviderArtifactRecoveryPort,
):
    event = execution.terminal_event
    if event.status is not ModelCallTerminalStatus.SUCCEEDED:
        raise ModelCallUnknownOutcome(
            execution.attempt.spec.id, provider=execution.attempt.spec.route.provider
        )
    if execution.result is not None:
        return execution.result
    if not execution.replayed or event.output_hash is None:
        raise ModelCallUnknownOutcome(
            execution.attempt.spec.id, provider=execution.attempt.spec.route.provider
        )
    try:
        recovered = recovery.recover_derived(
            ProviderArtifactRecoveryRequest(
                project_id=project_id,
                source_model_job_id=job_id,
                recovery_job_id=job_id,
                lease_token=lease.lease_token,
                fencing_generation=lease.fencing_generation,
                model_call_attempt_id=execution.attempt.spec.id,
                expected_output_hash=event.output_hash,
                output_schema=output_schema,
                application_output_schema=application_output_schema,
                purpose=purpose,
            )
        )
    except Exception as error:
        raise ModelCallUnknownOutcome(
            execution.attempt.spec.id, provider=execution.attempt.spec.route.provider
        ) from error
    bundle = recovered.bundle_lineage
    if (
        bundle is None
        or recovered.model_call_attempt_id != execution.attempt.spec.id
        or event.gateway_call_log_id is None
        or event.response_hash is None
        or event.provider_reported_model is None
        or event.lineage.capture_method is None
        or event.lineage.search_mode is None
        or execution.attempt.spec.requested_location is None
        or event.lineage.effective_location is None
    ):
        raise ModelCallUnknownOutcome(
            execution.attempt.spec.id, provider=execution.attempt.spec.route.provider
        )
    from geo_core.model_gateway.contracts import ModelGatewayResult

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
        provider=execution.attempt.spec.route.provider,
        adapter_release_id=execution.attempt.spec.route.adapter_release_id,
        adapter_release_hash=execution.attempt.spec.route.adapter_release_hash,
        model_release_id=execution.attempt.spec.route.model_release_id,
        model_release_hash=execution.attempt.spec.route.model_release_hash,
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
        usage_purpose=event.lineage.usage_purpose,
        usage_audience=event.lineage.usage_audience,
        capture_method=event.lineage.capture_method,
        search_mode=event.lineage.search_mode,
        requested_location=execution.attempt.spec.requested_location,
        effective_location=event.lineage.effective_location,
    )


def _assert_lease_job(lease: WorkerLease, state: SamplingExecutionState) -> None:
    if state.project_id != lease.project_id or state.durable_job_id != lease.job_id:
        raise WorkflowCSamplingWorkerError("sampling attempt differs from durable Job lease")


def _validate_lease(lease_for: timedelta) -> None:
    if lease_for < timedelta(seconds=30):
        raise ValueError("Workflow C sampling lease must be at least 30 seconds")


__all__ = [
    "MANUAL_IMPORT_KIND",
    "PROVIDER_EXECUTE_KIND",
    "PostgresManualSamplingOperation",
    "PostgresProviderSamplingOperation",
    "WorkflowCSamplingWorkerError",
]
