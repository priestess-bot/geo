"""Durable generation of governed GEO question candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
import hashlib
import json
from typing import Literal, Mapping, Protocol, Sequence

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.knowledge.question_domain import (
    FrozenQuestionDimension,
    QUESTION_GENERATION_BATCH_SIZE,
    QuestionCandidateDraft,
    QuestionContractError,
    QuestionGenerationClaim,
    canonical_question_artifact,
    parse_question_candidates,
    question_artifact_key,
)
from geo_core.knowledge.rag_domain import RagModelCallReservation
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
from geo_core.rag import RagSelection
from geo_core.workflow_runtime import (
    RetryableWorkflowExecutionError,
    WorkflowExecutionError,
    WorkflowExecutionRequest,
    WorkflowExecutor,
)


QUESTION_GENERATION_OUTPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["questions"],
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_id",
                    "dimension_key",
                    "variant_index",
                    "text",
                    "semantic_fingerprint",
                    "supported_fact_ids",
                    "supported_entity_ids",
                    "parent_candidate_id",
                ],
                "properties": {
                    "candidate_id": {"type": "string", "minLength": 1},
                    "dimension_key": {"type": "string", "minLength": 1},
                    "variant_index": {"type": "integer", "minimum": 1, "maximum": 3},
                    "text": {"type": "string", "minLength": 1},
                    "semantic_fingerprint": {"type": "string", "minLength": 1},
                    "supported_fact_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "supported_entity_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "parent_candidate_id": {"type": ["string", "null"]},
                },
            },
        }
    },
}


_SYSTEM_PROMPT = """Generate grounded GEO test questions for the supplied frozen dimensions.
Return exactly one JSON object with a questions array. Each question must contain only:
candidate_id, dimension_key, variant_index, text, semantic_fingerprint, supported_fact_ids,
supported_entity_ids, parent_candidate_id. Generate one or two natural user questions per dimension.
Use only supplied Fact and entity IDs. Every question needs at least one Fact. A follow-up question must
reference a supplied parent candidate. Do not invent product claims, entities, sources, or dimensions.
semantic_fingerprint must be a concise normalized intent, not a new claim.
"""


@dataclass(frozen=True)
class StoredQuestionArtifact:
    uri: str
    content_hash: str


@dataclass(frozen=True)
class QuestionBatchResult:
    output: Mapping[str, object]
    execution_backend: Literal["dify", "native"]
    actual_model: str


class StoredObjectLike(Protocol):
    uri: str
    content_hash: str


class QuestionArtifactStore(Protocol):
    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObjectLike: ...


class QuestionWorkerRepository(Protocol):
    def load(self, lease: WorkerLease) -> QuestionGenerationClaim: ...

    def reserve_model_call(
        self,
        lease: WorkerLease,
        claim: QuestionGenerationClaim,
        *,
        provider: str,
        request_hash: str,
    ) -> RagModelCallReservation: ...

    def record_model_call_success(
        self,
        lease: WorkerLease,
        claim: QuestionGenerationClaim,
        reservation: RagModelCallReservation,
        result: ModelGatewayResult,
    ) -> None: ...

    def record_model_call_failure(
        self,
        lease: WorkerLease,
        claim: QuestionGenerationClaim,
        reservation: RagModelCallReservation,
        *,
        classification: str,
        error_code: str,
    ) -> None: ...

    def finalize(
        self,
        lease: WorkerLease,
        claim: QuestionGenerationClaim,
        candidates: Sequence[QuestionCandidateDraft],
        artifact: StoredQuestionArtifact,
        *,
        execution_backend: Literal["dify", "native"],
        actual_model: str,
    ) -> Mapping[str, object]: ...


class KnowledgeQuestionGenerateHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: QuestionWorkerRepository,
        gateway: ModelGateway,
        object_store: QuestionArtifactStore,
        selection: RagSelection,
        selection_manifest_hash: str,
        lease_for: timedelta,
        workflow_executor: WorkflowExecutor | None = None,
    ) -> None:
        self._store = store
        self._repository = repository
        self._gateway = gateway
        self._object_store = object_store
        self._selection = selection
        self._selection_manifest_hash = selection_manifest_hash
        self._lease_for = lease_for
        self._workflow_executor = workflow_executor

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            claim = self._repository.load(lease)
            self._validate_selection(claim)
            candidates: list[QuestionCandidateDraft] = []
            execution_identities: set[tuple[Literal["dify", "native"], str]] = set()
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                for dimensions in _batches_by_turn(claim):
                    batch = self._generate_batch(lease, claim, dimensions, candidates)
                    execution_identities.add(
                        (batch.execution_backend, batch.actual_model)
                    )
                    candidates.extend(
                        parse_question_candidates(
                            batch.output,
                            dimensions=dimensions,
                            facts=claim.facts,
                            entities=claim.entities,
                            duplicate_threshold=claim.duplicate_threshold,
                            prior_candidates=candidates,
                        )
                    )
                    heartbeat.raise_if_stopped()
                content, content_hash = canonical_question_artifact(claim, candidates)
                stored = self._object_store.put_object(
                    key=question_artifact_key(
                        project_id=lease.project_id,
                        campaign_id=claim.campaign_id,
                        job_id=lease.job_id,
                        content_hash=content_hash,
                    ),
                    content=content,
                    content_type="application/json",
                    expected_hash=content_hash,
                )
                heartbeat.raise_if_stopped()
            if len(execution_identities) != 1:
                raise QuestionContractError(
                    "question generation batches used inconsistent execution identities"
                )
            execution_backend, actual_model = execution_identities.pop()
            details = self._repository.finalize(
                lease,
                claim,
                candidates,
                StoredQuestionArtifact(stored.uri, stored.content_hash),
                execution_backend=execution_backend,
                actual_model=actual_model,
            )
            return {"status": "succeeded", "job_id": str(lease.job_id), **details}
        except (JobCancellationRequested, LostJobLease):
            raise
        except Exception as exc:
            return self._fail(lease, exc)

    def _validate_selection(self, claim: QuestionGenerationClaim) -> None:
        if claim.adapter_release != self._selection.adapter_release:
            raise QuestionContractError("question Job adapter differs from runtime selection")
        if claim.selection_manifest_hash != self._selection_manifest_hash:
            raise QuestionContractError("question Job selection changed after enqueue")

    def _generate_batch(
        self,
        lease: WorkerLease,
        claim: QuestionGenerationClaim,
        dimensions: Sequence[FrozenQuestionDimension],
        prior: Sequence[QuestionCandidateDraft],
    ) -> QuestionBatchResult:
        dimension_rows = [asdict(value) for value in dimensions]
        parent_keys = {
            str(row.get("parent_dimension_key"))
            for row in dimension_rows
            if row.get("parent_dimension_key")
        }
        parents = [
            {
                "candidate_id": item.adapter_candidate_id,
                "dimension_key": item.dimension_key,
                "text": item.query_text,
            }
            for item in prior
            if item.dimension_key in parent_keys
        ]
        payload = {
            "project_id": str(lease.project_id),
            "campaign_id": str(claim.campaign_id),
            "dimensions": dimension_rows,
            "facts": [
                {
                    "fact_candidate_id": str(item.fact_candidate_id),
                    "statement": item.statement,
                }
                for item in claim.facts
            ],
            "entities": [
                {
                    "graph_entity_id": str(item.graph_entity_id),
                    "entity_type": item.entity_type,
                    "canonical_name": item.canonical_name,
                }
                for item in claim.entities
            ],
            "parent_candidates": parents,
        }
        if self._workflow_executor is not None:
            workflow_result = self._workflow_executor.execute_optional(
                lease,
                WorkflowExecutionRequest(
                    project_id=lease.project_id,
                    purpose="knowledge.question_generation",
                    context=payload,
                    input_hash=request_hash_for_payload(payload),
                    output_schema=QUESTION_GENERATION_OUTPUT_SCHEMA,
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=json.dumps(
                        payload, ensure_ascii=False, sort_keys=True, default=str
                    ),
                ),
            )
            if workflow_result is not None:
                return QuestionBatchResult(
                    output=workflow_result.output,
                    execution_backend="dify",
                    actual_model=(
                        workflow_result.provider_reported_model
                        or workflow_result.configured_model
                    ),
                )
        messages = (
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
            },
        )
        request_hash = hashlib.sha256(
            json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        provider = str(getattr(self._gateway, "provider", "unknown"))
        reservation = self._repository.reserve_model_call(
            lease, claim, provider=provider, request_hash=request_hash
        )
        request = ModelGatewayRequest(
            messages=tuple(dict(value) for value in messages),
            configured_model=claim.configured_model,
            prompt_bundle_hash=request_hash,
            project_id=lease.project_id,
            purpose="geo-question-candidate-generation",
            temperature=0.2,
            max_output_tokens=6000,
        )
        try:
            result = self._gateway.generate(
                request,
                policy=ModelPolicy(),
                budget=ModelCallBudget(1),
            )
        except Exception as exc:
            self._repository.record_model_call_failure(
                lease,
                claim,
                reservation,
                classification=_error_classification(exc),
                error_code=type(exc).__name__,
            )
            raise
        self._repository.record_model_call_success(lease, claim, reservation, result)
        return QuestionBatchResult(
            output=result.output,
            execution_backend="native",
            actual_model=result.provider_reported_model or result.configured_model,
        )

    def _fail(self, lease: WorkerLease, error: Exception) -> Mapping[str, object]:
        retryable = isinstance(
            error,
            (RetryableModelGatewayError, RetryableWorkflowExecutionError, ObjectStoreError),
        )
        status = self._store.fail(
            lease,
            error_code=type(error).__name__,
            details={
                "message": str(error)[:2000],
                "classification": _error_classification(error),
            },
            retry_delay=timedelta(seconds=30) if retryable else None,
        )
        return {"status": status, "job_id": str(lease.job_id)}


def _batches_by_turn(
    claim: QuestionGenerationClaim,
) -> tuple[tuple[FrozenQuestionDimension, ...], ...]:
    batches: list[tuple[FrozenQuestionDimension, ...]] = []
    for turn in range(1, 4):
        values = [item for item in claim.dimensions if item.turn_index == turn]
        batches.extend(
            tuple(values[index : index + QUESTION_GENERATION_BATCH_SIZE])
            for index in range(0, len(values), QUESTION_GENERATION_BATCH_SIZE)
        )
    return tuple(batches)


def _error_classification(error: Exception) -> str:
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
    if isinstance(error, QuestionContractError):
        return "contract"
    if isinstance(error, ObjectStoreError):
        return "retryable"
    return "unknown"


def request_hash_for_payload(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
