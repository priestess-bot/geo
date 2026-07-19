"""Atomic activation guards for Knowledge RAG revisions."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from geo_core.jobs.postgres import JobCancellationRequested
from geo_core.knowledge.locking import lock_source_aggregate
from geo_core.knowledge.rag_domain import KnowledgeRagClaim, KnowledgeRagContractError


def prepare_rag_activation(connection: Any, *, project_id: UUID, claim: KnowledgeRagClaim) -> None:
    if claim.project_id != project_id:
        raise KnowledgeRagContractError("Knowledge RAG claim crossed its project boundary")
    lock_source_aggregate(connection, claim.logical_source_id)
    context = _one(
        connection.execute(
            """SELECT source.status AS source_status,
                      source.logical_source_id,
                      run.status AS pipeline_status,
                      EXISTS (
                        SELECT 1 FROM knowledge_sources successor
                        WHERE successor.project_id = source.project_id
                          AND successor.supersedes_source_id = source.id
                      ) AS has_successor
               FROM knowledge_sources source
               JOIN knowledge_pipeline_runs run
                 ON run.id = %s AND run.project_id = source.project_id
                AND run.source_id = source.id
               JOIN knowledge_documents document
                 ON document.id = %s AND document.project_id = source.project_id
                AND document.pipeline_run_id = run.id
                AND document.source_id = source.id
               WHERE source.id = %s AND source.project_id = %s
               FOR UPDATE OF source, run, document""",
            (
                claim.pipeline_run_id,
                claim.document_id,
                claim.source_id,
                project_id,
            ),
        )
    )
    if context is not None and context["source_status"] == "archived":
        raise JobCancellationRequested("Knowledge source was archived during RAG extraction")
    if (
        context is None
        or context["source_status"] != "ready"
        or context["pipeline_status"] != "succeeded"
        or context["logical_source_id"] != claim.logical_source_id
        or context["has_successor"]
    ):
        raise KnowledgeRagContractError("Knowledge RAG source is no longer ready and current")

    newer = _one(
        connection.execute(
            """SELECT newer_run.id
               FROM knowledge_pipeline_runs newer_run
               JOIN knowledge_sources newer_source
                 ON newer_source.id = newer_run.source_id
                AND newer_source.project_id = newer_run.project_id
               JOIN knowledge_pipeline_runs claim_run
                 ON claim_run.id = %s AND claim_run.project_id = %s
                AND claim_run.source_id = %s
               WHERE newer_run.project_id = %s
                 AND newer_source.logical_source_id = %s
                 AND (newer_run.created_at, newer_run.id) >
                     (claim_run.created_at, claim_run.id)
               LIMIT 1""",
            (
                claim.pipeline_run_id,
                project_id,
                claim.source_id,
                project_id,
                claim.logical_source_id,
            ),
        )
    )
    if newer is not None:
        raise KnowledgeRagContractError(
            "Knowledge RAG result is stale because a newer run is already active"
        )

    current_chunks = _many(
        connection.execute(
            """SELECT id, pipeline_run_id, source_id, document_id,
                      chunk_index, text, text_hash
               FROM knowledge_chunks
               WHERE project_id = %s AND pipeline_run_id = %s
                 AND source_id = %s AND document_id = %s AND status = 'active'
               ORDER BY chunk_index, id
               FOR UPDATE""",
            (
                project_id,
                claim.pipeline_run_id,
                claim.source_id,
                claim.document_id,
            ),
        )
    )
    expected_chunks = {
        item.chunk_id: (item.chunk_index, item.text, item.text_hash) for item in claim.chunks
    }
    actual_chunks = {
        row["id"]: (int(row["chunk_index"]), str(row["text"]), str(row["text_hash"]))
        for row in current_chunks
        if row["pipeline_run_id"] == claim.pipeline_run_id
        and row["source_id"] == claim.source_id
        and row["document_id"] == claim.document_id
    }
    if actual_chunks != expected_chunks:
        raise KnowledgeRagContractError(
            "Knowledge RAG claim chunks are no longer the complete active source set"
        )


def retire_previous_run_content(
    connection: Any, *, project_id: UUID, claim: KnowledgeRagClaim
) -> None:
    for table, state_column, active_state, retired_state in (
        ("knowledge_fact_candidates", "lifecycle_status", "active", "superseded"),
        ("knowledge_chunks", "status", "active", "disabled"),
    ):
        connection.execute(
            f"""UPDATE {table} content
                   SET {state_column} = %s, updated_at = clock_timestamp()
                 WHERE content.project_id = %s AND content.source_id = %s
                   AND content.pipeline_run_id <> %s AND {state_column} = %s
                   AND EXISTS (
                     SELECT 1 FROM knowledge_pipeline_runs previous_run
                     WHERE previous_run.id = content.pipeline_run_id
                       AND previous_run.project_id = content.project_id
                       AND previous_run.source_id = content.source_id
                       AND previous_run.status = 'succeeded'
                   )""",  # nosec B608 - identifiers are closed constants above.
            (
                retired_state,
                project_id,
                claim.source_id,
                claim.pipeline_run_id,
                active_state,
            ),
        )


def _one(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((column.name for column in cursor.description), value, strict=True))


def _many(cursor: Any) -> list[dict[str, Any]]:
    return [
        dict(value)
        if isinstance(value, Mapping)
        else dict(zip((column.name for column in cursor.description), value, strict=True))
        for value in cursor.fetchall()
    ]
