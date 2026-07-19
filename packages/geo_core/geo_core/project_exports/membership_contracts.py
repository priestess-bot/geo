"""Exact observation membership frozen with each statistics-v2 snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Sequence
from uuid import UUID

from geo_core.project_exports.errors import ProjectExportRuleViolation
from geo_core.project_exports.field_validation import (
    lineage_ids,
    positive_int,
    sha256,
    uuid_value,
)


@dataclass(frozen=True)
class MetricObservationMembershipExportRecord:
    snapshot_id: UUID
    project_id: UUID
    campaign_id: UUID
    protocol_id: UUID
    observation_id: UUID
    ordinal: int
    payload_hash: str

    def __post_init__(self) -> None:
        lineage_ids(self)
        uuid_value(self.snapshot_id, "membership snapshot_id")
        uuid_value(self.protocol_id, "membership protocol_id")
        uuid_value(self.observation_id, "membership observation_id")
        positive_int(self.ordinal, "membership ordinal")
        sha256(self.payload_hash, "membership payload_hash")


def observation_membership_hash(
    memberships: Sequence[MetricObservationMembershipExportRecord],
) -> str:
    ordered = sorted(memberships, key=lambda item: item.ordinal)
    payload = "".join(
        f"{item.ordinal}:{item.observation_id}:{item.payload_hash}\n" for item in ordered
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def validate_membership_order(
    memberships: Sequence[MetricObservationMembershipExportRecord],
) -> None:
    ordinals = [item.ordinal for item in memberships]
    if sorted(ordinals) != list(range(1, len(ordinals) + 1)):
        raise ProjectExportRuleViolation("membership ordinals must be contiguous from one")
    observation_ids = [item.observation_id for item in memberships]
    if len(set(observation_ids)) != len(observation_ids):
        raise ProjectExportRuleViolation("snapshot membership observations must be unique")
