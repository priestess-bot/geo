"""Strict JSON codec for draft-only Recommendation downstream handoffs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, TypedDict
from uuid import UUID

from geo_core.recommendations.downstream_contracts import (
    ConcreteDraftStatus,
    ConcreteRecommendationDraft,
    ContentBriefDraft,
    ContentBriefPayload,
    ExperimentPlanDraft,
    ExperimentPlanPayload,
    QuestionSetDraft,
    QuestionSetPayload,
    SamplingPlanDraft,
    SamplingPlanPayload,
    SourceRecommendationReference,
)
from geo_core.recommendations.evidence import (
    RecommendationInputKind,
    RecommendationInputVersion,
)
from geo_core.recommendations.models import DownstreamDraftKind


def concrete_draft_payload(value: ConcreteRecommendationDraft) -> dict[str, object]:
    return {
        "contract_version": "recommendation-concrete-draft-v1",
        "id": str(value.id),
        "kind": value.kind.value,
        "source": {
            "project_id": str(value.source.project_id),
            "recommendation_id": str(value.source.recommendation_id),
            "recommendation_version": value.source.recommendation_version,
            "approval_id": str(value.source.approval_id),
            "evidence_graph_hash": value.source.evidence_graph_hash,
            "input_versions": [
                {
                    "kind": item.kind.value,
                    "resource_id": item.resource_id,
                    "version": item.version,
                    "sha256": item.sha256,
                }
                for item in value.source.input_versions
            ],
            "input_fingerprint": value.source.input_fingerprint,
            "valid_until": value.source.valid_until.isoformat(),
        },
        "idempotency_key": value.idempotency_key,
        "payload": _domain_payload(value),
        "created_at": value.created_at.isoformat(),
        "status": value.status.value,
        "blocked_at": value.blocked_at.isoformat() if value.blocked_at else None,
        "blocked_reason": value.blocked_reason,
    }


def concrete_draft_from_payload(value: object) -> ConcreteRecommendationDraft:
    root = _mapping(value, "concrete Recommendation draft")
    if root.get("contract_version") != "recommendation-concrete-draft-v1":
        raise ValueError("concrete Recommendation draft contract changed")
    kind = DownstreamDraftKind(_text(root, "kind"))
    source_value = _mapping(root.get("source"), "concrete draft source")
    source = SourceRecommendationReference(
        project_id=_uuid(source_value, "project_id"),
        recommendation_id=_uuid(source_value, "recommendation_id"),
        recommendation_version=_integer(source_value, "recommendation_version"),
        approval_id=_uuid(source_value, "approval_id"),
        evidence_graph_hash=_text(source_value, "evidence_graph_hash"),
        input_versions=tuple(
            _input_from_payload(item)
            for item in _sequence(source_value.get("input_versions"), "source inputs")
        ),
        input_fingerprint=_text(source_value, "input_fingerprint"),
        valid_until=_datetime(source_value, "valid_until"),
    )
    common: _CommonDraftValues = {
        "id": _uuid(root, "id"),
        "source": source,
        "idempotency_key": _text(root, "idempotency_key"),
        "created_at": _datetime(root, "created_at"),
        "status": ConcreteDraftStatus(_text(root, "status")),
        "blocked_at": _optional_datetime(root.get("blocked_at")),
        "blocked_reason": _optional_text(root.get("blocked_reason")),
    }
    payload = _mapping(root.get("payload"), "concrete draft domain payload")
    if kind is DownstreamDraftKind.EXPERIMENT_PLAN:
        return ExperimentPlanDraft(
            **common,
            payload=ExperimentPlanPayload(
                objective=_text(payload, "objective"),
                hypothesis=_text(payload, "hypothesis"),
                validation_steps=_texts(payload, "validation_steps"),
                metric_comparison_refs=_texts(payload, "metric_comparison_refs"),
            ),
        )
    if kind is DownstreamDraftKind.QUESTION_SET:
        return QuestionSetDraft(
            **common,
            payload=QuestionSetPayload(
                objective=_text(payload, "objective"),
                question_refs=_texts(payload, "question_refs"),
                surface_refs=_texts(payload, "surface_refs"),
            ),
        )
    if kind is DownstreamDraftKind.CONTENT_BRIEF:
        return ContentBriefDraft(
            **common,
            payload=ContentBriefPayload(
                objective=_text(payload, "objective"),
                content_asset_ref=_text(payload, "content_asset_ref"),
                question_refs=_texts(payload, "question_refs"),
                approved_fact_refs=_texts(payload, "approved_fact_refs"),
            ),
        )
    return SamplingPlanDraft(
        **common,
        payload=SamplingPlanPayload(
            objective=_text(payload, "objective"),
            question_refs=_texts(payload, "question_refs"),
            surface_refs=_texts(payload, "surface_refs"),
            repetitions_per_question=_integer(payload, "repetitions_per_question"),
        ),
    )


class _CommonDraftValues(TypedDict):
    id: UUID
    source: SourceRecommendationReference
    idempotency_key: str
    created_at: datetime
    status: ConcreteDraftStatus
    blocked_at: datetime | None
    blocked_reason: str | None


def _domain_payload(value: ConcreteRecommendationDraft) -> dict[str, object]:
    payload = value.payload
    if isinstance(payload, ExperimentPlanPayload):
        return {
            "objective": payload.objective,
            "hypothesis": payload.hypothesis,
            "validation_steps": list(payload.validation_steps),
            "metric_comparison_refs": list(payload.metric_comparison_refs),
        }
    if isinstance(payload, QuestionSetPayload):
        return {
            "objective": payload.objective,
            "question_refs": list(payload.question_refs),
            "surface_refs": list(payload.surface_refs),
        }
    if isinstance(payload, ContentBriefPayload):
        return {
            "objective": payload.objective,
            "content_asset_ref": payload.content_asset_ref,
            "question_refs": list(payload.question_refs),
            "approved_fact_refs": list(payload.approved_fact_refs),
        }
    return {
        "objective": payload.objective,
        "question_refs": list(payload.question_refs),
        "surface_refs": list(payload.surface_refs),
        "repetitions_per_question": payload.repetitions_per_question,
    }


def _input_from_payload(value: object) -> RecommendationInputVersion:
    item = _mapping(value, "source input")
    return RecommendationInputVersion(
        RecommendationInputKind(_text(item, "kind")),
        _text(item, "resource_id"),
        _text(item, "version"),
        _text(item, "sha256"),
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be an array")
    return tuple(value)


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be text")
    return item


def _texts(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    return tuple(str(item) for item in _sequence(value.get(key), key))


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{key} must be an integer")
    return item


def _uuid(value: Mapping[str, Any], key: str) -> UUID:
    return UUID(_text(value, key))


def _datetime(value: Mapping[str, Any], key: str) -> datetime:
    return datetime.fromisoformat(_text(value, key))


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional concrete draft text is invalid")
    return value


__all__ = ["concrete_draft_from_payload", "concrete_draft_payload"]
