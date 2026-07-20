"""Approved Knowledge Fact to governed Evidence promotion."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.access.models import AccessPrincipal
from geo_core.catalog.domain import (
    CatalogRuleViolation,
    Confidentiality,
    EntityType,
    EvidenceDraft,
    EvidenceItemType,
    EvidenceSnapshot,
    PublicCitation,
    SubjectRole,
    UsageRights,
    validate_subject_type,
)
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeNotFound,
    KnowledgeValidationError,
)
from geo_core.knowledge.evidence_request import (
    normalize_citation,
    promotion_idempotency_key,
    promotion_request_hash,
)
from geo_core.knowledge.evidence_persistence import insert_evidence
from geo_core.knowledge.locking import lock_source_aggregate


_PROMOTABLE_RIGHTS = frozenset(
    {UsageRights.OWNED, UsageRights.LICENSED, UsageRights.PUBLIC_REFERENCE}
)
_PROMOTABLE_CONFIDENTIALITY = frozenset(
    {Confidentiality.PUBLIC, Confidentiality.INTERNAL, Confidentiality.CONFIDENTIAL}
)


class KnowledgeEvidenceApplicationMixin:
    """Mixin implemented by ``KnowledgeApplication`` using its scoped connection."""

    def evidence_proposal(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        fact_id: UUID,
    ) -> Mapping[str, object]:
        with self._connection(principal, project_id) as connection:  # type: ignore[attr-defined]
            context = _fact_context(connection, project_id=project_id, fact_id=fact_id)
            if context is None:
                raise KnowledgeNotFound("knowledge fact candidate does not exist")
            return _proposal(context)

    def promote_fact_to_evidence(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        fact_id: UUID,
        idempotency_key: str,
        title: str,
        subject_entity_id: UUID | None,
        subject_role: SubjectRole,
        usage_rights: UsageRights,
        confidentiality: Confidentiality,
        public_citation: PublicCitation,
    ) -> Mapping[str, object]:
        key = promotion_idempotency_key(idempotency_key)
        normalized_title = title.strip()
        normalized_citation = normalize_citation(public_citation)
        if not normalized_title or len(normalized_title) > 500:
            raise KnowledgeValidationError(
                "evidence title is required and must be at most 500 characters"
            )
        if usage_rights not in _PROMOTABLE_RIGHTS:
            raise KnowledgeValidationError(
                "approved Fact Evidence requires owned, licensed or public_reference rights"
            )
        if confidentiality not in _PROMOTABLE_CONFIDENTIALITY:
            raise KnowledgeValidationError(
                "approved Fact Evidence cannot use restricted confidentiality"
            )
        if usage_rights == UsageRights.PUBLIC_REFERENCE and not all(
            value and value.strip()
            for value in (
                normalized_citation.source_url,
                normalized_citation.source_title,
                normalized_citation.label,
            )
        ):
            raise KnowledgeValidationError(
                "public_reference requires source URL, source title and citation label"
            )
        if usage_rights == UsageRights.PUBLIC_REFERENCE and not str(
            normalized_citation.source_url
        ).startswith(("https://", "http://")):
            raise KnowledgeValidationError("public_reference source URL must use HTTP or HTTPS")
        request_hash = promotion_request_hash(
            project_id=project_id,
            fact_id=fact_id,
            title=normalized_title,
            subject_entity_id=subject_entity_id,
            subject_role=subject_role,
            usage_rights=usage_rights,
            confidentiality=confidentiality,
            public_citation=normalized_citation,
        )

        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            identity = _fact_source_identity(
                connection, project_id=project_id, fact_id=fact_id
            )
            if identity is None:
                raise KnowledgeNotFound("knowledge fact candidate does not exist")
            lock_source_aggregate(connection, identity["logical_source_id"])
            locked = _fact_context(
                connection,
                project_id=project_id,
                fact_id=fact_id,
                for_update=True,
            )
            if locked is None:
                raise KnowledgeNotFound("knowledge fact candidate does not exist")
            connection.execute(
                """SELECT id FROM knowledge_chunks
                   WHERE id = %s AND project_id = %s FOR UPDATE""",
                (locked["knowledge_chunk_id"], project_id),
            )
            context = _fact_context(connection, project_id=project_id, fact_id=fact_id)
            if context is None:
                raise KnowledgeNotFound("knowledge fact candidate does not exist")
            if context.get("lineage_evidence_item_id") is not None:
                if context["lineage_idempotency_key"] == key:
                    if context["lineage_promotion_request_hash"] != request_hash:
                        raise KnowledgeConflict(
                            "Idempotency-Key was already used for different promotion metadata"
                        )
                else:
                    key_owner = _lineage_by_idempotency_key(
                        connection, project_id=project_id, idempotency_key=key
                    )
                    if key_owner is not None and key_owner["knowledge_fact_id"] != fact_id:
                        raise KnowledgeConflict(
                            "Idempotency-Key was already used for a different Knowledge Fact"
                        )
                return _promotion_result("existing", context)
            key_owner = _lineage_by_idempotency_key(
                connection, project_id=project_id, idempotency_key=key
            )
            if key_owner is not None:
                raise KnowledgeConflict(
                    "Idempotency-Key was already used for a different Knowledge Fact"
                )

            blockers = _promotion_blockers(context)
            if blockers:
                raise KnowledgeConflict("knowledge Fact cannot be promoted: " + ", ".join(blockers))
            _validate_subject(
                connection,
                project_id=project_id,
                subject_entity_id=subject_entity_id,
                subject_role=subject_role,
            )
            statement = str(context["fact_statement"])
            snapshot_hash = hashlib.sha256(statement.encode("utf-8")).hexdigest()
            try:
                draft = EvidenceDraft(
                    item_type=EvidenceItemType.APPROVED_FACT,
                    source_id=fact_id,
                    subject_entity_id=subject_entity_id,
                    subject_role=subject_role,
                    locator={},
                    snapshot=EvidenceSnapshot(
                        text=statement,
                        uri=None,
                        sha256=snapshot_hash,
                    ),
                    source_revision_kind="content_hash",
                    source_revision_value=str(context["fact_statement_hash"]),
                    usage_rights=usage_rights,
                    confidentiality=confidentiality,
                    public_citation=normalized_citation,
                )
            except CatalogRuleViolation as error:
                raise KnowledgeValidationError(str(error)) from error

            evidence_id = uuid5(
                NAMESPACE_URL,
                f"geo-knowledge-fact-evidence:{project_id}:{fact_id}",
            )
            insert_evidence(
                connection,
                evidence_id=evidence_id,
                project_id=project_id,
                draft=draft,
            )
            inserted = _one(
                connection.execute(
                    """INSERT INTO knowledge_fact_evidence_lineages (
                     project_id, pipeline_run_id, knowledge_source_id,
                     knowledge_document_id, knowledge_chunk_id, knowledge_fact_id,
                     evidence_item_id, evidence_title, promoted_by,
                     idempotency_key, promotion_request_hash, lineage_contract_version,
                     source_content_hash, document_cleaned_text_hash, chunk_text_hash,
                     fact_statement_hash, evidence_snapshot_hash
                   ) VALUES (
                     %s, %s, %s, %s, %s, %s, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s, %s, %s
                   ) ON CONFLICT (project_id, idempotency_key) DO NOTHING
                   RETURNING evidence_item_id""",
                    (
                        project_id,
                        context["pipeline_run_id"],
                        context["knowledge_source_id"],
                        context["knowledge_document_id"],
                        context["knowledge_chunk_id"],
                        fact_id,
                        evidence_id,
                        normalized_title,
                        principal.identity_id,
                        key,
                        request_hash,
                        "knowledge-fact-evidence-v1",
                        context["source_content_hash"],
                        context["document_cleaned_text_hash"],
                        context["chunk_text_hash"],
                        context["fact_statement_hash"],
                        snapshot_hash,
                    ),
                )
            )
            if inserted is None:
                raise KnowledgeConflict(
                    "Idempotency-Key was concurrently used for a different Knowledge Fact"
                )
            created = _fact_context(
                connection,
                project_id=project_id,
                fact_id=fact_id,
            )
            if created is None:
                raise RuntimeError("created Fact Evidence lineage could not be read")
            return _promotion_result("created", created)


def _lineage_by_idempotency_key(
    connection: Any, *, project_id: UUID, idempotency_key: str
) -> dict[str, Any] | None:
    return _one(
        connection.execute(
            """SELECT knowledge_fact_id, promotion_request_hash
               FROM knowledge_fact_evidence_lineages
               WHERE project_id = %s AND idempotency_key = %s""",
            (project_id, idempotency_key),
        )
    )


def _fact_source_identity(
    connection: Any, *, project_id: UUID, fact_id: UUID
) -> dict[str, Any] | None:
    return _one(
        connection.execute(
            """SELECT source.logical_source_id
               FROM knowledge_fact_candidates fact
               JOIN knowledge_sources source
                 ON source.id = fact.source_id AND source.project_id = fact.project_id
               WHERE fact.id = %s AND fact.project_id = %s""",
            (fact_id, project_id),
        )
    )


def _fact_context(
    connection: Any,
    *,
    project_id: UUID,
    fact_id: UUID,
    for_update: bool = False,
) -> dict[str, Any] | None:
    lock = " FOR UPDATE OF fact" if for_update else ""
    return _one(
        connection.execute(
            f"""SELECT
                 fact.project_id,
                 fact.id AS knowledge_fact_id,
                 pipeline_run.id AS pipeline_run_id,
                 pipeline_run.status AS pipeline_run_status,
                 pipeline_run.completed_at AS pipeline_run_completed_at,
                 source.id AS knowledge_source_id,
                 fact.chunk_id AS knowledge_chunk_id,
                 fact.statement AS fact_statement,
                 fact.statement_hash AS fact_statement_hash,
                 fact.status AS fact_status,
                 fact.lifecycle_status AS fact_lifecycle_status,
                 fact.extractor_release AS fact_extractor_release,
                 fact.reviewed_by AS fact_reviewed_by,
                 fact.reviewed_at AS fact_reviewed_at,
                 source.title AS source_title,
                 source.source_kind,
                 source.source_url,
                 source.status AS source_status,
                 source.content_hash AS source_content_hash,
                 source.raw_content IS NOT NULL
                   AND source.content_hash IS NOT NULL
                   AND encode(digest(source.raw_content, 'sha256'), 'hex') =
                       source.content_hash AS source_hash_valid,
                 document.id AS knowledge_document_id,
                 document.parser_version,
                 document.cleaned_text_hash AS document_cleaned_text_hash,
                 encode(digest(convert_to(document.cleaned_text, 'UTF8'), 'sha256'), 'hex') =
                   document.cleaned_text_hash AS document_hash_valid,
                 chunk.chunk_index,
                 chunk.text AS chunk_text,
                 chunk.text_hash AS chunk_text_hash,
                 chunk.status AS chunk_status,
                 chunk.char_count = char_length(chunk.text)
                   AND encode(digest(convert_to(chunk.text, 'UTF8'), 'sha256'), 'hex') =
                       chunk.text_hash AS chunk_integrity_valid,
                 encode(digest(convert_to(fact.statement, 'UTF8'), 'sha256'), 'hex') =
                   fact.statement_hash AS fact_hash_valid,
                 lineage.evidence_item_id AS lineage_evidence_item_id,
                 lineage.evidence_title AS lineage_evidence_title,
                 lineage.promoted_by,
                 lineage.promoted_at,
                 lineage.idempotency_key AS lineage_idempotency_key,
                 lineage.promotion_request_hash AS lineage_promotion_request_hash,
                 lineage.lineage_contract_version,
                 lineage.source_content_hash AS lineage_source_content_hash,
                 lineage.document_cleaned_text_hash AS lineage_document_hash,
                 lineage.chunk_text_hash AS lineage_chunk_hash,
                 lineage.fact_statement_hash AS lineage_fact_hash,
                 lineage.evidence_snapshot_hash AS lineage_evidence_hash,
                 evidence.item_type AS evidence_item_type,
                 evidence.subject_entity_id AS evidence_subject_entity_id,
                 evidence.subject_role AS evidence_subject_role,
                 evidence.snapshot_text AS evidence_snapshot_text,
                 evidence.snapshot_uri AS evidence_snapshot_uri,
                 evidence.snapshot_hash AS evidence_snapshot_hash,
                 evidence.source_revision_kind AS evidence_revision_kind,
                 evidence.source_revision_value AS evidence_revision_value,
                 evidence.usage_rights AS evidence_usage_rights,
                 evidence.confidentiality AS evidence_confidentiality,
                 evidence.public_disclosure_allowed,
                 evidence.public_source_url,
                 evidence.public_source_title,
                 evidence.citation_label,
                 evidence.quotation_allowed,
                 evidence.attribution_required,
                 evidence.created_at AS evidence_created_at
               FROM knowledge_fact_candidates fact
               JOIN knowledge_pipeline_runs pipeline_run
                 ON pipeline_run.id = fact.pipeline_run_id
                AND pipeline_run.project_id = fact.project_id
                AND pipeline_run.source_id = fact.source_id
               JOIN knowledge_chunks chunk
                 ON chunk.id = fact.chunk_id AND chunk.project_id = fact.project_id
                AND chunk.pipeline_run_id = fact.pipeline_run_id
                AND chunk.source_id = fact.source_id
                AND chunk.document_id = fact.document_id
               JOIN knowledge_documents document
                 ON document.id = fact.document_id
                AND document.id = chunk.document_id
                AND document.project_id = chunk.project_id
                AND document.pipeline_run_id = chunk.pipeline_run_id
                AND document.source_id = chunk.source_id
               JOIN knowledge_sources source
                 ON source.id = pipeline_run.source_id
                AND source.id = fact.source_id
                AND source.project_id = fact.project_id
               LEFT JOIN knowledge_fact_evidence_lineages lineage
                 ON lineage.project_id = fact.project_id
                AND lineage.knowledge_fact_id = fact.id
                AND lineage.lineage_contract_version = 'knowledge-fact-evidence-v1'
               LEFT JOIN evidence_items evidence
                 ON evidence.id = lineage.evidence_item_id
                AND evidence.project_id = lineage.project_id
               WHERE fact.id = %s AND fact.project_id = %s{lock}""",  # nosec B608
            (fact_id, project_id),
        )
    )


def _promotion_blockers(context: Mapping[str, object]) -> list[str]:
    blockers: list[str] = []
    if context["fact_lifecycle_status"] != "active":
        blockers.append("fact_not_active")
    if context["fact_status"] != "approved":
        blockers.append("fact_not_approved")
    if context["fact_reviewed_by"] is None or context["fact_reviewed_at"] is None:
        blockers.append("fact_review_metadata_missing")
    if context["source_status"] != "ready":
        blockers.append("source_not_ready")
    if context["source_content_hash"] is None:
        blockers.append("source_content_hash_missing")
    if (
        context["pipeline_run_status"] != "succeeded"
        or context["pipeline_run_completed_at"] is None
    ):
        blockers.append("pipeline_run_not_succeeded")
    if context["source_hash_valid"] is not True:
        blockers.append("source_content_hash_mismatch")
    if context["document_hash_valid"] is not True:
        blockers.append("document_cleaned_text_hash_mismatch")
    if context["chunk_status"] != "active":
        blockers.append("chunk_disabled")
    if context["chunk_integrity_valid"] is not True:
        blockers.append("chunk_integrity_mismatch")
    if context["fact_hash_valid"] is not True:
        blockers.append("fact_statement_hash_mismatch")
    return blockers


def _proposal(context: Mapping[str, object]) -> Mapping[str, object]:
    existing = (
        {
            "evidence": _evidence(context),
            "lineage": _lineage(context),
        }
        if context.get("lineage_evidence_item_id") is not None
        else None
    )
    blockers = [] if existing else _promotion_blockers(context)
    statement = str(context["fact_statement"])
    return {
        "project_id": context["project_id"],
        "promotable": not blockers,
        "blockers": blockers,
        "fact": {
            "id": context["knowledge_fact_id"],
            "status": context["fact_status"],
            "lifecycle_status": context["fact_lifecycle_status"],
            "extractor_release": context["fact_extractor_release"],
            "statement": statement,
            "statement_hash": context["fact_statement_hash"],
            "reviewed_by": context["fact_reviewed_by"],
            "reviewed_at": context["fact_reviewed_at"],
        },
        "source": {
            "id": context["knowledge_source_id"],
            "title": context["source_title"],
            "source_kind": context["source_kind"],
            "source_url": context["source_url"],
            "status": context["source_status"],
            "content_hash": context["source_content_hash"],
        },
        "document": {
            "id": context["knowledge_document_id"],
            "parser_version": context["parser_version"],
            "cleaned_text_hash": context["document_cleaned_text_hash"],
        },
        "chunk": {
            "id": context["knowledge_chunk_id"],
            "chunk_index": context["chunk_index"],
            "text": context["chunk_text"],
            "text_hash": context["chunk_text_hash"],
            "status": context["chunk_status"],
        },
        "existing": existing,
        "defaults": {
            "title": f"{context['source_title']}: {statement[:120]}",
            "source_url": context["source_url"],
            "source_title": context["source_title"],
            "citation_label": context["source_title"],
        },
    }


def _promotion_result(outcome: str, context: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "outcome": outcome,
        "evidence": _evidence(context),
        "lineage": _lineage(context),
    }


def _lineage(context: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "project_id": context["project_id"],
        "pipeline_run_id": context["pipeline_run_id"],
        "knowledge_source_id": context["knowledge_source_id"],
        "knowledge_document_id": context["knowledge_document_id"],
        "knowledge_chunk_id": context["knowledge_chunk_id"],
        "knowledge_fact_id": context["knowledge_fact_id"],
        "evidence_item_id": context["lineage_evidence_item_id"],
        "evidence_title": context["lineage_evidence_title"],
        "promoted_by": context["promoted_by"],
        "promoted_at": context["promoted_at"],
        "idempotency_key": context["lineage_idempotency_key"],
        "promotion_request_hash": context["lineage_promotion_request_hash"],
        "lineage_contract_version": context["lineage_contract_version"],
        "source_content_hash": context["lineage_source_content_hash"],
        "document_cleaned_text_hash": context["lineage_document_hash"],
        "chunk_text_hash": context["lineage_chunk_hash"],
        "fact_statement_hash": context["lineage_fact_hash"],
        "evidence_snapshot_hash": context["lineage_evidence_hash"],
    }


def _evidence(context: Mapping[str, object]) -> Mapping[str, object]:
    rights = str(context["evidence_usage_rights"])
    confidentiality = str(context["evidence_confidentiality"])
    disclosure = bool(context["public_disclosure_allowed"])
    eligible_for_generation = (
        rights not in {"unknown", "restricted"} and confidentiality != "restricted"
    )
    return {
        "id": context["lineage_evidence_item_id"],
        "project_id": context["project_id"],
        "title": context["lineage_evidence_title"],
        "item_type": context["evidence_item_type"],
        "subject_entity_id": context["evidence_subject_entity_id"],
        "subject_role": context["evidence_subject_role"],
        "snapshot": {
            "kind": "text" if context["evidence_snapshot_text"] is not None else "minio",
            "text": context["evidence_snapshot_text"],
            "uri": context["evidence_snapshot_uri"],
            "sha256": context["evidence_snapshot_hash"],
        },
        "source_revision": {
            "kind": context["evidence_revision_kind"],
            "value": context["evidence_revision_value"],
        },
        "usage_rights": rights,
        "confidentiality": confidentiality,
        "public_citation": {
            "disclosure_allowed": disclosure,
            "source_url": context["public_source_url"],
            "source_title": context["public_source_title"],
            "label": context["citation_label"],
            "quotation_allowed": bool(context["quotation_allowed"]),
            "attribution_required": bool(context["attribution_required"]),
        },
        "eligible_for_generation": eligible_for_generation,
        "eligible_for_publication": (
            eligible_for_generation and confidentiality == "public" and disclosure
        ),
        "created_at": context["evidence_created_at"],
    }


def _validate_subject(
    connection: Any,
    *,
    project_id: UUID,
    subject_entity_id: UUID | None,
    subject_role: SubjectRole,
) -> None:
    if subject_role == SubjectRole.NEUTRAL:
        if subject_entity_id is not None:
            raise KnowledgeValidationError("neutral Evidence cannot bind a subject entity")
        return
    if subject_entity_id is None:
        raise KnowledgeValidationError("non-neutral Evidence requires a subject entity")
    entity = _one(
        connection.execute(
            """SELECT entity_type FROM product_entities
               WHERE id = %s AND project_id = %s AND status = 'active'""",
            (subject_entity_id, project_id),
        )
    )
    if entity is None:
        raise KnowledgeNotFound("Evidence subject does not exist in this project")
    try:
        validate_subject_type(
            role=subject_role,
            entity_type=EntityType(str(entity["entity_type"])),
        )
    except CatalogRuleViolation as error:
        raise KnowledgeValidationError(str(error)) from error


def _one(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    return dict(value) if value is not None else None
