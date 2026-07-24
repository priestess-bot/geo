"""Durable parent/child handlers for PostgreSQL Recommendation generation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid5

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.model_gateway import (
    ExecuteModelCall,
    ModelAudience,
    ModelCallAttemptKind,
    ModelCallUnknownOutcome,
    ModelGatewayError,
    ModelGatewayRequest,
    NewModelCallJobAdmissionRequest,
    PromptAdmissionState,
    PromptReleaseAdmission,
    RetryableModelGatewayError,
)
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.model_gateway.prompt_admission import ModelCallAdmissionMode
from geo_core.model_gateway.runtime_execution import (
    ModelCallJobAdmitter,
    ModelCallRuntimeLoader,
)
from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.generation_contracts import (
    RecommendationGenerationOutputError,
    RecommendationGenerationResult,
    RecommendationGenerationSpec,
    RecommendationGenerationStale,
    ResolvedGenerationPrompt,
    canonical_hash,
)
from geo_core.recommendations.generation_artifacts import RecommendationTaskArtifactRef
from geo_core.recommendations.generation_ports import (
    ARBITER_APPLICATION_OUTPUT_SCHEMA,
    ARBITER_OUTPUT_SCHEMA,
    RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
    RECOMMENDATION_OUTPUT_SCHEMA,
    parse_recommendation_output,
    require_arbiter_acceptance,
    structured_arbiter_input,
    structured_generation_input,
    validated_recommendation_evidence_refs,
)
from geo_core.recommendations.generation_results import (
    build_insufficient_result,
    build_model_result,
)
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationChildStatus,
    RecommendationModelRole,
    RecommendationModelResultRef,
    RecommendationModelTask,
    RecommendationParentClaim,
)
from geo_core.recommendations.postgres.generation_worker_support import (
    assert_admitted_lineage as _assert_admitted_lineage,
    assert_task_lease as _assert_task_lease,
    model_task as _model_task,
    recoverable_result_ref as _recoverable_result_ref,
)


class RecommendationGenerationWorkerRepository(Protocol):
    def load_parent(self, lease: WorkerLease) -> RecommendationParentClaim: ...

    def assert_current_inputs(self, spec: RecommendationGenerationSpec) -> None: ...

    def resolve_prompt(
        self,
        *,
        spec: RecommendationGenerationSpec,
        role: RecommendationModelRole,
        structured_input: Mapping[str, object],
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> ResolvedGenerationPrompt: ...

    def reserve_model_task(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
    ) -> None: ...

    def prepare_model_task(
        self, task: RecommendationModelTask
    ) -> RecommendationTaskArtifactRef: ...

    def activate_model_task(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
        artifact: RecommendationTaskArtifactRef,
    ) -> None: ...

    def load_model_task(self, lease: WorkerLease) -> RecommendationModelTask: ...

    def record_model_success(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
        reference: RecommendationModelResultRef,
    ) -> None: ...

    def record_model_failure(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
        status: str,
        error_code: str,
    ) -> None: ...

    def wake_parent(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
    ) -> None: ...

    def finalize_parent(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        result: RecommendationGenerationResult,
    ) -> None: ...


class RecommendationParentHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: RecommendationGenerationWorkerRepository,
        poll_delay: timedelta = timedelta(seconds=5),
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._repository = repository
        self._poll_delay = poll_delay
        self._clock = clock

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            claim = self._repository.load_parent(lease)
            spec = claim.spec
            if spec.valid_until <= self._clock():
                return self._fail(lease, "expired_spec")
            self._repository.assert_current_inputs(spec)
            structured_input = structured_generation_input(spec.evidence)
            primary_prompt = self._repository.resolve_prompt(
                spec=spec,
                role=RecommendationModelRole.PRIMARY,
                structured_input=structured_input,
                output_schema=RECOMMENDATION_OUTPUT_SCHEMA,
                application_output_schema=RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
            )
            insufficiency = spec.evidence.insufficiency_reasons(
                minimum_real_observations=spec.minimum_real_observations
            )
            if insufficiency:
                result = build_insufficient_result(
                    spec,
                    insufficiency,
                    recommendation_id=uuid5(lease.job_id, "recommendation-result"),
                    created_at=self._clock(),
                )
                return self._finalize(lease, result)
            if claim.primary is None:
                return self._stage(lease, spec, RecommendationModelRole.PRIMARY, primary_prompt)
            waiting = self._waiting_or_failed(lease, claim.primary)
            if waiting is not None:
                return waiting
            assert claim.primary.result is not None
            parsed = parse_recommendation_output(
                claim.primary.result.output,
                evidence=spec.evidence,
            )
            calls = [claim.primary.result]
            prompts = [primary_prompt.binding]
            if spec.arbiter_binding is not None:
                arbiter_input = structured_arbiter_input(
                    claim.primary.result.output,
                    evidence=spec.evidence,
                )
                arbiter_prompt = self._repository.resolve_prompt(
                    spec=spec,
                    role=RecommendationModelRole.ARBITER,
                    structured_input=arbiter_input,
                    output_schema=ARBITER_OUTPUT_SCHEMA,
                    application_output_schema=ARBITER_APPLICATION_OUTPUT_SCHEMA,
                )
                if claim.arbiter is None:
                    return self._stage(
                        lease,
                        spec,
                        RecommendationModelRole.ARBITER,
                        arbiter_prompt,
                    )
                waiting = self._waiting_or_failed(lease, claim.arbiter)
                if waiting is not None:
                    return waiting
                assert claim.arbiter.result is not None
                require_arbiter_acceptance(
                    claim.arbiter.result.output,
                    evidence=spec.evidence,
                    candidate_id=canonical_hash(claim.primary.result.output),
                    evidence_refs=validated_recommendation_evidence_refs(
                        claim.primary.result.output,
                        evidence=spec.evidence,
                    ),
                )
                calls.append(claim.arbiter.result)
                prompts.append(arbiter_prompt.binding)
            self._repository.assert_current_inputs(spec)
            current_primary = self._repository.resolve_prompt(
                spec=spec,
                role=RecommendationModelRole.PRIMARY,
                structured_input=structured_input,
                output_schema=RECOMMENDATION_OUTPUT_SCHEMA,
                application_output_schema=RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
            )
            if current_primary.prompt_bundle_hash != primary_prompt.prompt_bundle_hash:
                raise RecommendationGenerationStale("Prompt changed before parent finalization")
            result = build_model_result(
                spec,
                parsed,
                tuple(calls),
                tuple(prompts),
                recommendation_id=uuid5(lease.job_id, "recommendation-result"),
                created_at=self._clock(),
            )
            return self._finalize(lease, result)
        except (JobCancellationRequested, LostJobLease):
            raise
        except RecommendationGenerationStale:
            return self._fail(lease, "stale_prompt_or_fact")
        except (RecommendationGenerationOutputError, RecommendationRuleViolation) as error:
            return self._fail(lease, type(error).__name__)
        except Exception as error:
            return self._fail(lease, type(error).__name__, retry_delay=timedelta(seconds=30))

    def _stage(self, lease, spec, role, prompt) -> Mapping[str, object]:
        task = _model_task(lease, spec, role, prompt)
        with self._store.fenced_transaction(lease) as connection:
            self._repository.reserve_model_task(
                connection=connection,
                lease=lease,
                task=task,
            )
        artifact = self._repository.prepare_model_task(task)
        with self._store.fenced_transaction(lease) as connection:
            self._repository.activate_model_task(
                connection=connection,
                lease=lease,
                task=task,
                artifact=artifact,
            )
            self._store.defer_in_transaction(
                connection,
                lease,
                reason_code=f"waiting_{role.value}",
                details={"child_job_id": str(task.child_job_id)},
                retry_delay=self._poll_delay,
            )
        return {"status": "retry_wait", "job_id": str(lease.job_id)}

    def _waiting_or_failed(self, lease, outcome) -> Mapping[str, object] | None:
        if not outcome.status.terminal:
            with self._store.fenced_transaction(lease) as connection:
                self._store.defer_in_transaction(
                    connection,
                    lease,
                    reason_code=f"waiting_{outcome.role.value}",
                    details={"child_job_id": str(outcome.child_job_id)},
                    retry_delay=self._poll_delay,
                )
            return {"status": "retry_wait", "job_id": str(lease.job_id)}
        if outcome.status is not RecommendationChildStatus.SUCCEEDED:
            return self._fail(lease, outcome.error_code or "model_child_failed")
        return None

    def _finalize(self, lease, result) -> Mapping[str, object]:
        with self._store.fenced_transaction(lease) as connection:
            self._repository.finalize_parent(
                connection=connection,
                lease=lease,
                result=result,
            )
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"recommendation:{result.recommendation.id}",
                details={"recommendation_id": str(result.recommendation.id)},
            )
        return {
            "status": "succeeded",
            "job_id": str(lease.job_id),
            "recommendation_id": str(result.recommendation.id),
        }

    def _fail(self, lease, error_code, retry_delay=None) -> Mapping[str, object]:
        status = self._store.fail(
            lease,
            error_code=error_code,
            details={"classification": "recommendation_generation"},
            retry_delay=retry_delay,
        )
        return {"status": status, "job_id": str(lease.job_id)}


class RecommendationModelChildHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: RecommendationGenerationWorkerRepository,
        model_job_admitter: ModelCallJobAdmitter,
        model_runtime_loader: ModelCallRuntimeLoader,
        lease_for: timedelta,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._repository = repository
        self._model_job_admitter = model_job_admitter
        self._model_runtime_loader = model_runtime_loader
        self._lease_for = lease_for
        self._clock = clock

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        task: RecommendationModelTask | None = None
        try:
            task = self._repository.load_model_task(lease)
            _assert_task_lease(task, lease)
            prompt = task.prompt
            output_schema_hash = canonical_json_hash(prompt.output_schema)
            application_output_schema_hash = canonical_json_hash(
                prompt.application_output_schema
            )
            prompt_admission = PromptReleaseAdmission(
                project_id=task.project_id,
                admission_mode=ModelCallAdmissionMode.RUNTIME_FROZEN,
                binding_id=prompt.binding.binding_id,
                state_id=prompt.binding.frozen_state_id,
                state_version=prompt.binding.frozen_state_version,
                release_id=prompt.binding.release_id,
                release_hash=prompt.binding.release_hash,
                purpose=prompt.binding.purpose,
                output_schema_hash=output_schema_hash,
                application_output_schema_hash=application_output_schema_hash,
                test_set_hash=None,
                state_status=PromptAdmissionState.FROZEN,
            )
            admission = self._model_job_admitter.load_or_admit_claimed_job(
                NewModelCallJobAdmissionRequest(
                    project_id=lease.project_id,
                    job_id=lease.job_id,
                    job_kind=lease.kind,
                    lease_token=lease.lease_token,
                    fencing_generation=lease.fencing_generation,
                    runtime_selection_id=task.runtime_selection_id,
                    required_purpose=prompt.binding.purpose,
                    search_mode=prompt.search_mode,
                    usage_audience=ModelAudience.INTERNAL_WORKER,
                    prompt=prompt_admission,
                    prompt_bundle_hash=prompt.prompt_bundle_hash,
                    output_schema_hash=output_schema_hash,
                    application_output_schema_hash=application_output_schema_hash,
                    maximum_paid_calls=1,
                    maximum_concurrent_calls=1,
                    admitted_by=task.admitted_by,
                    admitted_at=self._clock(),
                )
            )
            _assert_admitted_lineage(task, admission.job)
            runtime = self._model_runtime_loader.load(
                project_id=lease.project_id,
                job_id=lease.job_id,
            )
            _assert_admitted_lineage(task, runtime.job)
            request = ModelGatewayRequest(
                messages=prompt.messages,
                configured_model=prompt.configured_model,
                prompt_bundle_hash=prompt.prompt_bundle_hash,
                project_id=lease.project_id,
                purpose=prompt.binding.purpose,
                usage_audience=ModelAudience.INTERNAL_WORKER,
                temperature=0,
                max_output_tokens=4096,
                output_schema=prompt.output_schema,
                application_output_schema=prompt.application_output_schema,
                search_mode=prompt.search_mode,
                idempotency_key=f"recommendation:{task.parent_job_id}:{task.role.value}",
                capture_method=prompt.capture_method,
                provider_secret_handle=runtime.job.provider_secret_handle,
            )
            command = ExecuteModelCall(
                project_id=lease.project_id,
                job_id=lease.job_id,
                expected_job_version=runtime.job.job_version,
                lease_token=lease.lease_token,
                fencing_generation=lease.fencing_generation,
                runtime_manifest_id=runtime.job.runtime_manifest_id,
                runtime_manifest_hash=runtime.job.runtime_manifest_hash,
                runtime_option_id=runtime.job.runtime_option_id,
                runtime_option_hash=runtime.job.runtime_option_hash,
                route=runtime.job.route,
                prompt_binding_id=prompt.binding.binding_id,
                prompt_release_id=prompt.binding.release_id,
                prompt_release_hash=prompt.binding.release_hash,
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
                execution = runtime.application.execute(command, policy=runtime.policy)
                heartbeat.raise_if_stopped()
            if execution.result is None:
                raise RecommendationGenerationOutputError("model result is unavailable")
            reference = _recoverable_result_ref(execution)
            with self._store.fenced_transaction(lease) as connection:
                self._repository.record_model_success(
                    connection=connection,
                    lease=lease,
                    task=task,
                    reference=reference,
                )
                self._store.complete_in_transaction(
                    connection,
                    lease,
                    result_ref=f"model-call:{execution.result.call_log_id}",
                    details={"call_log_id": str(execution.result.call_log_id)},
                )
                self._repository.wake_parent(
                    connection=connection,
                    lease=lease,
                    task=task,
                )
            return {"status": "succeeded", "job_id": str(lease.job_id)}
        except (JobCancellationRequested, LostJobLease):
            raise
        except RecommendationGenerationStale as error:
            return self._fail(lease, task, type(error).__name__)
        except RetryableModelGatewayError as error:
            delay = timedelta(seconds=max(1.0, min(300.0, error.retry_after_seconds or 30)))
            return self._fail(lease, task, type(error).__name__, retry_delay=delay)
        except ModelCallUnknownOutcome as error:
            return self._fail(lease, task, type(error).__name__)
        except (ModelGatewayError, RecommendationGenerationOutputError) as error:
            return self._fail(lease, task, type(error).__name__)
        except Exception as error:
            return self._fail(
                lease,
                task,
                type(error).__name__,
                retry_delay=timedelta(seconds=30),
            )

    def _fail(self, lease, task, error_code, retry_delay=None) -> Mapping[str, object]:
        with self._store.fenced_transaction(lease) as connection:
            if retry_delay is None:
                self._store.fail_in_transaction(
                    connection,
                    lease,
                    error_code=error_code,
                    details={"classification": "recommendation_model"},
                )
                status = "failed"
            else:
                status = self._store.fail_with_retry_in_transaction(
                    connection,
                    lease,
                    error_code=error_code,
                    details={"classification": "recommendation_model"},
                    retry_delay=retry_delay,
                )
            if task is not None:
                self._repository.record_model_failure(
                    connection=connection,
                    lease=lease,
                    task=task,
                    status=status,
                    error_code=error_code,
                )
                if status in {"failed", "dead_lettered"}:
                    self._repository.wake_parent(
                        connection=connection,
                        lease=lease,
                        task=task,
                    )
        return {"status": status, "job_id": str(lease.job_id)}


__all__ = [
    "RecommendationGenerationWorkerRepository",
    "RecommendationModelChildHandler",
    "RecommendationParentHandler",
]
