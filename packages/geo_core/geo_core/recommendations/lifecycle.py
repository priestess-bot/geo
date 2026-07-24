"""Pure Recommendation review, approval, rejection, and invalidation transitions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid5

from geo_core.recommendations.errors import (
    RecommendationConflict,
    RecommendationRuleViolation,
    RecommendationSourceStale,
)
from geo_core.recommendations.evidence import (
    RecommendationInputVersion,
    freeze_input_versions,
    input_fingerprint,
)
from geo_core.recommendations.models import (
    ApprovalOutcome,
    DownstreamDraftStatus,
    InputChangeReason,
    LinkedDraft,
    Recommendation,
    RecommendationApproval,
    RecommendationStatus,
    RecommendationTransition,
    RecommendationWorkflow,
    normalise_idempotency_key,
    require_aware,
)


def submit_recommendation(
    workflow: RecommendationWorkflow,
    *,
    expected_version: int,
    actor_id: str,
    occurred_at: datetime,
) -> RecommendationWorkflow:
    recommendation = workflow.recommendation
    _require_version(recommendation, expected_version)
    if recommendation.status != RecommendationStatus.DRAFT:
        raise RecommendationConflict("only a draft recommendation can enter review")
    transitioned = _transition(
        recommendation,
        target=RecommendationStatus.IN_REVIEW,
        actor_id=actor_id,
        reason="submitted_for_review",
        occurred_at=occurred_at,
    )
    return RecommendationWorkflow(transitioned, workflow.drafts)


def approve_and_create_draft(
    workflow: RecommendationWorkflow,
    *,
    expected_version: int,
    approval_id: UUID,
    actor_id: str,
    current_inputs: tuple[RecommendationInputVersion, ...],
    occurred_at: datetime,
    draft_idempotency_key: str | None = None,
) -> ApprovalOutcome:
    recommendation = workflow.recommendation
    inputs = freeze_input_versions(current_inputs)
    if recommendation.status == RecommendationStatus.APPROVED:
        return _replay_approval(
            workflow,
            expected_version=expected_version,
            approval_id=approval_id,
            actor_id=actor_id,
            current_inputs=inputs,
            draft_idempotency_key=draft_idempotency_key,
        )
    _require_version(recommendation, expected_version)
    if recommendation.status != RecommendationStatus.IN_REVIEW:
        raise RecommendationConflict("only an in-review recommendation can be approved")
    require_aware(occurred_at, "approval time")
    if occurred_at >= recommendation.valid_until:
        raise RecommendationConflict("expired recommendation cannot be approved")
    if inputs != recommendation.evidence.input_versions:
        raise RecommendationSourceStale("recommendation inputs changed before approval")
    actor = _required_text(actor_id, "approval actor")
    target_version = recommendation.version + 1
    approval = RecommendationApproval(
        id=approval_id,
        approved_by=actor,
        approved_at=occurred_at,
        recommendation_version=target_version,
        frozen_input_versions=inputs,
        frozen_input_fingerprint=input_fingerprint(inputs),
        frozen_evidence_graph_hash=recommendation.evidence.graph_hash,
        valid_until=recommendation.valid_until,
    )
    approved = _transition(
        recommendation,
        target=RecommendationStatus.APPROVED,
        actor_id=actor,
        reason="approved_by_human",
        occurred_at=occurred_at,
        approval=approval,
    )
    draft = _new_linked_draft(
        approved,
        occurred_at=occurred_at,
        draft_idempotency_key=draft_idempotency_key,
    )
    updated = RecommendationWorkflow(approved, (() if draft is None else (draft,)))
    return ApprovalOutcome(updated, draft, replayed=False)


def reject_recommendation(
    workflow: RecommendationWorkflow,
    *,
    expected_version: int,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
) -> RecommendationWorkflow:
    recommendation = workflow.recommendation
    _require_version(recommendation, expected_version)
    if recommendation.status not in {
        RecommendationStatus.DRAFT,
        RecommendationStatus.IN_REVIEW,
    }:
        raise RecommendationConflict("only draft or in-review recommendations can be rejected")
    rejected = _transition(
        recommendation,
        target=RecommendationStatus.REJECTED,
        actor_id=actor_id,
        reason=reason,
        occurred_at=occurred_at,
    )
    return RecommendationWorkflow(rejected, workflow.drafts)


def expire_recommendation(
    workflow: RecommendationWorkflow,
    *,
    expected_version: int,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
) -> RecommendationWorkflow:
    recommendation = workflow.recommendation
    if recommendation.status == RecommendationStatus.EXPIRED:
        return workflow
    _require_version(recommendation, expected_version)
    if recommendation.status not in {
        RecommendationStatus.DRAFT,
        RecommendationStatus.IN_REVIEW,
        RecommendationStatus.APPROVED,
    }:
        raise RecommendationConflict("recommendation is already in an irreversible terminal state")
    expired = _transition(
        recommendation,
        target=RecommendationStatus.EXPIRED,
        actor_id=actor_id,
        reason=reason,
        occurred_at=occurred_at,
    )
    drafts = _block_unstarted_drafts(
        workflow.drafts,
        target=DownstreamDraftStatus.BLOCKED_SOURCE_EXPIRED,
        reason=reason,
        occurred_at=occurred_at,
    )
    return RecommendationWorkflow(expired, drafts)


def reconcile_approved_inputs(
    workflow: RecommendationWorkflow,
    *,
    current_inputs: tuple[RecommendationInputVersion, ...],
    current_evidence_graph_hash: str | None = None,
    change_reason: InputChangeReason,
    actor_id: str,
    occurred_at: datetime,
) -> RecommendationWorkflow:
    recommendation = workflow.recommendation
    if recommendation.status != RecommendationStatus.APPROVED:
        if recommendation.status in {RecommendationStatus.STALE, RecommendationStatus.EXPIRED}:
            return workflow
        raise RecommendationConflict("only an approved recommendation can become stale")
    inputs = freeze_input_versions(current_inputs)
    approval = recommendation.approval
    if approval is None:
        raise RecommendationRuleViolation("approved recommendation is missing approval")
    evidence_unchanged = (
        current_evidence_graph_hash is None
        or current_evidence_graph_hash == approval.frozen_evidence_graph_hash
    )
    if inputs == approval.frozen_input_versions and evidence_unchanged:
        return workflow
    reason = InputChangeReason(change_reason).value
    stale = _transition(
        recommendation,
        target=RecommendationStatus.STALE,
        actor_id=actor_id,
        reason=reason,
        occurred_at=occurred_at,
    )
    drafts = _block_unstarted_drafts(
        workflow.drafts,
        target=DownstreamDraftStatus.BLOCKED_SOURCE_STALE,
        reason=reason,
        occurred_at=occurred_at,
    )
    return RecommendationWorkflow(stale, drafts)


def _transition(
    recommendation: Recommendation,
    *,
    target: RecommendationStatus,
    actor_id: str,
    reason: str,
    occurred_at: datetime,
    approval: RecommendationApproval | None = None,
) -> Recommendation:
    actor = _required_text(actor_id, "transition actor")
    clean_reason = _required_text(reason, "transition reason")
    require_aware(occurred_at, "transition time")
    if occurred_at < recommendation.updated_at:
        raise RecommendationRuleViolation("transition time cannot move backwards")
    version = recommendation.version + 1
    event = RecommendationTransition(
        from_status=recommendation.status,
        to_status=target,
        actor_id=actor,
        reason=clean_reason,
        occurred_at=occurred_at,
        resulting_version=version,
    )
    return replace(
        recommendation,
        status=target,
        version=version,
        approval=approval if approval is not None else recommendation.approval,
        updated_at=occurred_at,
        transitions=(*recommendation.transitions, event),
    )


def _new_linked_draft(
    recommendation: Recommendation,
    *,
    occurred_at: datetime,
    draft_idempotency_key: str | None,
) -> LinkedDraft | None:
    kind = recommendation.proposed_draft_kind
    if kind is None:
        if draft_idempotency_key is not None:
            raise RecommendationRuleViolation("no_change approval cannot create a draft")
        return None
    if draft_idempotency_key is None:
        raise RecommendationRuleViolation("draft creation requires an idempotency key")
    key = normalise_idempotency_key(draft_idempotency_key)
    approval = recommendation.approval
    if approval is None:
        raise RecommendationRuleViolation("draft creation requires an approval")
    return LinkedDraft(
        id=uuid5(recommendation.id, f"recommendation-draft:{key}"),
        recommendation_id=recommendation.id,
        recommendation_version=recommendation.version,
        approval_id=approval.id,
        kind=kind,
        idempotency_key=key,
        frozen_input_versions=approval.frozen_input_versions,
        frozen_input_fingerprint=approval.frozen_input_fingerprint,
        frozen_evidence_graph_hash=approval.frozen_evidence_graph_hash,
        created_at=occurred_at,
    )


def _replay_approval(
    workflow: RecommendationWorkflow,
    *,
    expected_version: int,
    approval_id: UUID,
    actor_id: str,
    current_inputs: tuple[RecommendationInputVersion, ...],
    draft_idempotency_key: str | None,
) -> ApprovalOutcome:
    recommendation = workflow.recommendation
    approval = recommendation.approval
    if approval is None:
        raise RecommendationRuleViolation("approved recommendation is missing approval")
    if expected_version not in {approval.recommendation_version - 1, recommendation.version}:
        raise RecommendationConflict("recommendation version does not match approval retry")
    if approval.id != approval_id or approval.approved_by != actor_id.strip():
        raise RecommendationConflict("recommendation already has a different approval")
    if current_inputs != approval.frozen_input_versions:
        raise RecommendationSourceStale("recommendation inputs changed after approval")
    if recommendation.proposed_draft_kind is None:
        if draft_idempotency_key is not None or workflow.drafts:
            raise RecommendationConflict("no_change approval cannot own a downstream draft")
        return ApprovalOutcome(workflow, None, replayed=True)
    if draft_idempotency_key is None:
        raise RecommendationRuleViolation("draft creation requires an idempotency key")
    key = normalise_idempotency_key(draft_idempotency_key)
    if len(workflow.drafts) != 1:
        raise RecommendationConflict("approved recommendation is missing its linked draft")
    draft = workflow.drafts[0]
    if draft.idempotency_key != key or draft.kind != recommendation.proposed_draft_kind:
        raise RecommendationConflict("idempotency key already owns a different approval result")
    return ApprovalOutcome(workflow, draft, replayed=True)


def _block_unstarted_drafts(
    drafts: tuple[LinkedDraft, ...],
    *,
    target: DownstreamDraftStatus,
    reason: str,
    occurred_at: datetime,
) -> tuple[LinkedDraft, ...]:
    return tuple(
        replace(
            draft,
            status=target,
            blocked_at=occurred_at,
            blocked_reason=reason,
        )
        if draft.status == DownstreamDraftStatus.DRAFT
        else draft
        for draft in drafts
    )


def _require_version(recommendation: Recommendation, expected_version: int) -> None:
    if expected_version != recommendation.version:
        raise RecommendationConflict("recommendation version does not match current state")


def _required_text(value: str, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise RecommendationRuleViolation(f"{label} is required")
    return clean
