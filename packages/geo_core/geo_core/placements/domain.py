"""Pure placement domain rules.

Export, delivery and publication are intentionally separate concepts. Package
content is immutable; edits always create a new lineage node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType
from typing import Mapping
from uuid import UUID


class PlacementRuleViolation(ValueError):
    """A placement command violates an explicit business invariant."""


class ConcurrencyConflict(RuntimeError):
    """The caller edited a stale immutable version."""


class PlacementConflict(RuntimeError):
    """The command conflicts with the aggregate's current state."""


class PlacementNotFound(RuntimeError):
    """A project-scoped placement resource does not exist."""


class WorkflowStatus(StrEnum):
    GENERATED = "generated"
    QA_RUNNING = "qa_running"
    PENDING_HUMAN_REVIEW = "pending_human_review"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class AuthenticityRisk(StrEnum):
    SYNTHETIC_TESTIMONIAL = "synthetic_testimonial"
    FAKE_PERSONA = "fake_persona"
    UNSUPPORTED_FIRST_PERSON_EXPERIENCE = "unsupported_first_person_experience"
    HIDDEN_COMMERCIAL_RELATIONSHIP = "hidden_commercial_relationship"


HARD_AUTHENTICITY_BLOCKS: frozenset[AuthenticityRisk] = frozenset(AuthenticityRisk)


@dataclass(frozen=True)
class ConsumerExperience:
    description: str
    source: str
    usage_rights: str
    disclosure: str

    def __post_init__(self) -> None:
        values = (self.description, self.source, self.usage_rights, self.disclosure)
        if any(not value.strip() for value in values):
            raise PlacementRuleViolation(
                "consumer experience requires description, source, usage rights and disclosure"
            )


@dataclass(frozen=True)
class Campaign:
    id: UUID
    project_id: UUID
    market_profile_id: UUID
    primary_product_entity_id: UUID
    name: str
    objective: str
    status: str = "draft"


@dataclass(frozen=True)
class MonitoringQuery:
    id: UUID
    project_id: UUID
    market_profile_id: UUID
    query_text: str
    query_kind: str
    locale: str
    status: str = "active"


@dataclass(frozen=True)
class Destination:
    id: UUID
    project_id: UUID
    publication_channel: str
    destination_key: str
    operation_mode: str = "manual"
    destination_account_id: str | None = None
    canonical_url: str | None = None
    canonical_host: str = ""
    allowed_hosts: tuple[str, ...] = ()
    policy_status: str = "unreviewed"


@dataclass(frozen=True)
class DestinationPolicyVersion:
    id: UUID
    project_id: UUID
    destination_id: UUID
    version_number: int
    status: str
    rules: Mapping[str, object]
    identity_requirements: Mapping[str, object]
    disclosure_requirements: Mapping[str, object]
    allowed_hosts: tuple[str, ...]
    reviewed_by: UUID
    reviewed_at: datetime


@dataclass(frozen=True)
class Opportunity:
    id: UUID
    project_id: UUID
    campaign_id: UUID
    destination_id: UUID
    opportunity_ref: str
    rationale: str
    status: str = "identified"


@dataclass(frozen=True)
class BriefVersion:
    id: UUID
    project_id: UUID
    brief_id: UUID
    version_number: int
    goals: Mapping[str, object]
    constraints: Mapping[str, object]
    content_hash: str
    base_version_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "goals", MappingProxyType(dict(self.goals)))
        object.__setattr__(self, "constraints", MappingProxyType(dict(self.constraints)))


@dataclass(frozen=True)
class EvidencePackAttempt:
    id: UUID
    project_id: UUID
    brief_version_id: UUID
    attempt_number: int
    status: str = "building"
    pack_hash: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class PromptSkill:
    id: UUID
    project_id: UUID
    skill_key: str
    status: str = "active"


@dataclass(frozen=True)
class PromptReleaseView:
    id: UUID
    project_id: UUID
    skill_version_id: UUID
    release_number: int
    release_hash: str


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


@dataclass(frozen=True)
class JobReference:
    id: UUID
    project_id: UUID
    kind: str
    status: str


@dataclass(frozen=True)
class Claim:
    id: UUID
    project_id: UUID
    package_version_id: UUID
    claim_text: str
    claim_kind: str
    support_status: str
    evidence_item_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class PackageVersion:
    id: UUID
    project_id: UUID
    package_id: UUID
    prompt_bundle_id: UUID
    version_number: int
    content_json: Mapping[str, object]
    rendered_text: str
    content_hash: str
    workflow_status: WorkflowStatus = WorkflowStatus.GENERATED
    base_version_id: UUID | None = None
    edited_by: UUID | None = None
    edit_reason: str | None = None
    generated_by_job_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_json", MappingProxyType(dict(self.content_json)))


@dataclass(frozen=True)
class Review:
    id: UUID
    project_id: UUID
    package_version_id: UUID
    submitted_for_review_by: UUID
    reviewer_id: UUID
    decision: str
    claim_inventory_complete: bool
    extracted_claim_support_confirmed: bool
    score: float | None = None
    notes: str | None = None
    reviewed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.submitted_for_review_by == self.reviewer_id:
            raise PlacementRuleViolation("review submitter and reviewer must differ")
        if self.decision == "approved" and not (
            self.claim_inventory_complete and self.extracted_claim_support_confirmed
        ):
            raise PlacementRuleViolation("approval requires both claim review gates")
        if self.decision == "approved" and (self.score is None or self.score < 85):
            raise PlacementRuleViolation("approval requires a review score of at least 85")


@dataclass(frozen=True)
class ReviewSubmission:
    id: UUID
    project_id: UUID
    package_version_id: UUID
    submitted_by: UUID
    submitted_at: datetime


@dataclass(frozen=True)
class ExportReceipt:
    id: UUID
    project_id: UUID
    package_version_id: UUID
    content_hash: str
    exported_at: datetime
    export_format: str
    requested_by: UUID
    artifact_status: str
    storage_key: str
    artifact_uri: str | None
    package_version: PackageVersion
    claims: tuple[Claim, ...]


@dataclass(frozen=True)
class PublicationRequest:
    id: UUID
    project_id: UUID
    package_version_id: UUID
    destination_id: UUID
    publication_channel: str
    destination_key: str
    publication_attempt: int
    idempotency_key: str
    restricted_policy_acknowledged: bool = False
    policy_basis: str | None = None
    status: str = "requested"


@dataclass(frozen=True)
class Submission:
    id: UUID
    project_id: UUID
    publication_request_id: UUID
    status: str
    submitted_url: str | None = None
    provider_submission_id: str | None = None
    verification_result: Mapping[str, object] | None = None
    url_backfilled_by: UUID | None = None
    url_backfilled_at: datetime | None = None


@dataclass(frozen=True)
class Measurement:
    id: UUID
    project_id: UUID
    submission_id: UUID
    monitoring_query_id: UUID
    measured_at: datetime
    citation_present: bool
    result_snapshot_uri: str
    recommendation_position: int | None = None
    metrics: Mapping[str, object] = field(default_factory=dict)


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def validate_authenticity(
    *,
    experience: ConsumerExperience | None,
    risks: tuple[AuthenticityRisk, ...],
) -> None:
    del experience
    blocked = HARD_AUTHENTICITY_BLOCKS.intersection(risks)
    if blocked:
        labels = ", ".join(sorted(item.value for item in blocked))
        raise PlacementRuleViolation(f"authenticity policy hard block: {labels}")


def assert_approval_allowed(*, review: Review, claims: tuple[Claim, ...]) -> None:
    if review.decision != "approved":
        return
    if not claims:
        raise PlacementRuleViolation("approval requires a non-empty claim inventory")
    unsupported = [
        claim
        for claim in claims
        if claim.claim_kind != "non_factual" and claim.support_status != "supported"
    ]
    if unsupported:
        raise PlacementRuleViolation("all extracted factual claims must be supported")


def edit_package_version(
    *,
    base: PackageVersion,
    new_id: UUID,
    expected_hash: str,
    content_json: Mapping[str, object],
    rendered_text: str,
    edited_by: UUID,
    reason: str,
) -> PackageVersion:
    if expected_hash != base.content_hash:
        raise ConcurrencyConflict("base content hash no longer matches")
    if not rendered_text.strip() or not reason.strip():
        raise PlacementRuleViolation("edited content and reason are required")
    payload = {"content_json": dict(content_json), "rendered_text": rendered_text}
    return PackageVersion(
        id=new_id,
        project_id=base.project_id,
        package_id=base.package_id,
        prompt_bundle_id=base.prompt_bundle_id,
        version_number=base.version_number + 1,
        base_version_id=base.id,
        content_json=content_json,
        rendered_text=rendered_text,
        content_hash=canonical_hash(payload),
        edited_by=edited_by,
        edit_reason=reason,
    )
