from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
import hashlib
from uuid import uuid4

from geo_core.jobs.postgres import WorkerLease
from geo_core.knowledge.question_domain import (
    QuestionDimensionDraft,
    QuestionEntityInput,
    QuestionFactInput,
    QuestionGenerationClaim,
    freeze_dimensions,
)
from geo_core.knowledge.question_worker import KnowledgeQuestionGenerateHandler
from geo_core.rag import RagSelection
from geo_core.workflow_runtime import (
    RetryableWorkflowExecutionError,
    WorkflowExecutionResult,
)


class FakeStore:
    def __init__(self) -> None:
        self.failures = []

    def heartbeat(self, lease, *, lease_for):
        del lease, lease_for

    def fail(self, lease, *, error_code, details, retry_delay):
        del lease
        self.failures.append(
            {"error_code": error_code, "details": details, "retry_delay": retry_delay}
        )
        return "retry_wait" if retry_delay else "failed"


class FakeRepository:
    def __init__(self, claim: QuestionGenerationClaim) -> None:
        self.claim = claim
        self.reserve_calls = 0
        self.successes = []
        self.finalized = None

    def load(self, lease):
        assert lease.project_id == self.claim.project_id
        return self.claim

    def reserve_model_call(self, *args, **kwargs):
        del args, kwargs
        self.reserve_calls += 1
        raise AssertionError("bound Dify workflows must bypass the native model reservation")

    def record_model_call_success(self, *args, **kwargs):
        self.successes.append((args, kwargs))

    def record_model_call_failure(self, *args, **kwargs):
        raise AssertionError((args, kwargs))

    def finalize(self, lease, claim, candidates, artifact):
        del lease, claim
        self.finalized = (candidates, artifact)
        return {"question_candidate_count": len(candidates)}


@dataclass(frozen=True)
class StoredObject:
    uri: str
    content_hash: str


class FakeObjectStore:
    def __init__(self) -> None:
        self.keys = []

    def put_object(self, *, key, content, content_type, expected_hash=None):
        assert content_type == "application/json"
        actual = hashlib.sha256(content).hexdigest()
        assert actual == expected_hash
        self.keys.append(key)
        return StoredObject(f"s3://geo-artifacts/{key}", actual)


class FakeGateway:
    provider = "deepseek"

    def __init__(self) -> None:
        self.requests = []

    def generate(self, request, *, policy, budget):
        del policy, budget
        self.requests.append(request)
        raise AssertionError("bound Dify workflows must bypass the native gateway")


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
            runtime_release_hash="e" * 64,
            dify_task_id="question-task",
            dify_run_id="question-run",
            configured_model="deepseek-chat",
            provider_reported_model="deepseek-chat",
            prompt_tokens=10,
            completion_tokens=20,
            total_steps=3,
            elapsed_seconds=Decimal("0.5"),
            response_hash="f" * 64,
        )


def _claim_and_output():
    dimension = freeze_dimensions(
        (
            QuestionDimensionDraft(
                dimension_key="au-awareness",
                persona="Australian home owner",
                scenario="researching a robot mower",
                intent="verify product suitability",
                funnel="awareness",
                region="AU",
                language="en-AU",
                brand_scope="brand",
                platform="chatgpt_search",
                query_kind="research",
                subject="TerraMow V600",
            ),
        )
    )[0]
    fact_text = "TerraMow V600 is a robotic lawn mower."
    fact = QuestionFactInput(
        uuid4(), fact_text, hashlib.sha256(fact_text.encode()).hexdigest()
    )
    entity = QuestionEntityInput(uuid4(), "Product", "TerraMow V600")
    claim = QuestionGenerationClaim(
        project_id=uuid4(),
        campaign_id=uuid4(),
        input_hash="a" * 64,
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        adapter_release="project-native-rag-v1",
        selection_manifest_hash="b" * 64,
        duplicate_threshold=0.92,
        dimensions=(dimension,),
        facts=(fact,),
        entities=(entity,),
    )
    output = {
        "questions": [
            {
                "candidate_id": "candidate-1",
                "dimension_key": dimension.dimension_key,
                "variant_index": 1,
                "text": "Is the TerraMow V600 suitable for an Australian home lawn?",
                "semantic_fingerprint": "TerraMow V600 Australian home suitability",
                "supported_fact_ids": [str(fact.fact_candidate_id)],
                "supported_entity_ids": [str(entity.graph_entity_id)],
                "parent_candidate_id": None,
            }
        ]
    }
    return claim, output


def _lease(claim: QuestionGenerationClaim) -> WorkerLease:
    return WorkerLease(
        uuid4(),
        claim.project_id,
        "knowledge.question.generate",
        "worker",
        uuid4(),
        1,
        1,
        3,
    )


def _handler(claim, store, repository, gateway, object_store, workflow):
    return KnowledgeQuestionGenerateHandler(
        store=store,
        repository=repository,
        gateway=gateway,
        object_store=object_store,
        selection=RagSelection(
            "project-native-rag-v1", "project-native-rag-v1", "v1", "d" * 64
        ),
        selection_manifest_hash="b" * 64,
        lease_for=timedelta(seconds=30),
        workflow_executor=workflow,
    )


def test_question_worker_uses_bound_dify_workflow_without_native_model_call() -> None:
    claim, output = _claim_and_output()
    store = FakeStore()
    repository = FakeRepository(claim)
    gateway = FakeGateway()
    object_store = FakeObjectStore()
    workflow = FakeWorkflowExecutor(output)

    result = _handler(claim, store, repository, gateway, object_store, workflow).handle(
        _lease(claim)
    )

    assert result["status"] == "succeeded"
    assert result["question_candidate_count"] == 1
    assert workflow.requests[0].purpose == "knowledge.question_generation"
    assert workflow.requests[0].output_schema["additionalProperties"] is False
    assert not gateway.requests
    assert repository.reserve_calls == 0
    assert not repository.successes
    assert repository.finalized is not None
    assert len(object_store.keys) == 1


def test_question_worker_dify_failure_never_falls_back_to_native_gateway() -> None:
    claim, _output = _claim_and_output()
    store = FakeStore()
    repository = FakeRepository(claim)
    gateway = FakeGateway()
    object_store = FakeObjectStore()
    workflow = FakeWorkflowExecutor(
        error=RetryableWorkflowExecutionError("Dify is temporarily unavailable")
    )

    result = _handler(claim, store, repository, gateway, object_store, workflow).handle(
        _lease(claim)
    )

    assert result["status"] == "retry_wait"
    assert store.failures[0]["retry_delay"] == timedelta(seconds=30)
    assert not gateway.requests
    assert repository.reserve_calls == 0
    assert repository.finalized is None
    assert not object_store.keys
