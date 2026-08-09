"""Question generation application commands."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.access.models import AccessPrincipal
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeNotFound,
    KnowledgeValidationError,
)
from geo_core.knowledge.question_coverage import CoverageQuestionPlan
from geo_core.knowledge.question_domain import (
    DIMENSION_SCHEMA_VERSION,
    EMBEDDING_MODEL_KEY,
    QuestionContractError,
    QuestionDimensionDraft,
    freeze_dimensions,
    question_generation_minimum_call_budget,
)
from geo_core.knowledge.question_application_support import (
    canonical_hash as _canonical_hash,
    generation_result as _generation_result,
    idempotency_key as _idempotency_key,
    json_value as _json_value,
    many as _many,
    one as _one,
    validate_competitors as _validate_competitors,
)
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy


class KnowledgeQuestionGenerationApplicationMixin:
    """Mixed into ``KnowledgeApplication`` for question generation commands."""

    _question_policy: KnowledgeRagEnqueuePolicy | None

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
            input_value: dict[str, object] = {
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
