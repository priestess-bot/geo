"""Durable, audited execution of the selected Knowledge RAG adapter."""

from __future__ import annotations

from datetime import timedelta
from typing import Mapping, Protocol, Sequence

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.knowledge.rag_domain import (
    KnowledgeRagClaim,
    KnowledgeRagContractError,
    RagModelCallReservation,
    StoredRagArtifact,
    artifact_key,
    canonical_candidate_artifact,
    validate_candidate_graph,
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
from geo_core.object_store import ObjectStoreError
from geo_core.rag import CandidateGraph, RagSelection, selected_rag_adapter
from geo_core.rag.contracts import JsonModelInvoker


class StoredObjectLike(Protocol):
    uri: str
    content_hash: str


class RagArtifactStore(Protocol):
    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObjectLike: ...


class KnowledgeRagWorkerRepository(Protocol):
    def load(self, lease: WorkerLease) -> KnowledgeRagClaim: ...

    def reserve_model_call(
        self,
        lease: WorkerLease,
        claim: KnowledgeRagClaim,
        *,
        provider: str,
        request_hash: str,
    ) -> RagModelCallReservation: ...

    def record_model_call_success(
        self,
        lease: WorkerLease,
        claim: KnowledgeRagClaim,
        reservation: RagModelCallReservation,
        result: ModelGatewayResult,
    ) -> None: ...

    def record_model_call_failure(
        self,
        lease: WorkerLease,
        claim: KnowledgeRagClaim,
        reservation: RagModelCallReservation,
        *,
        classification: str,
        error_code: str,
    ) -> None: ...

    def finalize(
        self,
        lease: WorkerLease,
        claim: KnowledgeRagClaim,
        graph: CandidateGraph,
        artifact: StoredRagArtifact,
    ) -> Mapping[str, object]: ...


class KnowledgeRagExtractHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: KnowledgeRagWorkerRepository,
        gateway: ModelGateway,
        object_store: RagArtifactStore,
        selection: RagSelection,
        selection_manifest_hash: str,
        lease_for: timedelta,
    ) -> None:
        self._store = store
        self._repository = repository
        self._gateway = gateway
        self._object_store = object_store
        self._selection = selection
        self._selection_manifest_hash = selection_manifest_hash
        self._lease_for = lease_for

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            claim = self._repository.load(lease)
            self._validate_selection(claim)
            invoker = _AuditedRagInvoker(
                lease=lease,
                claim=claim,
                repository=self._repository,
                gateway=self._gateway,
            )
            adapter = selected_rag_adapter(self._selection, invoker)
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                graph = adapter.extract(claim.source_documents())
                heartbeat.raise_if_stopped()
                validate_candidate_graph(claim, graph)
                content, content_hash = canonical_candidate_artifact(claim, graph)
                stored = self._object_store.put_object(
                    key=artifact_key(claim, content_hash),
                    content=content,
                    content_type="application/json",
                    expected_hash=content_hash,
                )
                heartbeat.raise_if_stopped()
            details = self._repository.finalize(
                lease,
                claim,
                graph,
                StoredRagArtifact(stored.uri, stored.content_hash),
            )
            return {"status": "succeeded", "job_id": str(lease.job_id), **details}
        except (JobCancellationRequested, LostJobLease):
            raise
        except Exception as exc:
            return self._fail(lease, exc)

    def _validate_selection(self, claim: KnowledgeRagClaim) -> None:
        if claim.adapter_release != self._selection.adapter_release:
            raise KnowledgeRagContractError("RAG job adapter differs from runtime selection")
        if claim.selection_manifest_hash != self._selection_manifest_hash:
            raise KnowledgeRagContractError("RAG job selection manifest changed after enqueue")

    def _fail(self, lease: WorkerLease, error: Exception) -> Mapping[str, object]:
        retryable = isinstance(error, (RetryableModelGatewayError, ObjectStoreError)) or getattr(
            error, "sqlstate", None
        ) in {"40001", "40P01"}
        status = self._store.fail(
            lease,
            error_code=type(error).__name__,
            details={
                "message": str(error)[:2000],
                "classification": _model_error_classification(error),
            },
            retry_delay=timedelta(seconds=30) if retryable else None,
        )
        return {"status": status, "job_id": str(lease.job_id)}


class _AuditedRagInvoker(JsonModelInvoker):
    def __init__(
        self,
        *,
        lease: WorkerLease,
        claim: KnowledgeRagClaim,
        repository: KnowledgeRagWorkerRepository,
        gateway: ModelGateway,
    ) -> None:
        self._lease = lease
        self._claim = claim
        self._repository = repository
        self._gateway = gateway

    def complete_json(
        self,
        *,
        project_id: str,
        purpose: str,
        messages: Sequence[Mapping[str, str]],
        request_hash: str,
        max_output_tokens: int,
    ) -> Mapping[str, object]:
        if project_id != str(self._lease.project_id):
            raise KnowledgeRagContractError("RAG model request crossed its project boundary")
        provider = str(getattr(self._gateway, "provider", "unknown"))
        reservation = self._repository.reserve_model_call(
            self._lease,
            self._claim,
            provider=provider,
            request_hash=request_hash,
        )
        request = ModelGatewayRequest(
            messages=tuple(dict(value) for value in messages),
            configured_model=self._claim.configured_model,
            prompt_bundle_hash=request_hash,
            project_id=self._lease.project_id,
            purpose=purpose,
            temperature=0.0,
            max_output_tokens=max_output_tokens,
        )
        try:
            result = self._gateway.generate(
                request,
                policy=ModelPolicy(),
                budget=ModelCallBudget(1),
            )
        except Exception as exc:
            self._repository.record_model_call_failure(
                self._lease,
                self._claim,
                reservation,
                classification=_model_error_classification(exc),
                error_code=type(exc).__name__,
            )
            raise
        self._repository.record_model_call_success(
            self._lease,
            self._claim,
            reservation,
            result,
        )
        return result.output


def _model_error_classification(error: Exception) -> str:
    if isinstance(error, RetryableModelGatewayError):
        return "retryable"
    if isinstance(error, ProviderPolicyViolation):
        return "policy"
    if isinstance(error, ModelCallBudgetExceeded):
        return "budget"
    if isinstance(error, ModelGatewayError):
        return "permanent"
    if isinstance(error, KnowledgeRagContractError):
        return "contract"
    if isinstance(error, ObjectStoreError):
        return "retryable"
    return "unknown"
