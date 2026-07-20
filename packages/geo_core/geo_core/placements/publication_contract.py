"""Strict frozen inputs for public URL verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from geo_core.placements.domain import PlacementRuleViolation


@dataclass(frozen=True)
class PublicationVerificationContract:
    required_disclosures: tuple[str, ...]
    expected_links: tuple[str, ...]


def parse_publication_verification_contract(
    content_json: Mapping[str, object],
    *,
    disclosure_required: bool,
) -> PublicationVerificationContract:
    required_disclosures = _explicit_string_array(
        content_json, key="required_disclosures"
    )
    expected_links = _explicit_string_array(content_json, key="expected_links")
    if disclosure_required and not required_disclosures:
        raise PlacementRuleViolation(
            "frozen Destination policy requires at least one required disclosure"
        )
    return PublicationVerificationContract(required_disclosures, expected_links)


def parse_frozen_publication_verification_contract(
    content_json: Mapping[str, object],
    prompt_bundle: Mapping[str, object],
) -> PublicationVerificationContract:
    manifest = prompt_bundle.get("manifest")
    if not isinstance(manifest, Mapping) or manifest.get("schema") != "geo-prompt-bundle-v3":
        raise PlacementRuleViolation(
            "publication requires a current frozen Prompt Bundle manifest"
        )
    authoritative = manifest.get("authoritative")
    destination_policy = (
        authoritative.get("destination_policy")
        if isinstance(authoritative, Mapping)
        else None
    )
    disclosure_requirements = (
        destination_policy.get("disclosure_requirements")
        if isinstance(destination_policy, Mapping)
        else None
    )
    if not isinstance(disclosure_requirements, Mapping):
        raise PlacementRuleViolation(
            "frozen Prompt Bundle has no disclosure requirements contract"
        )
    return parse_publication_verification_contract(
        content_json,
        disclosure_required=_requirements_are_mandatory(disclosure_requirements),
    )


def _explicit_string_array(
    content_json: Mapping[str, object], *, key: str
) -> tuple[str, ...]:
    value = content_json.get(key)
    if not isinstance(value, list):
        raise PlacementRuleViolation(f"content_json.{key} must be an explicit string array")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PlacementRuleViolation(
                f"content_json.{key} entries must be non-empty strings"
            )
        normalized.append(item.strip())
    return tuple(normalized)


def _requirements_are_mandatory(requirements: Mapping[str, object]) -> bool:
    return any(_mandatory_marker(value) for value in requirements.values())


def _mandatory_marker(value: object) -> bool:
    if value is None or value is False:
        return False
    if value is True:
        return True
    if isinstance(value, str):
        marker = value.strip().casefold().replace("-", "_").replace(" ", "_")
        if marker in {"", "false", "none", "optional", "not_required"}:
            return False
        if marker in {"true", "yes", "required", "must", "mandatory"}:
            return True
        raise PlacementRuleViolation(
            "frozen disclosure requirements contain an unsupported requirement marker"
        )
    if isinstance(value, Mapping):
        return any(_mandatory_marker(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_mandatory_marker(item) for item in value)
    raise PlacementRuleViolation(
        "frozen disclosure requirements contain a malformed requirement marker"
    )
