from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
import hashlib
from uuid import uuid4

from geo_core.jobs.postgres import WorkerLease
from geo_core.knowledge.rag_domain import (
    KnowledgeRagChunk,
    KnowledgeRagClaim,
    RagModelCallReservation,
)
from geo_core.knowledge.rag_worker import KnowledgeRagExtractHandler
from geo_core.model_gateway import ModelGatewayResult
from geo_core.rag import RagSelection


class FakeStore:
    def __init__(self) -> None:
        self.failures: list[dict[str, object]] = []

    def fail(self, lease, *, error_code, details, retry_delay):
        self.failures.append(
            {
                "lease": lease,
                "error_code": error_code,
                "details": details,
                "retry_delay": retry_delay,
            }
        )
        return "retry_wait" if retry_delay else "failed"

    def heartbeat(self, lease, *, lease_for):
        del lease, lease_for


class FakeRepository:
    def __init__(self, claim: KnowledgeRagClaim) -> None:
        self.claim = claim
        self.reservations: list[RagModelCallReservation] = []
        self.successes: list[ModelGatewayResult] = []
        self.failures: list[str] = []
        self.finalized = None

    def load(self, lease):
        assert lease.project_id == self.claim.project_id
        return self.claim

    def reserve_model_call(self, lease, claim, *, provider, request_hash):
        del lease, claim
        value = RagModelCallReservation(len(self.reservations) + 1, request_hash, provider)
        self.reservations.append(value)
        return value

    def record_model_call_success(self, lease, claim, reservation, result):
        del lease, claim, reservation
        self.successes.append(result)

    def record_model_call_failure(self, lease, claim, reservation, *, classification, error_code):
        del lease, claim, reservation, classification
        self.failures.append(error_code)

    def finalize(self, lease, claim, graph, artifact):
        del lease, claim
        self.finalized = (graph, artifact)
        return {
            "rag_revision_id": str(uuid4()),
            "fact_candidate_count": len(graph.facts),
            "entity_candidate_count": len(graph.entities),
            "relation_candidate_count": len(graph.relations),
        }


class FakeGateway:
    provider = "deepseek"

    def __init__(self) -> None:
        self.requests = []

    def generate(self, request, *, policy, budget):
        del policy
        budget.consume()
        self.requests.append(request)
        return ModelGatewayResult(
            output={
                "facts": [
                    {
                        "text": "A1 的流量为每分钟 2 升。",
                        "source_quote": "A1 的流量为每分钟 2 升。",
                    }
                ],
                "entities": [
                    {"entity_type": "Product", "name": "A1", "source_quote": "A1"},
                    {"entity_type": "Brand", "name": "星澜", "source_quote": "星澜"},
                ],
                "relations": [
                    {
                        "subject": "A1",
                        "predicate": "belongs_to",
                        "object": "星澜",
                        "source_quote": "A1 belongs_to 星澜",
                    }
                ],
            },
            call_log_id=uuid4(),
            provider_request_id="provider-1",
            configured_model=request.configured_model,
            provider_reported_model=request.configured_model,
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=Decimal("0.01"),
            finish_reason="stop",
            response_hash="c" * 64,
        )


@dataclass(frozen=True)
class FakeStoredObject:
    uri: str
    content_hash: str


class FakeObjectStore:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def put_object(self, *, key, content, content_type, expected_hash=None):
        assert content_type == "application/json"
        actual = hashlib.sha256(content).hexdigest()
        assert actual == expected_hash
        self.keys.append(key)
        return FakeStoredObject(f"s3://geo-artifacts/{key}", actual)


def _claim() -> KnowledgeRagClaim:
    project_id = uuid4()
    text = "A1 的流量为每分钟 2 升。\nProduct: A1\nBrand: 星澜\nA1 belongs_to 星澜"
    chunk = KnowledgeRagChunk(uuid4(), 0, text, hashlib.sha256(text.encode()).hexdigest())
    return KnowledgeRagClaim(
        project_id=project_id,
        pipeline_run_id=uuid4(),
        source_id=uuid4(),
        logical_source_id=uuid4(),
        document_id=uuid4(),
        title="A1",
        input_hash="a" * 64,
        adapter_release="project-native-rag-v1",
        selection_manifest_hash="b" * 64,
        configured_model="deepseek-v4-flash",
        model_call_budget=3,
        requested_by=uuid4(),
        chunks=(chunk,),
    )


def _lease(claim: KnowledgeRagClaim) -> WorkerLease:
    return WorkerLease(
        uuid4(), claim.project_id, "knowledge.rag.extract", "worker-1", uuid4(), 1, 1, 3
    )


def _selection() -> RagSelection:
    return RagSelection("project-native-rag-v1", "project-native-rag-v1", "v1", "d" * 64)


def test_rag_worker_audits_model_archives_artifact_and_finalizes_candidates() -> None:
    claim = _claim()
    store = FakeStore()
    repository = FakeRepository(claim)
    gateway = FakeGateway()
    object_store = FakeObjectStore()
    handler = KnowledgeRagExtractHandler(
        store=store,
        repository=repository,
        gateway=gateway,
        object_store=object_store,
        selection=_selection(),
        selection_manifest_hash="b" * 64,
        lease_for=timedelta(minutes=2),
    )

    result = handler.handle(_lease(claim))

    assert result["status"] == "succeeded"
    assert result["fact_candidate_count"] == 1
    assert len(repository.reservations) == len(repository.successes) == 1
    assert not repository.failures
    assert repository.finalized is not None
    assert len(repository.finalized[0].entities) == 2
    assert object_store.keys[0].startswith("knowledge-rag-artifacts/")
    assert gateway.requests[0].project_id == claim.project_id
    assert not store.failures


def test_rag_worker_fails_closed_before_model_call_when_selection_changed() -> None:
    claim = _claim()
    store = FakeStore()
    repository = FakeRepository(claim)
    gateway = FakeGateway()
    handler = KnowledgeRagExtractHandler(
        store=store,
        repository=repository,
        gateway=gateway,
        object_store=FakeObjectStore(),
        selection=_selection(),
        selection_manifest_hash="e" * 64,
        lease_for=timedelta(minutes=2),
    )

    result = handler.handle(_lease(claim))

    assert result["status"] == "failed"
    assert store.failures[0]["error_code"] == "KnowledgeRagContractError"
    assert store.failures[0]["retry_delay"] is None
    assert not gateway.requests
