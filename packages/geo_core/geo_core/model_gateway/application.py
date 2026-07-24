"""Application service for exact, budgeted, append-only model calls."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Callable
from uuid import UUID, uuid4

from geo_core.model_gateway.application_support import (
    ExecuteModelCall,
    ModelCallAdmissionError,
    ModelCallExecution,
    ModelCallUnknownOutcome,
    RequestIdentity,
    attempt_draft,
    bind_result_artifact_policy,
    provider_outcome_is_unknown,
    request_identity,
    validate_admission,
    validate_capabilities,
    validate_parent,
    validate_result_identity,
)
from geo_core.model_gateway.application_events import failure_event, success_event
from geo_core.model_gateway.reconciliation import (
    ModelCallReconciliationService,
    ReconcileModelCall,
)
from geo_core.model_gateway.contracts import (
    ModelCallBudget,
    ModelGatewayError,
    ModelGatewayResult,
    ModelIdentityError,
    ModelPolicy,
    OutputSchemaDefinitionError,
    ProviderCapabilities,
    StructuredOutputValidationError,
)
from geo_core.model_gateway.ports import (
    ExactModelGatewayPort,
    ModelCallAttempt,
    ModelCallFailureClass,
    ModelCallIdempotencyConflict,
    ModelCallJobAdmission,
    ModelCallPersistenceError,
    ModelCallTerminalEvent,
    ModelCallUnitOfWorkFactory,
    PromptReleaseAdmission,
    StoredModelCallAttempt,
)
from geo_core.model_gateway.prompt_admission import ModelCallAdmissionMode
from geo_core.model_gateway.releases import AdapterRelease, ModelRelease, ModelReleaseRegistry
from geo_core.model_gateway.schema_validation import (
    validate_output_schema_pair,
    validate_structured_output,
)


class ModelCallApplication:
    """Reserve, execute and record one exact route without implicit fallback."""

    def __init__(
        self,
        *,
        gateway: ExactModelGatewayPort,
        release_registry: ModelReleaseRegistry,
        uow_factory: ModelCallUnitOfWorkFactory,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._gateway = gateway
        self._release_registry = release_registry
        self._uow_factory = uow_factory
        self._id_factory = id_factory
        self._clock = clock
        self._reconciliation = ModelCallReconciliationService(
            uow_factory=uow_factory,
            id_factory=id_factory,
            clock=clock,
        )

    def execute(
        self,
        command: ExecuteModelCall,
        *,
        policy: ModelPolicy,
    ) -> ModelCallExecution:
        adapter_release, model_release = self._release_registry.resolve(command.route)
        self._preflight_request(
            command,
            policy=policy,
            capabilities=adapter_release.capabilities,
            model_release=model_release,
        )
        identity = request_identity(command, policy=policy)
        stored = self._reserve(
            command,
            identity=identity,
            policy=policy,
            adapter_release=adapter_release,
        )
        if stored.replayed:
            return self._replay(command, stored.attempt, identity=identity)

        attempt = stored.attempt
        paid_budget = ModelCallBudget(1)
        execution_request = replace(
            command.request,
            model_call_job_id=command.job_id,
            model_call_attempt_id=attempt.spec.id,
        )
        try:
            result = self._gateway.generate(
                command.route,
                execution_request,
                policy=policy,
                budget=paid_budget,
            )
        except StructuredOutputValidationError as exc:
            self._record_known_failure(
                attempt,
                exc,
                paid_calls=paid_budget.consumed_calls,
                classification=ModelCallFailureClass.APPLICATION_STRUCTURED_OUTPUT,
            )
            raise
        except ModelGatewayError as exc:
            if provider_outcome_is_unknown(exc, paid_budget):
                raise ModelCallUnknownOutcome(
                    attempt.spec.id, provider=command.route.provider
                ) from exc
            self._record_known_failure(
                attempt,
                exc,
                paid_calls=paid_budget.consumed_calls,
                classification=ModelCallFailureClass.PROVIDER,
            )
            raise
        except Exception as exc:
            raise ModelCallUnknownOutcome(attempt.spec.id, provider=command.route.provider) from exc

        if paid_budget.consumed_calls != 1:
            raise ModelCallUnknownOutcome(attempt.spec.id, provider=command.route.provider)
        try:
            result = bind_result_artifact_policy(
                result,
                adapter_release=adapter_release,
                request=command.request,
            )
        except ModelGatewayError as exc:
            data_policy = adapter_release.data_policy
            sanitized_result = replace(
                result,
                raw_artifact_reference=None,
                derived_artifact_reference=None,
                raw_artifact_policy_hash=adapter_release.data_policy_hash,
                raw_artifact_storage_decision=data_policy.storage.value,
                raw_artifact_cache_decision=data_policy.cache.value,
                raw_artifact_display_decision=data_policy.display.value,
                raw_artifact_redistribution_decision=data_policy.redistribution.value,
                raw_artifact_retention_days=data_policy.retention_days,
                usage_purpose=command.request.purpose,
                usage_audience=command.request.usage_audience,
            )
            self._record_result_failure(
                attempt,
                sanitized_result,
                exc,
                classification=ModelCallFailureClass.APPLICATION_RESULT_CONTRACT,
            )
            raise
        self._validate_application_result(command, attempt=attempt, result=result)
        try:
            event = success_event(
                event_id=self._id_factory(),
                occurred_at=self._clock(),
                attempt=attempt,
                result=result,
            )
        except (ValueError, ModelGatewayError) as exc:
            contract_error = ModelIdentityError(
                "model result cannot be represented by the frozen call-log contract",
                provider=command.route.provider,
            )
            self._record_result_failure(
                attempt,
                result,
                contract_error,
                classification=ModelCallFailureClass.APPLICATION_RESULT_CONTRACT,
            )
            raise contract_error from exc
        self._append_terminal(attempt, event)
        return ModelCallExecution(attempt, event, result, replayed=False)

    def reconcile(self, command: ReconcileModelCall) -> ModelCallExecution:
        return self._reconciliation.reconcile(command)

    def _reserve(
        self,
        command: ExecuteModelCall,
        *,
        identity: RequestIdentity,
        policy: ModelPolicy,
        adapter_release: AdapterRelease,
    ) -> StoredModelCallAttempt:
        with self._uow_factory(project_id=command.project_id) as uow:
            existing = uow.calls.get_attempt_by_idempotency(
                project_id=command.project_id,
                job_id=command.job_id,
                idempotency_key_hash=identity.key_hash,
            )
            if existing is not None:
                if existing.attempt.spec.request_hash != identity.request_hash:
                    raise ModelCallIdempotencyConflict(
                        "model-call idempotency key was reused for another immutable request"
                    )
                return StoredModelCallAttempt(existing.attempt, replayed=True)
            job = _require_job(
                uow.calls.get_job(project_id=command.project_id, job_id=command.job_id)
            )
            if command.admission_mode is ModelCallAdmissionMode.RUNTIME_FROZEN:
                if command.prompt_binding_id is None:
                    raise ModelCallAdmissionError(
                        "runtime model call requires a Prompt binding"
                    )
                prompt = _require_prompt(
                    uow.calls.get_prompt_release(
                        project_id=command.project_id,
                        binding_id=command.prompt_binding_id,
                        release_id=command.prompt_release_id,
                    )
                )
            else:
                if (
                    command.prompt_state_id is None
                    or command.prompt_state_version is None
                    or command.prompt_test_set_hash is None
                ):
                    raise ModelCallAdmissionError(
                        "Prompt test model call requires exact draft lineage"
                    )
                prompt = _require_prompt(
                    uow.calls.get_prompt_test_release(
                        project_id=command.project_id,
                        release_id=command.prompt_release_id,
                        state_id=command.prompt_state_id,
                        state_version=command.prompt_state_version,
                        test_set_hash=command.prompt_test_set_hash,
                    )
                )
            validate_admission(
                command,
                identity=identity,
                job=job,
                prompt=prompt,
                policy=policy,
                adapter_release=adapter_release,
            )
            validate_parent(uow.calls, command, job=job)
            stored = uow.calls.reserve_attempt(
                draft=attempt_draft(
                    command,
                    identity=identity,
                    attempt_id=self._id_factory(),
                    job=job,
                ),
                expected_job_version=command.expected_job_version,
                expected_budget_version=job.budget_version,
                reserved_at=self._clock(),
            )
            uow.commit()
            return stored

    def _replay(
        self,
        command: ExecuteModelCall,
        attempt: ModelCallAttempt,
        *,
        identity: RequestIdentity,
    ) -> ModelCallExecution:
        if attempt.spec.request_hash != identity.request_hash:
            raise ModelCallIdempotencyConflict(
                "model-call idempotency key was reused for another immutable request"
            )
        with self._uow_factory(project_id=command.project_id) as uow:
            event = uow.calls.get_terminal_event(
                project_id=command.project_id,
                attempt_id=attempt.spec.id,
            )
        if event is None:
            raise ModelCallUnknownOutcome(attempt.spec.id, provider=command.route.provider)
        return ModelCallExecution(attempt, event, None, replayed=True)

    def _preflight_request(
        self,
        command: ExecuteModelCall,
        *,
        policy: ModelPolicy,
        capabilities: ProviderCapabilities,
        model_release: ModelRelease,
    ) -> None:
        request = command.request
        handle = request.provider_secret_handle
        if (
            handle is None
            or handle.project_id != command.project_id
            or handle.purpose != f"model_provider.{command.route.provider}"
        ):
            raise ModelCallAdmissionError(
                "model-call request requires the exact project-scoped provider secret version",
                provider=command.route.provider,
            )
        if request.output_schema is None or request.application_output_schema is None:
            raise OutputSchemaDefinitionError(
                "model-call application requires frozen Provider and application schemas",
                provider=command.route.provider,
            )
        try:
            validate_output_schema_pair(
                request.output_schema,
                request.application_output_schema,
            )
        except ModelGatewayError as exc:
            exc.provider = command.route.provider
            raise
        policy.validate(capabilities, adapter_release_id=command.route.adapter_release_id)
        validate_capabilities(request, capabilities)
        if request.configured_model != model_release.configured_model:
            raise ModelCallAdmissionError(
                "configured model does not match the exact Model Release",
                provider=command.route.provider,
            )
        if request.deadline_at is not None:
            if request.deadline_at.tzinfo is None:
                raise ModelCallAdmissionError("model-call deadline must be timezone-aware")
            if request.deadline_at <= self._clock():
                raise ModelCallAdmissionError("model-call deadline has elapsed")

    def _validate_application_result(
        self,
        command: ExecuteModelCall,
        *,
        attempt: ModelCallAttempt,
        result: ModelGatewayResult,
    ) -> None:
        try:
            validate_result_identity(result, command=command)
        except ModelGatewayError as exc:
            self._record_result_failure(
                attempt,
                result,
                exc,
                classification=ModelCallFailureClass.APPLICATION_RESULT_CONTRACT,
            )
            raise
        try:
            assert command.request.application_output_schema is not None
            validate_structured_output(
                result.output,
                command.request.application_output_schema,
            )
        except StructuredOutputValidationError as exc:
            exc.provider = command.route.provider
            self._record_result_failure(
                attempt,
                result,
                exc,
                classification=ModelCallFailureClass.APPLICATION_STRUCTURED_OUTPUT,
            )
            raise

    def _record_known_failure(
        self,
        attempt: ModelCallAttempt,
        error: ModelGatewayError,
        *,
        paid_calls: int,
        classification: ModelCallFailureClass,
    ) -> None:
        event = failure_event(
            event_id=self._id_factory(),
            occurred_at=self._clock(),
            attempt=attempt,
            error=error,
            paid_calls=paid_calls,
            classification=classification,
        )
        self._append_terminal(attempt, event)

    def _record_result_failure(
        self,
        attempt: ModelCallAttempt,
        result: ModelGatewayResult,
        error: ModelGatewayError,
        *,
        classification: ModelCallFailureClass,
    ) -> None:
        event = failure_event(
            event_id=self._id_factory(),
            occurred_at=self._clock(),
            attempt=attempt,
            error=error,
            paid_calls=1,
            classification=classification,
            result=result,
        )
        self._append_terminal(attempt, event)

    def _append_terminal(self, attempt: ModelCallAttempt, event: ModelCallTerminalEvent) -> None:
        try:
            with self._uow_factory(project_id=attempt.spec.project_id) as uow:
                job = _require_job(
                    uow.calls.get_job(
                        project_id=attempt.spec.project_id,
                        job_id=attempt.spec.job_id,
                    )
                )
                uow.calls.append_terminal_event(
                    event=event,
                    expected_budget_version=job.budget_version,
                )
                uow.commit()
        except ModelCallPersistenceError as exc:
            raise ModelCallUnknownOutcome(
                attempt.spec.id, provider=attempt.spec.route.provider
            ) from exc


def _require_job(value: ModelCallJobAdmission | None) -> ModelCallJobAdmission:
    if value is None:
        raise ModelCallAdmissionError("model-call Job admission does not exist")
    return value


def _require_prompt(value: PromptReleaseAdmission | None) -> PromptReleaseAdmission:
    if value is None:
        raise ModelCallAdmissionError("frozen Prompt Release admission does not exist")
    return value


__all__ = [
    "ExecuteModelCall",
    "ModelCallAdmissionError",
    "ModelCallApplication",
    "ModelCallExecution",
    "ModelCallUnknownOutcome",
    "ReconcileModelCall",
]
