from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from geo_core.model_gateway import ModelGatewayResult
from geo_core.placements.generation_worker import PlacementGenerationWorker
from geo_core.placements.ports import GenerationClaim


class FakeGenerationPort:
    def __init__(self, claim: GenerationClaim) -> None:
        self.claim = claim
        self.transaction_open = False
        self.finalized = None
        self.failed = None

    def claim_next(self, **values: object) -> GenerationClaim:
        del values
        self.transaction_open = True
        frozen = self.claim
        self.transaction_open = False
        return frozen

    def finalize(self, **values: object):
        self.finalized = values
        return values["placement"]

    def fail(self, **values: object) -> None:
        self.failed = values


class FakeGateway:
    def __init__(self, port: FakeGenerationPort, evidence_id: object) -> None:
        self.port = port
        self.evidence_id = evidence_id
        self.maximum_calls = None

    def generate(self, request, *, policy, budget):
        del request, policy
        assert not self.port.transaction_open
        self.maximum_calls = budget.maximum_calls
        budget.consume()
        return ModelGatewayResult(
            output={
                "content_json": {"title": "Robot vacuum review"},
                "rendered_text": "Robot vacuum review",
                "claims": [{
                    "text": "Daily cleaning was observed.", "kind": "factual",
                    "support_status": "supported",
                    "evidence_item_ids": [str(self.evidence_id)],
                }],
            },
            call_log_id=uuid4(), provider_request_id="request-1",
            configured_model="deepseek-chat", provider_reported_model="deepseek-chat",
            prompt_tokens=10, completion_tokens=20, cost_usd=Decimal("0.001"),
            finish_reason="stop", response_hash="f" * 64,
        )


def test_worker_calls_gateway_outside_transaction_and_preserves_job_budget() -> None:
    evidence_id = uuid4()
    claim = GenerationClaim(
        job_id=uuid4(), project_id=uuid4(), lease_token=uuid4(), fencing_generation=2,
        prompt_bundle_id=uuid4(), prompt_bundle_hash="a" * 64,
        rendered_prompt="Use evidence pack 1.", configured_model="deepseek-chat",
        model_call_budget=2, package_id=uuid4(), next_version_number=1,
        evidence_item_ids=(evidence_id,),
    )
    port = FakeGenerationPort(claim)
    gateway = FakeGateway(port, evidence_id)
    worker = PlacementGenerationWorker(
        port=port, gateway=gateway, worker_id="worker-1", lease_for=timedelta(minutes=2)
    )

    result = worker.run_once()

    assert result is port.finalized["placement"]
    assert gateway.maximum_calls == 2
    assert port.finalized["claim"].fencing_generation == 2
    assert port.finalized["placement"].claims[0].evidence_item_ids == (evidence_id,)
    assert port.failed is None
