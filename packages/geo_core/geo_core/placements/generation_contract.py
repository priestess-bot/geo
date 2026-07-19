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
    content = properties.get("content_json") if isinstance(properties, Mapping) else None
    content_required = content.get("required") if isinstance(content, Mapping) else None
    content_properties = content.get("properties") if isinstance(content, Mapping) else None
    if not isinstance(content_required, list) or not {
        "required_disclosures",
        "expected_links",
    }.issubset(map(str, content_required)):
        raise PlacementRuleViolation(
            "output schema must require the publication verification arrays"
        )
    for field in ("required_disclosures", "expected_links"):
        contract = (
            content_properties.get(field)
            if isinstance(content_properties, Mapping)
            else None
        )
        if not isinstance(contract, Mapping) or contract.get("type") != "array":
            raise PlacementRuleViolation(
                "output schema publication verification fields must be arrays"
            )
        items = contract.get("items")
        if not isinstance(items, Mapping) or items.get("type") != "string":
            raise PlacementRuleViolation(
                "output schema publication verification entries must be strings"
            )
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
