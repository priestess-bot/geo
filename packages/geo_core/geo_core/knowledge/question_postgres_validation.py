"""Staleness validation for governed GEO question generation inputs."""

from __future__ import annotations

from typing import Any, Mapping
from geo_core.jobs.postgres import WorkerLease
from geo_core.knowledge.question_domain import QuestionContractError, QuestionGenerationClaim


def lock_and_validate_generation_inputs(
    connection: Any, *, lease: WorkerLease, claim: QuestionGenerationClaim
) -> None:
    """Lock the frozen source rows and reject changes made during generation."""
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


def _many(cursor: Any) -> list[dict[str, Any]]:
    return [
        dict(row)
        if isinstance(row, Mapping)
        else dict(zip((column.name for column in cursor.description), row, strict=True))
        for row in cursor.fetchall()
    ]
