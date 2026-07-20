"""Campaign ancestry and immutable Prompt Release contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from geo_core.placements.errors import (
    CampaignContextMismatch,
    PlacementConflict,
    PlacementRuleViolation,
)


@dataclass(frozen=True)
class CampaignScope:
    project_id: UUID
    campaign_id: UUID


class CampaignResourceKind(StrEnum):
    OPPORTUNITY = "opportunity"
    BRIEF_VERSION = "brief_version"
    EVIDENCE_ATTEMPT = "evidence_attempt"
    PROMPT_BUNDLE = "prompt_bundle"
    JOB = "job"
    PACKAGE = "package"
    PACKAGE_VERSION = "package_version"
    EXPORT = "export"
    PUBLICATION = "publication"
    SUBMISSION = "submission"
    MEASUREMENT_TASK = "measurement_task"
    SIMULATION = "simulation"


@dataclass(frozen=True)
class CampaignResourceContext:
    scope: CampaignScope
    kind: CampaignResourceKind
    resource_id: UUID
    opportunity_id: UUID
    destination_id: UUID


def assert_same_campaign_lineage(
    *contexts: CampaignResourceContext,
    require_same_opportunity: bool = True,
    require_same_destination: bool = True,
) -> CampaignResourceContext:
    if not contexts:
        raise PlacementRuleViolation("campaign lineage requires at least one resource")
    first = contexts[0]
    for context in contexts[1:]:
        if context.scope != first.scope:
            raise CampaignContextMismatch("resources do not belong to the expected Campaign")
        if require_same_opportunity and context.opportunity_id != first.opportunity_id:
            raise CampaignContextMismatch("resources do not belong to the same Opportunity")
        if require_same_destination and context.destination_id != first.destination_id:
            raise CampaignContextMismatch("resources do not belong to the same Destination task")
    return first


class PromptReleaseStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REVOKED = "revoked"


PROMPT_RELEASE_TRANSITIONS: Mapping[PromptReleaseStatus, Mapping[str, PromptReleaseStatus]] = {
    PromptReleaseStatus.DRAFT: MappingProxyType({"approve": PromptReleaseStatus.APPROVED}),
    PromptReleaseStatus.APPROVED: MappingProxyType({"revoke": PromptReleaseStatus.REVOKED}),
    PromptReleaseStatus.REVOKED: MappingProxyType({}),
}


def transition_prompt_release_status(*, status: str, command: str) -> PromptReleaseStatus:
    try:
        current = PromptReleaseStatus(status)
    except ValueError as exc:
        raise PlacementConflict(f"unknown Prompt Release status: {status}") from exc
    target = PROMPT_RELEASE_TRANSITIONS[current].get(command)
    if target is None:
        raise PlacementConflict(
            f"Prompt Release command {command!r} is not allowed from {current.value!r}"
        )
    return target


@dataclass(frozen=True)
class PromptReleaseState:
    id: UUID
    project_id: UUID
    template_release_id: UUID
    version: int
    previous_state_id: UUID | None
    status: PromptReleaseStatus
    acted_by: UUID
    acted_at: datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise PlacementRuleViolation("Prompt Release state version must be positive")
        if (self.version == 1) != (self.previous_state_id is None):
            raise PlacementRuleViolation("Prompt Release state history must be linear")
        if self.status == PromptReleaseStatus.REVOKED and not (self.reason or "").strip():
            raise PlacementRuleViolation("revoking a Prompt Release requires a reason")


class PromptReleaseBindingStatus(StrEnum):
    UNBOUND = "unbound"
    BOUND = "bound"


@dataclass(frozen=True)
class OpportunityPromptReleaseBinding:
    id: UUID
    project_id: UUID
    campaign_id: UUID
    opportunity_id: UUID
    destination_id: UUID
    binding_version: int
    previous_binding_id: UUID | None
    status: PromptReleaseBindingStatus
    changed_by: UUID | None
    changed_at: datetime
    template_release_id: UUID | None = None
    skill_key: str | None = None
    skill_version_id: UUID | None = None
    release_version: int | None = None
    release_hash: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.binding_version < 1:
            raise PlacementRuleViolation("Prompt binding version must be positive")
        if (self.binding_version == 1) != (self.previous_binding_id is None):
            raise PlacementRuleViolation("Prompt binding history must be linear")
        release_values = (
            self.template_release_id,
            self.skill_version_id,
            self.release_version,
            self.release_hash,
        )
        if self.status == PromptReleaseBindingStatus.BOUND:
            if any(value is None for value in release_values):
                raise PlacementRuleViolation("a bound Opportunity requires full Release identity")
            if not _is_sha256(self.release_hash):
                raise PlacementRuleViolation("Prompt binding Release hash must be SHA-256")
        elif any(value is not None for value in release_values):
            raise PlacementRuleViolation("an unbound Opportunity cannot carry Release identity")


STANDARD_PLACEMENT_CHANNELS: tuple[str, ...] = (
    "owned_site",
    "productreview",
    "youtube",
    "reddit",
    "amazon",
    "ozbargain",
    "tiktok",
    "instagram",
    "quora",
)


class ChannelReadinessReason(StrEnum):
    MISSING_OPPORTUNITY = "missing_opportunity"
    DUPLICATE_CHANNEL = "duplicate_channel"
    CAMPAIGN_OWNER_MISMATCH = "campaign_owner_mismatch"
    OPPORTUNITY_BLOCKED = "opportunity_blocked"
    OPPORTUNITY_NOT_GENERATION_READY = "opportunity_not_generation_ready"
    DESTINATION_POLICY_MISSING = "destination_policy_missing"
    DESTINATION_POLICY_NOT_APPROVED = "destination_policy_not_approved"
    PROMPT_BINDING_MISSING = "prompt_binding_missing"
    PROMPT_RELEASE_DRAFT = "prompt_release_draft"
    PROMPT_RELEASE_REVOKED = "prompt_release_revoked"
    BRIEF_MISSING = "brief_missing"
    EVIDENCE_PACK_MISSING = "evidence_pack_missing"
    EVIDENCE_PACK_NOT_READY = "evidence_pack_not_ready"
    EVIDENCE_ITEMS_MISSING = "evidence_items_missing"


@dataclass(frozen=True)
class ChannelReadiness:
    publication_channel: str
    ready: bool
    reasons: tuple[ChannelReadinessReason, ...]
    opportunity_id: UUID | None = None
    destination_id: UUID | None = None
    prompt_binding_id: UUID | None = None
    template_release_id: UUID | None = None
    release_version: int | None = None
    release_hash: str | None = None
    brief_version_id: UUID | None = None
    evidence_pack_attempt_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.publication_channel not in STANDARD_PLACEMENT_CHANNELS:
            raise PlacementRuleViolation("readiness channel is not a standard placement channel")
        if self.ready == bool(self.reasons):
            raise PlacementRuleViolation("readiness status and reason codes are inconsistent")


@dataclass(frozen=True)
class CampaignPlacementReadiness:
    project_id: UUID
    campaign_id: UUID
    channels: tuple[ChannelReadiness, ...]

    def __post_init__(self) -> None:
        actual = tuple(item.publication_channel for item in self.channels)
        if actual != STANDARD_PLACEMENT_CHANNELS:
            raise PlacementRuleViolation("Campaign readiness must contain all standard channels")

    @property
    def ready_count(self) -> int:
        return sum(item.ready for item in self.channels)

    @property
    def is_ready(self) -> bool:
        return self.ready_count == len(STANDARD_PLACEMENT_CHANNELS)


@dataclass(frozen=True)
class PromptReleaseView:
    id: UUID
    project_id: UUID
    skill_version_id: UUID
    release_number: int
    release_hash: str
    source_text: str
    system_template: str
    user_template: str
    variable_schema: Mapping[str, object]
    output_schema: Mapping[str, object]
    compiler_version: str
    skill_version: int = 1
    status: PromptReleaseStatus = PromptReleaseStatus.APPROVED
    state_version: int = 1
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    revoked_by: UUID | None = None
    revoked_at: datetime | None = None
    state_reason: str | None = None
    skill_key: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "variable_schema", MappingProxyType(dict(self.variable_schema)))
        object.__setattr__(self, "output_schema", MappingProxyType(dict(self.output_schema)))


@dataclass(frozen=True)
class PromptBundleView:
    id: UUID
    project_id: UUID
    brief_version_id: UUID
    evidence_pack_attempt_id: UUID
    template_release_id: UUID
    bundle_hash: str
    storage_key: str
    artifact_status: str
    storage_uri: str | None
    campaign_id: UUID | None = None
    opportunity_id: UUID | None = None
    destination_id: UUID | None = None
    prompt_release_binding_id: UUID | None = None
    prompt_release_binding_version: int | None = None
    skill_version_id: UUID | None = None
    release_version: int | None = None
    release_hash: str | None = None

    def __post_init__(self) -> None:
        lineage = (
            self.prompt_release_binding_id,
            self.prompt_release_binding_version,
        )
        if any(value is None for value in lineage) and not all(value is None for value in lineage):
            raise ValueError("Prompt Bundle binding lineage must be exact or legacy")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
