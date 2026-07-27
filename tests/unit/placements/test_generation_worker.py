from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway import ModelGatewayRequest, ModelGatewayResult
from geo_core.placements.domain import PackageVersion, WorkflowStatus
from geo_core.placements.domain import PlacementRuleViolation
from geo_core.placements.generation_worker import parse_generated_placement
from geo_core.placements.ports import GenerationClaim
from geo_core.placements.worker_composition import GenerationHandler
from geo_core.placements.worker_models import ModelCallReservation
from geo_core.workflow_runtime import (
    RetryableWorkflowExecutionError,
    WorkflowExecutionResult,
)


class FakeStore:
    def __init__(self) -> None:
        self.transaction_open = False
        self.failed = None

    def heartbeat(self, lease, *, lease_for):
        del lease, lease_for

    def fail(self, lease, **values):
        del lease
        self.failed = values
        return "retry_wait"


class FakeRepository:
    def __init__(self, claim: GenerationClaim) -> None:
        self.claim = claim
        self.finalized = None
        self.success_log = None
        self.reserve_calls = 0

    def reserve_model_call(self, lease, claim, *, provider, request_hash):
        del lease, claim
        self.reserve_calls += 1
        return ModelCallReservation(1, request_hash, provider)

    def record_model_call_success(self, lease, claim, reservation, result):
        self.success_log = (lease, claim, reservation, result)

    def record_model_call_failure(self, lease, claim, reservation, **values):
        raise AssertionError((lease, claim, reservation, values))

    def load_generation(self, lease):
        del lease
        return self.claim

    def finalize_generation(self, lease, claim, placement, result):
        self.finalized = (lease, claim, placement, result)
        return PackageVersion(
            uuid4(),
            claim.project_id,
            claim.package_id,
            claim.prompt_bundle_id,
            1,
            placement.content_json,
            placement.rendered_text,
            "c" * 64,
            WorkflowStatus.GENERATED,
            generated_by_job_id=lease.job_id,
        )


class FakeGateway:
    provider = "deepseek"

    def __init__(self, store: FakeStore, evidence_id: object) -> None:
        self.store = store
        self.evidence_id = evidence_id
        self.maximum_calls = None
        self.request: ModelGatewayRequest | None = None

    def generate(self, request, *, policy, budget):
        del policy
        self.request = request
        assert not self.store.transaction_open
        self.maximum_calls = budget.maximum_calls
        budget.consume()
        return ModelGatewayResult(
            output={
                "content_json": {
                    "title": "Robot vacuum review",
                    "required_disclosures": [],
                    "expected_links": [],
                },
                "rendered_text": "Robot vacuum review",
                "claims": [
                    {
                        "text": "Daily cleaning was observed.",
                        "kind": "factual",
                        "support_status": "supported",
                        "evidence_item_ids": [str(self.evidence_id)],
                    }
                ],
                "internal_evidence_refs": [str(self.evidence_id)],
                "public_citation_refs": [str(self.evidence_id)],
            },
            call_log_id=uuid4(),
            provider_request_id="request-1",
            configured_model="deepseek-v4-flash",
            provider_reported_model="deepseek-v4-flash",
            prompt_tokens=10,
            completion_tokens=20,
            cost_usd=Decimal("0.001"),
            finish_reason="stop",
            response_hash="f" * 64,
        )


class FakeWorkflowExecutor:
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
            dify_task_id="task-1",
            dify_run_id="run-1",
            configured_model="deepseek-chat",
            provider_reported_model="deepseek-chat",
            prompt_tokens=10,
            completion_tokens=20,
            total_steps=3,
            elapsed_seconds=Decimal("0.5"),
            response_hash="e" * 64,
        )


def _valid_output(evidence_id):
    return {
        "content_json": {
            "title": "Robot vacuum review",
            "required_disclosures": [],
            "expected_links": [],
        },
        "rendered_text": "Robot vacuum review",
        "claims": [
            {
                "text": "Daily cleaning was observed.",
                "kind": "factual",
                "support_status": "supported",
                "evidence_item_ids": [str(evidence_id)],
            }
        ],
        "internal_evidence_refs": [str(evidence_id)],
        "public_citation_refs": [str(evidence_id)],
    }


def _generation_fixture():
    evidence_id, project_id, job_id = uuid4(), uuid4(), uuid4()
    lease = WorkerLease(job_id, project_id, "placement.generate", "worker", uuid4(), 2, 1, 3)
    claim = GenerationClaim(
        job_id=job_id,
        project_id=project_id,
        lease_token=lease.lease_token,
        fencing_generation=2,
        prompt_bundle_id=uuid4(),
        prompt_bundle_hash="a" * 64,
        system_prompt="Write in the published comparison voice.",
        rendered_prompt="Return JSON using evidence pack 1.",
        configured_model="deepseek-v4-flash",
        model_call_budget=2,
        package_id=uuid4(),
        next_version_number=1,
        base_version_id=None,
        evidence_item_ids=(evidence_id,),
        public_citation_item_ids=(evidence_id,),
        output_schema={"type": "object", "required": ["content_json", "claims"]},
    )
    return evidence_id, lease, claim


def test_generation_handler_calls_gateway_outside_transaction_and_preserves_budget() -> None:
    evidence_id, lease, claim = _generation_fixture()
    store = FakeStore()
    repository = FakeRepository(claim)
    gateway = FakeGateway(store, evidence_id)
    handler = GenerationHandler(
        store=store,
        repository=repository,
        gateway=gateway,
        lease_for=timedelta(minutes=2),
    )

    result = handler.handle(lease)

    assert result["status"] == "succeeded"
    assert gateway.maximum_calls == 1
    assert gateway.request is not None
    assert gateway.request.messages[0]["role"] == "system"
    assert "frozen output schema" in gateway.request.messages[0]["content"]
    assert gateway.request.messages[1] == {
        "role": "system",
        "content": "Write in the published comparison voice.",
    }
    assert gateway.request.messages[2]["role"] == "user"
    assert repository.finalized[2].claims[0].evidence_item_ids == (evidence_id,)
    assert repository.success_log[2].provider == "deepseek"
    assert store.failed is None


def test_generation_uses_bound_dify_workflow_without_native_model_call() -> None:
    evidence_id, lease, claim = _generation_fixture()
    store = FakeStore()
    repository = FakeRepository(claim)
    gateway = FakeGateway(store, evidence_id)
    workflow = FakeWorkflowExecutor(_valid_output(evidence_id))

    result = GenerationHandler(
        store=store,
        repository=repository,
        gateway=gateway,
        lease_for=timedelta(minutes=2),
        workflow_executor=workflow,
    ).handle(lease)

    assert result["status"] == "succeeded"
    assert workflow.requests[0].purpose == "placements.generation"
    assert gateway.request is None
    assert repository.reserve_calls == 0
    assert repository.success_log is None
    assert repository.finalized[3].provider == "dify"


def test_generation_dify_failure_never_falls_back_to_native_gateway() -> None:
    evidence_id, lease, claim = _generation_fixture()
    store = FakeStore()
    repository = FakeRepository(claim)
    gateway = FakeGateway(store, evidence_id)
    workflow = FakeWorkflowExecutor(
        error=RetryableWorkflowExecutionError("Dify is temporarily unavailable")
    )

    result = GenerationHandler(
        store=store,
        repository=repository,
        gateway=gateway,
        lease_for=timedelta(minutes=2),
        workflow_executor=workflow,
    ).handle(lease)

    assert result["status"] == "retry_wait"
    assert store.failed["retry_delay"] == timedelta(seconds=30)
    assert gateway.request is None
    assert repository.reserve_calls == 0
    assert repository.finalized is None


def test_internal_evidence_cannot_be_promoted_to_public_citation() -> None:
    evidence_id, project_id, job_id = uuid4(), uuid4(), uuid4()
    claim = GenerationClaim(
        job_id=job_id,
        project_id=project_id,
        lease_token=uuid4(),
        fencing_generation=1,
        prompt_bundle_id=uuid4(),
        prompt_bundle_hash="a" * 64,
        system_prompt="Frozen system prompt",
        rendered_prompt="frozen",
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        package_id=uuid4(),
        next_version_number=1,
        base_version_id=None,
        evidence_item_ids=(evidence_id,),
        public_citation_item_ids=(),
        output_schema={},
    )
    output = {
        "content_json": {"required_disclosures": [], "expected_links": []},
        "rendered_text": "Supported internally.",
        "claims": [
            {
                "text": "Supported internally.",
                "kind": "factual",
                "support_status": "supported",
                "evidence_item_ids": [str(evidence_id)],
            }
        ],
        "internal_evidence_refs": [str(evidence_id)],
        "public_citation_refs": [str(evidence_id)],
    }
    omitted_contract = {**output, "content_json": {"nested": {"disclosure": "decoy"}}}
    with pytest.raises(PlacementRuleViolation, match="required_disclosures"):
        parse_generated_placement(omitted_contract, claim=claim)
    with pytest.raises(PlacementRuleViolation, match="non-disclosable"):
        parse_generated_placement(output, claim=claim)
