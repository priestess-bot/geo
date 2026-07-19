"""Persistence helpers for governed Knowledge Fact Evidence."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from geo_core.catalog.domain import EvidenceDraft


def insert_evidence(
    connection: Any,
    *,
    evidence_id: UUID,
    project_id: UUID,
    draft: EvidenceDraft,
) -> None:
    citation = draft.public_citation
    connection.execute(
        """INSERT INTO evidence_items (
             id, project_id, item_type, source_id, subject_entity_id, subject_role,
             locator, snapshot_text, snapshot_uri, snapshot_hash,
             source_revision_kind, source_revision_value, usage_rights,
             confidentiality, public_disclosure_allowed, public_source_url,
             public_source_title, citation_label, quotation_allowed,
             attribution_required, fact_lineage_status
           ) VALUES (
             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
           )""",
        (
            evidence_id,
            project_id,
            draft.item_type.value,
            draft.source_id,
            draft.subject_entity_id,
            draft.subject_role.value,
            Jsonb({}),
            draft.snapshot.text,
            draft.snapshot.uri,
            draft.snapshot.sha256,
            draft.source_revision_kind,
            draft.source_revision_value,
            draft.usage_rights.value,
            draft.confidentiality.value,
            citation.disclosure_allowed,
            citation.source_url,
            citation.source_title,
            citation.label,
            citation.quotation_allowed,
            citation.attribution_required,
            "verified",
        ),
    )
