"""PostgreSQL persistence for governed GEO question generation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.knowledge.question_domain import (
    EMBEDDING_MODEL_KEY,
    FrozenQuestionDimension,
    QuestionCandidateDraft,
    QuestionContractError,
    QuestionCoverageSlotClaim,
    QuestionEntityInput,
    QuestionFactInput,
    QuestionGenerationClaim,
    vector_literal,
)
from geo_core.knowledge.question_worker import StoredQuestionArtifact
from geo_core.knowledge.rag_domain import RagModelCallReservation
from geo_core.model_gateway import ModelGatewayResult
from geo_core.model_gateway.contracts import ModelCallBudgetExceeded


class KnowledgeQuestionPostgresRepository:
    def __init__(self, store: PostgresDurableJobStore) -> None:
        self._store = store

    def load(self, lease: WorkerLease) -> QuestionGenerationClaim:
        connection = self._store.open_project(lease.project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT spec.campaign_id, spec.configured_model,
                              spec.model_call_budget, spec.adapter_release,
                              spec.selection_manifest_hash,
                              spec.semantic_duplicate_threshold, job.input_hash,
                              spec.generation_mode, spec.coverage_profile,
                              spec.coverage_profile_hash, spec.target_count,
                              spec.product_entity_id, spec.product_category,
                              spec.product_name_snapshot
                       FROM knowledge_question_generation_specs spec
                       JOIN durable_jobs job
                         ON job.id = spec.job_id AND job.project_id = spec.project_id
                        AND job.campaign_id = spec.campaign_id
                       WHERE spec.job_id = %s AND spec.project_id = %s""",
                    (lease.job_id, lease.project_id),
                )
            )
            if row is None:
                raise QuestionContractError("question generation specification is missing")
            dimensions = _many(
                connection.execute(
                    """SELECT dimension_key, ordinal, turn_index,
                              parent_dimension_key, persona, scenario, intent, funnel,
                              region, language, brand_scope, platform, query_kind,
                              subject, competitor_entity_id, coverage_role,
                              topic_cluster, planned_query_text
                       FROM knowledge_question_dimensions
                       WHERE job_id = %s AND project_id = %s AND campaign_id = %s
                       ORDER BY ordinal""",
                    (lease.job_id, lease.project_id, row["campaign_id"]),
                )
            )
            facts = _many(
                connection.execute(
                    """SELECT input.fact_candidate_id, input.statement_snapshot,
                              input.statement_hash
                       FROM knowledge_question_generation_fact_inputs input
                       JOIN knowledge_fact_candidates fact
                         ON fact.id = input.fact_candidate_id
                        AND fact.project_id = input.project_id
                        AND fact.pipeline_run_id = input.pipeline_run_id
                        AND fact.source_id = input.source_id
                        AND fact.document_id = input.document_id
                        AND fact.chunk_id = input.chunk_id
                        AND fact.statement_hash = input.statement_hash
                       JOIN knowledge_sources source
                         ON source.id = fact.source_id AND source.project_id = fact.project_id
                       JOIN knowledge_chunks chunk
                         ON chunk.id = fact.chunk_id AND chunk.project_id = fact.project_id
                       WHERE input.job_id = %s AND input.project_id = %s
                         AND input.campaign_id = %s
                         AND fact.status = 'approved'
                         AND fact.lifecycle_status = 'active'
                         AND source.status = 'ready' AND chunk.status = 'active'
                       ORDER BY input.fact_candidate_id""",
                    (lease.job_id, lease.project_id, row["campaign_id"]),
                )
            )
            entities = _many(
                connection.execute(
                    """SELECT input.graph_entity_id, input.entity_type_snapshot,
                              input.canonical_name_snapshot
                       FROM knowledge_question_generation_entity_inputs input
                       JOIN knowledge_graph_entities entity
                         ON entity.id = input.graph_entity_id
                        AND entity.project_id = input.project_id
                       WHERE input.job_id = %s AND input.project_id = %s
                         AND input.campaign_id = %s AND entity.status = 'current'
                         AND EXISTS (
                           SELECT 1 FROM knowledge_graph_entity_sources source
                           JOIN knowledge_chunks chunk
                             ON chunk.id = source.chunk_id
                            AND chunk.project_id = source.project_id
                           WHERE source.project_id = entity.project_id
                             AND source.graph_entity_id = entity.id
                             AND source.lifecycle_status = 'active'
                             AND chunk.status = 'active'
                         )
                       ORDER BY input.graph_entity_id""",
                    (lease.job_id, lease.project_id, row["campaign_id"]),
                )
            )
            expected_facts = _count(
                connection,
                "knowledge_question_generation_fact_inputs",
                lease,
                row["campaign_id"],
            )
            expected_entities = _count(
                connection,
                "knowledge_question_generation_entity_inputs",
                lease,
                row["campaign_id"],
            )
            if len(facts) != expected_facts or len(entities) != expected_entities:
                raise QuestionContractError("question generation frozen sources are stale")
            claim = QuestionGenerationClaim(
                project_id=lease.project_id,
                campaign_id=row["campaign_id"],
                input_hash=str(row["input_hash"]),
                configured_model=str(row["configured_model"]),
                model_call_budget=int(row["model_call_budget"]),
                adapter_release=str(row["adapter_release"]),
                selection_manifest_hash=str(row["selection_manifest_hash"]),
                duplicate_threshold=float(row["semantic_duplicate_threshold"]),
                dimensions=tuple(
                    FrozenQuestionDimension(
                        **{
                            key: value
                            for key, value in item.items()
                            if key not in {"coverage_role", "topic_cluster", "planned_query_text"}
                        }
                    )
                    for item in dimensions
                ),
                facts=tuple(
                    QuestionFactInput(
                        fact_candidate_id=item["fact_candidate_id"],
                        statement=str(item["statement_snapshot"]),
                        statement_hash=str(item["statement_hash"]),
                    )
                    for item in facts
                ),
                entities=tuple(
                    QuestionEntityInput(
                        graph_entity_id=item["graph_entity_id"],
                        entity_type=str(item["entity_type_snapshot"]),
                        canonical_name=str(item["canonical_name_snapshot"]),
                    )
                    for item in entities
                ),
                generation_mode=str(row["generation_mode"]),
                coverage_profile=row["coverage_profile"],
                coverage_profile_hash=row["coverage_profile_hash"],
                target_count=row["target_count"],
                product_entity_id=row["product_entity_id"],
                product_category=row["product_category"],
                product_name=row["product_name_snapshot"],
                coverage_slots=tuple(
                    QuestionCoverageSlotClaim(
                        dimension_key=str(item["dimension_key"]),
                        coverage_role=item["coverage_role"],
                        topic_cluster=str(item["topic_cluster"]),
                        planned_query_text=item["planned_query_text"],
                    )
                    for item in dimensions
                    if item["coverage_role"] is not None
                ),
            )
            connection.rollback()
            return claim
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def load_batch_checkpoint(
        self, lease: WorkerLease, *, batch_index: int
    ) -> tuple[Mapping[str, object], str, str] | None:
        connection = self._store.open_project(lease.project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT output, execution_backend, actual_model
                       FROM knowledge_question_generation_batches
                       WHERE job_id = %s AND project_id = %s AND batch_index = %s""",
                    (lease.job_id, lease.project_id, batch_index),
                )
            )
            connection.rollback()
            if row is None:
                return None
            return row["output"], str(row["execution_backend"]), str(row["actual_model"])
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_batch_checkpoint(
        self,
        lease: WorkerLease,
        claim: QuestionGenerationClaim,
        *,
        batch_index: int,
        dimensions: Sequence[FrozenQuestionDimension],
        output: Mapping[str, object],
        execution_backend: str,
        actual_model: str,
    ) -> None:
        encoded = json.dumps(
            output, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        output_hash = hashlib.sha256(encoded.encode()).hexdigest()
        with self._store.fenced_transaction(lease) as connection:
            existing = _one(
                connection.execute(
                    """SELECT output_hash FROM knowledge_question_generation_batches
                       WHERE job_id = %s AND project_id = %s AND batch_index = %s""",
                    (lease.job_id, lease.project_id, batch_index),
                )
            )
            if existing is not None:
                if existing["output_hash"] != output_hash:
                    raise QuestionContractError("question batch checkpoint content changed")
                return
            connection.execute(
                """INSERT INTO knowledge_question_generation_batches
                     (job_id, project_id, campaign_id, batch_index, ordinal_start,
                      ordinal_end, slot_count, output, output_hash,
                      execution_backend, actual_model)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)""",
                (
                    lease.job_id,
                    lease.project_id,
                    claim.campaign_id,
                    batch_index,
                    dimensions[0].ordinal,
                    dimensions[-1].ordinal,
                    len(dimensions),
                    encoded,
                    output_hash,
                    execution_backend,
                    actual_model,
                ),
            )

    def reserve_model_call(
        self,
        lease: WorkerLease,
        claim: QuestionGenerationClaim,
        *,
        provider: str,
        request_hash: str,
    ) -> RagModelCallReservation:
        with self._store.fenced_transaction(lease) as connection:
            consumed = _one(
                connection.execute(
                    """SELECT count(*) AS count FROM model_call_logs
                       WHERE job_id = %s AND project_id = %s AND status = 'reserved'""",
                    (lease.job_id, lease.project_id),
                )
            )
            call_number = int(consumed["count"] if consumed else 0) + 1
            if call_number > claim.model_call_budget:
                raise ModelCallBudgetExceeded("question model call budget exhausted")
            connection.execute(
                """INSERT INTO model_call_logs
                     (project_id, job_id, call_number, status, request_hash,
                      prompt_bundle_hash, provider, configured_model)
                   VALUES (%s, %s, %s, 'reserved', %s, %s, %s, %s)""",
                (
                    lease.project_id,
                    lease.job_id,
                    call_number,
                    request_hash,
                    claim.input_hash,
                    provider,
                    claim.configured_model,
                ),
            )
            return RagModelCallReservation(call_number, request_hash, provider)

    def record_model_call_success(
        self,
        lease: WorkerLease,
        claim: QuestionGenerationClaim,
        reservation: RagModelCallReservation,
        result: ModelGatewayResult,
    ) -> None:
        with self._store.fenced_transaction(lease) as connection:
            connection.execute(
                """INSERT INTO model_call_logs
                     (project_id, job_id, call_number, status, request_hash,
                      prompt_bundle_hash, provider, configured_model, gateway_call_log_id,
                      provider_request_id, provider_reported_model, prompt_tokens,
                      completion_tokens, cost_usd, finish_reason, response_hash)
                   VALUES (%s, %s, %s, 'succeeded', %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s)""",
                (
                    lease.project_id,
                    lease.job_id,
                    reservation.call_number,
                    reservation.request_hash,
                    claim.input_hash,
                    reservation.provider,
                    claim.configured_model,
                    result.call_log_id,
                    result.provider_request_id,
                    result.provider_reported_model,
                    result.prompt_tokens,
                    result.completion_tokens,
                    result.cost_usd,
                    result.finish_reason,
                    result.response_hash,
                ),
            )

    def record_model_call_failure(
        self,
        lease: WorkerLease,
        claim: QuestionGenerationClaim,
        reservation: RagModelCallReservation,
        *,
        classification: str,
        error_code: str,
    ) -> None:
        with self._store.fenced_transaction(lease) as connection:
            connection.execute(
                """INSERT INTO model_call_logs
                     (project_id, job_id, call_number, status, request_hash,
                      prompt_bundle_hash, provider, configured_model,
                      error_classification, error_code)
                   VALUES (%s, %s, %s, 'failed', %s, %s, %s, %s, %s, %s)""",
                (
                    lease.project_id,
                    lease.job_id,
                    reservation.call_number,
                    reservation.request_hash,
                    claim.input_hash,
                    reservation.provider,
                    claim.configured_model,
                    classification,
                    error_code,
                ),
            )

    def finalize(
        self,
        lease: WorkerLease,
        claim: QuestionGenerationClaim,
        candidates: Sequence[QuestionCandidateDraft],
        artifact: StoredQuestionArtifact,
        *,
        execution_backend: str,
        actual_model: str,
    ) -> Mapping[str, object]:
        ids = {
            item.adapter_candidate_id: uuid5(
                NAMESPACE_URL,
                f"geo-question-candidate:{lease.job_id}:{item.adapter_candidate_id}",
            )
            for item in candidates
        }
        with self._store.fenced_transaction(lease) as connection:
            _lock_and_validate_generation_inputs(connection, lease=lease, claim=claim)
            for candidate in candidates:
                candidate_id = ids[candidate.adapter_candidate_id]
                connection.execute(
                    """INSERT INTO knowledge_question_candidates
                         (id, project_id, campaign_id, generated_by_job_id,
                          adapter_candidate_id, dimension_key, variant_index, turn_index,
                          parent_candidate_id, query_text, query_text_hash,
                          normalized_text_hash, semantic_fingerprint, embedding,
                          embedding_model_key, nearest_candidate_id, nearest_similarity,
                          dedup_status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s::vector, %s, %s, %s, %s)""",
                    (
                        candidate_id,
                        lease.project_id,
                        claim.campaign_id,
                        lease.job_id,
                        candidate.adapter_candidate_id,
                        candidate.dimension_key,
                        candidate.variant_index,
                        candidate.turn_index,
                        ids.get(candidate.parent_adapter_candidate_id or ""),
                        candidate.query_text,
                        candidate.query_text_hash,
                        candidate.normalized_text_hash,
                        candidate.semantic_fingerprint,
                        vector_literal(candidate.embedding),
                        EMBEDDING_MODEL_KEY,
                        ids.get(candidate.nearest_adapter_candidate_id or ""),
                        candidate.nearest_similarity,
                        candidate.dedup_status,
                    ),
                )
                for fact_id in candidate.fact_source_ids:
                    connection.execute(
                        """INSERT INTO knowledge_question_candidate_fact_sources
                             (candidate_id, generated_by_job_id, project_id,
                              campaign_id, fact_candidate_id)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (
                            candidate_id,
                            lease.job_id,
                            lease.project_id,
                            claim.campaign_id,
                            fact_id,
                        ),
                    )
                for entity_id in candidate.entity_source_ids:
                    connection.execute(
                        """INSERT INTO knowledge_question_candidate_entity_sources
                             (candidate_id, generated_by_job_id, project_id,
                              campaign_id, graph_entity_id)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (
                            candidate_id,
                            lease.job_id,
                            lease.project_id,
                            claim.campaign_id,
                            entity_id,
                        ),
                    )
            supported = len({item.dimension_key for item in candidates})
            possible = sum(item.dedup_status == "possible_duplicate" for item in candidates)
            connection.execute(
                """INSERT INTO knowledge_question_generation_results
                     (job_id, project_id, campaign_id, output_hash, artifact_uri,
                      artifact_hash, dimension_count, candidate_count,
                      supported_dimension_count, possible_duplicate_count,
                      execution_backend, actual_model, generated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           clock_timestamp())""",
                (
                    lease.job_id,
                    lease.project_id,
                    claim.campaign_id,
                    artifact.content_hash,
                    artifact.uri,
                    artifact.content_hash,
                    len(claim.dimensions),
                    len(candidates),
                    supported,
                    possible,
                    execution_backend,
                    actual_model,
                ),
            )
            details: dict[str, object] = {
                "artifact_uri": artifact.uri,
                "artifact_hash": artifact.content_hash,
                "dimension_count": len(claim.dimensions),
                "candidate_count": len(candidates),
                "supported_dimension_count": supported,
                "possible_duplicate_count": possible,
                "execution_backend": execution_backend,
                "actual_model": actual_model,
            }
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"knowledge-question-generation:{lease.job_id}",
                details=details,
            )
            return details


def _lock_and_validate_generation_inputs(
    connection: Any, *, lease: WorkerLease, claim: QuestionGenerationClaim
) -> None:
    facts = _many(
        connection.execute(
            """SELECT input.fact_candidate_id, input.statement_snapshot,
                      input.statement_hash
               FROM knowledge_question_generation_fact_inputs input
               JOIN knowledge_fact_candidates fact
                 ON fact.id = input.fact_candidate_id
                AND fact.project_id = input.project_id
                AND fact.pipeline_run_id = input.pipeline_run_id
                AND fact.source_id = input.source_id
                AND fact.document_id = input.document_id
                AND fact.chunk_id = input.chunk_id
                AND fact.rag_revision_id IS NOT DISTINCT FROM input.rag_revision_id
                AND fact.statement = input.statement_snapshot
                AND fact.statement_hash = input.statement_hash
                AND fact.source_locator IS NOT DISTINCT FROM input.source_locator
                AND fact.extractor_release = input.extractor_release
               JOIN knowledge_sources source
                 ON source.id = input.source_id AND source.project_id = input.project_id
               JOIN knowledge_chunks chunk
                 ON chunk.id = input.chunk_id AND chunk.project_id = input.project_id
                AND chunk.pipeline_run_id = input.pipeline_run_id
                AND chunk.source_id = input.source_id
                AND chunk.document_id = input.document_id
               WHERE input.job_id = %s AND input.project_id = %s
                 AND input.campaign_id = %s
                 AND fact.status = 'approved'
                 AND fact.lifecycle_status = 'active'
                 AND source.status = 'ready' AND chunk.status = 'active'
               ORDER BY input.fact_candidate_id
               FOR SHARE OF fact, source, chunk""",
            (lease.job_id, lease.project_id, claim.campaign_id),
        )
    )
    expected_facts = {
        (item.fact_candidate_id, item.statement, item.statement_hash) for item in claim.facts
    }
    current_facts = {
        (
            item["fact_candidate_id"],
            str(item["statement_snapshot"]),
            str(item["statement_hash"]),
        )
        for item in facts
    }
    if current_facts != expected_facts:
        raise QuestionContractError("question generation Fact inputs became stale during execution")

    source_rows = _many(
        connection.execute(
            """SELECT input.graph_entity_id, source.chunk_id
               FROM knowledge_question_generation_entity_inputs input
               JOIN knowledge_graph_entity_sources source
                 ON source.graph_entity_id = input.graph_entity_id
                AND source.project_id = input.project_id
               WHERE input.job_id = %s AND input.project_id = %s
                 AND input.campaign_id = %s
                 AND source.lifecycle_status = 'active'
               ORDER BY input.graph_entity_id, source.chunk_id
               FOR SHARE OF source""",
            (lease.job_id, lease.project_id, claim.campaign_id),
        )
    )
    expected_entity_ids = {item.graph_entity_id for item in claim.entities}
    if {item["graph_entity_id"] for item in source_rows} != expected_entity_ids:
        raise QuestionContractError(
            "question generation Entity inputs became stale during execution"
        )

    entities = _many(
        connection.execute(
            """SELECT input.graph_entity_id, input.entity_type_snapshot,
                      input.canonical_name_snapshot
               FROM knowledge_question_generation_entity_inputs input
               JOIN knowledge_graph_entities entity
                 ON entity.id = input.graph_entity_id
                AND entity.project_id = input.project_id
                AND entity.entity_type = input.entity_type_snapshot
                AND entity.canonical_name = input.canonical_name_snapshot
                AND entity.name_hash = input.name_hash
               WHERE input.job_id = %s AND input.project_id = %s
                 AND input.campaign_id = %s AND entity.status = 'current'
               ORDER BY input.graph_entity_id
               FOR SHARE OF entity""",
            (lease.job_id, lease.project_id, claim.campaign_id),
        )
    )
    expected_entities = {
        (item.graph_entity_id, item.entity_type, item.canonical_name) for item in claim.entities
    }
    current_entities = {
        (
            item["graph_entity_id"],
            str(item["entity_type_snapshot"]),
            str(item["canonical_name_snapshot"]),
        )
        for item in entities
    }
    if current_entities != expected_entities:
        raise QuestionContractError(
            "question generation Entity inputs became stale during execution"
        )

    active_entity_chunks = _many(
        connection.execute(
            """SELECT input.graph_entity_id, chunk.id AS chunk_id
               FROM knowledge_question_generation_entity_inputs input
               JOIN knowledge_graph_entity_sources source
                 ON source.graph_entity_id = input.graph_entity_id
                AND source.project_id = input.project_id
                AND source.lifecycle_status = 'active'
               JOIN knowledge_chunks chunk
                 ON chunk.id = source.chunk_id AND chunk.project_id = source.project_id
                AND chunk.pipeline_run_id = source.pipeline_run_id
                AND chunk.source_id = source.source_id
                AND chunk.document_id = source.document_id
               WHERE input.job_id = %s AND input.project_id = %s
                 AND input.campaign_id = %s AND chunk.status = 'active'
               ORDER BY input.graph_entity_id, chunk.id
               FOR SHARE OF chunk""",
            (lease.job_id, lease.project_id, claim.campaign_id),
        )
    )
    if {item["graph_entity_id"] for item in active_entity_chunks} != expected_entity_ids:
        raise QuestionContractError(
            "question generation Entity inputs became stale during execution"
        )


def _count(
    connection: Any,
    table: str,
    lease: WorkerLease,
    campaign_id: UUID,
) -> int:
    row = _one(
        connection.execute(
            f"""SELECT count(*) AS count FROM {table}
                WHERE job_id = %s AND project_id = %s AND campaign_id = %s""",  # nosec B608
            (lease.job_id, lease.project_id, campaign_id),
        )
    )
    return int(row["count"] if row else 0)


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((column.name for column in cursor.description), row, strict=True))


def _many(cursor: Any) -> list[dict[str, Any]]:
    return [
        dict(row)
        if isinstance(row, Mapping)
        else dict(zip((column.name for column in cursor.description), row, strict=True))
        for row in cursor.fetchall()
    ]
