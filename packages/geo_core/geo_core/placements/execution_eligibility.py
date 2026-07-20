"""Current-source gates for Evidence-backed model execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID


APPROVED_FACT_LINEAGE_JOINS = """
    LEFT JOIN knowledge_fact_candidates fact
      ON fact.id = lineage.knowledge_fact_id
     AND fact.project_id = lineage.project_id
     AND fact.pipeline_run_id = lineage.pipeline_run_id
     AND fact.source_id = lineage.knowledge_source_id
     AND fact.document_id = lineage.knowledge_document_id
     AND fact.chunk_id = lineage.knowledge_chunk_id
     AND fact.statement_hash = lineage.fact_statement_hash
    LEFT JOIN knowledge_chunks chunk
      ON chunk.id = lineage.knowledge_chunk_id
     AND chunk.project_id = lineage.project_id
     AND chunk.pipeline_run_id = lineage.pipeline_run_id
     AND chunk.source_id = lineage.knowledge_source_id
     AND chunk.document_id = lineage.knowledge_document_id
     AND chunk.text_hash = lineage.chunk_text_hash
"""

CURRENT_APPROVED_FACT_FILTER = """
    (e.item_type <> 'approved_fact'
     OR (e.fact_lineage_status = 'verified'
         AND e.source_id = fact.id
         AND e.source_revision_kind = 'content_hash'
         AND e.source_revision_value = lineage.fact_statement_hash
         AND e.snapshot_text = fact.statement
         AND e.snapshot_hash = lineage.evidence_snapshot_hash
         AND lineage.lineage_contract_version = 'knowledge-fact-evidence-v1'
         AND fact.status = 'approved'
         AND fact.lifecycle_status = 'active'
         AND chunk.status = 'active'))
"""


def approved_fact_evidence_is_current(
    db: Any,
    *,
    project_id: UUID,
    evidence_ids: Sequence[UUID],
) -> bool:
    """Lock and validate every approved-Fact Evidence item in an inventory."""

    unique_ids = tuple(dict.fromkeys(evidence_ids))
    if not unique_ids:
        return True
    expected = {
        _first(row)
        for row in db.execute(
            """SELECT e.id
               FROM evidence_items AS e
               WHERE e.project_id = %s AND e.id = ANY(%s)
                 AND e.item_type = 'approved_fact'""",
            (project_id, list(unique_ids)),
        ).fetchall()
    }
    if not expected:
        return True

    current_facts = {
        _first(row)
        for row in db.execute(
            """SELECT e.id
               FROM evidence_items AS e
               JOIN knowledge_fact_evidence_lineages AS lineage
                 ON lineage.evidence_item_id = e.id
                AND lineage.project_id = e.project_id
               JOIN knowledge_fact_candidates AS fact
                 ON fact.id = lineage.knowledge_fact_id
                AND fact.project_id = lineage.project_id
                AND fact.pipeline_run_id = lineage.pipeline_run_id
                AND fact.source_id = lineage.knowledge_source_id
                AND fact.document_id = lineage.knowledge_document_id
                AND fact.chunk_id = lineage.knowledge_chunk_id
                AND fact.statement_hash = lineage.fact_statement_hash
               WHERE e.project_id = %s AND e.id = ANY(%s)
                 AND e.item_type = 'approved_fact'
                 AND e.fact_lineage_status = 'verified'
                 AND e.source_id = fact.id
                 AND e.source_revision_kind = 'content_hash'
                 AND e.source_revision_value = lineage.fact_statement_hash
                 AND e.snapshot_text = fact.statement
                 AND e.snapshot_hash = lineage.evidence_snapshot_hash
                 AND lineage.lineage_contract_version = 'knowledge-fact-evidence-v1'
                 AND fact.status = 'approved'
                 AND fact.lifecycle_status = 'active'
               ORDER BY fact.id
               FOR SHARE OF fact""",
            (project_id, list(unique_ids)),
        ).fetchall()
    }
    if current_facts != expected:
        return False

    current_chunks = {
        _first(row)
        for row in db.execute(
            """SELECT e.id
               FROM evidence_items AS e
               JOIN knowledge_fact_evidence_lineages AS lineage
                 ON lineage.evidence_item_id = e.id
                AND lineage.project_id = e.project_id
               JOIN knowledge_chunks AS chunk
                 ON chunk.id = lineage.knowledge_chunk_id
                AND chunk.project_id = lineage.project_id
                AND chunk.pipeline_run_id = lineage.pipeline_run_id
                AND chunk.source_id = lineage.knowledge_source_id
                AND chunk.document_id = lineage.knowledge_document_id
                AND chunk.text_hash = lineage.chunk_text_hash
               WHERE e.project_id = %s AND e.id = ANY(%s)
                 AND e.item_type = 'approved_fact'
                 AND chunk.status = 'active'
               ORDER BY chunk.id
               FOR SHARE OF chunk""",
            (project_id, list(unique_ids)),
        ).fetchall()
    }
    return current_chunks == expected


def question_candidate_sources_are_current(
    db: Any,
    *,
    project_id: UUID,
    candidate_id: UUID,
) -> bool:
    """Lock a question's source facts/chunks and validate its frozen lineage."""

    facts = db.execute(
        """SELECT fact.id
           FROM knowledge_question_candidate_fact_sources AS source
           JOIN knowledge_question_generation_fact_inputs AS input
             ON input.job_id = source.generated_by_job_id
            AND input.project_id = source.project_id
            AND input.campaign_id = source.campaign_id
            AND input.fact_candidate_id = source.fact_candidate_id
           JOIN knowledge_fact_candidates AS fact
             ON fact.id = input.fact_candidate_id
            AND fact.project_id = input.project_id
            AND fact.pipeline_run_id = input.pipeline_run_id
            AND fact.source_id = input.source_id
            AND fact.document_id = input.document_id
            AND fact.chunk_id = input.chunk_id
           WHERE source.candidate_id = %s AND source.project_id = %s
           ORDER BY fact.id
           FOR SHARE OF fact""",
        (candidate_id, project_id),
    ).fetchall()
    if not facts:
        return False

    db.execute(
        """SELECT lineage.graph_entity_id, lineage.source_id, lineage.chunk_id
           FROM knowledge_question_candidate_entity_sources AS source
           JOIN knowledge_graph_entity_sources AS lineage
             ON lineage.graph_entity_id = source.graph_entity_id
            AND lineage.project_id = source.project_id
           WHERE source.candidate_id = %s AND source.project_id = %s
             AND lineage.lifecycle_status = 'active'
           ORDER BY lineage.graph_entity_id, lineage.source_id, lineage.chunk_id
           FOR SHARE OF lineage""",
        (candidate_id, project_id),
    ).fetchall()
    db.execute(
        """SELECT graph.id
           FROM knowledge_question_candidate_entity_sources AS source
           JOIN knowledge_graph_entities AS graph
             ON graph.id = source.graph_entity_id
            AND graph.project_id = source.project_id
           WHERE source.candidate_id = %s AND source.project_id = %s
           ORDER BY graph.id
           FOR SHARE OF graph""",
        (candidate_id, project_id),
    ).fetchall()
    db.execute(
        """SELECT chunk.id
           FROM knowledge_chunks AS chunk
           WHERE chunk.project_id = %s AND chunk.id IN (
             SELECT input.chunk_id
             FROM knowledge_question_candidate_fact_sources AS source
             JOIN knowledge_question_generation_fact_inputs AS input
               ON input.job_id = source.generated_by_job_id
              AND input.project_id = source.project_id
              AND input.campaign_id = source.campaign_id
              AND input.fact_candidate_id = source.fact_candidate_id
             WHERE source.candidate_id = %s AND source.project_id = %s
             UNION
             SELECT lineage.chunk_id
             FROM knowledge_question_candidate_entity_sources AS source
             JOIN knowledge_graph_entity_sources AS lineage
               ON lineage.graph_entity_id = source.graph_entity_id
              AND lineage.project_id = source.project_id
             WHERE source.candidate_id = %s AND source.project_id = %s
               AND lineage.lifecycle_status = 'active'
           )
           ORDER BY chunk.id
           FOR SHARE OF chunk""",
        (
            project_id,
            candidate_id,
            project_id,
            candidate_id,
            project_id,
        ),
    ).fetchall()
    row = db.execute(
        """SELECT geo_question_candidate_sources_current(%s)
           FROM knowledge_question_candidates AS candidate
           WHERE candidate.id = %s AND candidate.project_id = %s""",
        (candidate_id, candidate_id, project_id),
    ).fetchone()
    return row is not None and _first(row) is True


def _first(row: Any) -> Any:
    if isinstance(row, Mapping):
        return next(iter(row.values()))
    return row[0]
