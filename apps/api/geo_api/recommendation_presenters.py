"""Recommendation transport-to-domain conversion and response presentation."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from geo_api.recommendation_contracts import (
    ApprovalResponse,
    ApprovedRecommendationResponse,
    DecisionContract,
    DraftKindValue,
    DraftStatusValue,
    EvidenceGraphContract,
    EvidenceSelectorContract,
    InputKindValue,
    InputVersionContract,
    InvalidatedRecommendationResponse,
    LinkedDraftResponse,
    PreparedDraftActionResponse,
    RecommendationCommandResponse,
    RecommendationPageResponse,
    RecommendationResponse,
    RecommendationReviewResponse,
    RecommendationStatusValue,
    RecommendationTypeValue,
    ScopeSelectionContract,
    RecommendationWorkflowResponse,
    ReviewedRecommendationResponse,
)
from geo_api.recommendation_runtime import RecommendationPageRead
from geo_core.recommendations import (
    ApprovedRecommendation,
    CommandReceipt,
    InvalidatedRecommendation,
    PreparedDraftAction,
    RecommendationDecision,
    RecommendationEvidenceGraph,
    RecommendationScope,
    RecommendationWorkflow,
    ReviewedRecommendation,
)
from geo_core.recommendations.resolution import (
    RecommendationEvidenceKind,
    RecommendationEvidenceSelector,
)


def selection_scope(
    project_id: UUID, item: ScopeSelectionContract
) -> RecommendationScope:
    return RecommendationScope(
        project_id=project_id,
        applicable_version=item.applicable_version,
        campaign_id=item.campaign_id,
        question_or_cluster_ref=item.question_or_cluster_ref,
        surface_ref=item.surface_ref,
        content_asset_ref=item.content_asset_ref,
        url_ref=item.url_ref,
    )


def decision_from_contract(item: DecisionContract) -> RecommendationDecision:
    return RecommendationDecision(
        impact_chain=tuple(item.impact_chain),
        risk=item.risk,
        effort=item.effort,
        business_value=item.business_value,
        confidence=item.confidence,
        counterevidence=tuple(item.counterevidence),
        validation_plan=tuple(item.validation_plan),
        stale_conditions=tuple(item.stale_conditions),
    )


def selectors_from_contract(
    values: list[EvidenceSelectorContract],
) -> tuple[RecommendationEvidenceSelector, ...]:
    return tuple(
        RecommendationEvidenceSelector(
            kind=RecommendationEvidenceKind(item.kind),
            resource_id=item.resource_id,
        )
        for item in values
    )


def workflow_response(item: RecommendationWorkflow) -> RecommendationWorkflowResponse:
    recommendation = item.recommendation
    approval = recommendation.approval
    return RecommendationWorkflowResponse(
        recommendation=RecommendationResponse(
            id=recommendation.id,
            project_id=recommendation.project_id,
            recommendation_type=cast(
                RecommendationTypeValue, recommendation.recommendation_type.value
            ),
            status=cast(RecommendationStatusValue, recommendation.status.value),
            version=recommendation.version,
            proposed_draft_kind=(
                cast(DraftKindValue, recommendation.proposed_draft_kind.value)
                if recommendation.proposed_draft_kind
                else None
            ),
            valid_until=recommendation.valid_until,
            created_by=recommendation.created_by,
            created_at=recommendation.created_at,
            updated_at=recommendation.updated_at,
            evidence=_evidence_contract(recommendation.evidence),
            evidence_graph_hash=recommendation.evidence.graph_hash,
            input_fingerprint=recommendation.evidence.input_fingerprint,
            input_versions=[
                InputVersionContract(
                    kind=cast(InputKindValue, input_version.kind.value),
                    resource_id=input_version.resource_id,
                    version=input_version.version,
                    sha256=input_version.sha256,
                )
                for input_version in recommendation.evidence.input_versions
            ],
            approval=(
                ApprovalResponse(
                    id=approval.id,
                    approved_by=approval.approved_by,
                    approved_at=approval.approved_at,
                    recommendation_version=approval.recommendation_version,
                    frozen_input_fingerprint=approval.frozen_input_fingerprint,
                    frozen_evidence_graph_hash=approval.frozen_evidence_graph_hash,
                    valid_until=approval.valid_until,
                )
                if approval
                else None
            ),
        ),
        drafts=[_draft(item) for item in item.drafts],
    )


def workflow_command_response(
    item: CommandReceipt[RecommendationWorkflow],
) -> RecommendationCommandResponse:
    value = workflow_response(item.value)
    return RecommendationCommandResponse(**value.model_dump(), replayed=item.replayed)


def reviewed_response(
    item: CommandReceipt[ReviewedRecommendation],
) -> ReviewedRecommendationResponse:
    value = workflow_response(item.value.workflow)
    review = item.value.review
    return ReviewedRecommendationResponse(
        **value.model_dump(),
        review=RecommendationReviewResponse(
            id=review.id,
            recommendation_id=review.recommendation_id,
            recommendation_version=review.recommendation_version,
            evidence_graph_hash=review.evidence_graph_hash,
            reviewed_by=review.reviewed_by,
            notes=review.notes,
            reviewed_at=review.reviewed_at,
        ),
        replayed=item.replayed,
    )


def approved_response(
    item: CommandReceipt[ApprovedRecommendation],
) -> ApprovedRecommendationResponse:
    value = workflow_response(item.value.workflow)
    created = item.value.downstream_draft
    linked = next(
        (draft for draft in item.value.workflow.drafts if created and draft.id == created.draft_id),
        None,
    )
    return ApprovedRecommendationResponse(
        **value.model_dump(),
        downstream_draft=_draft(linked) if linked else None,
        replayed=item.replayed,
    )


def invalidated_response(
    item: CommandReceipt[InvalidatedRecommendation],
) -> InvalidatedRecommendationResponse:
    value = workflow_response(item.value.workflow)
    return InvalidatedRecommendationResponse(
        **value.model_dump(),
        cancelled_outbox_ids=list(item.value.cancelled_outbox_ids),
        replayed=item.replayed,
    )


def prepared_response(
    item: CommandReceipt[PreparedDraftAction],
) -> PreparedDraftActionResponse:
    value = workflow_response(item.value.check.workflow)
    return PreparedDraftActionResponse(
        **value.model_dump(),
        draft=_draft(item.value.check.draft),
        authorized=True,
        replayed=item.replayed,
    )


def page_response(item: RecommendationPageRead) -> RecommendationPageResponse:
    return RecommendationPageResponse(
        items=[workflow_response(workflow) for workflow in item.items],
        total=item.total,
        limit=item.limit,
        offset=item.offset,
    )


def _evidence_contract(item: RecommendationEvidenceGraph) -> EvidenceGraphContract:
    references = {
        "observations": [_ref_value(ref) for ref in item.observations],
        "metric_comparisons": [_ref_value(ref) for ref in item.metric_comparisons],
        "facts": [_ref_value(ref) for ref in item.facts],
        "rules": [_ref_value(ref) for ref in item.rules],
        "prompt_releases": [_ref_value(ref) for ref in item.prompt_releases],
        "model_calls": [_ref_value(ref) for ref in item.model_calls],
        "contents": [_ref_value(ref) for ref in item.contents],
        "questions": [_ref_value(ref) for ref in item.questions],
        "surfaces": [_ref_value(ref) for ref in item.surfaces],
        "attributions": [_ref_value(ref) for ref in item.attributions],
    }
    return EvidenceGraphContract.model_validate(
        {
            "scope": item.scope.canonical_value(),
            "decision": item.decision.canonical_value(),
            **references,
        }
    )


def _ref_value(item: object) -> dict[str, object]:
    canonical = dict(item.canonical_value())  # type: ignore[attr-defined]
    canonical.pop("kind", None)
    return canonical


def _draft(item: object) -> LinkedDraftResponse:
    from geo_core.recommendations import LinkedDraft

    if not isinstance(item, LinkedDraft):
        raise TypeError("Recommendation response draft is invalid")
    return LinkedDraftResponse(
        id=item.id,
        recommendation_id=item.recommendation_id,
        recommendation_version=item.recommendation_version,
        approval_id=item.approval_id,
        kind=cast(DraftKindValue, item.kind.value),
        status=cast(DraftStatusValue, item.status.value),
        frozen_input_fingerprint=item.frozen_input_fingerprint,
        frozen_evidence_graph_hash=item.frozen_evidence_graph_hash,
        created_at=item.created_at,
        started_at=item.started_at,
        blocked_at=item.blocked_at,
        blocked_reason=item.blocked_reason,
    )
