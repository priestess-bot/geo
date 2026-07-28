"""JSON codecs for immutable Recommendation PostgreSQL records."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from geo_core.recommendations.application_support import (
    ApprovedRecommendation,
    InvalidatedRecommendation,
    ReviewedRecommendation,
)
from geo_core.recommendations.decision import RecommendationDecision
from geo_core.recommendations.evidence import (
    AttributionRef,
    ContentRef,
    FactRef,
    MetricComparisonRef,
    ModelCallRef,
    ObservationRef,
    PromptReleaseRef,
    QuestionRef,
    RecommendationEvidenceGraph,
    RecommendationInputKind,
    RecommendationInputVersion,
    RecommendationScope,
    RuleRef,
    SurfaceRef,
)
from geo_core.recommendations.models import (
    DownstreamDraftKind,
    DownstreamDraftStatus,
    DraftActionCheck,
    LinkedDraft,
    Recommendation,
    RecommendationApproval,
    RecommendationStatus,
    RecommendationTransition,
    RecommendationType,
    RecommendationWorkflow,
)
from geo_core.recommendations.evidence_graph import (
    EVIDENCE_GRAPH_CONTRACT_V1,
    EVIDENCE_GRAPH_CONTRACT_V2,
)
from geo_core.recommendations.ports import (
    CreatedDownstreamDraft,
    PreparedDraftAction,
    RecommendationCommandOperation,
    RecommendationReview,
)
from geo_core.recommendations.postgres.evidence import evidence_ref_from_payload


def workflow_payload(workflow: RecommendationWorkflow) -> dict[str, object]:
    item = workflow.recommendation
    return {
        "recommendation": {
            "id": str(item.id),
            "project_id": str(item.project_id),
            "recommendation_type": item.recommendation_type.value,
            "evidence": item.evidence.canonical_value(),
            "proposed_draft_kind": (
                item.proposed_draft_kind.value if item.proposed_draft_kind else None
            ),
            "valid_until": item.valid_until.isoformat(),
            "created_by": item.created_by,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
            "status": item.status.value,
            "version": item.version,
            "approval": _approval_payload(item.approval),
            "transitions": [_transition_payload(value) for value in item.transitions],
        },
        "drafts": [_draft_payload(value) for value in workflow.drafts],
    }


def workflow_from_payload(value: object) -> RecommendationWorkflow:
    root = _mapping(value, "workflow")
    item = _mapping(root.get("recommendation"), "recommendation")
    recommendation = Recommendation(
        id=_uuid(item, "id"),
        project_id=_uuid(item, "project_id"),
        recommendation_type=RecommendationType(_text(item, "recommendation_type")),
        evidence=evidence_graph_from_payload(item.get("evidence")),
        proposed_draft_kind=(
            DownstreamDraftKind(str(item["proposed_draft_kind"]))
            if item.get("proposed_draft_kind") is not None
            else None
        ),
        valid_until=_datetime(item, "valid_until"),
        created_by=_text(item, "created_by"),
        created_at=_datetime(item, "created_at"),
        updated_at=_datetime(item, "updated_at"),
        status=RecommendationStatus(_text(item, "status")),
        version=_integer(item, "version"),
        approval=_approval_from_payload(item.get("approval")),
        transitions=tuple(
            _transition_from_payload(entry)
            for entry in _sequence(item.get("transitions"), "transitions")
        ),
    )
    return RecommendationWorkflow(
        recommendation,
        tuple(
            _draft_from_payload(entry)
            for entry in _sequence(root.get("drafts"), "drafts")
        ),
    )


def evidence_graph_from_payload(value: object) -> RecommendationEvidenceGraph:
    root = _mapping(value, "evidence")
    contract_version = _text(root, "contract_version")
    if contract_version not in {
        EVIDENCE_GRAPH_CONTRACT_V1,
        EVIDENCE_GRAPH_CONTRACT_V2,
    }:
        raise ValueError("unsupported Recommendation evidence graph contract")
    scope_value = _mapping(root.get("scope"), "evidence scope")
    decision_value = _mapping(root.get("decision"), "evidence decision")
    scope = RecommendationScope(
        project_id=_uuid(scope_value, "project_id"),
        applicable_version=_text(scope_value, "applicable_version"),
        campaign_id=_optional_uuid(scope_value.get("campaign_id")),
        question_or_cluster_ref=_optional_text(scope_value.get("question_or_cluster_ref")),
        surface_ref=_optional_text(scope_value.get("surface_ref")),
        content_asset_ref=_optional_text(scope_value.get("content_asset_ref")),
        url_ref=_optional_text(scope_value.get("url_ref")),
    )
    decision = RecommendationDecision(
        impact_chain=_texts(decision_value, "impact_chain"),
        risk=_text(decision_value, "risk"),
        effort=_text(decision_value, "effort"),
        business_value=_text(decision_value, "business_value"),
        confidence=decision_value["confidence"],
        counterevidence=_texts(decision_value, "counterevidence"),
        validation_plan=_texts(decision_value, "validation_plan"),
        stale_conditions=_texts(decision_value, "stale_conditions"),
    )
    references = tuple(
        evidence_ref_from_payload(_mapping(entry, "evidence reference"))
        for entry in _sequence(root.get("references"), "evidence references")
    )
    return RecommendationEvidenceGraph(
        scope=scope,
        decision=decision,
        observations=tuple(item for item in references if isinstance(item, ObservationRef)),
        metric_comparisons=tuple(
            item for item in references if isinstance(item, MetricComparisonRef)
        ),
        facts=tuple(item for item in references if isinstance(item, FactRef)),
        rules=tuple(item for item in references if isinstance(item, RuleRef)),
        prompt_releases=tuple(
            item for item in references if isinstance(item, PromptReleaseRef)
        ),
        model_calls=tuple(item for item in references if isinstance(item, ModelCallRef)),
        contents=tuple(item for item in references if isinstance(item, ContentRef)),
        questions=tuple(item for item in references if isinstance(item, QuestionRef)),
        surfaces=tuple(item for item in references if isinstance(item, SurfaceRef)),
        attributions=tuple(
            item for item in references if isinstance(item, AttributionRef)
        ),
        contract_version=contract_version,
    )


def review_payload(item: RecommendationReview) -> dict[str, object]:
    return {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "recommendation_id": str(item.recommendation_id),
        "recommendation_version": item.recommendation_version,
        "evidence_graph_hash": item.evidence_graph_hash,
        "reviewed_by": str(item.reviewed_by),
        "notes": item.notes,
        "reviewed_at": item.reviewed_at.isoformat(),
    }


def review_from_payload(value: object) -> RecommendationReview:
    item = _mapping(value, "review")
    return RecommendationReview(
        id=_uuid(item, "id"),
        project_id=_uuid(item, "project_id"),
        recommendation_id=_uuid(item, "recommendation_id"),
        recommendation_version=_integer(item, "recommendation_version"),
        evidence_graph_hash=_text(item, "evidence_graph_hash"),
        reviewed_by=_uuid(item, "reviewed_by"),
        notes=_text(item, "notes"),
        reviewed_at=_datetime(item, "reviewed_at"),
    )


def command_result_payload(result: object) -> tuple[str, dict[str, object]]:
    if isinstance(result, RecommendationWorkflow):
        return "workflow", {"workflow": workflow_payload(result)}
    if isinstance(result, ReviewedRecommendation):
        return "reviewed", {
            "workflow": workflow_payload(result.workflow),
            "review": review_payload(result.review),
        }
    if isinstance(result, ApprovedRecommendation):
        return "approved", {
            "workflow": workflow_payload(result.workflow),
            "downstream_draft": (
                _created_draft_payload(result.downstream_draft)
                if result.downstream_draft
                else None
            ),
        }
    if isinstance(result, InvalidatedRecommendation):
        return "invalidated", {
            "workflow": workflow_payload(result.workflow),
            "cancelled_outbox_ids": [str(value) for value in result.cancelled_outbox_ids],
        }
    if isinstance(result, PreparedDraftAction):
        return "prepared", {
            "check": _check_payload(result.check),
            "cancelled_outbox_ids": [str(value) for value in result.cancelled_outbox_ids],
        }
    raise TypeError("unsupported Recommendation command result")


def command_result_from_payload(
    operation: RecommendationCommandOperation,
    result_kind: str,
    value: object,
) -> object:
    item = _mapping(value, "command result")
    expected = {
        RecommendationCommandOperation.CREATE: "workflow",
        RecommendationCommandOperation.SUBMIT: "workflow",
        RecommendationCommandOperation.REVIEW: "reviewed",
        RecommendationCommandOperation.APPROVE: "approved",
        RecommendationCommandOperation.REJECT: "workflow",
        RecommendationCommandOperation.EXPIRE: "invalidated",
        RecommendationCommandOperation.RECONCILE_STALE: "invalidated",
        RecommendationCommandOperation.PREPARE_DRAFT_ACTION: "prepared",
    }[operation]
    if result_kind != expected:
        raise ValueError("Recommendation command result kind changed")
    if result_kind == "workflow":
        return workflow_from_payload(item.get("workflow"))
    if result_kind == "reviewed":
        return ReviewedRecommendation(
            workflow_from_payload(item.get("workflow")),
            review_from_payload(item.get("review")),
        )
    if result_kind == "approved":
        draft_value = item.get("downstream_draft")
        return ApprovedRecommendation(
            workflow_from_payload(item.get("workflow")),
            _created_draft_from_payload(draft_value) if draft_value else None,
        )
    cancelled = tuple(
        UUID(str(value))
        for value in _sequence(item.get("cancelled_outbox_ids"), "cancelled outbox IDs")
    )
    if result_kind == "invalidated":
        return InvalidatedRecommendation(
            workflow_from_payload(item.get("workflow")), cancelled
        )
    return PreparedDraftAction(_check_from_payload(item.get("check")), cancelled)


def _approval_payload(item: RecommendationApproval | None) -> object:
    if item is None:
        return None
    return {
        "id": str(item.id),
        "approved_by": item.approved_by,
        "approved_at": item.approved_at.isoformat(),
        "recommendation_version": item.recommendation_version,
        "frozen_input_versions": [_input_payload(value) for value in item.frozen_input_versions],
        "frozen_input_fingerprint": item.frozen_input_fingerprint,
        "frozen_evidence_graph_hash": item.frozen_evidence_graph_hash,
        "valid_until": item.valid_until.isoformat(),
    }


def _approval_from_payload(value: object) -> RecommendationApproval | None:
    if value is None:
        return None
    item = _mapping(value, "approval")
    return RecommendationApproval(
        id=_uuid(item, "id"),
        approved_by=_text(item, "approved_by"),
        approved_at=_datetime(item, "approved_at"),
        recommendation_version=_integer(item, "recommendation_version"),
        frozen_input_versions=tuple(
            _input_from_payload(entry)
            for entry in _sequence(item.get("frozen_input_versions"), "approval inputs")
        ),
        frozen_input_fingerprint=_text(item, "frozen_input_fingerprint"),
        frozen_evidence_graph_hash=_text(item, "frozen_evidence_graph_hash"),
        valid_until=_datetime(item, "valid_until"),
    )


def _transition_payload(item: RecommendationTransition) -> dict[str, object]:
    return {
        "from_status": item.from_status.value,
        "to_status": item.to_status.value,
        "actor_id": item.actor_id,
        "reason": item.reason,
        "occurred_at": item.occurred_at.isoformat(),
        "resulting_version": item.resulting_version,
    }


def _transition_from_payload(value: object) -> RecommendationTransition:
    item = _mapping(value, "transition")
    return RecommendationTransition(
        from_status=RecommendationStatus(_text(item, "from_status")),
        to_status=RecommendationStatus(_text(item, "to_status")),
        actor_id=_text(item, "actor_id"),
        reason=_text(item, "reason"),
        occurred_at=_datetime(item, "occurred_at"),
        resulting_version=_integer(item, "resulting_version"),
    )


def _draft_payload(item: LinkedDraft) -> dict[str, object]:
    return {
        "id": str(item.id),
        "recommendation_id": str(item.recommendation_id),
        "recommendation_version": item.recommendation_version,
        "approval_id": str(item.approval_id),
        "kind": item.kind.value,
        "idempotency_key": item.idempotency_key,
        "frozen_input_versions": [_input_payload(value) for value in item.frozen_input_versions],
        "frozen_input_fingerprint": item.frozen_input_fingerprint,
        "frozen_evidence_graph_hash": item.frozen_evidence_graph_hash,
        "created_at": item.created_at.isoformat(),
        "status": item.status.value,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "blocked_at": item.blocked_at.isoformat() if item.blocked_at else None,
        "blocked_reason": item.blocked_reason,
    }


def _draft_from_payload(value: object) -> LinkedDraft:
    item = _mapping(value, "draft")
    return LinkedDraft(
        id=_uuid(item, "id"),
        recommendation_id=_uuid(item, "recommendation_id"),
        recommendation_version=_integer(item, "recommendation_version"),
        approval_id=_uuid(item, "approval_id"),
        kind=DownstreamDraftKind(_text(item, "kind")),
        idempotency_key=_text(item, "idempotency_key"),
        frozen_input_versions=tuple(
            _input_from_payload(entry)
            for entry in _sequence(item.get("frozen_input_versions"), "draft inputs")
        ),
        frozen_input_fingerprint=_text(item, "frozen_input_fingerprint"),
        frozen_evidence_graph_hash=_text(item, "frozen_evidence_graph_hash"),
        created_at=_datetime(item, "created_at"),
        status=DownstreamDraftStatus(_text(item, "status")),
        started_at=_optional_datetime(item.get("started_at")),
        blocked_at=_optional_datetime(item.get("blocked_at")),
        blocked_reason=_optional_text(item.get("blocked_reason")),
    )


def _input_payload(item: RecommendationInputVersion) -> dict[str, object]:
    return {
        "kind": item.kind.value,
        "resource_id": item.resource_id,
        "version": item.version,
        "sha256": item.sha256,
    }


def _input_from_payload(value: object) -> RecommendationInputVersion:
    item = _mapping(value, "input version")
    return RecommendationInputVersion(
        RecommendationInputKind(_text(item, "kind")),
        _text(item, "resource_id"),
        _text(item, "version"),
        _text(item, "sha256"),
    )


def _created_draft_payload(item: CreatedDownstreamDraft) -> dict[str, object]:
    return {
        "project_id": str(item.project_id),
        "draft_id": str(item.draft_id),
        "kind": item.kind.value,
    }


def _created_draft_from_payload(value: object) -> CreatedDownstreamDraft:
    item = _mapping(value, "created downstream draft")
    return CreatedDownstreamDraft(
        _uuid(item, "project_id"),
        _uuid(item, "draft_id"),
        DownstreamDraftKind(_text(item, "kind")),
    )


def _check_payload(item: DraftActionCheck) -> dict[str, object]:
    return {
        "workflow": workflow_payload(item.workflow),
        "draft_id": str(item.draft.id),
        "authorized": item.authorized,
        "problem_code": item.problem_code,
        "detail": item.detail,
    }


def _check_from_payload(value: object) -> DraftActionCheck:
    item = _mapping(value, "draft action check")
    workflow = workflow_from_payload(item.get("workflow"))
    draft_id = _uuid(item, "draft_id")
    draft = next(value for value in workflow.drafts if value.id == draft_id)
    return DraftActionCheck(
        workflow,
        draft,
        _boolean(item, "authorized"),
        _optional_text(item.get("problem_code")),
        _optional_text(item.get("detail")),
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} payload must be an object")
    return value


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} payload must be an array")
    return tuple(value)


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be text")
    return item


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional text field is invalid")
    return value


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{key} must be an integer")
    return item


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"{key} must be boolean")
    return item


def _uuid(value: Mapping[str, Any], key: str) -> UUID:
    return UUID(_text(value, key))


def _optional_uuid(value: object) -> UUID | None:
    return UUID(str(value)) if value is not None else None


def _datetime(value: Mapping[str, Any], key: str) -> datetime:
    return datetime.fromisoformat(_text(value, key))


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _texts(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    return tuple(str(item) for item in _sequence(value.get(key), key))


__all__ = [
    "command_result_from_payload",
    "command_result_payload",
    "evidence_graph_from_payload",
    "review_from_payload",
    "review_payload",
    "workflow_from_payload",
    "workflow_payload",
]
