"""Human review and immutable source revision workflows for Knowledge RAG."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.access.models import AccessPrincipal
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeNotFound,
    KnowledgeValidationError,
)
from geo_core.knowledge.rag_domain import CATALOG_MAPPABLE_GRAPH_TYPES, KnowledgeGraphEntityType
from geo_core.knowledge.rag_source_application import KnowledgeRagSourceApplicationMixin


class KnowledgeRagApplicationMixin(KnowledgeRagSourceApplicationMixin):
    """Mixin implemented by ``KnowledgeApplication`` using its scoped transaction."""

    def list_rag_revisions(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        with self._connection(principal, project_id) as connection:  # type: ignore[attr-defined]
            return tuple(
                _many(
                    connection.execute(
                        """SELECT id, project_id, job_id, pipeline_run_id, source_id,
                                  logical_source_id, document_id, adapter_release,
                                  selection_manifest_hash, input_hash, output_hash,
                                  artifact_uri, artifact_hash, lifecycle_status,
                                  superseded_at, completed_at, created_at
                           FROM knowledge_rag_revisions
                           WHERE project_id = %s ORDER BY created_at DESC, id DESC""",
                        (project_id,),
                    )
                )
            )

    def list_rag_entity_candidates(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        with self._connection(principal, project_id) as connection:  # type: ignore[attr-defined]
            return tuple(
                _many(
                    connection.execute(
                        """SELECT candidate.id, candidate.project_id,
                                  candidate.rag_revision_id, candidate.entity_type,
                                  candidate.name, candidate.name_hash,
                                  candidate.workflow_status, candidate.lifecycle_status,
                                  candidate.reviewed_by, candidate.review_notes,
                                  candidate.reviewed_at, candidate.graph_entity_id,
                                  candidate.created_at
                           FROM knowledge_entity_candidates candidate
                           WHERE candidate.project_id = %s
                           ORDER BY candidate.created_at DESC, candidate.id DESC
                           LIMIT 500""",
                        (project_id,),
                    )
                )
            )

    def list_rag_relation_candidates(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        with self._connection(principal, project_id) as connection:  # type: ignore[attr-defined]
            return tuple(
                _many(
                    connection.execute(
                        """SELECT relation.id, relation.project_id,
                                  relation.rag_revision_id, relation.predicate,
                                  subject.name AS subject, object.name AS object,
                                  relation.source_locator, relation.workflow_status,
                                  relation.lifecycle_status, relation.reviewed_by,
                                  relation.review_notes, relation.reviewed_at,
                                  relation.graph_relation_id, relation.created_at
                           FROM knowledge_relation_candidates relation
                           JOIN knowledge_entity_candidates subject
                             ON subject.id = relation.subject_entity_candidate_id
                            AND subject.project_id = relation.project_id
                           JOIN knowledge_entity_candidates object
                             ON object.id = relation.object_entity_candidate_id
                            AND object.project_id = relation.project_id
                           WHERE relation.project_id = %s
                           ORDER BY relation.created_at DESC, relation.id DESC
                           LIMIT 500""",
                        (project_id,),
                    )
                )
            )

    def review_rag_entity_candidate(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        candidate_id: UUID,
        decision: str,
        notes: str,
    ) -> Mapping[str, object]:
        _review_decision(decision)
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            candidate = _one(
                connection.execute(
                    """SELECT id, rag_revision_id, entity_type, name, name_hash,
                              workflow_status, lifecycle_status, graph_entity_id
                       FROM knowledge_entity_candidates
                       WHERE id = %s AND project_id = %s FOR UPDATE""",
                    (candidate_id, project_id),
                )
            )
            if candidate is None:
                raise KnowledgeNotFound("Knowledge graph entity candidate does not exist")
            _require_active_candidate(candidate)
            if candidate["workflow_status"] != "pending_review":
                if candidate["workflow_status"] == decision:
                    return {"outcome": "existing", **candidate}
                raise KnowledgeConflict("Knowledge graph entity candidate was already reviewed")
            graph_entity_id: UUID | None = None
            if decision == "approved":
                graph_entity_id = uuid5(
                    NAMESPACE_URL,
                    (
                        f"geo-knowledge-graph-entity:{project_id}:"
                        f"{candidate['entity_type']}:{candidate['name_hash']}"
                    ),
                )
                connection.execute(
                    """INSERT INTO knowledge_graph_entities
                         (id, project_id, entity_type, canonical_name, name_hash,
                          status, approved_by, approved_at)
                       VALUES (%s, %s, %s, %s, %s, 'current', %s, clock_timestamp())
                       ON CONFLICT (project_id, entity_type, name_hash) DO UPDATE SET
                         status = 'current', updated_at = clock_timestamp()
                       WHERE knowledge_graph_entities.canonical_name = EXCLUDED.canonical_name""",
                    (
                        graph_entity_id,
                        project_id,
                        candidate["entity_type"],
                        candidate["name"],
                        candidate["name_hash"],
                        principal.identity_id,
                    ),
                )
                connection.execute(
                    """INSERT INTO knowledge_graph_entity_sources
                         (project_id, graph_entity_id, rag_revision_id,
                          entity_candidate_id, pipeline_run_id, source_id,
                          document_id, chunk_id, source_locator, approved_by,
                          lifecycle_status)
                       SELECT source.project_id, %s, source.rag_revision_id,
                              source.entity_candidate_id, source.pipeline_run_id,
                              source.source_id, source.document_id, source.chunk_id,
                              source.source_locator, %s, 'active'
                       FROM knowledge_entity_candidate_sources source
                       WHERE source.project_id = %s AND source.entity_candidate_id = %s
                       ON CONFLICT DO NOTHING""",
                    (graph_entity_id, principal.identity_id, project_id, candidate_id),
                )
            reviewed = _one(
                connection.execute(
                    """UPDATE knowledge_entity_candidates
                       SET workflow_status = %s, graph_entity_id = %s,
                           reviewed_by = %s, review_notes = %s,
                           reviewed_at = clock_timestamp(), updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s
                       RETURNING id, project_id, entity_type, name, workflow_status,
                                 lifecycle_status, graph_entity_id, reviewed_by,
                                 review_notes, reviewed_at""",
                    (
                        decision,
                        graph_entity_id,
                        principal.identity_id,
                        notes.strip() or None,
                        candidate_id,
                        project_id,
                    ),
                )
            )
            assert reviewed is not None
            return {"outcome": "reviewed", **reviewed}

    def review_rag_relation_candidate(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        candidate_id: UUID,
        decision: str,
        notes: str,
    ) -> Mapping[str, object]:
        _review_decision(decision)
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            candidate = _one(
                connection.execute(
                    """SELECT relation.id, relation.rag_revision_id,
                              relation.pipeline_run_id, relation.source_id,
                              relation.document_id,
                              relation.workflow_status, relation.lifecycle_status,
                              relation.predicate, relation.chunk_id,
                              relation.source_locator, relation.graph_relation_id,
                              subject.workflow_status AS subject_status,
                              subject.graph_entity_id AS subject_graph_entity_id,
                              object.workflow_status AS object_status,
                              object.graph_entity_id AS object_graph_entity_id
                       FROM knowledge_relation_candidates relation
                       JOIN knowledge_entity_candidates subject
                         ON subject.id = relation.subject_entity_candidate_id
                        AND subject.project_id = relation.project_id
                       JOIN knowledge_entity_candidates object
                         ON object.id = relation.object_entity_candidate_id
                        AND object.project_id = relation.project_id
                       WHERE relation.id = %s AND relation.project_id = %s
                       FOR UPDATE OF relation""",
                    (candidate_id, project_id),
                )
            )
            if candidate is None:
                raise KnowledgeNotFound("Knowledge graph relation candidate does not exist")
            _require_active_candidate(candidate)
            if candidate["workflow_status"] != "pending_review":
                if candidate["workflow_status"] == decision:
                    return {"outcome": "existing", **candidate}
                raise KnowledgeConflict("Knowledge graph relation candidate was already reviewed")
            graph_relation_id: UUID | None = None
            if decision == "approved":
                if (
                    candidate["subject_status"] != "approved"
                    or candidate["object_status"] != "approved"
                    or candidate["subject_graph_entity_id"] is None
                    or candidate["object_graph_entity_id"] is None
                ):
                    raise KnowledgeConflict(
                        "Knowledge graph relation endpoints must be approved first"
                    )
                graph_relation_id = uuid5(
                    NAMESPACE_URL,
                    (
                        f"geo-knowledge-graph-relation:{project_id}:"
                        f"{candidate['subject_graph_entity_id']}:{candidate['predicate']}:"
                        f"{candidate['object_graph_entity_id']}"
                    ),
                )
                connection.execute(
                    """INSERT INTO knowledge_graph_relations
                         (id, project_id, subject_graph_entity_id, predicate,
                          object_graph_entity_id, status, approved_by, approved_at)
                       VALUES (%s, %s, %s, %s, %s, 'current', %s, clock_timestamp())
                       ON CONFLICT (
                         project_id, subject_graph_entity_id, predicate,
                         object_graph_entity_id
                       ) DO UPDATE SET status = 'current', updated_at = clock_timestamp()""",
                    (
                        graph_relation_id,
                        project_id,
                        candidate["subject_graph_entity_id"],
                        candidate["predicate"],
                        candidate["object_graph_entity_id"],
                        principal.identity_id,
                    ),
                )
                connection.execute(
                    """INSERT INTO knowledge_graph_relation_sources
                         (project_id, graph_relation_id, rag_revision_id,
                          relation_candidate_id, pipeline_run_id, source_id,
                          document_id, chunk_id, source_locator, approved_by,
                          lifecycle_status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
                       ON CONFLICT DO NOTHING""",
                    (
                        project_id,
                        graph_relation_id,
                        candidate["rag_revision_id"],
                        candidate_id,
                        candidate["pipeline_run_id"],
                        candidate["source_id"],
                        candidate["document_id"],
                        candidate["chunk_id"],
                        candidate["source_locator"],
                        principal.identity_id,
                    ),
                )
            reviewed = _one(
                connection.execute(
                    """UPDATE knowledge_relation_candidates
                       SET workflow_status = %s, graph_relation_id = %s,
                           reviewed_by = %s, review_notes = %s,
                           reviewed_at = clock_timestamp(), updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s
                       RETURNING id, project_id, predicate, workflow_status,
                                 lifecycle_status, graph_relation_id, reviewed_by,
                                 review_notes, reviewed_at""",
                    (
                        decision,
                        graph_relation_id,
                        principal.identity_id,
                        notes.strip() or None,
                        candidate_id,
                        project_id,
                    ),
                )
            )
            assert reviewed is not None
            return {"outcome": "reviewed", **reviewed}

    def map_graph_entity_to_catalog(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        graph_entity_id: UUID,
        catalog_entity_id: UUID,
    ) -> Mapping[str, object]:
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            graph = _one(
                connection.execute(
                    """SELECT id, entity_type, canonical_name, status, catalog_entity_id
                       FROM knowledge_graph_entities
                       WHERE id = %s AND project_id = %s FOR UPDATE""",
                    (graph_entity_id, project_id),
                )
            )
            if graph is None:
                raise KnowledgeNotFound("approved Knowledge graph entity does not exist")
            graph_type = KnowledgeGraphEntityType(str(graph["entity_type"]))
            if graph_type not in CATALOG_MAPPABLE_GRAPH_TYPES:
                raise KnowledgeValidationError(
                    "only brand, product, competitor and market graph entities map to Catalog"
                )
            catalog = _one(
                connection.execute(
                    """SELECT id, entity_type, canonical_name, status
                       FROM product_entities WHERE id = %s AND project_id = %s""",
                    (catalog_entity_id, project_id),
                )
            )
            if (
                catalog is None
                or catalog["status"] != "active"
                or catalog["entity_type"] != graph_type.value
                or catalog["canonical_name"] != graph["canonical_name"]
            ):
                raise KnowledgeConflict(
                    "Catalog mapping must match the graph entity project, type and canonical name"
                )
            if graph["catalog_entity_id"] not in {None, catalog_entity_id}:
                raise KnowledgeConflict(
                    "Knowledge graph entity already maps to another Catalog row"
                )
            mapped = _one(
                connection.execute(
                    """UPDATE knowledge_graph_entities SET catalog_entity_id = %s,
                              updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s
                       RETURNING id, project_id, entity_type, canonical_name,
                                 status, catalog_entity_id""",
                    (catalog_entity_id, graph_entity_id, project_id),
                )
            )
            assert mapped is not None
            return mapped

def _review_decision(value: str) -> None:
    if value not in {"approved", "rejected"}:
        raise KnowledgeValidationError("candidate decision must be approved or rejected")


def _require_active_candidate(candidate: Mapping[str, object]) -> None:
    if candidate["lifecycle_status"] != "active":
        raise KnowledgeConflict("only active Knowledge graph candidates may be reviewed")


def _one(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    return dict(value) if value is not None else None


def _many(cursor: Any) -> list[dict[str, Any]]:
    return [dict(value) for value in cursor.fetchall()]
