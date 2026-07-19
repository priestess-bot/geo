"""PostgreSQL persistence for project-scoped Knowledge RAG candidates."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.knowledge.rag_graph_lifecycle import archive_unreferenced_graph_rows
from geo_core.knowledge.rag_domain import (
    KnowledgeRagChunk,
    KnowledgeRagClaim,
    KnowledgeRagContractError,
    RagModelCallReservation,
    StoredRagArtifact,
    candidate_fingerprint,
    graph_entity_type,
    graph_predicate,
    validate_candidate_graph,
)
from geo_core.model_gateway import ModelGatewayResult
from geo_core.model_gateway.contracts import ModelCallBudgetExceeded
from geo_core.rag import CandidateGraph


class KnowledgeRagPostgresRepository:
    def __init__(self, store: PostgresDurableJobStore) -> None:
        self._store = store

    def load(self, lease: WorkerLease) -> KnowledgeRagClaim:
        connection = self._store.open_project(lease.project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT spec.pipeline_run_id, spec.source_id, spec.document_id,
                              spec.configured_model, spec.model_call_budget,
                              spec.adapter_release, spec.selection_manifest_hash,
                              spec.requested_by, job.input_hash, source.logical_source_id,
                              source.title, source.status AS source_status,
                              run.status AS pipeline_status
                       FROM knowledge_rag_job_specs spec
                       JOIN durable_jobs job
                         ON job.id = spec.job_id AND job.project_id = spec.project_id
                       JOIN knowledge_pipeline_runs run
                         ON run.id = spec.pipeline_run_id
                        AND run.project_id = spec.project_id
                        AND run.source_id = spec.source_id
                       JOIN knowledge_sources source
                         ON source.id = spec.source_id AND source.project_id = spec.project_id
                       JOIN knowledge_documents document
                         ON document.id = spec.document_id
                        AND document.project_id = spec.project_id
                        AND document.pipeline_run_id = spec.pipeline_run_id
                        AND document.source_id = spec.source_id
                       WHERE spec.job_id = %s AND spec.project_id = %s""",
                    (lease.job_id, lease.project_id),
                )
            )
            if row is None:
                raise KnowledgeRagContractError("Knowledge RAG job specification is missing")
            if row["source_status"] != "ready" or row["pipeline_status"] != "succeeded":
                raise KnowledgeRagContractError("Knowledge source is not ready for RAG extraction")
            chunk_rows = _many(
                connection.execute(
                    """SELECT id, chunk_index, text, text_hash
                       FROM knowledge_chunks
                       WHERE project_id = %s AND pipeline_run_id = %s
                         AND source_id = %s AND document_id = %s AND status = 'active'
                       ORDER BY chunk_index, id""",
                    (
                        lease.project_id,
                        row["pipeline_run_id"],
                        row["source_id"],
                        row["document_id"],
                    ),
                )
            )
            claim = KnowledgeRagClaim(
                project_id=lease.project_id,
                pipeline_run_id=row["pipeline_run_id"],
                source_id=row["source_id"],
                logical_source_id=row["logical_source_id"],
                document_id=row["document_id"],
                title=str(row["title"]),
                input_hash=str(row["input_hash"]),
                adapter_release=str(row["adapter_release"]),
                selection_manifest_hash=str(row["selection_manifest_hash"]),
                configured_model=str(row["configured_model"]),
                model_call_budget=int(row["model_call_budget"]),
                requested_by=row["requested_by"],
                chunks=tuple(
                    KnowledgeRagChunk(
                        chunk_id=value["id"],
                        chunk_index=int(value["chunk_index"]),
                        text=str(value["text"]),
                        text_hash=str(value["text_hash"]),
                    )
                    for value in chunk_rows
                ),
            )
            connection.rollback()
            return claim
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reserve_model_call(
        self,
        lease: WorkerLease,
        claim: KnowledgeRagClaim,
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
                raise ModelCallBudgetExceeded("Knowledge RAG model call budget exhausted")
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
        claim: KnowledgeRagClaim,
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
        claim: KnowledgeRagClaim,
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
        claim: KnowledgeRagClaim,
        graph: CandidateGraph,
        artifact: StoredRagArtifact,
    ) -> Mapping[str, object]:
        validate_candidate_graph(claim, graph)
        revision_id = uuid5(NAMESPACE_URL, f"geo-knowledge-rag-revision:{lease.job_id}")
        chunk_by_id = {str(item.chunk_id): item for item in claim.chunks}
        with self._store.fenced_transaction(lease) as connection:
            previous = _many(
                connection.execute(
                    """UPDATE knowledge_rag_revisions
                       SET lifecycle_status = 'superseded', superseded_at = clock_timestamp()
                       WHERE project_id = %s AND logical_source_id = %s
                         AND lifecycle_status = 'active'
                       RETURNING id""",
                    (lease.project_id, claim.logical_source_id),
                )
            )
            previous_ids = [value["id"] for value in previous]
            if previous_ids:
                for table in (
                    "knowledge_fact_candidates",
                    "knowledge_entity_candidates",
                    "knowledge_relation_candidates",
                ):
                    connection.execute(
                        f"""UPDATE {table} SET lifecycle_status = 'superseded',
                                  updated_at = clock_timestamp()
                            WHERE project_id = %s AND rag_revision_id = ANY(%s)""",  # nosec B608
                        (lease.project_id, previous_ids),
                    )
                connection.execute(
                    """UPDATE knowledge_graph_entity_sources
                       SET lifecycle_status = 'superseded'
                       WHERE project_id = %s AND rag_revision_id = ANY(%s)""",
                    (lease.project_id, previous_ids),
                )
                connection.execute(
                    """UPDATE knowledge_graph_relation_sources
                       SET lifecycle_status = 'superseded'
                       WHERE project_id = %s AND rag_revision_id = ANY(%s)""",
                    (lease.project_id, previous_ids),
                )
                archive_unreferenced_graph_rows(connection, lease.project_id)
            connection.execute(
                """INSERT INTO knowledge_rag_revisions
                     (id, project_id, job_id, pipeline_run_id, source_id,
                      logical_source_id, document_id, adapter_release,
                      selection_manifest_hash, input_hash, output_hash,
                      artifact_uri, artifact_hash, lifecycle_status, created_by,
                      completed_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, 'active', %s, clock_timestamp())""",
                (
                    revision_id,
                    lease.project_id,
                    lease.job_id,
                    claim.pipeline_run_id,
                    claim.source_id,
                    claim.logical_source_id,
                    claim.document_id,
                    claim.adapter_release,
                    claim.selection_manifest_hash,
                    claim.input_hash,
                    artifact.content_hash,
                    artifact.uri,
                    artifact.content_hash,
                    claim.requested_by,
                ),
            )
            fact_count = self._persist_facts(
                connection, lease, claim, revision_id, graph, chunk_by_id
            )
            entity_ids = self._persist_entities(
                connection, lease, claim, revision_id, graph, chunk_by_id
            )
            relation_count = self._persist_relations(
                connection, lease, claim, revision_id, graph, entity_ids
            )
            self._persist_findings(connection, lease, revision_id, graph)
            archived_sources = _many(
                connection.execute(
                    """UPDATE knowledge_sources SET status = 'archived',
                              updated_at = clock_timestamp()
                       WHERE project_id = %s AND logical_source_id = %s
                         AND id <> %s AND status = 'ready'
                       RETURNING id""",
                    (lease.project_id, claim.logical_source_id, claim.source_id),
                )
            )
            archived_source_ids = [value["id"] for value in archived_sources]
            if previous_ids:
                connection.execute(
                    """UPDATE knowledge_chunks chunk SET status = 'disabled',
                              updated_at = clock_timestamp()
                       WHERE chunk.project_id = %s AND chunk.status = 'active'
                         AND chunk.pipeline_run_id <> %s
                         AND EXISTS (
                           SELECT 1 FROM knowledge_rag_revisions revision
                           WHERE revision.id = ANY(%s)
                             AND revision.project_id = chunk.project_id
                             AND revision.pipeline_run_id = chunk.pipeline_run_id
                         )""",
                    (lease.project_id, claim.pipeline_run_id, previous_ids),
                )
            if archived_source_ids:
                connection.execute(
                    """UPDATE knowledge_chunks SET status = 'disabled',
                              updated_at = clock_timestamp()
                       WHERE project_id = %s AND source_id = ANY(%s)
                         AND status = 'active'""",
                    (lease.project_id, archived_source_ids),
                )
                connection.execute(
                    """UPDATE knowledge_fact_candidates
                       SET lifecycle_status = 'superseded', updated_at = clock_timestamp()
                       WHERE project_id = %s AND source_id = ANY(%s)
                         AND lifecycle_status = 'active'""",
                    (lease.project_id, archived_source_ids),
                )
            details: dict[str, object] = {
                "rag_revision_id": str(revision_id),
                "adapter_release": claim.adapter_release,
                "selection_manifest_hash": claim.selection_manifest_hash,
                "artifact_uri": artifact.uri,
                "artifact_hash": artifact.content_hash,
                "fact_candidate_count": fact_count,
                "entity_candidate_count": len(entity_ids),
                "relation_candidate_count": relation_count,
                "validation_finding_count": len(graph.validation_findings),
                "superseded_revision_count": len(previous_ids),
                "superseded_source_count": len(archived_source_ids),
            }
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"knowledge-rag-revision:{revision_id}",
                details=details,
            )
            return details

    @staticmethod
    def _persist_facts(
        connection: Any,
        lease: WorkerLease,
        claim: KnowledgeRagClaim,
        revision_id: UUID,
        graph: CandidateGraph,
        chunk_by_id: Mapping[str, KnowledgeRagChunk],
    ) -> int:
        connection.execute(
            """UPDATE knowledge_fact_candidates
               SET lifecycle_status = 'superseded', updated_at = clock_timestamp()
               WHERE project_id = %s AND pipeline_run_id = %s AND rag_revision_id IS NULL""",
            (lease.project_id, claim.pipeline_run_id),
        )
        fact_ids: dict[str, UUID] = {}
        for fact in graph.facts:
            statement_hash = hashlib.sha256(fact.text.encode()).hexdigest()
            chunk = chunk_by_id[fact.source_document_id]
            row = _one(
                connection.execute(
                    """INSERT INTO knowledge_fact_candidates
                         (id, project_id, pipeline_run_id, source_id, document_id,
                          chunk_id, statement, statement_hash, rag_revision_id,
                          extractor_release, source_locator, lifecycle_status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
                       ON CONFLICT (rag_revision_id, statement_hash) DO UPDATE SET
                         extractor_release = EXCLUDED.extractor_release,
                         lifecycle_status = 'active', updated_at = clock_timestamp()
                       RETURNING id""",
                    (
                        uuid5(
                            NAMESPACE_URL,
                            f"geo-knowledge-rag-fact:{revision_id}:{statement_hash}",
                        ),
                        lease.project_id,
                        claim.pipeline_run_id,
                        claim.source_id,
                        claim.document_id,
                        chunk.chunk_id,
                        fact.text,
                        statement_hash,
                        revision_id,
                        claim.adapter_release,
                        fact.source_locator,
                    ),
                )
            )
            if row is None:
                raise KnowledgeRagContractError("RAG fact candidate could not be persisted")
            fact_id = row["id"]
            fact_ids.setdefault(statement_hash, fact_id)
            connection.execute(
                """INSERT INTO knowledge_fact_candidate_sources
                     (project_id, fact_candidate_id, rag_revision_id, pipeline_run_id,
                      source_id, document_id, chunk_id, source_locator)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    lease.project_id,
                    fact_id,
                    revision_id,
                    claim.pipeline_run_id,
                    claim.source_id,
                    claim.document_id,
                    chunk.chunk_id,
                    fact.source_locator,
                ),
            )
        return len(fact_ids)

    @staticmethod
    def _persist_entities(
        connection: Any,
        lease: WorkerLease,
        claim: KnowledgeRagClaim,
        revision_id: UUID,
        graph: CandidateGraph,
        chunk_by_id: Mapping[str, KnowledgeRagChunk],
    ) -> dict[str, UUID]:
        result: dict[str, UUID] = {}
        for entity in graph.entities:
            entity_type = graph_entity_type(entity.entity_type).value
            name_hash = hashlib.sha256(entity.name.encode()).hexdigest()
            candidate_id = uuid5(
                NAMESPACE_URL,
                f"geo-knowledge-rag-entity:{revision_id}:{entity_type}:{name_hash}",
            )
            connection.execute(
                """INSERT INTO knowledge_entity_candidates
                     (id, project_id, rag_revision_id, pipeline_run_id, source_id,
                      document_id, adapter_candidate_id, entity_type, name, name_hash,
                      generated_by_job_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    candidate_id,
                    lease.project_id,
                    revision_id,
                    claim.pipeline_run_id,
                    claim.source_id,
                    claim.document_id,
                    entity.candidate_id,
                    entity_type,
                    entity.name,
                    name_hash,
                    lease.job_id,
                ),
            )
            if entity.name in result:
                raise KnowledgeRagContractError("RAG entity names are ambiguous within a revision")
            result[entity.name] = candidate_id
            for source_id in entity.source_document_ids:
                chunk = chunk_by_id[source_id]
                connection.execute(
                    """INSERT INTO knowledge_entity_candidate_sources
                         (project_id, entity_candidate_id, rag_revision_id,
                          pipeline_run_id, source_id, document_id, chunk_id,
                          source_locator)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        lease.project_id,
                        candidate_id,
                        revision_id,
                        claim.pipeline_run_id,
                        claim.source_id,
                        claim.document_id,
                        chunk.chunk_id,
                        _line_locator(chunk.text, entity.name),
                    ),
                )
        return result

    @staticmethod
    def _persist_relations(
        connection: Any,
        lease: WorkerLease,
        claim: KnowledgeRagClaim,
        revision_id: UUID,
        graph: CandidateGraph,
        entity_ids: Mapping[str, UUID],
    ) -> int:
        seen: set[str] = set()
        for relation in graph.relations:
            predicate = graph_predicate(relation.predicate).value
            fingerprint = candidate_fingerprint(
                [relation.subject, predicate, relation.object, relation.source_document_id]
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            connection.execute(
                """INSERT INTO knowledge_relation_candidates
                     (id, project_id, rag_revision_id, pipeline_run_id, source_id,
                      document_id, chunk_id, adapter_candidate_id,
                      subject_entity_candidate_id, predicate, object_entity_candidate_id,
                      source_locator, generated_by_job_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    uuid5(NAMESPACE_URL, f"geo-knowledge-rag-relation:{revision_id}:{fingerprint}"),
                    lease.project_id,
                    revision_id,
                    claim.pipeline_run_id,
                    claim.source_id,
                    claim.document_id,
                    UUID(relation.source_document_id),
                    relation.candidate_id,
                    entity_ids[relation.subject],
                    predicate,
                    entity_ids[relation.object],
                    relation.source_locator,
                    lease.job_id,
                ),
            )
        return len(seen)

    @staticmethod
    def _persist_findings(
        connection: Any,
        lease: WorkerLease,
        revision_id: UUID,
        graph: CandidateGraph,
    ) -> None:
        for finding in graph.validation_findings:
            connection.execute(
                """INSERT INTO knowledge_rag_validation_findings
                     (project_id, rag_revision_id, pipeline_run_id, source_id,
                      document_id, chunk_id, candidate_kind, reason_code,
                      candidate_hash)
                   SELECT %s, %s, revision.pipeline_run_id, revision.source_id,
                          revision.document_id, %s, %s, %s, %s
                   FROM knowledge_rag_revisions revision
                   WHERE revision.id = %s AND revision.project_id = %s
                   ON CONFLICT DO NOTHING""",
                (
                    lease.project_id,
                    revision_id,
                    UUID(finding.source_document_id),
                    finding.candidate_kind,
                    finding.reason_code,
                    finding.candidate_hash,
                    revision_id,
                    lease.project_id,
                ),
            )


def _line_locator(content: str, value: str) -> str:
    offset = content.find(value)
    if offset < 0:
        raise KnowledgeRagContractError("RAG entity source is not traceable to its chunk")
    return f"line:{content.count(chr(10), 0, offset) + 1}"


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
