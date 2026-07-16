from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway import ModelGatewayResult
from geo_core.placements.simulation_worker import PromptSimulationHandler
from geo_core.placements.worker_models import (
    ModelCallReservation,
    PromptSimulationClaim,
)


class _Store:
    def heartbeat(self, lease, *, lease_for):
        del lease, lease_for

    def fail(self, lease, *, error_code, details, retry_delay):
        del lease, error_code, details, retry_delay
        return "failed"


class _Repository:
    def __init__(self, claim: PromptSimulationClaim) -> None:
        self.claim = claim
        self.finalized = None

    def load_prompt_simulation(self, lease):
        del lease
        return self.claim

    def reserve_model_call(self, lease, claim, *, provider, request_hash):
        del lease, claim
        return ModelCallReservation(1, request_hash, provider)

    def record_model_call_success(self, lease, claim, reservation, result):
        del lease, claim, reservation, result

    def record_model_call_failure(self, *args, **kwargs):
        raise AssertionError("the deterministic gateway must not fail")

    def finalize_prompt_simulation(self, lease, claim, placement, result):
        del lease, claim, result
        self.finalized = placement
        return {
            "simulation_id": str(self.claim.simulation_id),
            "test_only": True,
            "publication_eligible": False,
        }


class _Gateway:
    provider = "deterministic"

    def __init__(self, evidence_id) -> None:
        self.evidence_id = evidence_id
        self.request = None

    def generate(self, request, *, policy, budget):
        del policy
        budget.consume()
        self.request = request
        return ModelGatewayResult(
            output={
                "content_json": {"headline": "Technical preview"},
                "rendered_text": "Evidence-led technical preview.",
                "claims": [
                    {
                        "text": "Evidence-led technical preview.",
                        "kind": "factual",
                        "support_status": "supported",
                        "evidence_item_ids": [str(self.evidence_id)],
                    }
                ],
                "internal_evidence_refs": [str(self.evidence_id)],
                "public_citation_refs": [str(self.evidence_id)],
            },
            call_log_id=uuid4(),
            provider_request_id="simulation-unit",
            configured_model="deepseek-v4-flash",
            provider_reported_model="deepseek-v4-flash",
            prompt_tokens=10,
            completion_tokens=20,
            cost_usd=Decimal("0"),
            finish_reason="stop",
            response_hash="b" * 64,
        )


def test_prompt_simulation_handler_never_returns_a_publishable_result() -> None:
    evidence_id = uuid4()
    output_schema = {
        "type": "object",
        "required": [
            "content_json",
            "rendered_text",
            "claims",
            "internal_evidence_refs",
            "public_citation_refs",
        ],
    }
    claim = PromptSimulationClaim(
        simulation_id=uuid4(),
        project_id=uuid4(),
        input_hash="a" * 64,
        input_snapshot={},
        system_prompt="Use the selected platform style.",
        rendered_prompt="Generate a preview.",
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        evidence_item_ids=(evidence_id,),
        public_citation_item_ids=(evidence_id,),
        output_schema=output_schema,
    )
    repository = _Repository(claim)
    gateway = _Gateway(evidence_id)
    lease = WorkerLease(
        uuid4(), claim.project_id, "prompt_simulation.generate", "unit-worker",
        uuid4(), 1, 1, 3,
    )

    result = PromptSimulationHandler(
        store=_Store(),
        repository=repository,
        gateway=gateway,
        lease_for=timedelta(seconds=30),
    ).handle(lease)

    assert result["status"] == "succeeded"
    assert result["test_only"] is True
    assert result["publication_eligible"] is False
    assert gateway.request.purpose == "geo-prompt-simulation"
    assert gateway.request.prompt_bundle_hash == claim.input_hash
    assert repository.finalized is not None
