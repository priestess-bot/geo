"""Claim inventory rules shared by package edit and review commands."""

from __future__ import annotations

from geo_core.placements.domain import PlacementRuleViolation
from geo_core.placements.ports import GeneratedClaim


def validate_edited_claims(claims: tuple[GeneratedClaim, ...]) -> None:
    if not claims:
        raise PlacementRuleViolation("edited package requires a complete claim inventory")
    texts: set[str] = set()
    for claim in claims:
        text = claim.text.strip()
        if not text or text in texts:
            raise PlacementRuleViolation("edited claim texts must be non-empty and unique")
        texts.add(text)
        if claim.kind not in {"factual", "comparative", "experience", "non_factual"}:
            raise PlacementRuleViolation("edited claim kind is invalid")
        if claim.support_status not in {
            "supported",
            "unsupported",
            "conflict",
            "not_required",
        }:
            raise PlacementRuleViolation("edited claim support status is invalid")
        if (
            claim.kind != "non_factual"
            and claim.support_status == "supported"
            and not claim.evidence_item_ids
        ):
            raise PlacementRuleViolation("a supported factual edited claim requires evidence")
