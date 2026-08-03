"""Strict API contracts for Knowledge Fact Evidence promotion."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KnowledgeEvidenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FactEvidencePublicCitationRequest(KnowledgeEvidenceContract):
    disclosure_allowed: bool = False
    source_url: str | None = Field(default=None, max_length=2000)
    source_title: str | None = Field(default=None, max_length=500)
    label: str | None = Field(default=None, max_length=200)
    quotation_allowed: bool = False
    attribution_required: bool = False


class PromoteFactEvidenceRequest(KnowledgeEvidenceContract):
    title: str = Field(min_length=1, max_length=500)
    subject_entity_id: UUID | None = None
    subject_role: Literal["primary_brand", "competitor", "market", "product", "neutral"]
    usage_rights: Literal["owned", "licensed", "public_reference"]
    confidentiality: Literal["public", "internal", "confidential"]
    public_citation: FactEvidencePublicCitationRequest = Field(
        default_factory=FactEvidencePublicCitationRequest
    )

    @model_validator(mode="after")
    def subject_contract(self) -> "PromoteFactEvidenceRequest":
        if (self.subject_role == "neutral") != (self.subject_entity_id is None):
            raise ValueError(
                "neutral Evidence cannot bind an entity; other roles require an entity"
            )
        return self


class KnowledgeFactView(KnowledgeEvidenceContract):
    id: UUID
    status: str
    lifecycle_status: str
    extractor_release: str
    statement: str
    statement_hash: str
    reviewed_by: UUID | None
    reviewed_at: datetime | None


class KnowledgeSourceView(KnowledgeEvidenceContract):
    id: UUID
    title: str
    source_kind: str
    source_url: str | None
    status: str
    content_hash: str | None


class KnowledgeDocumentView(KnowledgeEvidenceContract):
    id: UUID
    parser_version: str
    cleaned_text_hash: str


class KnowledgeChunkView(KnowledgeEvidenceContract):
    id: UUID
    chunk_index: int
    text: str
    text_hash: str
    status: str


class FactEvidenceDefaultsView(KnowledgeEvidenceContract):
    title: str
    source_url: str | None
    source_title: str
    citation_label: str


class FactEvidenceLineageView(KnowledgeEvidenceContract):
    project_id: UUID
    pipeline_run_id: UUID
    knowledge_source_id: UUID
    knowledge_document_id: UUID
    knowledge_chunk_id: UUID
    knowledge_fact_id: UUID
    evidence_item_id: UUID
    evidence_title: str
    promoted_by: UUID
    promoted_at: datetime
    idempotency_key: str
    promotion_request_hash: str
    lineage_contract_version: Literal[
        "legacy-relational-v1", "knowledge-fact-evidence-v1"
    ]
    source_content_hash: str
    document_cleaned_text_hash: str
    chunk_text_hash: str
    fact_statement_hash: str
    evidence_snapshot_hash: str


class FactEvidenceSnapshotView(KnowledgeEvidenceContract):
    kind: Literal["text", "minio"]
    text: str | None
    uri: str | None
    sha256: str


class FactEvidenceSourceRevisionView(KnowledgeEvidenceContract):
    kind: str
    value: str


class FactEvidencePublicCitationView(KnowledgeEvidenceContract):
    disclosure_allowed: bool
    source_url: str | None
    source_title: str | None
    label: str | None
    quotation_allowed: bool
    attribution_required: bool


class PromotedEvidenceView(KnowledgeEvidenceContract):
    id: UUID
    project_id: UUID
    title: str
    item_type: Literal["approved_fact"]
    subject_entity_id: UUID | None
    subject_role: str
    snapshot: FactEvidenceSnapshotView
    source_revision: FactEvidenceSourceRevisionView
    usage_rights: str
    confidentiality: str
    public_citation: FactEvidencePublicCitationView
    eligible_for_generation: bool
    eligible_for_publication: bool
    created_at: datetime


class ExistingFactEvidenceView(KnowledgeEvidenceContract):
    evidence: PromotedEvidenceView
    lineage: FactEvidenceLineageView


class FactEvidenceProposalResponse(KnowledgeEvidenceContract):
    project_id: UUID
    promotable: bool
    blockers: list[str]
    fact: KnowledgeFactView
    source: KnowledgeSourceView
    document: KnowledgeDocumentView
    chunk: KnowledgeChunkView
    existing: ExistingFactEvidenceView | None
    defaults: FactEvidenceDefaultsView


class FactEvidencePromotionResponse(KnowledgeEvidenceContract):
    outcome: Literal["created", "existing"]
    evidence: PromotedEvidenceView
    lineage: FactEvidenceLineageView
