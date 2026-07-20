"""Exact observation-membership verification for F027 metric snapshots."""

from __future__ import annotations

from dataclasses import fields
import hashlib
from typing import Mapping, cast
from uuid import UUID

from geo_core.project_exports.constants import PROJECT_EXPORT_SCHEMA_VERSION
from geo_core.project_exports.errors import ProjectExportVerificationError
from geo_core.project_exports.membership_contracts import (
    MetricObservationMembershipExportRecord,
)


def verify_metric_memberships(
    snapshot: Mapping[str, object],
    *,
    observations_by_id: Mapping[str, Mapping[str, object]],
    project_id: str,
    campaign_id: object,
) -> list[dict[str, object]]:
    has_membership = snapshot["observation_membership_version"] is not None
    if has_membership:
        memberships = _object_list(
            snapshot["observation_memberships"],
            "metric observation memberships",
        )
    else:
        if (
            snapshot["observation_membership_count"] is not None
            or snapshot["observation_membership_hash"] is not None
            or snapshot["observation_memberships"] is not None
        ):
            raise ProjectExportVerificationError(
                "historical metric observation membership must be entirely null"
            )
        return []
    ordinals = [_integer(item["ordinal"], "membership ordinal") for item in memberships]
    if ordinals != list(range(1, len(memberships) + 1)):
        raise ProjectExportVerificationError(
            "metric observation membership ordinals must be contiguous from one"
        )
    observation_ids: list[str] = []
    hash_payload = ""
    for membership in memberships:
        _verify_membership_shape(
            membership,
            project_id=project_id,
            campaign_id=campaign_id,
        )
        if membership["snapshot_id"] != snapshot["id"]:
            raise ProjectExportVerificationError(
                "metric observation membership crosses snapshot lineage"
            )
        observation_id = _uuid_text(membership["observation_id"], "membership observation id")
        observation_ids.append(observation_id)
        try:
            observation = observations_by_id[observation_id]
        except KeyError as exc:
            raise ProjectExportVerificationError(
                "metric observation membership references a missing observation"
            ) from exc
        payload_hash = _sha_text(membership["payload_hash"], "membership payload hash")
        if payload_hash != observation["payload_hash"]:
            raise ProjectExportVerificationError(
                "metric observation membership payload hash differs from observation"
            )
        if membership["protocol_id"] != snapshot["protocol_id"]:
            raise ProjectExportVerificationError(
                "metric observation membership crosses protocol lineage"
            )
        hash_payload += f"{membership['ordinal']}:{observation_id}:{payload_hash}\n"
    if len(set(observation_ids)) != len(observation_ids):
        raise ProjectExportVerificationError(
            "metric observation membership observations must be unique"
        )
    if _integer(
        snapshot["observation_membership_count"],
        "observation membership count",
    ) != len(memberships):
        raise ProjectExportVerificationError(
            "metric observation membership count differs from nested rows"
        )
    expected_hash = hashlib.sha256(hash_payload.encode("ascii")).hexdigest()
    if snapshot["observation_membership_hash"] != expected_hash:
        raise ProjectExportVerificationError(
            "metric observation membership hash differs from nested rows"
        )
    return memberships


def _verify_membership_shape(
    value: Mapping[str, object], *, project_id: str, campaign_id: object
) -> None:
    expected = {field.name for field in fields(MetricObservationMembershipExportRecord)} | {
        "schema_version"
    }
    if set(value) != expected:
        raise ProjectExportVerificationError(
            "metric observation membership does not match the public field whitelist"
        )
    if value["schema_version"] != PROJECT_EXPORT_SCHEMA_VERSION:
        raise ProjectExportVerificationError(
            "metric observation membership schema version mismatch"
        )
    if value["project_id"] != project_id or (
        campaign_id is not None and value["campaign_id"] != campaign_id
    ):
        raise ProjectExportVerificationError(
            "metric observation membership crosses project or campaign scope"
        )


def _object_list(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ProjectExportVerificationError(f"{label} must be a JSON array")
    if not all(
        isinstance(item, dict) and all(isinstance(key, str) for key in item) for item in value
    ):
        raise ProjectExportVerificationError(f"{label} must contain JSON objects")
    return cast(list[dict[str, object]], value)


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProjectExportVerificationError(f"{label} must be an integer")
    return value


def _uuid_text(value: object, label: str) -> str:
    result = _text(value, label)
    try:
        parsed = UUID(result)
    except ValueError as exc:
        raise ProjectExportVerificationError(f"{label} must be a UUID") from exc
    if str(parsed) != result:
        raise ProjectExportVerificationError(f"{label} must be a canonical UUID")
    return result


def _sha_text(value: object, label: str) -> str:
    result = _text(value, label)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ProjectExportVerificationError(f"{label} must be a lowercase SHA-256")
    return result


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectExportVerificationError(f"{label} must be non-empty text")
    return value
