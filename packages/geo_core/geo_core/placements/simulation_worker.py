"""Durable model execution for internal prompt simulations."""

from __future__ import annotations

from datetime import timedelta
from typing import Mapping, Protocol

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.model_gateway import (
    ModelCallBudget,
    ModelGateway,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.contracts import (
    ModelCallBudgetExceeded,
    ModelGatewayError,
    ProviderPolicyViolation,
    RetryableModelGatewayError,
)
from geo_core.placements.domain import (
    PlacementRuleViolation,
    canonical_hash,
    canonical_json_bytes,
)
from geo_core.placements.generation_worker import (
    parse_generated_placement,
    validate_output_schema,
)
from geo_core.placements.ports import GeneratedPlacement, ModelCallClaim
from geo_core.placements.runtime_prompts import simulation_system_prompt
from geo_core.placements.worker_models import (
    ModelCallReservation,
    PromptSimulationClaim,
)


class PromptSimulationWorkerRepository(Protocol):
    def load_prompt_simulation(self, lease: WorkerLease) -> PromptSimulationClaim: ...

    def reserve_model_call(
        self,
        lease: WorkerLease,
        claim: ModelCallClaim,
        *,
        provider: str,
        request_hash: str,
    ) -> ModelCallReservation: ...

    def record_model_call_success(
        self,
        lease: WorkerLease,
        claim: ModelCallClaim,
        reservation: ModelCallReservation,
        result: ModelGatewayResult,
    ) -> None: ...

    def record_model_call_failure(
        self,
        lease: WorkerLease,
        claim: ModelCallClaim,
        reservation: ModelCallReservation,
        *,
        classification: str,
        error_code: str,
    ) -> None: ...

    def finalize_prompt_simulation(
        self,
        lease: WorkerLease,
        claim: PromptSimulationClaim,
        placement: GeneratedPlacement,
        result: ModelGatewayResult,
    ) -> Mapping[str, object]: ...


class PromptSimulationHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: PromptSimulationWorkerRepository,
        gateway: ModelGateway,
        lease_for: timedelta,
    ) -> None:
        self._store = store
        self._repository = repository
        self._gateway = gateway
        self._lease_for = lease_for

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            claim = self._repository.load_prompt_simulation(lease)
        except PlacementRuleViolation as exc:
            return self._fail(lease, exc, retry=False, classification="contract")
        request = build_prompt_simulation_request(claim)
        request_hash = canonical_hash(
            {
                "messages": request.messages,
                "configured_model": request.configured_model,
                "prompt_input_hash": claim.input_hash,
                "purpose": request.purpose,
                "temperature": request.temperature,
                "max_output_tokens": request.max_output_tokens,
            }
        )
        provider = str(getattr(self._gateway, "provider", "unknown"))
        try:
            reservation = self._repository.reserve_model_call(
                lease, claim, provider=provider, request_hash=request_hash
            )
        except ModelCallBudgetExceeded as exc:
            return self._fail(lease, exc, retry=False, classification="budget")
        try:
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                result = self._gateway.generate(
                    request,
                    policy=ModelPolicy(),
                    budget=ModelCallBudget(1),
                )
                heartbeat.raise_if_stopped()
        except (JobCancellationRequested, LostJobLease):
            raise
        except Exception as exc:
            classification = _model_error_classification(exc)
            self._repository.record_model_call_failure(
                lease,
                claim,
                reservation,
                classification=classification,
                error_code=type(exc).__name__,
            )
            return self._fail(
                lease,
                exc,
                retry=isinstance(exc, RetryableModelGatewayError),
                classification=classification,
            )
        self._repository.record_model_call_success(lease, claim, reservation, result)
        try:
            validate_output_schema(result.output, claim.output_schema)
            placement = parse_generated_placement(result.output, claim=claim)
            details = self._repository.finalize_prompt_simulation(lease, claim, placement, result)
            return {"status": "succeeded", "job_id": str(lease.job_id), **details}
        except PlacementRuleViolation as exc:
            return self._fail(lease, exc, retry=False, classification="contract")

    def _fail(
        self,
        lease: WorkerLease,
        error: Exception,
        *,
        retry: bool,
        classification: str,
    ) -> Mapping[str, object]:
        status = self._store.fail(
            lease,
            error_code=type(error).__name__,
            details={"message": str(error), "classification": classification},
            retry_delay=timedelta(seconds=30) if retry else None,
        )
        return {"status": status, "job_id": str(lease.job_id)}


def build_prompt_simulation_request(claim: PromptSimulationClaim) -> ModelGatewayRequest:
    """Build the exact frozen request used by the simulation worker."""
    serialized_schema = canonical_json_bytes(claim.output_schema).decode("utf-8")
    return ModelGatewayRequest(
        messages=(
            {"role": "system", "content": claim.system_prompt},
            {
                "role": "system",
                "content": simulation_system_prompt(
                    authenticity_mode=claim.authenticity_mode,
                    internal_evidence_ids=claim.evidence_item_ids,
                    public_citation_ids=claim.public_citation_item_ids,
                    output_schema=serialized_schema,
                ),
            },
            {"role": "user", "content": claim.rendered_prompt},
        ),
        configured_model=claim.configured_model,
        prompt_bundle_hash=claim.input_hash,
        project_id=claim.project_id,
        purpose="geo-prompt-simulation",
        temperature=0.0,
        max_output_tokens=8192,
    )


def _model_error_classification(error: Exception) -> str:
    if isinstance(error, RetryableModelGatewayError):
        return "retryable"
    if isinstance(error, ProviderPolicyViolation):
        return "policy"
    if isinstance(error, ModelCallBudgetExceeded):
        return "budget"
    if isinstance(error, ModelGatewayError):
        return "permanent"
    return "unknown"
