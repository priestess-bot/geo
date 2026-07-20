"""Strict Internal API contracts for Project Catalog and Evidence governance."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CatalogContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProjectRequest(CatalogContract):
    name: str = Field(min_length=1, max_length=200)


class UpdateProjectRequest(CatalogContract):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "paused", "archived"] | None = None

    @model_validator(mode="after")
    def has_change(self) -> "UpdateProjectRequest":
        if self.name is None and self.status is None:
            raise ValueError("project update requires name or status")
        return self


class CatalogProjectResponse(CatalogContract):
    id: UUID
    tenant_id: UUID
    name: str
    status: str
    created_at: datetime
    updated_at: datetime


class CreateEntityRequest(CatalogContract):
    entity_type: Literal["brand", "product", "competitor", "market"]
    canonical_name: str = Field(min_length=1, max_length=300)
    canonical_url: str | None = Field(default=None, max_length=2000)
    attributes: dict[str, object] = Field(default_factory=dict)


class EntityResponse(CatalogContract):
    id: UUID
    project_id: UUID
    entity_type: Literal["brand", "product", "competitor", "market"]
    canonical_name: str
    canonical_url: str | None
    attributes: dict[str, object]
    status: str
    created_at: datetime


class CreateMarketProfileRequest(CatalogContract):
    market_code: str = Field(pattern=r"^[A-Za-z]{2}$")
    locale: str = Field(min_length=1, max_length=80)
    timezone: str = Field(min_length=1, max_length=100)
    rules: dict[str, object] = Field(default_factory=dict)


class MarketProfileResponse(CatalogContract):
    id: UUID
    project_id: UUID
    market_code: str
    locale: str
    timezone: str
    rules: dict[str, object]
    status: str
    created_at: datetime


class TextEvidenceSnapshot(CatalogContract):
    kind: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=32768)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MinioEvidenceSnapshot(CatalogContract):
    kind: Literal["minio"] = "minio"
    uri: str = Field(pattern=r"^s3://[a-z0-9][a-z0-9.-]{2,62}/[^\s]+$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


EvidenceSnapshotRequest = Annotated[
    TextEvidenceSnapshot | MinioEvidenceSnapshot, Field(discriminator="kind")
]


class SourceRevisionRequest(CatalogContract):
    kind: Literal["row_version", "content_hash", "report_version"]
    value: str = Field(min_length=1, max_length=300)


class PublicCitationRequest(CatalogContract):
    disclosure_allowed: bool = False
    source_url: str | None = Field(default=None, max_length=2000)
    source_title: str | None = Field(default=None, max_length=500)
    label: str | None = Field(default=None, max_length=200)
    quotation_allowed: bool = False
    attribution_required: bool = False


class CreateEvidenceRequest(CatalogContract):
    item_type: Literal[
        "chunk",
        "citation",
        "report_extract",
        "source_asset",
        "consumer_experience",
    ]
    source_id: UUID
    subject_entity_id: UUID | None = None
    subject_role: Literal["primary_brand", "competitor", "market", "product", "neutral"]
    locator: dict[str, object] = Field(default_factory=dict)
    snapshot: EvidenceSnapshotRequest
    source_revision: SourceRevisionRequest
    usage_rights: Literal[
        "owned",
        "licensed",
        "public_reference",
        "authorised_experience",
        "restricted",
        "unknown",
    ]
    confidentiality: Literal["public", "internal", "confidential", "restricted"]
    public_citation: PublicCitationRequest = Field(default_factory=PublicCitationRequest)


class EvidenceSnapshotResponse(CatalogContract):
    kind: Literal["text", "minio"]
    text: str | None = None
    uri: str | None = None
    sha256: str


class SourceRevisionResponse(CatalogContract):
    kind: str
    value: str


class PublicCitationResponse(CatalogContract):
    disclosure_allowed: bool
    source_url: str | None
    source_title: str | None
    label: str | None
    quotation_allowed: bool
    attribution_required: bool


class EvidenceResponse(CatalogContract):
    id: UUID
    project_id: UUID
    item_type: str
    source_id: UUID
    subject_entity_id: UUID | None
    subject_role: str
    locator: dict[str, object]
    snapshot: EvidenceSnapshotResponse
    source_revision: SourceRevisionResponse
    usage_rights: str
    confidentiality: str
    public_citation: PublicCitationResponse
    eligible_for_generation: bool
    eligible_for_publication: bool
    created_at: datetime


class DevelopmentBootstrapRequest(CatalogContract):
    tenant_name: str = Field(min_length=1, max_length=200)
    identity_subject: str = Field(min_length=1, max_length=300)
    identity_email: str | None = Field(default=None, max_length=320)
    project_name: str = Field(min_length=1, max_length=200)


class DevelopmentBootstrapResponse(CatalogContract):
    tenant_id: UUID
    identity_id: UUID
    project: CatalogProjectResponse
