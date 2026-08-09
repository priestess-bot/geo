"""Application commands and reads for governed GEO question generation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.access.models import AccessPrincipal
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeNotFound,
    KnowledgeValidationError,
)
from geo_core.knowledge.question_coverage import (
    COVERAGE_PROFILE_KEY,
    QuestionCoverageError,
    build_coverage_question_plan,
    coverage_question_identity_error,
)
from geo_core.knowledge.question_application_support import (
    idempotency_key as _idempotency_key,
    many as _many,
    one as _one,
)
from geo_core.knowledge.question_candidate_application import KnowledgeQuestionCandidateApplicationMixin
from geo_core.knowledge.question_generation_application import KnowledgeQuestionGenerationApplicationMixin
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy


_MAX_COVERAGE_REQUIREMENTS_LENGTH = 120


class KnowledgeQuestionApplicationMixin(
    KnowledgeQuestionGenerationApplicationMixin,
    KnowledgeQuestionCandidateApplicationMixin,
):
    """Mixed into ``KnowledgeApplication``; its connection enforces role and RLS scope."""

    _question_policy: KnowledgeRagEnqueuePolicy | None

    def create_question_coverage_pack(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        configured_model: str,
        model_call_budget: int,
        semantic_duplicate_threshold: float,
        idempotency_key: str,
        coverage_profile: str = COVERAGE_PROFILE_KEY,
        custom_requirements: str = "",
    ) -> Mapping[str, object]:
        requirements = custom_requirements.strip()
        if len(requirements) > _MAX_COVERAGE_REQUIREMENTS_LENGTH:
            raise KnowledgeValidationError(
                "question custom requirements exceed 120 characters; keep them to one focus"
            )
        with self._connection(principal, project_id) as connection:  # type: ignore[attr-defined]
            product = _one(
                connection.execute(
                    """SELECT entity.id, entity.canonical_name, entity.canonical_url,
                              entity.attributes
                       FROM geo_campaigns campaign
                       JOIN product_entities entity
                         ON entity.id = campaign.primary_product_entity_id
                        AND entity.project_id = campaign.project_id
                       WHERE campaign.id = %s AND campaign.project_id = %s
                         AND entity.status = 'active'""",
                    (campaign_id, project_id),
                )
            )
            if product is None:
                raise KnowledgeNotFound("GEO Campaign or its active primary product is missing")
            attributes = product["attributes"]
            if not isinstance(attributes, Mapping):
                raise KnowledgeConflict("Campaign primary product attributes are invalid")
            category = str(attributes.get("category", "")).strip()
            context_parts: list[str] = []
            marketed_area = attributes.get("marketed_lawn_area_sqm")
            if isinstance(marketed_area, (int, float)) and marketed_area > 0:
                context_parts.append(f"marketed lawn area {marketed_area:g} sqm")
            if requirements:
                context_parts.append("operator focus: " + requirements)
            try:
                plan = build_coverage_question_plan(
                    category_key=category,
                    product_name=str(product["canonical_name"]),
                    product_context=" ".join(context_parts),
                    profile_key=coverage_profile,
                )
            except QuestionCoverageError as exc:
                raise KnowledgeValidationError(str(exc)) from exc
            fact_rows = _many(
                connection.execute(
                    """SELECT fact.id
                       FROM knowledge_fact_candidates fact
                       JOIN knowledge_sources source
                         ON source.id = fact.source_id AND source.project_id = fact.project_id
                       JOIN knowledge_chunks chunk
                         ON chunk.id = fact.chunk_id AND chunk.project_id = fact.project_id
                       WHERE fact.project_id = %s
                         AND rtrim(source.source_url, '/') = rtrim(%s, '/')
                         AND fact.status = 'approved'
                         AND fact.lifecycle_status = 'active'
                         AND source.status = 'ready' AND chunk.status = 'active'
                       ORDER BY fact.created_at, fact.id
                       LIMIT 500""",
                    (project_id, product["canonical_url"]),
                )
            )
        if not fact_rows:
            raise KnowledgeConflict(
                "The primary product has no approved active Facts from its official URL"
            )
        return self.create_question_generation(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
            dimensions=tuple(slot.dimension for slot in plan.slots),
            fact_candidate_ids=tuple(item["id"] for item in fact_rows),
            graph_entity_ids=(),
            configured_model=configured_model,
            model_call_budget=model_call_budget,
            semantic_duplicate_threshold=semantic_duplicate_threshold,
            idempotency_key=idempotency_key,
            generation_mode="coverage_pack",
            coverage_plan=plan,
            product_entity_id=product["id"],
        )


    def list_question_generations(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
    ) -> tuple[dict[str, Any], ...]:
        with self._connection(principal, project_id) as connection:  # type: ignore[attr-defined]
            return tuple(
                _many(
                    connection.execute(
                        """SELECT spec.job_id, spec.project_id, spec.campaign_id,
                                  job.status, job.input_hash, job.error_code,
                                  spec.configured_model, spec.model_call_budget,
                                  spec.generation_mode, spec.coverage_profile,
                                  spec.coverage_profile_hash, spec.target_count,
                                  spec.product_entity_id, spec.product_category,
                                  spec.product_name_snapshot,
                                  result.execution_backend, result.actual_model,
                                  spec.adapter_release, spec.semantic_duplicate_threshold,
                                  result.artifact_uri, result.artifact_hash,
                                  result.dimension_count, result.candidate_count,
                                  result.supported_dimension_count,
                                  result.possible_duplicate_count,
                                  result.generated_at, spec.created_at,
                                  CASE
                                    WHEN spec.generation_mode = 'coverage_pack'
                                      THEN CEIL(spec.target_count / 10.0)::integer
                                    ELSE CEIL(COALESCE(dimensions.count, 0) / 10.0)::integer
                                  END AS batch_count,
                                  COALESCE(batches.completed_count, 0)::integer
                                    AS completed_batch_count,
                                  COALESCE(batches.candidate_count, 0)::integer
                                    AS checkpoint_candidate_count
                           FROM knowledge_question_generation_specs spec
                           JOIN durable_jobs job
                             ON job.id = spec.job_id AND job.project_id = spec.project_id
                            AND job.campaign_id = spec.campaign_id
                           LEFT JOIN knowledge_question_generation_results result
                             ON result.job_id = spec.job_id
                            AND result.project_id = spec.project_id
                            AND result.campaign_id = spec.campaign_id
                           LEFT JOIN LATERAL (
                             SELECT count(*) AS count
                             FROM knowledge_question_dimensions dimension
                             WHERE dimension.job_id = spec.job_id
                               AND dimension.project_id = spec.project_id
                               AND dimension.campaign_id = spec.campaign_id
                           ) dimensions ON true
                           LEFT JOIN LATERAL (
                             SELECT count(*) AS completed_count,
                                    COALESCE(sum(jsonb_array_length(output -> 'questions')), 0)
                                      AS candidate_count
                             FROM knowledge_question_generation_batches batch
                             WHERE batch.job_id = spec.job_id
                               AND batch.project_id = spec.project_id
                               AND batch.campaign_id = spec.campaign_id
                           ) batches ON true
                           WHERE spec.project_id = %s AND spec.campaign_id = %s
                           ORDER BY spec.created_at DESC, spec.job_id DESC""",
                        (project_id, campaign_id),
                    )
                )
            )

    def resume_question_coverage_pack(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        generation_job_id: UUID,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        key = _idempotency_key(idempotency_key)
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            previous = _one(
                connection.execute(
                    """SELECT job.id
                       FROM job_retry_requests request
                       JOIN durable_jobs job
                         ON job.id = request.job_id AND job.project_id = request.project_id
                       JOIN knowledge_question_generation_specs spec
                         ON spec.job_id = job.id AND spec.project_id = job.project_id
                        AND spec.campaign_id = job.campaign_id
                       WHERE request.project_id = %s AND request.job_id = %s
                         AND request.idempotency_key = %s
                         AND job.campaign_id = %s
                         AND job.kind = 'knowledge.question.generate'
                         AND spec.generation_mode = 'coverage_pack'""",
                    (project_id, generation_job_id, key, campaign_id),
                )
            )
            if previous is None:
                resumed = _one(
                    connection.execute(
                        """UPDATE durable_jobs job
                           SET status = 'retry_wait', next_run_at = clock_timestamp(),
                               completed_at = NULL, error_code = NULL, error_detail = NULL,
                               cancel_requested_at = NULL,
                               max_attempts = CASE
                                 WHEN job.status = 'dead_lettered'
                                   THEN job.max_attempts + 1
                                 ELSE job.max_attempts
                               END,
                               updated_at = clock_timestamp()
                           FROM knowledge_question_generation_specs spec
                           WHERE job.id = %s AND job.project_id = %s
                             AND job.campaign_id = %s
                             AND job.kind = 'knowledge.question.generate'
                             AND (
                               (job.status IN ('failed', 'retry_wait')
                                AND job.attempt_count < job.max_attempts)
                               OR (job.status = 'dead_lettered'
                                   AND job.attempt_count = job.max_attempts
                                   AND job.max_attempts < 6)
                             )
                             AND spec.job_id = job.id AND spec.project_id = job.project_id
                             AND spec.campaign_id = job.campaign_id
                             AND spec.generation_mode = 'coverage_pack'
                           RETURNING job.id""",
                        (generation_job_id, project_id, campaign_id),
                    )
                )
                if resumed is None:
                    exists = _one(
                        connection.execute(
                            """SELECT job.status, job.attempt_count, job.max_attempts
                               FROM durable_jobs job
                               JOIN knowledge_question_generation_specs spec
                                 ON spec.job_id = job.id AND spec.project_id = job.project_id
                                AND spec.campaign_id = job.campaign_id
                               WHERE job.id = %s AND job.project_id = %s
                                 AND job.campaign_id = %s
                                 AND job.kind = 'knowledge.question.generate'
                                 AND spec.generation_mode = 'coverage_pack'""",
                            (generation_job_id, project_id, campaign_id),
                        )
                    )
                    if exists is None:
                        raise KnowledgeNotFound(
                            "100-question generation does not exist in this Campaign"
                        )
                    raise KnowledgeConflict(
                        "only failed, retry-wait, or bounded dead-letter 100-question "
                        "generations can continue"
                    )
                connection.execute(
                    """INSERT INTO job_retry_requests
                         (project_id, job_id, idempotency_key, requested_by)
                       VALUES (%s, %s, %s, %s)""",
                    (project_id, generation_job_id, key, principal.identity_id),
                )
                connection.execute(
                    """INSERT INTO broker_outbox
                         (project_id, job_id, topic, payload, idempotency_key)
                       VALUES (%s, %s, 'knowledge.question.generate', %s::jsonb, %s)
                       ON CONFLICT (project_id, idempotency_key) DO NOTHING""",
                    (
                        project_id,
                        generation_job_id,
                        json.dumps(
                            {
                                "job_id": str(generation_job_id),
                                "project_id": str(project_id),
                                "campaign_id": str(campaign_id),
                            }
                        ),
                        f"resume:knowledge-question:{generation_job_id}:{key}",
                    ),
                )
                connection.execute(
                    """INSERT INTO durable_job_events
                         (project_id, job_id, event_type, worker_id, details)
                       VALUES (%s, %s, 'question_generation_resumed', %s, %s::jsonb)""",
                    (
                        project_id,
                        generation_job_id,
                        f"api:{principal.identity_id}",
                        json.dumps({"campaign_id": str(campaign_id)}),
                    ),
                )
        generations = self.list_question_generations(
            principal,
            project_id=project_id,
            campaign_id=campaign_id,
        )
        return next(item for item in generations if item["job_id"] == generation_job_id)

    def edit_question_candidate(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        candidate_id: UUID,
        query_text: str,
    ) -> Mapping[str, object]:
        from geo_core.knowledge.question_domain import normalize_question_text

        text = query_text.strip()
        if not text or len(text) > 2000:
            raise KnowledgeValidationError("question text must contain 1 to 2000 characters")
        normalized = normalize_question_text(text)
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        normalized_hash = hashlib.sha256(normalized.encode()).hexdigest()
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            candidate = _one(
                connection.execute(
                    """SELECT candidate.id, candidate.generated_by_job_id,
                              candidate.workflow_status, candidate.dedup_status,
                              candidate.query_text_hash,
                              spec.generation_mode, spec.product_name_snapshot,
                              dimension.coverage_role
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
                       WHERE candidate.id = %s AND candidate.project_id = %s
                         AND candidate.campaign_id = %s
                       FOR UPDATE OF candidate""",
                    (candidate_id, project_id, campaign_id),
                )
            )
            if candidate is None:
                raise KnowledgeNotFound("question candidate does not exist")
            can_repair_rejected_duplicate = (
                candidate["workflow_status"] == "rejected"
                and candidate["dedup_status"] == "possible_duplicate"
            )
            if (
                candidate["workflow_status"] != "pending_review"
                and not can_repair_rejected_duplicate
            ):
                raise KnowledgeConflict("reviewed question candidates cannot be edited")
            if candidate["generation_mode"] == "coverage_pack":
                identity_error = coverage_question_identity_error(
                    text=text,
                    coverage_role=candidate["coverage_role"],
                    product_name=str(candidate["product_name_snapshot"]),
                )
                if identity_error:
                    raise KnowledgeValidationError(identity_error)
            latest = _one(
                connection.execute(
                    """SELECT id, revision_number, query_text, query_text_hash
                       FROM knowledge_question_candidate_revisions
                       WHERE candidate_id = %s AND project_id = %s AND campaign_id = %s
                       ORDER BY revision_number DESC LIMIT 1""",
                    (candidate_id, project_id, campaign_id),
                )
            )
            if can_repair_rejected_duplicate and (
                text_hash == candidate["query_text_hash"]
                or (latest is not None and text_hash == latest["query_text_hash"])
            ):
                raise KnowledgeValidationError(
                    "rejected duplicate repair must change the effective question"
                )
            outcome = "existing"
            revision = latest
            if latest is None or latest["query_text_hash"] != text_hash:
                duplicate = _one(
                    connection.execute(
                        """SELECT other.id
                           FROM knowledge_question_candidates other
                           LEFT JOIN LATERAL (
                             SELECT value.normalized_text_hash
                             FROM knowledge_question_candidate_revisions value
                             WHERE value.candidate_id = other.id
                             ORDER BY value.revision_number DESC LIMIT 1
                           ) revision ON true
                           WHERE other.generated_by_job_id = %s
                             AND other.project_id = %s AND other.campaign_id = %s
                             AND other.id <> %s
                             AND COALESCE(revision.normalized_text_hash,
                                          other.normalized_text_hash) = %s
                           LIMIT 1""",
                        (
                            candidate["generated_by_job_id"],
                            project_id,
                            campaign_id,
                            candidate_id,
                            normalized_hash,
                        ),
                    )
                )
                if duplicate is not None:
                    raise KnowledgeConflict("edited question duplicates another candidate")
                revision_number = int(latest["revision_number"] if latest else 0) + 1
                revision_id = uuid5(
                    NAMESPACE_URL,
                    f"geo-question-revision:{candidate_id}:{revision_number}:{text_hash}",
                )
                revision = _one(
                    connection.execute(
                        """INSERT INTO knowledge_question_candidate_revisions
                             (id, project_id, campaign_id, generated_by_job_id, candidate_id,
                              revision_number, query_text, query_text_hash,
                              normalized_text_hash, edited_by)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           RETURNING id, revision_number, query_text, query_text_hash,
                                     normalized_text_hash, created_at""",
                        (
                            revision_id,
                            project_id,
                            campaign_id,
                            candidate["generated_by_job_id"],
                            candidate_id,
                            revision_number,
                            text,
                            text_hash,
                            normalized_hash,
                            principal.identity_id,
                        ),
                    )
                )
                outcome = "revised"
            assert revision is not None
            if can_repair_rejected_duplicate:
                connection.execute(
                    """UPDATE knowledge_question_candidates
                          SET workflow_status = 'pending_review', reviewed_by = NULL,
                              review_notes = NULL, reviewed_at = NULL,
                              updated_at = clock_timestamp()
                        WHERE id = %s AND project_id = %s AND campaign_id = %s
                          AND workflow_status = 'rejected'
                          AND dedup_status = 'possible_duplicate'""",
                    (candidate_id, project_id, campaign_id),
                )
            return {"outcome": outcome, **revision}

    def review_question_candidate(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        candidate_id: UUID,
        decision: str,
        notes: str | None = None,
    ) -> Mapping[str, object]:
        if decision not in {"approved", "rejected"}:
            raise KnowledgeValidationError("question decision must be approved or rejected")
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            candidate = _one(
                connection.execute(
                    """SELECT id, workflow_status, dedup_status, review_notes
                       FROM knowledge_question_candidates
                       WHERE id = %s AND project_id = %s AND campaign_id = %s
                       FOR UPDATE""",
                    (candidate_id, project_id, campaign_id),
                )
            )
            if candidate is None:
                raise KnowledgeNotFound("question candidate does not exist")
            if candidate["workflow_status"] != "pending_review":
                if candidate["workflow_status"] == decision:
                    return {"outcome": "existing", **candidate}
                raise KnowledgeConflict("question candidate was already reviewed")
            if decision == "approved" and candidate["dedup_status"] == "exact_duplicate":
                raise KnowledgeConflict("exact duplicate question candidates cannot be approved")
            review_notes = (notes or "").strip() or None
            reviewed = _one(
                connection.execute(
                    """UPDATE knowledge_question_candidates
                       SET workflow_status = %s, reviewed_by = %s,
                           review_notes = %s, reviewed_at = clock_timestamp(),
                           updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s AND campaign_id = %s
                       RETURNING id, project_id, campaign_id, generated_by_job_id,
                                 dimension_key, query_text, dedup_status,
                                 workflow_status, reviewed_by, review_notes, reviewed_at""",
                    (
                        decision,
                        principal.identity_id,
                        review_notes,
                        candidate_id,
                        project_id,
                        campaign_id,
                    ),
                )
            )
            assert reviewed is not None
            return {"outcome": "reviewed", **reviewed}
