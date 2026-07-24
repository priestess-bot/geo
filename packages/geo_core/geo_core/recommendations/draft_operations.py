"""Execution-boundary checks for Recommendation-created downstream drafts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from geo_core.recommendations.errors import (
    SOURCE_STALE_PROBLEM_CODE,
    RecommendationConflict,
    RecommendationRuleViolation,
)
from geo_core.recommendations.evidence import (
    RecommendationInputVersion,
    freeze_input_versions,
)
from geo_core.recommendations.lifecycle import (
    expire_recommendation,
    reconcile_approved_inputs,
)
from geo_core.recommendations.models import (
    DownstreamDraftStatus,
    DraftActionCheck,
    InputChangeReason,
    LinkedDraft,
    RecommendationStatus,
    RecommendationWorkflow,
    require_aware,
)


def prepare_draft_action(
    workflow: RecommendationWorkflow,
    *,
    draft_id: UUID,
    expected_recommendation_version: int,
    current_inputs: tuple[RecommendationInputVersion, ...],
    current_evidence_graph_hash: str,
    occurred_at: datetime,
    actor_id: str,
    change_reason: InputChangeReason = InputChangeReason.DATA_REFRESHED,
) -> DraftActionCheck:
    require_aware(occurred_at, "draft source check time")
    recommendation = workflow.recommendation
    inputs = freeze_input_versions(current_inputs)
    reconciled = workflow
    if recommendation.status == RecommendationStatus.APPROVED:
        if occurred_at >= recommendation.valid_until:
            reconciled = expire_recommendation(
                workflow,
                expected_version=recommendation.version,
                actor_id=actor_id,
                reason="validity_window_elapsed",
                occurred_at=occurred_at,
            )
        elif recommendation.approval is None:
            raise RecommendationRuleViolation("approved recommendation is missing approval")
        elif (
            inputs != recommendation.approval.frozen_input_versions
            or current_evidence_graph_hash
            != recommendation.approval.frozen_evidence_graph_hash
        ):
            reconciled = reconcile_approved_inputs(
                workflow,
                current_inputs=inputs,
                current_evidence_graph_hash=current_evidence_graph_hash,
                change_reason=change_reason,
                actor_id=actor_id,
                occurred_at=occurred_at,
            )
    draft = _draft_by_id(reconciled, draft_id)
    recommendation = reconciled.recommendation
    approval = recommendation.approval
    authorized = (
        recommendation.status == RecommendationStatus.APPROVED
        and approval is not None
        and recommendation.version == expected_recommendation_version
        and draft.recommendation_version == recommendation.version
        and draft.approval_id == approval.id
        and draft.frozen_input_versions == inputs
        and draft.frozen_evidence_graph_hash == current_evidence_graph_hash
        and draft.status == DownstreamDraftStatus.DRAFT
        and occurred_at < approval.valid_until
    )
    if authorized:
        return DraftActionCheck(reconciled, draft, True, None, None)
    return DraftActionCheck(
        reconciled,
        draft,
        False,
        SOURCE_STALE_PROBLEM_CODE,
        "source Recommendation is not the same current approved version",
    )


def mark_draft_started(check: DraftActionCheck, *, started_at: datetime) -> RecommendationWorkflow:
    check.require_authorized()
    require_aware(started_at, "draft start time")
    if started_at < check.draft.created_at:
        raise RecommendationRuleViolation("draft cannot start before it was created")
    started = replace(
        check.draft,
        status=DownstreamDraftStatus.STARTED,
        started_at=started_at,
    )
    drafts = tuple(started if item.id == started.id else item for item in check.workflow.drafts)
    return RecommendationWorkflow(check.workflow.recommendation, drafts)


def _draft_by_id(workflow: RecommendationWorkflow, draft_id: UUID) -> LinkedDraft:
    for draft in workflow.drafts:
        if draft.id == draft_id:
            return draft
    raise RecommendationConflict("linked recommendation draft does not exist")
