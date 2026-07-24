"""Immutable recommendation lifecycle and downstream-draft state models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from geo_core.recommendations.errors import (
    SOURCE_STALE_PROBLEM_CODE,
    RecommendationRuleViolation,
    RecommendationSourceStale,
)
from geo_core.recommendations.evidence import (
    SHA256_PATTERN,
    RecommendationEvidenceGraph,
    RecommendationInputVersion,
    freeze_input_versions,
    input_fingerprint,
)


MAX_IDEMPOTENCY_KEY_LENGTH = 200


class RecommendationType(StrEnum):
    HARD_BLOCKER = "hard_blocker"
    GAP = "gap"
    EXPERIMENT = "experiment"
    OPTIONAL = "optional"
    NO_CHANGE = "no_change"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RecommendationStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    STALE = "stale"
    EXPIRED = "expired"


class InputChangeReason(StrEnum):
    FACT_RETIRED = "fact_retired"
    DATA_REFRESHED = "data_refreshed"
    ALERT_RESOLVED = "alert_resolved"
    METHOD_REPLACED = "method_replaced"
    CONTENT_VERSION_CHANGED = "content_version_changed"
    PROMPT_RELEASE_CHANGED = "prompt_release_changed"
    INPUT_ADDED_OR_REMOVED = "input_added_or_removed"


class DownstreamDraftKind(StrEnum):
    EXPERIMENT_PLAN = "experiment_plan"
    QUESTION_SET = "question_set"
    CONTENT_BRIEF = "content_brief"
    SAMPLING_PLAN = "sampling_plan"


class DownstreamDraftStatus(StrEnum):
    DRAFT = "draft"
    STARTED = "started"
    BLOCKED_SOURCE_STALE = "blocked_source_stale"
    BLOCKED_SOURCE_EXPIRED = "blocked_source_expired"


@dataclass(frozen=True)
class RecommendationApproval:
    id: UUID
    approved_by: str
    approved_at: datetime
    recommendation_version: int
    frozen_input_versions: tuple[RecommendationInputVersion, ...]
    frozen_input_fingerprint: str
    frozen_evidence_graph_hash: str
    valid_until: datetime

    def __post_init__(self) -> None:
        actor = self.approved_by.strip()
        if not actor:
            raise RecommendationRuleViolation("approval actor is required")
        if self.recommendation_version < 1:
            raise RecommendationRuleViolation("approved recommendation version must be positive")
        require_aware(self.approved_at, "approval time")
        require_aware(self.valid_until, "approval expiry")
        if self.valid_until <= self.approved_at:
            raise RecommendationRuleViolation("approval expiry must follow approval time")
        frozen = freeze_input_versions(self.frozen_input_versions)
        if self.frozen_input_fingerprint != input_fingerprint(frozen):
            raise RecommendationRuleViolation("approval input fingerprint does not match inputs")
        if not SHA256_PATTERN.fullmatch(self.frozen_evidence_graph_hash):
            raise RecommendationRuleViolation(
                "approval evidence graph hash must be lowercase SHA-256"
            )
        object.__setattr__(self, "approved_by", actor)
        object.__setattr__(self, "frozen_input_versions", frozen)


@dataclass(frozen=True)
class RecommendationTransition:
    from_status: RecommendationStatus
    to_status: RecommendationStatus
    actor_id: str
    reason: str
    occurred_at: datetime
    resulting_version: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_status", RecommendationStatus(self.from_status))
        object.__setattr__(self, "to_status", RecommendationStatus(self.to_status))
        actor = self.actor_id.strip()
        reason = self.reason.strip()
        if not actor or not reason:
            raise RecommendationRuleViolation("transition actor and reason are required")
        if self.resulting_version < 2:
            raise RecommendationRuleViolation("transition version must follow the initial version")
        require_aware(self.occurred_at, "transition time")
        object.__setattr__(self, "actor_id", actor)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True)
class Recommendation:
    id: UUID
    project_id: UUID
    recommendation_type: RecommendationType
    evidence: RecommendationEvidenceGraph
    proposed_draft_kind: DownstreamDraftKind | None
    valid_until: datetime
    created_by: str
    created_at: datetime
    updated_at: datetime
    status: RecommendationStatus = RecommendationStatus.DRAFT
    version: int = 1
    approval: RecommendationApproval | None = None
    transitions: tuple[RecommendationTransition, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "recommendation_type", RecommendationType(self.recommendation_type)
        )
        object.__setattr__(self, "status", RecommendationStatus(self.status))
        if self.proposed_draft_kind is not None:
            object.__setattr__(
                self, "proposed_draft_kind", DownstreamDraftKind(self.proposed_draft_kind)
            )
        actor = self.created_by.strip()
        if not actor:
            raise RecommendationRuleViolation("recommendation creator is required")
        if self.project_id != self.evidence.scope.project_id:
            raise RecommendationRuleViolation("recommendation scope must belong to its project")
        evidence_failures = self.evidence.conclusive_failures()
        if (
            self.recommendation_type != RecommendationType.INSUFFICIENT_EVIDENCE
            and evidence_failures
        ):
            joined = ", ".join(evidence_failures)
            raise RecommendationRuleViolation(
                f"conclusive recommendation evidence is incomplete ({joined}); "
                "use insufficient_evidence with a Sampling Plan"
            )
        if self.version < 1:
            raise RecommendationRuleViolation("recommendation version must be positive")
        require_aware(self.created_at, "recommendation creation time")
        require_aware(self.updated_at, "recommendation update time")
        require_aware(self.valid_until, "recommendation expiry")
        if self.updated_at < self.created_at or self.valid_until <= self.created_at:
            raise RecommendationRuleViolation("recommendation timestamps are inconsistent")
        if self.recommendation_type == RecommendationType.NO_CHANGE:
            if self.proposed_draft_kind is not None:
                raise RecommendationRuleViolation("no_change cannot propose a downstream draft")
        elif self.proposed_draft_kind is None:
            raise RecommendationRuleViolation("actionable recommendations require a draft plan")
        if (
            self.recommendation_type == RecommendationType.INSUFFICIENT_EVIDENCE
            and self.proposed_draft_kind != DownstreamDraftKind.SAMPLING_PLAN
        ):
            raise RecommendationRuleViolation(
                "insufficient_evidence can only propose a sampling plan"
            )
        if (
            self.recommendation_type == RecommendationType.EXPERIMENT
            and self.proposed_draft_kind != DownstreamDraftKind.EXPERIMENT_PLAN
        ):
            raise RecommendationRuleViolation("experiment can only propose an experiment plan")
        approved_states = {RecommendationStatus.APPROVED, RecommendationStatus.STALE}
        if self.status in approved_states and self.approval is None:
            raise RecommendationRuleViolation(f"{self.status.value} requires an approval")
        if (
            self.status
            in {
                RecommendationStatus.DRAFT,
                RecommendationStatus.IN_REVIEW,
                RecommendationStatus.REJECTED,
            }
            and self.approval is not None
        ):
            raise RecommendationRuleViolation(f"{self.status.value} cannot carry an approval")
        if self.approval is not None:
            if self.approval.frozen_input_versions != self.evidence.input_versions:
                raise RecommendationRuleViolation(
                    "approval must freeze the evidence input versions"
                )
            if self.approval.frozen_evidence_graph_hash != self.evidence.graph_hash:
                raise RecommendationRuleViolation("approval must freeze the evidence graph hash")
            if self.approval.recommendation_version > self.version:
                raise RecommendationRuleViolation("approval cannot reference a future version")
            if (
                self.status == RecommendationStatus.APPROVED
                and self.approval.recommendation_version != self.version
            ):
                raise RecommendationRuleViolation("approved state must match approval version")
        if len(self.transitions) != self.version - 1:
            raise RecommendationRuleViolation("transition history must cover every state version")
        if self.transitions:
            if self.transitions[-1].to_status != self.status:
                raise RecommendationRuleViolation("transition history does not match current state")
            if self.transitions[-1].resulting_version != self.version:
                raise RecommendationRuleViolation(
                    "transition history does not match current version"
                )
        object.__setattr__(self, "created_by", actor)


@dataclass(frozen=True)
class LinkedDraft:
    id: UUID
    recommendation_id: UUID
    recommendation_version: int
    approval_id: UUID
    kind: DownstreamDraftKind
    idempotency_key: str
    frozen_input_versions: tuple[RecommendationInputVersion, ...]
    frozen_input_fingerprint: str
    frozen_evidence_graph_hash: str
    created_at: datetime
    status: DownstreamDraftStatus = DownstreamDraftStatus.DRAFT
    started_at: datetime | None = None
    blocked_at: datetime | None = None
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", DownstreamDraftKind(self.kind))
        object.__setattr__(self, "status", DownstreamDraftStatus(self.status))
        key = normalise_idempotency_key(self.idempotency_key)
        if self.recommendation_version < 1:
            raise RecommendationRuleViolation("draft recommendation version must be positive")
        frozen = freeze_input_versions(self.frozen_input_versions)
        if self.frozen_input_fingerprint != input_fingerprint(frozen):
            raise RecommendationRuleViolation("draft input fingerprint does not match lineage")
        if not SHA256_PATTERN.fullmatch(self.frozen_evidence_graph_hash):
            raise RecommendationRuleViolation("draft evidence graph hash must be lowercase SHA-256")
        require_aware(self.created_at, "draft creation time")
        if self.status == DownstreamDraftStatus.STARTED:
            if self.started_at is None or self.blocked_at is not None:
                raise RecommendationRuleViolation("started draft requires only a start time")
        elif self.started_at is not None:
            raise RecommendationRuleViolation("unstarted draft cannot carry a start time")
        blocked = self.status in {
            DownstreamDraftStatus.BLOCKED_SOURCE_STALE,
            DownstreamDraftStatus.BLOCKED_SOURCE_EXPIRED,
        }
        if blocked:
            if (
                self.blocked_at is None
                or not self.blocked_reason
                or not self.blocked_reason.strip()
            ):
                raise RecommendationRuleViolation("blocked draft requires time and reason")
        elif self.blocked_at is not None or self.blocked_reason is not None:
            raise RecommendationRuleViolation("unblocked draft cannot carry blocking details")
        if self.started_at is not None:
            require_aware(self.started_at, "draft start time")
        if self.blocked_at is not None:
            require_aware(self.blocked_at, "draft blocked time")
        object.__setattr__(self, "idempotency_key", key)
        object.__setattr__(self, "frozen_input_versions", frozen)


@dataclass(frozen=True)
class RecommendationWorkflow:
    recommendation: Recommendation
    drafts: tuple[LinkedDraft, ...] = ()

    def __post_init__(self) -> None:
        if len(self.drafts) > 1:
            raise RecommendationRuleViolation(
                "one approval can create at most one downstream draft"
            )
        for draft in self.drafts:
            if draft.recommendation_id != self.recommendation.id:
                raise RecommendationRuleViolation("linked draft belongs to another recommendation")
            approval = self.recommendation.approval
            if approval is None or draft.approval_id != approval.id:
                raise RecommendationRuleViolation("linked draft must reference current approval")
            if draft.recommendation_version != approval.recommendation_version:
                raise RecommendationRuleViolation("linked draft must freeze approved version")
            if draft.frozen_input_versions != approval.frozen_input_versions:
                raise RecommendationRuleViolation("linked draft must freeze approved input lineage")
            if draft.frozen_evidence_graph_hash != approval.frozen_evidence_graph_hash:
                raise RecommendationRuleViolation("linked draft must freeze approved graph hash")
        if self.recommendation.status in {
            RecommendationStatus.STALE,
            RecommendationStatus.EXPIRED,
        }:
            expected = (
                DownstreamDraftStatus.BLOCKED_SOURCE_STALE
                if self.recommendation.status == RecommendationStatus.STALE
                else DownstreamDraftStatus.BLOCKED_SOURCE_EXPIRED
            )
            for draft in self.drafts:
                if draft.status not in {expected, DownstreamDraftStatus.STARTED}:
                    raise RecommendationRuleViolation(
                        "terminal source must block every unstarted draft"
                    )


@dataclass(frozen=True)
class ApprovalOutcome:
    workflow: RecommendationWorkflow
    draft: LinkedDraft | None
    replayed: bool


@dataclass(frozen=True)
class DraftActionCheck:
    workflow: RecommendationWorkflow
    draft: LinkedDraft
    authorized: bool
    problem_code: str | None
    detail: str | None

    def require_authorized(self) -> None:
        if not self.authorized:
            raise RecommendationSourceStale(self.detail or SOURCE_STALE_PROBLEM_CODE)


def normalise_idempotency_key(value: str) -> str:
    key = value.strip()
    if not key or len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise RecommendationRuleViolation("a bounded draft idempotency key is required")
    return key


def require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RecommendationRuleViolation(f"{label} must be timezone-aware")
