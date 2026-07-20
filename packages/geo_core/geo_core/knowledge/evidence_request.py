"""Canonical client-controlled metadata for Fact Evidence promotion."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from geo_core.catalog.domain import (
    Confidentiality,
    PublicCitation,
    SubjectRole,
    UsageRights,
)
from geo_core.knowledge.domain import KnowledgeValidationError


def promotion_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 200:
        raise KnowledgeValidationError("Idempotency-Key must contain 1 to 200 characters")
    return normalized


def normalize_citation(citation: PublicCitation) -> PublicCitation:
    return PublicCitation(
        disclosure_allowed=citation.disclosure_allowed,
        source_url=_optional_text(citation.source_url),
        source_title=_optional_text(citation.source_title),
        label=_optional_text(citation.label),
        quotation_allowed=citation.quotation_allowed,
        attribution_required=citation.attribution_required,
    )


def promotion_request_hash(
    *,
    project_id: UUID,
    fact_id: UUID,
    title: str,
    subject_entity_id: UUID | None,
    subject_role: SubjectRole,
    usage_rights: UsageRights,
    confidentiality: Confidentiality,
    public_citation: PublicCitation,
) -> str:
    payload = {
        "project_id": str(project_id),
        "fact_id": str(fact_id),
        "title": title,
        "subject_entity_id": str(subject_entity_id) if subject_entity_id else None,
        "subject_role": subject_role.value,
        "usage_rights": usage_rights.value,
        "confidentiality": confidentiality.value,
        "public_citation": {
            "disclosure_allowed": public_citation.disclosure_allowed,
            "source_url": public_citation.source_url,
            "source_title": public_citation.source_title,
            "label": public_citation.label,
            "quotation_allowed": public_citation.quotation_allowed,
            "attribution_required": public_citation.attribution_required,
        },
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _optional_text(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    return normalized or None
