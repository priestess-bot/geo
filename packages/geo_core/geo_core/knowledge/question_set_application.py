"""Application commands for immutable governed GEO QuestionSets."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Sequence, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.access.models import AccessPrincipal
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeNotFound,
    KnowledgeValidationError,
)
from geo_core.knowledge.question_set_application_support import effective_dedup_statuses

# Keep the private name available to existing internal callers while the implementation
# lives in the focused support module.
_effective_dedup_statuses = effective_dedup_statuses


class KnowledgeQuestionSetApplicationMixin:
    def finalize_question_coverage_pack(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        name: str,
        generation_job_id: UUID,
        included_candidate_ids: Sequence[UUID],
        idempotency_key: str,
        series_id: UUID | None = None,
        previous_version_id: UUID | None = None,
    ) -> Mapping[str, object]:
        included = tuple(included_candidate_ids)
        if len(included) != 100 or len(set(included)) != len(included):
            raise KnowledgeValidationError(
                "coverage QuestionSet requires exactly 100 unique included questions"
            )
        if (series_id is None) != (previous_version_id is None):
            raise KnowledgeValidationError(
                "QuestionSet series and previous version must be supplied together"
            )
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            generation = _one(
                connection.execute(
                    """SELECT spec.target_count, job.status, result.candidate_count
                       FROM knowledge_question_generation_specs spec
                       JOIN durable_jobs job
                         ON job.id = spec.job_id AND job.project_id = spec.project_id
                       JOIN knowledge_question_generation_results result
                         ON result.job_id = spec.job_id AND result.project_id = spec.project_id
                       WHERE spec.job_id = %s AND spec.project_id = %s
                         AND spec.campaign_id = %s
                         AND spec.generation_mode = 'coverage_pack'""",
                    (generation_job_id, project_id, campaign_id),
                )
            )
            if (
                generation is None
                or generation["status"] != "succeeded"
                or int(generation["candidate_count"]) != int(generation["target_count"])
                or int(generation["target_count"]) != 100
            ):
                raise KnowledgeConflict(
                    "coverage generation must finish with exactly 100 candidates before finalization"
                )
            candidates = _many(
                connection.execute(
                    """SELECT candidate.id, candidate.workflow_status, candidate.dedup_status,
                              candidate.dimension_key, candidate.variant_index,
                              candidate.turn_index,
                              candidate.semantic_fingerprint, candidate.query_text,
                              candidate.normalized_text_hash,
                              dimension.ordinal AS dimension_ordinal,
                              dimension.parent_dimension_key, dimension.persona,
                              dimension.scenario, dimension.intent, dimension.funnel,
                              dimension.region, dimension.language, dimension.brand_scope,
                              dimension.platform, dimension.query_kind, dimension.subject,
                              dimension.competitor_entity_id,
                              spec.semantic_duplicate_threshold,
                              COALESCE(revision.query_text, candidate.query_text)
                                AS effective_query_text,
                              COALESCE(revision.normalized_text_hash,
                                       candidate.normalized_text_hash)
                                AS effective_normalized_text_hash,
                              revision.id AS effective_revision_id
                       FROM knowledge_question_candidates candidate
                       JOIN knowledge_question_generation_specs spec
                         ON spec.job_id = candidate.generated_by_job_id
                        AND spec.project_id = candidate.project_id
                        AND spec.campaign_id = candidate.campaign_id
                       JOIN knowledge_question_dimensions dimension
                         ON dimension.job_id = candidate.generated_by_job_id
                        AND dimension.project_id = candidate.project_id
                        AND dimension.campaign_id = candidate.campaign_id
                        AND dimension.dimension_key = candidate.dimension_key
                       LEFT JOIN LATERAL (
                         SELECT value.id, value.query_text, value.normalized_text_hash
                         FROM knowledge_question_candidate_revisions value
                         WHERE value.candidate_id = candidate.id
                           AND value.project_id = candidate.project_id
                           AND value.campaign_id = candidate.campaign_id
                         ORDER BY value.revision_number DESC LIMIT 1
                       ) revision ON true
                       WHERE candidate.generated_by_job_id = %s
                         AND candidate.project_id = %s
                         AND candidate.campaign_id = %s
                       ORDER BY dimension.ordinal, candidate.variant_index, candidate.id
                       FOR UPDATE OF candidate""",
                    (generation_job_id, project_id, campaign_id),
                )
            )
            all_ids = {item["id"] for item in candidates}
            included_set = set(included)
            if len(candidates) != 100 or not included_set.issubset(all_ids):
                raise KnowledgeConflict("included questions crossed the completed coverage generation")
            effective_statuses = _effective_dedup_statuses(candidates)
            for candidate in candidates:
                should_approve = candidate["id"] in included_set
                expected = "approved" if should_approve else "rejected"
                if should_approve and effective_statuses[candidate["id"]] != "unique":
                    raise KnowledgeConflict(
                        "duplicate or near-duplicate questions cannot be finalized after effective recheck"
                    )
                if candidate["workflow_status"] not in {"pending_review", expected}:
                    raise KnowledgeConflict(
                        "a previously reviewed question conflicts with this final selection"
                    )
            connection.execute(
                """UPDATE knowledge_question_candidates
                   SET workflow_status = CASE WHEN id = ANY(%s) THEN 'approved' ELSE 'rejected' END,
                       reviewed_by = %s, reviewed_at = clock_timestamp(),
                       review_notes = NULL, updated_at = clock_timestamp()
                   WHERE generated_by_job_id = %s AND project_id = %s AND campaign_id = %s
                     AND workflow_status = 'pending_review'""",
                (
                    list(included),
                    principal.identity_id,
                    generation_job_id,
                    project_id,
                    campaign_id,
                ),
            )
        created = self.create_question_set(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            name=name,
            generation_job_id=generation_job_id,
            candidate_ids=included,
            series_id=series_id,
            previous_version_id=previous_version_id,
            idempotency_key=f"{idempotency_key}:set",
        )
        if created["status"] == "frozen":
            return created
        approved = created
        if created["status"] == "draft":
            approved = self.approve_question_set(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
                question_set_id=cast(UUID, created["id"]),
            )
        return self.freeze_question_set(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            question_set_id=cast(UUID, approved["id"]),
        )

    def create_question_set(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        name: str,
        generation_job_id: UUID,
        candidate_ids: Sequence[UUID],
        series_id: UUID | None,
        previous_version_id: UUID | None,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        normalized_name = name.strip()
        key = _idempotency_key(idempotency_key)
        if not normalized_name or len(normalized_name) > 300:
            raise KnowledgeValidationError("QuestionSet name is required and bounded")
        if not candidate_ids or len(candidate_ids) > 500:
            raise KnowledgeValidationError("QuestionSet requires 1 to 500 candidates")
        if len(set(candidate_ids)) != len(candidate_ids):
            raise KnowledgeValidationError("QuestionSet candidate IDs must be unique")
        if (series_id is None) != (previous_version_id is None):
            raise KnowledgeValidationError(
                "QuestionSet series and previous version must be supplied together"
            )
        set_id = uuid5(
            NAMESPACE_URL,
            f"geo-question-set:{project_id}:{campaign_id}:{key}",
        )
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            existing = _question_set_view(
                connection, project_id, campaign_id, set_id, required=False
            )
            if existing is not None:
                existing_items = cast(list[dict[str, object]], existing["items"])
                existing_ids = [item["question_candidate_id"] for item in existing_items]
                if (
                    existing["name"] != normalized_name
                    or existing["generated_by_job_id"] != generation_job_id
                    or existing_ids != list(candidate_ids)
                    or existing["previous_version_id"] != previous_version_id
                ):
                    raise KnowledgeConflict(
                        "QuestionSet idempotency key was used for different content"
                    )
                return existing
            version_number = 1
            resolved_series = set_id
            if previous_version_id is not None and series_id is not None:
                previous = _one(
                    connection.execute(
                        """SELECT id, series_id, version_number, status
                           FROM knowledge_question_sets
                           WHERE id = %s AND project_id = %s AND campaign_id = %s
                           FOR SHARE""",
                        (previous_version_id, project_id, campaign_id),
                    )
                )
                if (
                    previous is None
                    or previous["series_id"] != series_id
                    or previous["status"] != "frozen"
                ):
                    raise KnowledgeConflict(
                        "QuestionSet version requires its frozen exact predecessor"
                    )
                resolved_series = series_id
                version_number = int(previous["version_number"]) + 1
            candidates = _many(
                connection.execute(
                    """SELECT candidate.id, candidate.dimension_key,
                              candidate.variant_index, candidate.turn_index,
                              candidate.semantic_fingerprint,
                              COALESCE(revision.query_text, candidate.query_text) AS query_text,
                              COALESCE(revision.query_text_hash, candidate.query_text_hash)
                                AS query_text_hash,
                              COALESCE(revision.normalized_text_hash,
                                       candidate.normalized_text_hash) AS normalized_text_hash,
                              revision.id AS effective_revision_id,
                              candidate.dedup_status, dimension.ordinal AS dimension_ordinal,
                              dimension.parent_dimension_key, dimension.persona,
                              dimension.scenario, dimension.intent, dimension.funnel,
                              dimension.region, dimension.language, dimension.brand_scope,
                              dimension.platform, dimension.subject, dimension.competitor_entity_id,
                              spec.semantic_duplicate_threshold,
                              dimension.query_kind, dimension.coverage_role,
                              dimension.topic_cluster,
                              geo_question_candidate_source_lineage_hash(candidate.id)
                                AS source_lineage_hash,
                              geo_question_candidate_sources_current(candidate.id)
                                AS sources_current
                       FROM knowledge_question_candidates candidate
                       JOIN knowledge_question_generation_specs spec
                         ON spec.job_id = candidate.generated_by_job_id
                        AND spec.project_id = candidate.project_id
                        AND spec.campaign_id = candidate.campaign_id
                       JOIN knowledge_question_dimensions dimension
                         ON dimension.job_id = candidate.generated_by_job_id
                        AND dimension.project_id = candidate.project_id
                        AND dimension.campaign_id = candidate.campaign_id
                        AND dimension.dimension_key = candidate.dimension_key
                       LEFT JOIN LATERAL (
                         SELECT value.id, value.query_text, value.query_text_hash,
                                value.normalized_text_hash
                         FROM knowledge_question_candidate_revisions value
                         WHERE value.candidate_id = candidate.id
                           AND value.project_id = candidate.project_id
                           AND value.campaign_id = candidate.campaign_id
                         ORDER BY value.revision_number DESC LIMIT 1
                       ) revision ON true
                       WHERE candidate.project_id = %s AND candidate.campaign_id = %s
                         AND candidate.generated_by_job_id = %s
                         AND candidate.id = ANY(%s)
                         AND candidate.workflow_status = 'approved'
                       ORDER BY array_position(%s::uuid[], candidate.id)
                       FOR SHARE OF candidate""",
                    (
                        project_id,
                        campaign_id,
                        generation_job_id,
                        list(candidate_ids),
                        list(candidate_ids),
                    ),
                )
            )
            if [item["id"] for item in candidates] != list(candidate_ids) or not all(
                item["sources_current"] for item in candidates
            ):
                raise KnowledgeConflict(
                    "QuestionSet candidates must be approved, current, and from one generation"
                )
            total_row = _one(
                connection.execute(
                    """SELECT count(*) AS count FROM knowledge_question_dimensions
                       WHERE job_id = %s AND project_id = %s AND campaign_id = %s""",
                    (generation_job_id, project_id, campaign_id),
                )
            )
            dimension_count = int(total_row["count"] if total_row else 0)
            covered = len({str(item["dimension_key"]) for item in candidates})
            effective_statuses = _effective_dedup_statuses(candidates)
            if any(status == "exact_duplicate" for status in effective_statuses.values()):
                raise KnowledgeConflict("exact duplicate questions cannot enter a QuestionSet")
            if any(
                item["effective_revision_id"] is not None
                and effective_statuses[item["id"]] != "unique"
                for item in candidates
            ):
                raise KnowledgeConflict(
                    "revised QuestionSet candidates must be unique after deterministic re-check"
                )
            # Original evidence remains immutable. A successful revision supersedes its
            # admission status, while unedited possible duplicates retain the legacy count.
            possible = sum(
                item["dedup_status"] == "possible_duplicate"
                and item["effective_revision_id"] is None
                for item in candidates
            )
            coverage = _ratio(covered, dimension_count)
            duplicate = _ratio(possible, len(candidates))
            connection.execute(
                """INSERT INTO knowledge_question_sets
                     (id, project_id, campaign_id, series_id, previous_version_id,
                      version_number, generated_by_job_id, name, dimension_count,
                      covered_dimension_count, possible_duplicate_count,
                      coverage_ratio, duplicate_ratio, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    set_id,
                    project_id,
                    campaign_id,
                    resolved_series,
                    previous_version_id,
                    version_number,
                    generation_job_id,
                    normalized_name,
                    dimension_count,
                    covered,
                    possible,
                    coverage,
                    duplicate,
                    principal.identity_id,
                ),
            )
            for ordinal, candidate in enumerate(candidates, start=1):
                connection.execute(
                    """INSERT INTO knowledge_question_set_items
                         (id, project_id, campaign_id, question_set_id,
                          generated_by_job_id, question_candidate_id, ordinal,
                          dimension_key, query_text_snapshot, query_text_hash,
                          normalized_text_hash, query_kind_snapshot,
                          query_cluster_key, source_lineage_hash, brand_scope_snapshot,
                          coverage_role_snapshot, topic_cluster_snapshot, funnel_snapshot)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        uuid5(
                            NAMESPACE_URL,
                            f"geo-question-set-item:{set_id}:{candidate['id']}",
                        ),
                        project_id,
                        campaign_id,
                        set_id,
                        generation_job_id,
                        candidate["id"],
                        ordinal,
                        candidate["dimension_key"],
                        candidate["query_text"],
                        candidate["query_text_hash"],
                        candidate["normalized_text_hash"],
                        candidate["query_kind"],
                        candidate["topic_cluster"] or candidate["dimension_key"],
                        candidate["source_lineage_hash"],
                        candidate["brand_scope"],
                        candidate["coverage_role"],
                        candidate["topic_cluster"],
                        candidate["funnel"],
                    ),
                )
            result = _question_set_view(
                connection, project_id, campaign_id, set_id, required=True
            )
            assert result is not None
            return result

    def list_question_sets(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
    ) -> tuple[dict[str, object], ...]:
        with self._connection(principal, project_id) as connection:  # type: ignore[attr-defined]
            ids = [
                row["id"]
                for row in _many(
                    connection.execute(
                        """SELECT id FROM knowledge_question_sets
                           WHERE project_id = %s AND campaign_id = %s
                           ORDER BY created_at DESC, id DESC""",
                        (project_id, campaign_id),
                    )
                )
            ]
            return tuple(
                _required_view(connection, project_id, campaign_id, set_id)
                for set_id in ids
            )

    def approve_question_set(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        question_set_id: UUID,
    ) -> Mapping[str, object]:
        return self._transition_question_set(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            question_set_id=question_set_id,
            target="approved",
        )

    def freeze_question_set(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        question_set_id: UUID,
    ) -> Mapping[str, object]:
        return self._transition_question_set(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            question_set_id=question_set_id,
            target="frozen",
        )

    def _transition_question_set(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        question_set_id: UUID,
        target: str,
    ) -> Mapping[str, object]:
        expected = "draft" if target == "approved" else "approved"
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            current = _one(
                connection.execute(
                    """SELECT status FROM knowledge_question_sets
                       WHERE id = %s AND project_id = %s AND campaign_id = %s
                       FOR UPDATE""",
                    (question_set_id, project_id, campaign_id),
                )
            )
            if current is None:
                raise KnowledgeNotFound("QuestionSet does not exist")
            if current["status"] == target:
                return _required_view(
                    connection, project_id, campaign_id, question_set_id
                )
            if current["status"] != expected:
                raise KnowledgeConflict(f"QuestionSet cannot transition to {target}")
            if target == "approved":
                connection.execute(
                    """UPDATE knowledge_question_sets
                       SET status = 'approved', approved_by = %s,
                           approved_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s AND campaign_id = %s""",
                    (principal.identity_id, question_set_id, project_id, campaign_id),
                )
            else:
                content = _one(
                    connection.execute(
                        "SELECT geo_question_set_content_hash(%s) AS content_hash",
                        (question_set_id,),
                    )
                )
                if content is None or not content["content_hash"]:
                    raise KnowledgeConflict("QuestionSet content hash cannot be computed")
                connection.execute(
                    """UPDATE knowledge_question_sets
                       SET status = 'frozen', frozen_by = %s,
                           frozen_at = clock_timestamp(), content_hash = %s
                       WHERE id = %s AND project_id = %s AND campaign_id = %s""",
                    (
                        principal.identity_id,
                        content["content_hash"],
                        question_set_id,
                        project_id,
                        campaign_id,
                    ),
                )
            return _required_view(connection, project_id, campaign_id, question_set_id)


def _question_set_view(
    connection: Any,
    project_id: UUID,
    campaign_id: UUID,
    question_set_id: UUID,
    *,
    required: bool,
) -> dict[str, object] | None:
    row = _one(
        connection.execute(
            """SELECT id, project_id, campaign_id, series_id, previous_version_id,
                      version_number, generated_by_job_id, name, status,
                      dimension_count, covered_dimension_count,
                      possible_duplicate_count, coverage_ratio, duplicate_ratio,
                      content_hash, created_at, approved_at, frozen_at
               FROM knowledge_question_sets
               WHERE id = %s AND project_id = %s AND campaign_id = %s""",
            (question_set_id, project_id, campaign_id),
        )
    )
    if row is None:
        if required:
            raise KnowledgeNotFound("QuestionSet does not exist")
        return None
    row["items"] = _many(
        connection.execute(
            """SELECT id, ordinal, question_candidate_id, dimension_key,
                      query_text_snapshot, query_text_hash, query_kind_snapshot,
                      query_cluster_key, source_lineage_hash, brand_scope_snapshot,
                      coverage_role_snapshot, topic_cluster_snapshot, funnel_snapshot
               FROM knowledge_question_set_items
               WHERE question_set_id = %s AND project_id = %s AND campaign_id = %s
               ORDER BY ordinal""",
            (question_set_id, project_id, campaign_id),
        )
    )
    return row


def _required_view(
    connection: Any, project_id: UUID, campaign_id: UUID, question_set_id: UUID
) -> dict[str, object]:
    result = _question_set_view(
        connection, project_id, campaign_id, question_set_id, required=True
    )
    assert result is not None
    return result


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator < 1:
        raise KnowledgeValidationError("QuestionSet has no planned dimensions")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 200:
        raise KnowledgeValidationError("Idempotency-Key must contain 1 to 200 characters")
    return normalized


def _one(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    return dict(value) if value is not None else None


def _many(cursor: Any) -> list[dict[str, Any]]:
    return [dict(value) for value in cursor.fetchall()]
