"""Application commands and reads for governed GEO question generation."""

from __future__ import annotations

import hashlib
import json
import math
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
)
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy


class KnowledgeQuestionApplicationMixin:
    """Mixed into ``KnowledgeApplication``; its connection enforces role and RLS scope."""

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
    ) -> Mapping[str, object]:
        policy = self._question_policy
        if policy is None:
            raise KnowledgeValidationError("question generation runtime selection is not configured")
        key = _idempotency_key(idempotency_key)
        try:
            frozen_dimensions = freeze_dimensions(dimensions)
        except QuestionContractError as exc:
            raise KnowledgeValidationError(str(exc)) from exc
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
        minimum_calls = math.ceil(len(frozen_dimensions) / 10) * policy.maximum_attempts
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
                       WHERE fact.project_id = %s AND fact.id = ANY(%s)
                         AND fact.status = 'approved'
                         AND fact.lifecycle_status = 'active'
                         AND source.status = 'ready'
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
                           WHERE source.project_id = entity.project_id
                             AND source.graph_entity_id = entity.id
                             AND source.lifecycle_status = 'active'
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
                "schema": "knowledge-question-generation-input-v1",
                "project_id": str(project_id),
                "campaign_id": str(campaign_id),
                "adapter_release": policy.adapter_release,
                "selection_manifest_hash": policy.selection_manifest_hash,
                "configured_model": configured_model.strip(),
                "model_call_budget": model_call_budget,
                "semantic_duplicate_threshold": semantic_duplicate_threshold,
                "dimensions": [_json_value(item.__dict__) for item in frozen_dimensions],
                "facts": [_json_value(item) for item in facts],
                "entities": [_json_value(item) for item in entities],
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
                      semantic_duplicate_threshold, requested_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
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
                ),
            )
            for dimension in frozen_dimensions:
                connection.execute(
                    """INSERT INTO knowledge_question_dimensions
                         (job_id, project_id, campaign_id, dimension_key, ordinal,
                          turn_index, parent_dimension_key, persona, scenario, intent,
                          funnel, region, language, brand_scope, platform, query_kind,
                          subject, competitor_entity_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s)""",
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
                                  spec.adapter_release, spec.semantic_duplicate_threshold,
                                  result.artifact_uri, result.artifact_hash,
                                  result.dimension_count, result.candidate_count,
                                  result.supported_dimension_count,
                                  result.possible_duplicate_count,
                                  result.generated_at, spec.created_at
                           FROM knowledge_question_generation_specs spec
                           JOIN durable_jobs job
                             ON job.id = spec.job_id AND job.project_id = spec.project_id
                            AND job.campaign_id = spec.campaign_id
                           LEFT JOIN knowledge_question_generation_results result
                             ON result.job_id = spec.job_id
                            AND result.project_id = spec.project_id
                            AND result.campaign_id = spec.campaign_id
                           WHERE spec.project_id = %s AND spec.campaign_id = %s
                           ORDER BY spec.created_at DESC, spec.job_id DESC""",
                        (project_id, campaign_id),
                    )
                )
            )

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
                                  candidate.dimension_key, candidate.variant_index,
                                  candidate.turn_index, candidate.parent_candidate_id,
                                  candidate.query_text, candidate.query_text_hash,
                                  candidate.semantic_fingerprint, candidate.dedup_status,
                                  candidate.nearest_candidate_id,
                                  candidate.nearest_similarity,
                                  candidate.workflow_status, candidate.review_notes,
                                  candidate.reviewed_at, candidate.created_at,
                                  COALESCE(facts.ids, ARRAY[]::uuid[]) AS fact_source_ids,
                                  COALESCE(entities.ids, ARRAY[]::uuid[]) AS entity_source_ids
                           FROM knowledge_question_candidates candidate
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
                           ORDER BY candidate.dimension_key, candidate.variant_index,
                                    candidate.id""",
                        (project_id, campaign_id, generation_job_id),
                    )
                )
            )

    def review_question_candidate(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        candidate_id: UUID,
        decision: str,
        notes: str,
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
            if (
                decision == "approved"
                and candidate["dedup_status"] == "possible_duplicate"
                and not notes.strip()
            ):
                raise KnowledgeValidationError(
                    "approving a possible duplicate requires review notes"
                )
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
                        notes.strip() or None,
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
    value: Mapping[str, object], *, dimensions: int, facts: int, entities: int
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
