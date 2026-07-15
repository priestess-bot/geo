"""Framework-independent Catalog and Evidence governance rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import re
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from geo_core.access.models import AccessPrincipal


CONTRIBUTOR_ROLES = frozenset({"owner", "admin", "analyst"})
PROJECT_ADMIN_ROLES = frozenset({"owner", "admin"})
READER_ROLES = frozenset({"owner", "admin", "analyst", "viewer", "customer"})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
S3_URI_PATTERN = re.compile(r"^s3://[a-z0-9][a-z0-9.-]{2,62}/[^\s]+$")
MAX_TEXT_SNAPSHOT_BYTES = 32 * 1024


class CatalogError(RuntimeError):
    """Base class for errors safe to map at the API boundary."""


class CatalogRuleViolation(CatalogError, ValueError):
    """A command violates a deterministic catalog invariant."""


class CatalogForbidden(CatalogError):
    """The authenticated principal lacks the required project role."""


class CatalogNotFound(CatalogError):
    """A scoped project resource does not exist."""


class CatalogConflict(CatalogError):
    """A unique catalog identity or source revision already exists."""


class CatalogPersistenceUnavailable(CatalogError):
    """PostgreSQL could not complete a Catalog transaction."""


class EntityType(StrEnum):
    BRAND = "brand"
    PRODUCT = "product"
    COMPETITOR = "competitor"
    MARKET = "market"


class SubjectRole(StrEnum):
    PRIMARY_BRAND = "primary_brand"
    PRODUCT = "product"
    COMPETITOR = "competitor"
    MARKET = "market"
    NEUTRAL = "neutral"


class UsageRights(StrEnum):
    OWNED = "owned"
    LICENSED = "licensed"
    PUBLIC_REFERENCE = "public_reference"
    AUTHORISED_EXPERIENCE = "authorised_experience"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class Confidentiality(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class EvidenceItemType(StrEnum):
    APPROVED_FACT = "approved_fact"
    CHUNK = "chunk"
    CITATION = "citation"
    REPORT_EXTRACT = "report_extract"
    SOURCE_ASSET = "source_asset"
    CONSUMER_EXPERIENCE = "consumer_experience"


@dataclass(frozen=True)
class Project:
    id: UUID
    tenant_id: UUID
    name: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ProductEntity:
    id: UUID
    project_id: UUID
    entity_type: EntityType
    canonical_name: str
    canonical_url: str | None
    attributes: Mapping[str, object]
    status: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))


@dataclass(frozen=True)
class MarketProfile:
    id: UUID
    project_id: UUID
    market_code: str
    locale: str
    timezone: str
    rules: Mapping[str, object]
    status: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "rules", MappingProxyType(dict(self.rules)))


@dataclass(frozen=True)
class EvidenceSnapshot:
    text: str | None
    uri: str | None
    sha256: str

    def __post_init__(self) -> None:
        if (self.text is None) == (self.uri is None):
            raise CatalogRuleViolation("evidence snapshot requires exactly one of text or URI")
        if not SHA256_PATTERN.fullmatch(self.sha256):
            raise CatalogRuleViolation("evidence snapshot hash must be lowercase SHA-256")
        if self.text is not None:
            encoded = self.text.encode("utf-8")
            if not self.text.strip() or len(encoded) > MAX_TEXT_SNAPSHOT_BYTES:
                raise CatalogRuleViolation("text evidence must be non-empty and at most 32 KiB")
            if hashlib.sha256(encoded).hexdigest() != self.sha256:
                raise CatalogRuleViolation("text evidence hash does not match its snapshot")
        if self.uri is not None and not S3_URI_PATTERN.fullmatch(self.uri):
            raise CatalogRuleViolation("long evidence snapshots require an s3:// MinIO URI")


@dataclass(frozen=True)
class PublicCitation:
    disclosure_allowed: bool
    source_url: str | None = None
    source_title: str | None = None
    label: str | None = None
    quotation_allowed: bool = False
    attribution_required: bool = False


@dataclass(frozen=True)
class EvidenceDraft:
    item_type: EvidenceItemType
    source_id: UUID
    subject_entity_id: UUID | None
    subject_role: SubjectRole
    locator: Mapping[str, object]
    snapshot: EvidenceSnapshot
    source_revision_kind: str
    source_revision_value: str
    usage_rights: UsageRights
    confidentiality: Confidentiality
    public_citation: PublicCitation

    def __post_init__(self) -> None:
        object.__setattr__(self, "locator", MappingProxyType(dict(self.locator)))
        if not self.source_revision_value.strip():
            raise CatalogRuleViolation("source revision value is required")
        if self.source_revision_kind not in {"row_version", "content_hash", "report_version"}:
            raise CatalogRuleViolation("source revision kind is unsupported")
        if self.subject_role == SubjectRole.NEUTRAL and self.subject_entity_id is not None:
            raise CatalogRuleViolation("neutral evidence must not bind a subject entity")
        if self.subject_role != SubjectRole.NEUTRAL and self.subject_entity_id is None:
            raise CatalogRuleViolation("non-neutral evidence requires a subject entity")
        if (
            self.item_type == EvidenceItemType.CONSUMER_EXPERIENCE
            and self.usage_rights != UsageRights.AUTHORISED_EXPERIENCE
        ):
            raise CatalogRuleViolation("consumer experience requires authorised usage rights")
        citation = self.public_citation
        if citation.disclosure_allowed:
            eligible_rights = self.usage_rights not in {
                UsageRights.UNKNOWN,
                UsageRights.RESTRICTED,
            }
            if not eligible_rights or self.confidentiality != Confidentiality.PUBLIC:
                raise CatalogRuleViolation(
                    "public disclosure requires eligible rights and public confidentiality"
                )
            if not all(
                value and value.strip()
                for value in (citation.source_url, citation.source_title, citation.label)
            ):
                raise CatalogRuleViolation("public citation URL, title and label are required")
            if not str(citation.source_url).startswith(("https://", "http://")):
                raise CatalogRuleViolation("public citation URL must use HTTP or HTTPS")


@dataclass(frozen=True)
class EvidenceItem:
    id: UUID
    project_id: UUID
    draft: EvidenceDraft
    created_at: datetime

    @property
    def eligible_for_generation(self) -> bool:
        return self.draft.usage_rights not in {
            UsageRights.UNKNOWN,
            UsageRights.RESTRICTED,
        } and self.draft.confidentiality != Confidentiality.RESTRICTED

    @property
    def eligible_for_publication(self) -> bool:
        return (
            self.eligible_for_generation
            and self.draft.confidentiality == Confidentiality.PUBLIC
            and self.draft.public_citation.disclosure_allowed
        )


@dataclass(frozen=True)
class BootstrapResult:
    tenant_id: UUID
    identity_id: UUID
    project: Project


def require_project_role(
    principal: AccessPrincipal, project_id: UUID, *, allowed: frozenset[str]
) -> str:
    for membership in principal.memberships:
        if membership.project_id == project_id and membership.tenant_id == principal.tenant_id:
            if membership.role not in allowed:
                raise CatalogForbidden("The project role cannot perform this operation.")
            return membership.role
    raise CatalogNotFound("The requested project does not exist in the authenticated scope.")


def require_tenant_project_admin(principal: AccessPrincipal) -> None:
    if not any(
        membership.tenant_id == principal.tenant_id
        and membership.role in PROJECT_ADMIN_ROLES
        for membership in principal.memberships
    ):
        raise CatalogForbidden(
            "Creating a project requires an existing owner or admin role in the tenant."
        )


def validate_subject_type(*, role: SubjectRole, entity_type: EntityType) -> None:
    expected = {
        SubjectRole.PRIMARY_BRAND: EntityType.BRAND,
        SubjectRole.PRODUCT: EntityType.PRODUCT,
        SubjectRole.COMPETITOR: EntityType.COMPETITOR,
        SubjectRole.MARKET: EntityType.MARKET,
    }
    if role != SubjectRole.NEUTRAL and expected[role] != entity_type:
        raise CatalogRuleViolation("evidence subject role does not match the entity type")
