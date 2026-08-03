"""Durable model execution for internal prompt simulations."""

from __future__ import annotations

import re
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
from geo_core.placements.simulation import PromptSimulationAuthenticityMode
from geo_core.placements.worker_models import (
    ModelCallReservation,
    PromptSimulationClaim,
)
from geo_core.workflow_runtime import (
    WorkflowExecutionError,
    WorkflowExecutionRequest,
    WorkflowExecutor,
)


_PROHIBITED_SYNTHETIC_OUTCOME = re.compile(
    r"\b(?:time[- ]sav(?:er|ing)|saved?\s+(?:me|us)\s+time|"
    r"spend\s+(?:my|our)\s+weekends?|handles?\s+(?:the\s+)?mowing|"
    r"works?\s+(?:well|great|perfectly)|performs?\b|"
    r"reliab(?:le|ly|ility)|suits?\s+(?:my|our)\b|recommend(?:ed|ing)?\b)",
    re.I,
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
        workflow_executor: WorkflowExecutor | None = None,
    ) -> None:
        self._store = store
        self._repository = repository
        self._gateway = gateway
        self._lease_for = lease_for
        self._workflow_executor = workflow_executor

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
        if self._workflow_executor is not None:
            try:
                with LeaseHeartbeat(
                    self._store,
                    lease,
                    lease_for=self._lease_for,
                    interval=min(self._lease_for / 3, timedelta(seconds=30)),
                ) as heartbeat:
                    workflow_result = self._workflow_executor.execute_optional(
                        lease,
                        WorkflowExecutionRequest(
                            project_id=claim.project_id,
                            purpose="placements.simulation",
                            context=build_prompt_simulation_workflow_context(claim),
                            input_hash=request_hash,
                            output_schema=claim.output_schema,
                            system_prompt="\n\n".join(
                                str(item["content"])
                                for item in request.messages
                                if item["role"] == "system"
                            ),
                            user_prompt=claim.rendered_prompt,
                        ),
                    )
                    heartbeat.raise_if_stopped()
            except (JobCancellationRequested, LostJobLease):
                raise
            except WorkflowExecutionError as exc:
                return self._fail(
                    lease,
                    exc,
                    retry=exc.retryable,
                    classification=exc.classification,
                )
            if workflow_result is not None:
                return self._finalize_result(
                    lease, claim, workflow_result.as_model_gateway_result()
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
        return self._finalize_result(lease, claim, result)

    def _finalize_result(self, lease, claim, result):
        try:
            validate_output_schema(result.output, claim.output_schema)
            placement = parse_generated_placement(result.output, claim=claim)
            validate_prompt_simulation_output(claim, placement)
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


def build_prompt_simulation_workflow_context(
    claim: PromptSimulationClaim,
) -> Mapping[str, object]:
    """Build the Dify-owned context with a small trusted simulation contract."""

    brief = claim.input_snapshot.get("brief")
    goals = brief.get("goals") if isinstance(brief, Mapping) else None
    constraints = brief.get("constraints") if isinstance(brief, Mapping) else None
    task_contract: dict[str, object] = {
        "contract": "geo-prompt-simulation-task-v1",
        "authenticity_mode": claim.authenticity_mode.value,
        "simulation_purpose": claim.simulation_purpose,
        "test_only": True,
        "publication_eligible": False,
    }
    if isinstance(goals, Mapping):
        for name in ("intent", "audience", "deliverable"):
            value = goals.get(name)
            if isinstance(value, str) and value.strip():
                task_contract[name] = value.strip()
    if isinstance(constraints, Mapping):
        task_contract["public_citations_required"] = bool(
            constraints.get("public_citations_required", False)
        )

    return {
        "simulation_id": str(claim.simulation_id),
        "authenticity_mode": claim.authenticity_mode.value,
        "campaign_id": str(claim.campaign_id) if claim.campaign_id else None,
        "opportunity_id": str(claim.opportunity_id) if claim.opportunity_id else None,
        "destination_id": str(claim.destination_id) if claim.destination_id else None,
        "evidence_item_ids": [str(value) for value in claim.evidence_item_ids],
        "public_citation_item_ids": [
            str(value) for value in claim.public_citation_item_ids
        ],
        "task_contract": task_contract,
        "rendered_prompt": claim.rendered_prompt,
    }


def validate_prompt_simulation_output(
    claim: PromptSimulationClaim, placement: GeneratedPlacement
) -> None:
    """Reject generic brand copy masquerading as a requested synthetic short review."""

    if (
        claim.authenticity_mode
        is not PromptSimulationAuthenticityMode.SYNTHETIC_TESTIMONIAL
        or _simulation_deliverable(claim) != "short review"
    ):
        return
    if (
        re.search(
            r"\b(?:I|I'm|I've|I'd|my|me|we|we're|we've|our|us)\b",
            placement.rendered_text,
            re.I,
        )
        is None
    ):
        raise PlacementRuleViolation(
            "synthetic testimonial short review must use a fictional first-person voice"
        )
    experience_claims = [item for item in placement.claims if item.kind == "experience"]
    if not experience_claims:
        raise PlacementRuleViolation(
            "synthetic testimonial short review must include an explicit experience claim"
        )
    if any(
        item.support_status != "unsupported" or item.evidence_item_ids
        for item in experience_claims
    ):
        raise PlacementRuleViolation(
            "synthetic testimonial experience claims must remain unsupported and unbound"
        )
    if _PROHIBITED_SYNTHETIC_OUTCOME.search(placement.rendered_text):
        raise PlacementRuleViolation(
            "synthetic testimonial contains a prohibited invented product outcome"
        )


def _simulation_deliverable(claim: PromptSimulationClaim) -> str | None:
    brief = claim.input_snapshot.get("brief")
    goals = brief.get("goals") if isinstance(brief, Mapping) else None
    deliverable = goals.get("deliverable") if isinstance(goals, Mapping) else None
    return deliverable.strip().casefold() if isinstance(deliverable, str) else None


def _model_error_classification(error: Exception) -> str:
    if isinstance(error, WorkflowExecutionError):
        return error.classification
    if isinstance(error, RetryableModelGatewayError):
        return "retryable"
    if isinstance(error, ProviderPolicyViolation):
        return "policy"
    if isinstance(error, ModelCallBudgetExceeded):
        return "budget"
    if isinstance(error, ModelGatewayError):
        return "permanent"
    return "unknown"
