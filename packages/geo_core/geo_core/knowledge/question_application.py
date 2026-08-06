"""Application commands and reads for governed GEO question generation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.access.models import AccessPrincipal
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeNotFound,
    KnowledgeValidationError,
)
from geo_core.knowledge.question_domain import (
    DIMENSION_SCHEMA_VERSION,
    EMBEDDING_MODEL_KEY,
    QuestionContractError,
    QuestionDimensionDraft,
    freeze_dimensions,
    question_generation_minimum_call_budget,
)
from geo_core.knowledge.question_coverage import (
    COVERAGE_PROFILE_KEY,
    CoverageQuestionPlan,
    QuestionCoverageError,
    build_coverage_question_plan,
    coverage_question_identity_error,
)
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy


_MAX_COVERAGE_REQUIREMENTS_LENGTH = 120


class KnowledgeQuestionApplicationMixin:
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

    def create_question_generation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        dimensions: Sequence[QuestionDimensionDraft],
        fact_candidate_ids: Sequence[UUID],
        graph_entity_ids: Sequence[UUID],
        configured_model: str,
        model_call_budget: int,
        semantic_duplicate_threshold: float,
        idempotency_key: str,
        generation_mode: str = "single_scenario",
        coverage_plan: CoverageQuestionPlan | None = None,
        product_entity_id: UUID | None = None,
    ) -> Mapping[str, object]:
        policy = self._question_policy
        if policy is None:
            raise KnowledgeValidationError("question generation runtime selection is not configured")
        key = _idempotency_key(idempotency_key)
        try:
            frozen_dimensions = freeze_dimensions(dimensions)
        except QuestionContractError as exc:
            raise KnowledgeValidationError(str(exc)) from exc
        if generation_mode not in {"single_scenario", "coverage_pack"}:
            raise KnowledgeValidationError("question generation mode is unsupported")
        if generation_mode == "single_scenario" and (
            coverage_plan is not None or product_entity_id is not None
        ):
            raise KnowledgeValidationError("single-scenario generation has coverage fields")
        if generation_mode == "coverage_pack" and (
            coverage_plan is None
            or product_entity_id is None
            or coverage_plan.target_count != len(frozen_dimensions)
        ):
            raise KnowledgeValidationError("question coverage plan is incomplete")
        if len(set(fact_candidate_ids)) != len(fact_candidate_ids) or not fact_candidate_ids:
            raise KnowledgeValidationError("question generation requires unique approved Facts")
        if len(set(graph_entity_ids)) != len(graph_entity_ids):
            raise KnowledgeValidationError("question generation graph entities must be unique")
        if len(fact_candidate_ids) > 500 or len(graph_entity_ids) > 500:
            raise KnowledgeValidationError("question generation source inventory exceeds 500 rows")
        if (
            configured_model.strip() != policy.configured_model
            or not 1 <= model_call_budget <= 1000
        ):
            raise KnowledgeValidationError("question model and call budget are invalid")
        minimum_calls = question_generation_minimum_call_budget(
            frozen_dimensions, policy.maximum_attempts
        )
        if model_call_budget < minimum_calls:
            raise KnowledgeValidationError(
                "question model call budget cannot cover every planned durable attempt"
            )
        if not 0.8 <= semantic_duplicate_threshold <= 1.0:
            raise KnowledgeValidationError("semantic duplicate threshold must be 0.80 to 1.00")

        job_id = uuid5(
            NAMESPACE_URL,
            f"geo-question-generation:{project_id}:{campaign_id}:{key}",
        )
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            campaign = _one(
                connection.execute(
                    """SELECT id FROM geo_campaigns
                       WHERE id = %s AND project_id = %s""",
                    (campaign_id, project_id),
                )
            )
            if campaign is None:
                raise KnowledgeNotFound("GEO Campaign does not exist in this project")
            facts = _many(
                connection.execute(
                    """SELECT fact.id AS fact_candidate_id, fact.pipeline_run_id,
                              fact.source_id, fact.document_id, fact.chunk_id,
                              fact.rag_revision_id, fact.statement AS statement_snapshot,
                              fact.statement_hash, fact.source_locator,
                              fact.extractor_release
                       FROM knowledge_fact_candidates fact
                       JOIN knowledge_sources source
                         ON source.id = fact.source_id AND source.project_id = fact.project_id
                       JOIN knowledge_chunks chunk
                         ON chunk.id = fact.chunk_id AND chunk.project_id = fact.project_id
                       WHERE fact.project_id = %s AND fact.id = ANY(%s)
                         AND fact.status = 'approved'
                         AND fact.lifecycle_status = 'active'
                         AND source.status = 'ready' AND chunk.status = 'active'
                       ORDER BY fact.id FOR SHARE OF fact""",
                    (project_id, list(fact_candidate_ids)),
                )
            )
            if {item["fact_candidate_id"] for item in facts} != set(fact_candidate_ids):
                raise KnowledgeConflict(
                    "question generation Facts must be active, approved, and ready"
                )
            entities = _many(
                connection.execute(
                    """SELECT entity.id AS graph_entity_id,
                              entity.entity_type AS entity_type_snapshot,
                              entity.canonical_name AS canonical_name_snapshot,
                              entity.name_hash
                       FROM knowledge_graph_entities entity
                       WHERE entity.project_id = %s AND entity.id = ANY(%s)
                         AND entity.status = 'current'
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
                       ORDER BY entity.id FOR SHARE OF entity""",
                    (project_id, list(graph_entity_ids)),
                )
            )
            if {item["graph_entity_id"] for item in entities} != set(graph_entity_ids):
                raise KnowledgeConflict(
                    "question generation entities must be current with active sources"
                )
            _validate_competitors(connection, project_id, campaign_id, frozen_dimensions)
            input_value = {
                "schema": (
                    "knowledge-question-generation-input-v2"
                    if generation_mode == "coverage_pack"
                    else "knowledge-question-generation-input-v1"
                ),
                "project_id": str(project_id),
                "campaign_id": str(campaign_id),
                "generation_mode": generation_mode,
                "adapter_release": policy.adapter_release,
                "selection_manifest_hash": policy.selection_manifest_hash,
                "configured_model": configured_model.strip(),
                "model_call_budget": model_call_budget,
                "semantic_duplicate_threshold": semantic_duplicate_threshold,
                "dimensions": [_json_value(item.__dict__) for item in frozen_dimensions],
                "facts": [_json_value(item) for item in facts],
                "entities": [_json_value(item) for item in entities],
            }
            if coverage_plan is not None:
                input_value["coverage"] = {
                    "profile": coverage_plan.profile_key,
                    "profile_version": coverage_plan.profile_version,
                    "profile_hash": coverage_plan.profile_hash,
                    "target_count": coverage_plan.target_count,
                    "product_entity_id": str(product_entity_id),
                    "product_category": coverage_plan.category_key,
                    "product_name": coverage_plan.product_name,
                    "slots": [
                        {
                            "dimension_key": slot.dimension.dimension_key,
                            "coverage_role": slot.coverage_role,
                            "topic_cluster": slot.topic_cluster,
                            "planned_query_text": slot.planned_query_text,
                        }
                        for slot in coverage_plan.slots
                    ],
                }
            input_hash = _canonical_hash(input_value)
            existing = _one(
                connection.execute(
                    """SELECT id AS job_id, project_id, campaign_id, status, input_hash
                       FROM durable_jobs
                       WHERE id = %s AND project_id = %s AND campaign_id = %s""",
                    (job_id, project_id, campaign_id),
                )
            )
            if existing is not None:
                if existing["input_hash"] != input_hash:
                    raise KnowledgeConflict(
                        "question generation idempotency key was used for different input"
                    )
                return _generation_result(
                    existing,
                    dimensions=len(frozen_dimensions),
                    facts=len(facts),
                    entities=len(entities),
                    generation_mode=generation_mode,
                    coverage_plan=coverage_plan,
                )
            connection.execute(
                """INSERT INTO durable_jobs
                     (id, project_id, campaign_id, kind, input_hash,
                      idempotency_key, max_attempts)
                   VALUES (%s, %s, %s, 'knowledge.question.generate', %s, %s, %s)""",
                (
                    job_id,
                    project_id,
                    campaign_id,
                    input_hash,
                    f"knowledge-question:{campaign_id}:{key}",
                    policy.maximum_attempts,
                ),
            )
            connection.execute(
                """INSERT INTO knowledge_question_generation_specs
                     (job_id, project_id, campaign_id, configured_model,
                      model_call_budget, adapter_release, selection_manifest_hash,
                      dimension_schema_version, embedding_model_key,
                      semantic_duplicate_threshold, requested_by, generation_mode,
                      coverage_profile, coverage_profile_hash, target_count,
                      product_entity_id, product_category, product_name_snapshot)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s)""",
                (
                    job_id,
                    project_id,
                    campaign_id,
                    configured_model.strip(),
                    model_call_budget,
                    policy.adapter_release,
                    policy.selection_manifest_hash,
                    DIMENSION_SCHEMA_VERSION,
                    EMBEDDING_MODEL_KEY,
                    semantic_duplicate_threshold,
                    principal.identity_id,
                    generation_mode,
                    coverage_plan.profile_key if coverage_plan else None,
                    coverage_plan.profile_hash if coverage_plan else None,
                    coverage_plan.target_count if coverage_plan else None,
                    product_entity_id,
                    coverage_plan.category_key if coverage_plan else None,
                    coverage_plan.product_name if coverage_plan else None,
                ),
            )
            coverage_by_key = {
                slot.dimension.dimension_key: slot for slot in coverage_plan.slots
            } if coverage_plan else {}
            for dimension in frozen_dimensions:
                coverage_slot = coverage_by_key.get(dimension.dimension_key)
                planned_query = coverage_slot.planned_query_text if coverage_slot else None
                connection.execute(
                    """INSERT INTO knowledge_question_dimensions
                         (job_id, project_id, campaign_id, dimension_key, ordinal,
                          turn_index, parent_dimension_key, persona, scenario, intent,
                          funnel, region, language, brand_scope, platform, query_kind,
                          subject, competitor_entity_id, coverage_role, topic_cluster,
                          planned_query_text, planned_query_hash)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        job_id,
                        project_id,
                        campaign_id,
                        dimension.dimension_key,
                        dimension.ordinal,
                        dimension.turn_index,
                        dimension.parent_dimension_key,
                        dimension.persona,
                        dimension.scenario,
                        dimension.intent,
                        dimension.funnel,
                        dimension.region,
                        dimension.language,
                        dimension.brand_scope,
                        dimension.platform,
                        dimension.query_kind,
                        dimension.subject,
                        dimension.competitor_entity_id,
                        coverage_slot.coverage_role if coverage_slot else None,
                        coverage_slot.topic_cluster if coverage_slot else None,
                        planned_query,
                        hashlib.sha256(planned_query.encode()).hexdigest()
                        if planned_query
                        else None,
                    ),
                )
            for fact in facts:
                connection.execute(
                    """INSERT INTO knowledge_question_generation_fact_inputs
                         (job_id, project_id, campaign_id, fact_candidate_id,
                          pipeline_run_id, source_id, document_id, chunk_id,
                          rag_revision_id, statement_snapshot, statement_hash,
                          source_locator, extractor_release)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        job_id,
                        project_id,
                        campaign_id,
                        fact["fact_candidate_id"],
                        fact["pipeline_run_id"],
                        fact["source_id"],
                        fact["document_id"],
                        fact["chunk_id"],
                        fact["rag_revision_id"],
                        fact["statement_snapshot"],
                        fact["statement_hash"],
                        fact["source_locator"],
                        fact["extractor_release"],
                    ),
                )
            for entity in entities:
                connection.execute(
                    """INSERT INTO knowledge_question_generation_entity_inputs
                         (job_id, project_id, campaign_id, graph_entity_id,
                          entity_type_snapshot, canonical_name_snapshot, name_hash)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        job_id,
                        project_id,
                        campaign_id,
                        entity["graph_entity_id"],
                        entity["entity_type_snapshot"],
                        entity["canonical_name_snapshot"],
                        entity["name_hash"],
                    ),
                )
            connection.execute(
                """INSERT INTO broker_outbox
                     (project_id, job_id, topic, payload, idempotency_key)
                   VALUES (%s, %s, 'knowledge.question.generate', %s::jsonb, %s)""",
                (
                    project_id,
                    job_id,
                    json.dumps(
                        {
                            "job_id": str(job_id),
                            "project_id": str(project_id),
                            "campaign_id": str(campaign_id),
                        }
                    ),
                    f"wake:knowledge-question:{campaign_id}:{key}",
                ),
            )
            return _generation_result(
                {
                    "job_id": job_id,
                    "project_id": project_id,
                    "campaign_id": campaign_id,
                    "status": "queued",
                    "input_hash": input_hash,
                },
                dimensions=len(frozen_dimensions),
                facts=len(facts),
                entities=len(entities),
                generation_mode=generation_mode,
                coverage_plan=coverage_plan,
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
                              candidate.workflow_status, candidate.query_text_hash,
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
            if candidate["workflow_status"] != "pending_review":
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
            if latest is not None and latest["query_text_hash"] == text_hash:
                return {"outcome": "existing", **latest}
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
            created = _one(
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
            assert created is not None
            return {"outcome": "revised", **created}

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


def _validate_competitors(
    connection: Any,
    project_id: UUID,
    campaign_id: UUID,
    dimensions: Sequence[Any],
) -> None:
    competitor_ids = {
        item.competitor_entity_id
        for item in dimensions
        if item.competitor_entity_id is not None
    }
    if not competitor_ids:
        return
    rows = _many(
        connection.execute(
            """SELECT entity.id
               FROM product_entities entity
               JOIN campaign_entities member
                 ON member.entity_id = entity.id AND member.project_id = entity.project_id
               WHERE entity.project_id = %s AND entity.id = ANY(%s)
                 AND entity.entity_type = 'competitor' AND entity.status = 'active'
                 AND member.campaign_id = %s AND member.entity_role = 'competitor'""",
            (project_id, list(competitor_ids), campaign_id),
        )
    )
    if {item["id"] for item in rows} != competitor_ids:
        raise KnowledgeConflict("question competitor dimensions require Campaign competitors")


def _generation_result(
    value: Mapping[str, object],
    *,
    dimensions: int,
    facts: int,
    entities: int,
    generation_mode: str = "single_scenario",
    coverage_plan: CoverageQuestionPlan | None = None,
) -> Mapping[str, object]:
    return {
        "job_id": value["job_id"],
        "project_id": value["project_id"],
        "campaign_id": value["campaign_id"],
        "status": value["status"],
        "input_hash": value["input_hash"],
        "dimension_count": dimensions,
        "fact_input_count": facts,
        "entity_input_count": entities,
        "generation_mode": generation_mode,
        "coverage_profile": coverage_plan.profile_key if coverage_plan else None,
        "target_count": coverage_plan.target_count if coverage_plan else None,
    }


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 200:
        raise KnowledgeValidationError("Idempotency-Key must contain 1 to 200 characters")
    return normalized


def _canonical_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _one(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    return dict(value) if value is not None else None


def _many(cursor: Any) -> list[dict[str, Any]]:
    return [dict(value) for value in cursor.fetchall()]
