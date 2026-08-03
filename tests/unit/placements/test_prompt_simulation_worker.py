from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway import ModelGatewayResult
from geo_core.placements.simulation_worker import PromptSimulationHandler
from geo_core.placements.simulation import PromptSimulationAuthenticityMode
from geo_core.placements.worker_models import (
    ModelCallReservation,
    PromptSimulationClaim,
)
from geo_core.workflow_runtime import (
    RetryableWorkflowExecutionError,
    WorkflowExecutionResult,
)


class _Store:
    def __init__(self) -> None:
        self.failure = None

    def heartbeat(self, lease, *, lease_for):
        del lease, lease_for

    def fail(self, lease, *, error_code, details, retry_delay):
        del lease
        self.failure = {
            "error_code": error_code,
            "details": details,
            "retry_delay": retry_delay,
        }
        return "retry_wait" if retry_delay else "failed"


class _Repository:
    def __init__(self, claim: PromptSimulationClaim) -> None:
        self.claim = claim
        self.finalized = None
        self.reserve_calls = 0
        self.success_log = None

    def load_prompt_simulation(self, lease):
        del lease
        return self.claim

    def reserve_model_call(self, lease, claim, *, provider, request_hash):
        del lease, claim
        self.reserve_calls += 1
        return ModelCallReservation(1, request_hash, provider)

    def record_model_call_success(self, lease, claim, reservation, result):
        self.success_log = (lease, claim, reservation, result)

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
                "content_json": {
                    "headline": "Synthetic consumer testimonial",
                    "required_disclosures": [],
                    "expected_links": [],
                },
                "rendered_text": (
                    "I've used the TerraMow V600 for six months and it transformed my lawn."
                ),
                "claims": [
                    {
                        "text": "I've used the TerraMow V600 for six months.",
                        "kind": "experience",
                        "support_status": "unsupported",
                        "evidence_item_ids": [],
                    }
                ],
                "internal_evidence_refs": [],
                "public_citation_refs": [],
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


class _WorkflowExecutor:
    def __init__(self, output=None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.requests = []

    def execute_optional(self, lease, request):
        del lease
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.output is not None
        return WorkflowExecutionResult(
            output=self.output,
            attempt_id=uuid4(),
            runtime_release_id=uuid4(),
            runtime_release_hash="d" * 64,
            dify_task_id="simulation-task",
            dify_run_id="simulation-run",
            configured_model="deepseek-chat",
            provider_reported_model="deepseek-chat",
            prompt_tokens=10,
            completion_tokens=20,
            total_steps=3,
            elapsed_seconds=Decimal("0.5"),
            response_hash="e" * 64,
        )


def _simulation_output():
    return {
        "content_json": {
            "headline": "Synthetic consumer testimonial",
            "required_disclosures": [],
            "expected_links": [],
        },
        "rendered_text": "I've used the TerraMow V600 for six months.",
        "claims": [
            {
                "text": "I've used the TerraMow V600 for six months.",
                "kind": "experience",
                "support_status": "unsupported",
                "evidence_item_ids": [],
            }
        ],
        "internal_evidence_refs": [],
        "public_citation_refs": [],
    }


@pytest.mark.parametrize(
    ("authenticity_mode", "expected_instruction"),
    (
        (
            PromptSimulationAuthenticityMode.FAKE_PERSONA,
            "Invent a plausible consumer identity",
        ),
        (
            PromptSimulationAuthenticityMode.SYNTHETIC_TESTIMONIAL,
            "fictional first-person consumer testimonial",
        ),
    ),
)
def test_prompt_simulation_handler_allows_synthetic_consumer_copy_but_never_publishable(
    authenticity_mode: PromptSimulationAuthenticityMode,
    expected_instruction: str,
) -> None:
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
        input_snapshot={
            "brief": {
                "goals": {
                    "intent": "product recommendation",
                    "audience": "Australian homeowners",
                    "deliverable": "short review",
                },
                "constraints": {"public_citations_required": True},
            }
        },
        authenticity_mode=authenticity_mode,
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
        uuid4(),
        claim.project_id,
        "prompt_simulation.generate",
        "unit-worker",
        uuid4(),
        1,
        1,
        3,
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
    assert gateway.request.temperature == 0.0
    assert gateway.request.max_output_tokens == 8192
    assert gateway.request.messages[0]["content"] == claim.system_prompt
    instruction = " ".join(gateway.request.messages[1]["content"].split())
    assert authenticity_mode.value in instruction
    assert expected_instruction in instruction
    assert "written by an independent consumer" not in instruction
    assert "does not permit invented product or offer capabilities" in instruction
    assert "boundary wires, apps, schedules" in instruction
    assert "Marking one of those statements unsupported is not permission" in instruction
    assert "remove every unsupported capability" in instruction
    assert "use it as the only experience storyline" in instruction
    assert "must remain unsupported with no evidence IDs" in instruction
    assert "Delete unsupported time-saving, performance, reliability" in instruction
    assert "do not add unlisted installation steps" in instruction
    assert str(evidence_id) in instruction
    assert "never return null, none, labels, or invented IDs" in instruction
    assert repository.finalized is not None
    assert repository.finalized.rendered_text.startswith("I've used")
    assert repository.finalized.claims[0].support_status == "unsupported"


def test_simulation_uses_bound_dify_workflow_without_native_model_call() -> None:
    evidence_id = uuid4()
    claim = PromptSimulationClaim(
        simulation_id=uuid4(),
        project_id=uuid4(),
        input_hash="a" * 64,
        input_snapshot={
            "brief": {
                "goals": {
                    "intent": "product recommendation",
                    "audience": "Australian homeowners",
                    "deliverable": "short review",
                },
                "constraints": {"public_citations_required": True},
            }
        },
        authenticity_mode=PromptSimulationAuthenticityMode.SYNTHETIC_TESTIMONIAL,
        system_prompt="Use the selected platform style.",
        rendered_prompt="Generate a preview.",
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        evidence_item_ids=(evidence_id,),
        public_citation_item_ids=(evidence_id,),
        output_schema={"type": "object", "required": ["content_json", "claims"]},
    )
    repository = _Repository(claim)
    gateway = _Gateway(evidence_id)
    workflow = _WorkflowExecutor(_simulation_output())
    lease = WorkerLease(
        uuid4(), claim.project_id, "prompt_simulation.generate", "worker", uuid4(), 1, 1, 3
    )

    result = PromptSimulationHandler(
        store=_Store(),
        repository=repository,
        gateway=gateway,
        lease_for=timedelta(seconds=30),
        workflow_executor=workflow,
    ).handle(lease)

    assert result["status"] == "succeeded"
    assert workflow.requests[0].purpose == "placements.simulation"
    assert workflow.requests[0].context["task_contract"] == {
        "contract": "geo-prompt-simulation-task-v1",
        "authenticity_mode": "synthetic_testimonial",
        "simulation_purpose": "content_preview",
        "test_only": True,
        "publication_eligible": False,
        "intent": "product recommendation",
        "audience": "Australian homeowners",
        "deliverable": "short review",
        "public_citations_required": True,
    }
    assert gateway.request is None
    assert repository.reserve_calls == 0
    assert repository.success_log is None


def test_simulation_rejects_generic_brand_copy_for_synthetic_short_review() -> None:
    evidence_id = uuid4()
    claim = PromptSimulationClaim(
        simulation_id=uuid4(),
        project_id=uuid4(),
        input_hash="a" * 64,
        input_snapshot={"brief": {"goals": {"deliverable": "short review"}}},
        authenticity_mode=PromptSimulationAuthenticityMode.SYNTHETIC_TESTIMONIAL,
        system_prompt="Use the selected platform style.",
        rendered_prompt="Generate a preview.",
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        evidence_item_ids=(evidence_id,),
        public_citation_item_ids=(evidence_id,),
        output_schema={"type": "object", "required": ["content_json", "claims"]},
    )
    generic_output = {
        "content_json": {"required_disclosures": [], "expected_links": []},
        "rendered_text": "The TerraMow V600 is designed for medium-sized lawns.",
        "claims": [
            {
                "text": "The TerraMow V600 is designed for medium-sized lawns.",
                "kind": "factual",
                "support_status": "supported",
                "evidence_item_ids": [str(evidence_id)],
            }
        ],
        "internal_evidence_refs": [str(evidence_id)],
        "public_citation_refs": [str(evidence_id)],
    }
    store = _Store()
    repository = _Repository(claim)
    workflow = _WorkflowExecutor(generic_output)
    lease = WorkerLease(
        uuid4(), claim.project_id, "prompt_simulation.generate", "worker", uuid4(), 1, 1, 3
    )

    result = PromptSimulationHandler(
        store=store,
        repository=repository,
        gateway=_Gateway(evidence_id),
        lease_for=timedelta(seconds=30),
        workflow_executor=workflow,
    ).handle(lease)

    assert result["status"] == "failed"
    assert store.failure["details"]["classification"] == "contract"
    assert "fictional first-person voice" in store.failure["details"]["message"]
    assert repository.finalized is None


def test_simulation_rejects_invented_product_outcome_in_synthetic_short_review() -> None:
    evidence_id = uuid4()
    claim = PromptSimulationClaim(
        simulation_id=uuid4(),
        project_id=uuid4(),
        input_hash="a" * 64,
        input_snapshot={"brief": {"goals": {"deliverable": "short review"}}},
        authenticity_mode=PromptSimulationAuthenticityMode.SYNTHETIC_TESTIMONIAL,
        system_prompt="Use the selected platform style.",
        rendered_prompt="Generate a preview.",
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        evidence_item_ids=(evidence_id,),
        public_citation_item_ids=(evidence_id,),
        output_schema={"type": "object", "required": ["content_json", "claims"]},
    )
    output = _simulation_output()
    output["rendered_text"] = (
        "I've used the TerraMow V600 for a few weeks and it has been a real time-saver."
    )
    store = _Store()
    repository = _Repository(claim)
    lease = WorkerLease(
        uuid4(), claim.project_id, "prompt_simulation.generate", "worker", uuid4(), 1, 1, 3
    )

    result = PromptSimulationHandler(
        store=store,
        repository=repository,
        gateway=_Gateway(evidence_id),
        lease_for=timedelta(seconds=30),
        workflow_executor=_WorkflowExecutor(output),
    ).handle(lease)

    assert result["status"] == "failed"
    assert "prohibited invented product outcome" in store.failure["details"]["message"]
    assert repository.finalized is None


def test_simulation_dify_failure_never_falls_back_to_native_gateway() -> None:
    evidence_id = uuid4()
    claim = PromptSimulationClaim(
        simulation_id=uuid4(),
        project_id=uuid4(),
        input_hash="a" * 64,
        input_snapshot={},
        authenticity_mode=PromptSimulationAuthenticityMode.FAKE_PERSONA,
        system_prompt="Use the selected platform style.",
        rendered_prompt="Generate a preview.",
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        evidence_item_ids=(evidence_id,),
        public_citation_item_ids=(evidence_id,),
        output_schema={"type": "object", "required": ["content_json", "claims"]},
    )
    store = _Store()
    repository = _Repository(claim)
    gateway = _Gateway(evidence_id)
    workflow = _WorkflowExecutor(
        error=RetryableWorkflowExecutionError("Dify is temporarily unavailable")
    )
    lease = WorkerLease(
        uuid4(), claim.project_id, "prompt_simulation.generate", "worker", uuid4(), 1, 1, 3
    )

    result = PromptSimulationHandler(
        store=store,
        repository=repository,
        gateway=gateway,
        lease_for=timedelta(seconds=30),
        workflow_executor=workflow,
    ).handle(lease)

    assert result["status"] == "retry_wait"
    assert store.failure["retry_delay"] == timedelta(seconds=30)
    assert gateway.request is None
    assert repository.reserve_calls == 0
    assert repository.finalized is None
