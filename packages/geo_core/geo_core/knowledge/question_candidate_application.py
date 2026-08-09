"""Question candidate read application commands."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.knowledge.question_application_support import many as _many


class KnowledgeQuestionCandidateApplicationMixin:
    """Mixed into ``KnowledgeApplication`` for candidate reads."""

    def list_question_candidates(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        generation_job_id: UUID,
    ) -> tuple[dict[str, Any], ...]:
        with self._connection(principal, project_id) as connection:  # type: ignore[attr-defined]
            return tuple(
                _many(
                    connection.execute(
                        """SELECT candidate.id, candidate.project_id,
                                  candidate.campaign_id, candidate.generated_by_job_id,
                                  candidate.dimension_key, dimension.ordinal,
                                  candidate.variant_index,
                                  candidate.turn_index, candidate.parent_candidate_id,
                                  candidate.query_text AS original_query_text,
                                  candidate.query_text_hash AS original_query_text_hash,
                                  COALESCE(revision.query_text, candidate.query_text)
                                    AS query_text,
                                  COALESCE(revision.query_text_hash, candidate.query_text_hash)
                                    AS query_text_hash,
                                  revision.id AS revision_id,
                                  revision.revision_number,
                                  (revision.id IS NOT NULL) AS was_edited,
                                  candidate.semantic_fingerprint, candidate.dedup_status,
                                  candidate.nearest_candidate_id,
                                  candidate.nearest_similarity,
                                  candidate.workflow_status, candidate.review_notes,
                                  candidate.reviewed_at, candidate.created_at,
                                  dimension.brand_scope, dimension.coverage_role,
                                  dimension.topic_cluster, dimension.funnel,
                                  dimension.query_kind, dimension.subject,
                                  COALESCE(facts.ids, ARRAY[]::uuid[]) AS fact_source_ids,
                                  COALESCE(entities.ids, ARRAY[]::uuid[]) AS entity_source_ids
                           FROM knowledge_question_candidates candidate
                           JOIN knowledge_question_dimensions dimension
                             ON dimension.job_id = candidate.generated_by_job_id
                            AND dimension.project_id = candidate.project_id
                            AND dimension.campaign_id = candidate.campaign_id
                            AND dimension.dimension_key = candidate.dimension_key
                           LEFT JOIN LATERAL (
                             SELECT value.id, value.revision_number, value.query_text,
                                    value.query_text_hash
                             FROM knowledge_question_candidate_revisions value
                             WHERE value.candidate_id = candidate.id
                               AND value.project_id = candidate.project_id
                               AND value.campaign_id = candidate.campaign_id
                             ORDER BY value.revision_number DESC
                             LIMIT 1
                           ) revision ON true
                           LEFT JOIN LATERAL (
                             SELECT array_agg(source.fact_candidate_id ORDER BY source.fact_candidate_id) AS ids
                             FROM knowledge_question_candidate_fact_sources source
                             WHERE source.candidate_id = candidate.id
                               AND source.project_id = candidate.project_id
                               AND source.campaign_id = candidate.campaign_id
                           ) facts ON true
                           LEFT JOIN LATERAL (
                             SELECT array_agg(source.graph_entity_id ORDER BY source.graph_entity_id) AS ids
                             FROM knowledge_question_candidate_entity_sources source
                             WHERE source.candidate_id = candidate.id
                               AND source.project_id = candidate.project_id
                               AND source.campaign_id = candidate.campaign_id
                           ) entities ON true
                           WHERE candidate.project_id = %s
                             AND candidate.campaign_id = %s
                             AND candidate.generated_by_job_id = %s
                           ORDER BY dimension.ordinal, candidate.variant_index,
                                    candidate.id""",
                        (project_id, campaign_id, generation_job_id),
                    )
                )
            )
