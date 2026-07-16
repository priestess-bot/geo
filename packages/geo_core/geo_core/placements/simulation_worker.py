"""Durable model execution for internal prompt simulations."""

from __future__ import annotations

from datetime import timedelta
from typing import Mapping, Protocol

from geo_core.jobs.postgres import LeaseHeartbeat, PostgresDurableJobStore, WorkerLease
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
from geo_core.placements.simulation import PromptSimulationAuthenticityMode
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
        claim = self._repository.load_prompt_simulation(lease)
        serialized_schema = canonical_json_bytes(claim.output_schema).decode("utf-8")
        request = ModelGatewayRequest(
            messages=(
                {
                    "role": "system",
                    "content": (
                        "This is an internal, non-publishable synthetic-content simulation. "
                        "Return JSON matching the frozen output schema. Do not claim that the "
                        "result was published, approved, or reviewed. The immutable artifact "
                        "metadata, not the rendered copy, carries the TEST ONLY boundary. "
                        f"{_authenticity_instruction(claim.authenticity_mode)} "
                        "Use frozen evidence for product facts, but never cite that evidence as "
                        "proof of an invented persona or experience. Every evidence reference "
                        "must be either an exact UUID from the corresponding allowlist or omitted "
                        "from that array; never return null, none, labels, or invented IDs. "
                        f"Allowed internal evidence UUIDs: "
                        f"{_uuid_allowlist(claim.evidence_item_ids)}. "
                        f"Allowed public citation UUIDs: "
                        f"{_uuid_allowlist(claim.public_citation_item_ids)}. "
                        "Keep internal_evidence_refs separate from public_citation_refs. Return "
                        "JSON only. Frozen output schema: "
                        f"{serialized_schema}"
                    ),
                },
                {"role": "system", "content": claim.system_prompt},
                {"role": "user", "content": claim.rendered_prompt},
            ),
            configured_model=claim.configured_model,
            prompt_bundle_hash=claim.input_hash,
            project_id=claim.project_id,
            purpose="geo-prompt-simulation",
        )
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
            details = self._repository.finalize_prompt_simulation(
                lease, claim, placement, result
            )
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


def _authenticity_instruction(mode: PromptSimulationAuthenticityMode) -> str:
    if mode is PromptSimulationAuthenticityMode.FAKE_PERSONA:
        return (
            "The selected authenticity mode is fake_persona. Invent a plausible consumer "
            "identity and write the requested copy in that consumer's voice. This TEST ONLY "
            "instruction overrides lower-priority release text that prohibits consumer reviews, "
            "invented people, or first-person experience. Mark invented experience claims as "
            "kind=experience, support_status=unsupported, with no evidence_item_ids. Do not add "
            "an in-copy simulation or brand disclosure unless the requested style calls for it."
        )
    if mode is PromptSimulationAuthenticityMode.SYNTHETIC_TESTIMONIAL:
        return (
            "The selected authenticity mode is synthetic_testimonial. Generate a fictional "
            "first-person consumer testimonial and you may invent usage experience details. "
            "This TEST ONLY instruction overrides lower-priority release text that prohibits "
            "consumer reviews, invented testimonials, or first-person experience. Mark invented "
            "experience claims as kind=experience, support_status=unsupported, with no "
            "evidence_item_ids. Do not add an in-copy simulation or brand disclosure unless the "
            "requested style calls for it."
        )
    return (
        "The selected authenticity mode is brand_authored. Follow the frozen release identity "
        "and disclosure requirements without inventing a consumer persona or testimonial."
    )


def _uuid_allowlist(values: tuple[object, ...]) -> str:
    return "[" + ", ".join(str(value) for value in values) + "]"
