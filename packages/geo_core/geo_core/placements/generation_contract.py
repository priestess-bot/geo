"""Validation for the stable placement model output schema."""

from __future__ import annotations

from typing import Mapping

from geo_core.placements.domain import PlacementRuleViolation


def validate_generation_schema(schema: Mapping[str, object]) -> None:
    required_fields = {
        "content_json",
        "rendered_text",
        "claims",
        "internal_evidence_refs",
        "public_citation_refs",
    }
    required = schema.get("required")
    if not isinstance(required, list) or not required_fields.issubset(map(str, required)):
        raise PlacementRuleViolation(
            "output schema must require content, claims, and separate evidence/citation refs"
        )
    properties = schema.get("properties")
    claims = properties.get("claims") if isinstance(properties, Mapping) else None
    items = claims.get("items") if isinstance(claims, Mapping) else None
    claim_required = items.get("required") if isinstance(items, Mapping) else None
    if not isinstance(claim_required, list) or not {
        "text",
        "kind",
        "support_status",
        "evidence_item_ids",
    }.issubset(map(str, claim_required)):
        raise PlacementRuleViolation("output schema must require the complete claim contract")
