"""Validation of structured placement generation output."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from geo_core.placements.domain import PlacementRuleViolation
from geo_core.placements.ports import (
    GeneratedClaim,
    GeneratedPlacement,
    GenerationEvidenceScope,
)


def parse_generated_placement(
    output: Mapping[str, object], *, claim: GenerationEvidenceScope
) -> GeneratedPlacement:
    content_json = output.get("content_json")
    rendered_text = output.get("rendered_text")
    raw_claims = output.get("claims")
    raw_internal_refs = output.get("internal_evidence_refs")
    raw_public_refs = output.get("public_citation_refs")
    if not isinstance(content_json, Mapping):
        raise PlacementRuleViolation("model output content_json must be an object")
    if not isinstance(rendered_text, str) or not rendered_text.strip():
        raise PlacementRuleViolation("model output rendered_text is required")
    if not isinstance(raw_claims, list):
        raise PlacementRuleViolation("model output claims must be an array")
    internal_refs = _reference_ids(raw_internal_refs, label="internal evidence")
    public_refs = _reference_ids(raw_public_refs, label="public citation")
    allowed_evidence = set(claim.evidence_item_ids)
    if not set(internal_refs).issubset(allowed_evidence):
        raise PlacementRuleViolation("internal refs contain evidence outside the frozen pack")
    if not set(public_refs).issubset(set(claim.public_citation_item_ids)):
        raise PlacementRuleViolation("public citations contain non-disclosable evidence")
    claims: list[GeneratedClaim] = []
    for item in raw_claims:
        if not isinstance(item, Mapping):
            raise PlacementRuleViolation("each generated claim must be an object")
        text = item.get("text")
        kind = item.get("kind")
        status = item.get("support_status")
        raw_evidence = item.get("evidence_item_ids", [])
        if not isinstance(text, str) or not text.strip():
            raise PlacementRuleViolation("generated claim text is required")
        if kind not in {"factual", "comparative", "experience", "non_factual"}:
            raise PlacementRuleViolation("generated claim kind is invalid")
        if status not in {"supported", "unsupported", "conflict", "not_required"}:
            raise PlacementRuleViolation("generated claim support status is invalid")
        if not isinstance(raw_evidence, list):
            raise PlacementRuleViolation("generated claim evidence ids must be an array")
        try:
            evidence_ids = tuple(UUID(str(value)) for value in raw_evidence)
        except (TypeError, ValueError) as exc:
            raise PlacementRuleViolation("generated claim evidence id is invalid") from exc
        if not set(evidence_ids).issubset(allowed_evidence):
            raise PlacementRuleViolation("claim references evidence outside the frozen pack")
        if kind != "non_factual" and status == "supported" and not evidence_ids:
            raise PlacementRuleViolation("a supported factual claim requires evidence")
        claims.append(GeneratedClaim(text.strip(), str(kind), str(status), evidence_ids))
    enriched_content = {
        **dict(content_json),
        "internal_evidence_refs": [str(value) for value in internal_refs],
        "public_citation_refs": [str(value) for value in public_refs],
    }
    return GeneratedPlacement(
        enriched_content,
        rendered_text.strip(),
        tuple(claims),
        internal_refs,
        public_refs,
    )


def _reference_ids(value: object, *, label: str) -> tuple[UUID, ...]:
    if not isinstance(value, list):
        raise PlacementRuleViolation(f"model output {label} refs must be an array")
    try:
        return tuple(UUID(str(item)) for item in value)
    except (TypeError, ValueError) as exc:
        raise PlacementRuleViolation(f"model output {label} ref is invalid") from exc


def validate_output_schema(output: Mapping[str, object], schema: Mapping[str, object]) -> None:
    """Validate the stable top-level JSON contract without provider-specific libraries."""
    if schema.get("type") not in (None, "object"):
        raise PlacementRuleViolation("placement output schema must describe an object")
    required = schema.get("required", ())
    if not isinstance(required, list):
        raise PlacementRuleViolation("output schema required must be an array")
    missing = [str(name) for name in required if str(name) not in output]
    if missing:
        raise PlacementRuleViolation(f"model output misses schema fields: {', '.join(missing)}")
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise PlacementRuleViolation("output schema properties must be an object")
    types: dict[str, Any] = {
        "object": Mapping,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }
    for name, contract in properties.items():
        if name not in output or not isinstance(contract, Mapping):
            continue
        expected = contract.get("type")
        expected_type = types.get(str(expected))
        if expected_type is not None and not isinstance(output[name], expected_type):
            raise PlacementRuleViolation(f"model output field has wrong type: {name}")
