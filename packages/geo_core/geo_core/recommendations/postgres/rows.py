"""Strict row mappings shared by Recommendation PostgreSQL adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from geo_core.recommendations.generation_artifacts import RecommendationTaskArtifactRef
from geo_core.recommendations.downstream_contracts import ConcreteRecommendationDraft
from geo_core.recommendations.generation_contracts import (
    RecommendationGenerationResult,
    RecommendationGenerationSpec,
    canonical_hash,
)
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationModelResultRef,
    RecommendationModelRole,
    RecommendationModelTask,
)
from geo_core.workflow_runtime import WorkflowExecutionResult
from geo_core.recommendations.models import RecommendationWorkflow
from geo_core.recommendations.ports import (
    RecommendationCommandIdentity,
    RecommendationCommandOperation,
    RecommendationCommandRecord,
    RecommendationReview,
)
from geo_core.recommendations.postgres.codec import (
    command_result_from_payload,
    workflow_from_payload,
)
from geo_core.recommendations.postgres.downstream_codec import concrete_draft_from_payload
from geo_core.recommendations.postgres.generation_codec import (
    generation_result_from_payload,
    generation_spec_from_payload,
)


Row = Mapping[str, Any]


@dataclass(frozen=True)
class RecommendationGenerationSpecRecord:
    job_id: UUID
    api_version: int
    spec: RecommendationGenerationSpec
    idempotency_key_hash: str
    created_at: datetime


def workflow_from_row(row: Row) -> RecommendationWorkflow:
    payload = _mapping(row.get("workflow_payload"), "Recommendation workflow payload")
    _payload_hash(payload, row, "workflow_payload_hash")
    workflow = workflow_from_payload(payload)
    item = workflow.recommendation
    normalized = (
        row.get("project_id"),
        row.get("recommendation_id"),
        row.get("version"),
        row.get("status"),
        row.get("recommendation_type"),
        row.get("proposed_draft_kind"),
        row.get("evidence_graph_hash"),
        row.get("input_fingerprint"),
        row.get("valid_until"),
        str(row.get("created_by")),
    )
    observed = (
        item.project_id,
        item.id,
        item.version,
        item.status.value,
        item.recommendation_type.value,
        item.proposed_draft_kind.value if item.proposed_draft_kind else None,
        item.evidence.graph_hash,
        item.evidence.input_fingerprint,
        item.valid_until,
        item.created_by,
    )
    if normalized != observed:
        raise ValueError("Recommendation workflow row differs from its immutable payload")
    return workflow


def review_from_row(row: Row) -> RecommendationReview:
    return RecommendationReview(
        id=_uuid(row, "id"),
        project_id=_uuid(row, "project_id"),
        recommendation_id=_uuid(row, "recommendation_id"),
        recommendation_version=_integer(row, "recommendation_version"),
        evidence_graph_hash=_text(row, "evidence_graph_hash"),
        reviewed_by=_uuid(row, "reviewed_by"),
        notes=_text(row, "notes"),
        reviewed_at=_datetime(row, "reviewed_at"),
    )


def command_record_from_row(row: Row) -> RecommendationCommandRecord:
    operation = RecommendationCommandOperation(_text(row, "operation"))
    result_payload = _mapping(
        row.get("result_payload"), "Recommendation command result payload"
    )
    _payload_hash(result_payload, row, "result_payload_hash")
    return RecommendationCommandRecord(
        RecommendationCommandIdentity(
            project_id=_uuid(row, "project_id"),
            idempotency_key_hash=_text(row, "idempotency_key_hash"),
            operation=operation,
            request_hash=_text(row, "request_hash"),
        ),
        command_result_from_payload(
            operation,
            _text(row, "result_kind"),
            result_payload,
        ),
    )


def concrete_draft_from_row(row: Row) -> ConcreteRecommendationDraft:
    payload = _mapping(row.get("draft_payload"), "concrete Recommendation draft")
    _payload_hash(payload, row, "draft_payload_hash")
    draft = concrete_draft_from_payload(payload)
    source = draft.source
    expected = (
        _uuid(row, "id"),
        _uuid(row, "project_id"),
        _uuid(row, "recommendation_id"),
        _integer(row, "recommendation_version"),
        _uuid(row, "approval_id"),
        _text(row, "kind"),
        _text(row, "idempotency_key"),
        _text(row, "frozen_input_fingerprint"),
        _text(row, "frozen_evidence_graph_hash"),
        _datetime(row, "source_valid_until"),
        _text(row, "status"),
        _datetime(row, "created_at"),
        row.get("blocked_at"),
        row.get("blocked_reason"),
    )
    observed = (
        draft.id,
        source.project_id,
        source.recommendation_id,
        source.recommendation_version,
        source.approval_id,
        draft.kind.value,
        draft.idempotency_key,
        source.input_fingerprint,
        source.evidence_graph_hash,
        source.valid_until,
        draft.status.value,
        draft.created_at,
        draft.blocked_at,
        draft.blocked_reason,
    )
    if expected != observed:
        raise ValueError("Recommendation draft row differs from its immutable payload")
    return draft


def generation_spec_record_from_row(row: Row) -> RecommendationGenerationSpecRecord:
    payload = _mapping(row.get("spec_payload"), "Recommendation generation spec")
    _payload_hash(payload, row, "spec_payload_hash")
    spec = generation_spec_from_payload(payload)
    if (
        spec.project_id != _uuid(row, "project_id")
        or spec.input_hash != _text(row, "input_hash")
        or spec.valid_until != _datetime(row, "valid_until")
        or spec.created_by != str(row.get("created_by"))
    ):
        raise ValueError("Recommendation generation spec row differs from its payload")
    return RecommendationGenerationSpecRecord(
        job_id=_uuid(row, "job_id"),
        api_version=_integer(row, "api_version"),
        spec=spec,
        idempotency_key_hash=_text(row, "idempotency_key_hash"),
        created_at=_datetime(row, "created_at"),
    )


def generation_result_from_row(row: Row) -> RecommendationGenerationResult:
    payload = _mapping(row.get("result_payload"), "Recommendation generation result")
    _payload_hash(payload, row, "result_hash")
    result = generation_result_from_payload(payload)
    recommendation = result.recommendation
    if (
        recommendation.project_id != _uuid(row, "project_id")
        or recommendation.id != _uuid(row, "recommendation_id")
    ):
        raise ValueError("Recommendation generation result row differs from its payload")
    return result


def task_artifact_from_row(row: Row) -> RecommendationTaskArtifactRef:
    return RecommendationTaskArtifactRef(
        uri=_text(row, "task_artifact_uri"),
        manifest_hash=_text(row, "task_artifact_manifest_hash"),
        payload_uri=_text(row, "task_artifact_payload_uri"),
        payload_hash=_text(row, "task_payload_hash"),
        content_hash=_text(row, "task_artifact_content_hash"),
        byte_size=_integer(row, "task_artifact_byte_size"),
    )


def assert_model_task_row(row: Row, task: RecommendationModelTask) -> None:
    prompt = task.prompt
    route = prompt.route
    expected = (
        _uuid(row, "project_id"),
        _uuid(row, "parent_job_id"),
        _uuid(row, "child_job_id"),
        RecommendationModelRole(_text(row, "role")),
        _text(row, "execution_backend"),
        row.get("workflow_release_id"),
        row.get("workflow_release_hash"),
        _text(row, "parent_input_hash"),
        _uuid(row, "runtime_selection_id"),
        _uuid(row, "runtime_manifest_id"),
        _text(row, "runtime_manifest_hash"),
        _uuid(row, "runtime_option_id"),
        _text(row, "runtime_option_hash"),
        _uuid(row, "prompt_binding_id"),
        _integer(row, "prompt_binding_version"),
        _uuid(row, "prompt_frozen_state_id"),
        _integer(row, "prompt_state_version"),
        _uuid(row, "prompt_release_id"),
        _integer(row, "prompt_release_version"),
        _text(row, "prompt_release_hash"),
        _text(row, "prompt_purpose"),
        _text(row, "provider"),
        _text(row, "adapter_release_id"),
        _text(row, "adapter_release_hash"),
        _text(row, "model_release_id"),
        _text(row, "model_release_hash"),
        _text(row, "configured_model"),
        _text(row, "capture_method"),
        row.get("search_mode"),
        _text(row, "prompt_bundle_hash"),
        _text(row, "structured_input_hash"),
        _text(row, "output_schema_hash"),
        _text(row, "application_output_schema_hash"),
        _datetime(row, "task_artifact_expires_at"),
        _uuid(row, "admitted_by"),
    )
    observed = (
        task.project_id,
        task.parent_job_id,
        task.child_job_id,
        task.role,
        task.execution_backend.value,
        task.workflow_release_id,
        task.workflow_release_hash,
        task.parent_input_hash,
        task.runtime_selection_id,
        task.runtime_manifest_id,
        task.runtime_manifest_hash,
        task.runtime_option_id,
        task.runtime_option_hash,
        prompt.binding.binding_id,
        prompt.binding.binding_version,
        prompt.binding.frozen_state_id,
        prompt.binding.frozen_state_version,
        prompt.binding.release_id,
        prompt.binding.release_version,
        prompt.binding.release_hash,
        prompt.binding.purpose,
        route.provider,
        route.adapter_release_id,
        route.adapter_release_hash,
        route.model_release_id,
        route.model_release_hash,
        prompt.configured_model,
        prompt.capture_method.value,
        prompt.search_mode,
        prompt.prompt_bundle_hash,
        prompt.structured_input_hash,
        canonical_hash(prompt.output_schema),
        canonical_hash(prompt.application_output_schema),
        task.artifact_expires_at,
        task.admitted_by,
    )
    if expected != observed:
        raise ValueError("Recommendation model task row differs from its encrypted artifact")


def model_result_ref_from_row(row: Row) -> RecommendationModelResultRef:
    return RecommendationModelResultRef(
        model_attempt_id=_uuid(row, "model_attempt_id"),
        model_call_log_id=_uuid(row, "model_call_log_id"),
        response_hash=_text(row, "response_hash"),
        output_hash=_text(row, "output_hash"),
        artifact_uri=_text(row, "derived_artifact_uri"),
        artifact_manifest_hash=_text(row, "derived_artifact_manifest_hash"),
        artifact_content_hash=_text(row, "derived_artifact_content_hash"),
    )


def dify_result_from_row(row: Row) -> WorkflowExecutionResult:
    output = _mapping(row.get("dify_output"), "Recommendation Dify output")
    return WorkflowExecutionResult(
        output=dict(output),
        attempt_id=_uuid(row, "dify_attempt_id"),
        runtime_release_id=_uuid(row, "dify_release_id"),
        runtime_release_hash=_text(row, "dify_release_hash"),
        dify_task_id=(
            str(row["dify_task_id"]) if row.get("dify_task_id") is not None else None
        ),
        dify_run_id=_text(row, "dify_run_id"),
        configured_model=_text(row, "dify_configured_model"),
        provider_reported_model=(
            str(row["dify_reported_model"])
            if row.get("dify_reported_model") is not None
            else None
        ),
        prompt_tokens=row.get("dify_prompt_tokens"),
        completion_tokens=row.get("dify_completion_tokens"),
        total_steps=row.get("dify_total_steps"),
        elapsed_seconds=row.get("dify_elapsed_seconds"),
        response_hash=_text(row, "dify_response_hash"),
    )


def _payload_hash(payload: Mapping[str, Any], row: Row, key: str) -> None:
    if canonical_hash(payload) != _text(row, key):
        raise ValueError(f"stored Recommendation {key} is invalid")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _text(row: Row, key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Recommendation row {key} must be text")
    return value


def _integer(row: Row, key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Recommendation row {key} must be an integer")
    return value


def _uuid(row: Row, key: str) -> UUID:
    value = row.get(key)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Recommendation row {key} must be a UUID") from error


def _datetime(row: Row, key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime):
        raise ValueError(f"Recommendation row {key} must be a datetime")
    return value


__all__ = [
    "RecommendationGenerationSpecRecord",
    "assert_model_task_row",
    "command_record_from_row",
    "concrete_draft_from_row",
    "generation_result_from_row",
    "generation_spec_record_from_row",
    "model_result_ref_from_row",
    "review_from_row",
    "task_artifact_from_row",
    "workflow_from_row",
]
