from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from geo_core.model_gateway import (
    EffectiveModelLocation,
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayResult,
    RequestedModelLocation,
)
from geo_core.model_gateway.location import ModelLocationControl
from geo_core.recommendations import (
    ApprovedRecommendation,
    CreatedDownstreamDraft,
    InvalidatedRecommendation,
    PreparedDraftAction,
    RecommendationCommandOperation,
    RecommendationType,
)
from geo_core.recommendations.downstream_service import concrete_draft_from_approval
from geo_core.recommendations.models import DownstreamDraftKind
from geo_core.recommendations.generation_contracts import canonical_hash
from geo_core.recommendations.generation_ports import (
    RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
    RECOMMENDATION_OUTPUT_SCHEMA,
    structured_generation_input,
)
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationModelRole,
    RecommendationModelTask,
)
from geo_core.recommendations.postgres.codec import (
    command_result_from_payload,
    command_result_payload,
    workflow_from_payload,
    workflow_payload,
)
from geo_core.recommendations.postgres.downstream_codec import (
    concrete_draft_from_payload,
    concrete_draft_payload,
)
from geo_core.recommendations.postgres.generation_codec import (
    generation_spec_from_payload,
    generation_spec_payload,
)
from geo_core.recommendations.postgres.generation_worker_codec import (
    model_result_from_payload,
    model_result_hash,
    model_result_payload,
    model_task_from_payload,
    model_task_payload,
)
from geo_core.recommendations.postgres.rows import (
    assert_model_task_row,
    command_record_from_row,
    concrete_draft_from_row,
    generation_spec_record_from_row,
    model_result_ref_from_row,
    workflow_from_row,
)
from tests.unit.recommendations.generation_test_support import (
    NOW,
    PromptResolverStub,
    generation_spec,
)
from tests.unit.recommendations.test_application import (
    PROJECT_ID,
    _application,
    _approved_workflow,
    _create_submit_review,
    _principal,
)
from tests.unit.recommendations.test_generation_artifacts import _task
from tests.unit.recommendations.test_downstream_drafts import _approved


def test_workflow_json_codec_round_trips_exact_evidence_and_approval() -> None:
    application, _ = _application()
    workflow = _approved_workflow(application)

    loaded = workflow_from_payload(workflow_payload(workflow))

    assert loaded == workflow
    assert loaded.recommendation.evidence.graph_hash == workflow.recommendation.evidence.graph_hash


def test_command_result_codec_preserves_each_replay_result_shape() -> None:
    application, _ = _application()
    review = _create_submit_review(
        application,
        _principal("analyst"),
        _principal("owner"),
    ).value
    approved_workflow = _approved_workflow(application)
    draft = approved_workflow.drafts[0]
    values: tuple[tuple[RecommendationCommandOperation, object], ...] = (
        (RecommendationCommandOperation.REVIEW, review),
        (
            RecommendationCommandOperation.APPROVE,
            ApprovedRecommendation(
                approved_workflow,
                CreatedDownstreamDraft(PROJECT_ID, draft.id, draft.kind),
            ),
        ),
        (
            RecommendationCommandOperation.EXPIRE,
            InvalidatedRecommendation(approved_workflow, ()),
        ),
        (
            RecommendationCommandOperation.PREPARE_DRAFT_ACTION,
            PreparedDraftAction(
                check=_authorized_check(approved_workflow),
                cancelled_outbox_ids=(),
            ),
        ),
    )

    for operation, result in values:
        kind, payload = command_result_payload(result)
        assert command_result_from_payload(operation, kind, payload) == result


def test_generation_spec_codec_preserves_primary_and_arbiter_lineage() -> None:
    spec = generation_spec(with_arbiter=True)

    loaded = generation_spec_from_payload(generation_spec_payload(spec))

    assert loaded == spec
    assert loaded.input_hash == spec.input_hash


def test_generation_model_task_codec_preserves_exact_prompt_and_runtime_lineage() -> None:
    spec = generation_spec()
    prompt = PromptResolverStub().resolve(
        binding=spec.prompt_binding,
        route=spec.route,
        configured_model=spec.configured_model,
        model_policy=spec.model_policy,
        capture_method=spec.capture_method,
        search_mode=spec.search_mode,
        structured_input=structured_generation_input(spec.evidence),
        output_schema=RECOMMENDATION_OUTPUT_SCHEMA,
        application_output_schema=RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
    )
    task = RecommendationModelTask(
        child_job_id=uuid4(),
        parent_job_id=uuid4(),
        project_id=spec.project_id,
        parent_input_hash=spec.input_hash,
        role=RecommendationModelRole.PRIMARY,
        runtime_selection_id=spec.runtime_selection_id,
        runtime_manifest_id=spec.runtime_manifest_id,
        runtime_manifest_hash=spec.runtime_manifest_hash,
        runtime_option_id=spec.runtime_option_id,
        runtime_option_hash=spec.runtime_option_hash,
        prompt=prompt,
        admitted_by=uuid4(),
        artifact_expires_at=spec.valid_until,
    )

    payload = model_task_payload(task)

    assert model_task_from_payload(payload) == task
    assert "secret" not in repr(payload).lower()
    with pytest.raises(ValueError, match="unsupported Recommendation payload"):
        model_task_from_payload({**payload, "contract_version": "changed"})


def test_generation_model_result_codec_preserves_audited_provider_lineage() -> None:
    result = ModelGatewayResult(
        output={"accepted": True},
        call_log_id=uuid4(),
        provider_request_id="provider-request-1",
        configured_model="fixture-model",
        provider_reported_model="fixture-model-2026-07",
        prompt_tokens=21,
        completion_tokens=8,
        cost_usd=Decimal("0.0042"),
        finish_reason="stop",
        response_hash="a" * 64,
        provider="openai",
        adapter_release_id="openai-adapter-v1",
        adapter_release_hash="b" * 64,
        model_release_id="openai-model-v1",
        model_release_hash="c" * 64,
        latency_ms=120,
        citations=({"url": "https://example.test/evidence"},),
        tool_events=({"type": "search"},),
        usage_purpose="recommendations.recommendation",
        usage_audience=ModelAudience.INTERNAL_WORKER,
        capture_method=ModelCaptureMethod.PROVIDER_API,
        search_mode="web",
        usage_details={"total_tokens": 29},
        requested_location=RequestedModelLocation("AU", None, "en-AU", "en"),
        effective_location=EffectiveModelLocation(
            ModelLocationControl.COUNTRY,
            "AU",
            None,
            None,
            None,
            "d" * 64,
        ),
    )

    payload = model_result_payload(result)
    loaded = model_result_from_payload(payload)

    assert loaded == result
    assert model_result_hash(loaded) == model_result_hash(result)


@pytest.mark.parametrize(
    ("recommendation_type", "kind"),
    (
        (RecommendationType.EXPERIMENT, DownstreamDraftKind.EXPERIMENT_PLAN),
        (RecommendationType.GAP, DownstreamDraftKind.QUESTION_SET),
        (RecommendationType.OPTIONAL, DownstreamDraftKind.CONTENT_BRIEF),
        (
            RecommendationType.INSUFFICIENT_EVIDENCE,
            DownstreamDraftKind.SAMPLING_PLAN,
        ),
    ),
)
def test_concrete_draft_codec_and_row_cover_all_guarded_domain_shells(
    recommendation_type: RecommendationType,
    kind: DownstreamDraftKind,
) -> None:
    draft = concrete_draft_from_approval(_approved(recommendation_type, kind))
    assert draft is not None
    payload = concrete_draft_payload(draft)
    row = {
        "id": draft.id,
        "project_id": draft.source.project_id,
        "recommendation_id": draft.source.recommendation_id,
        "recommendation_version": draft.source.recommendation_version,
        "approval_id": draft.source.approval_id,
        "kind": draft.kind.value,
        "idempotency_key": draft.idempotency_key,
        "frozen_input_fingerprint": draft.source.input_fingerprint,
        "frozen_evidence_graph_hash": draft.source.evidence_graph_hash,
        "source_valid_until": draft.source.valid_until,
        "status": draft.status.value,
        "created_at": draft.created_at,
        "blocked_at": draft.blocked_at,
        "blocked_reason": draft.blocked_reason,
        "draft_payload": payload,
        "draft_payload_hash": canonical_hash(payload),
    }

    assert concrete_draft_from_payload(payload) == draft
    assert concrete_draft_from_row(row) == draft
    with pytest.raises(ValueError, match="differs"):
        concrete_draft_from_row({**row, "status": "blocked_source_stale"})


def test_workflow_and_generation_rows_cross_check_normalized_columns_and_payload_hash() -> None:
    application, _ = _application()
    workflow = _approved_workflow(application)
    item = workflow.recommendation
    payload = workflow_payload(workflow)
    workflow_row = {
        "project_id": item.project_id,
        "recommendation_id": item.id,
        "version": item.version,
        "status": item.status.value,
        "recommendation_type": item.recommendation_type.value,
        "proposed_draft_kind": item.proposed_draft_kind.value,
        "evidence_graph_hash": item.evidence.graph_hash,
        "input_fingerprint": item.evidence.input_fingerprint,
        "valid_until": item.valid_until,
        "created_by": item.created_by,
        "workflow_payload": payload,
        "workflow_payload_hash": canonical_hash(payload),
    }

    assert workflow_from_row(workflow_row) == workflow
    with pytest.raises(ValueError, match="differs"):
        workflow_from_row({**workflow_row, "status": "stale"})

    spec = generation_spec()
    spec_payload = generation_spec_payload(spec)
    spec_row = {
        "project_id": spec.project_id,
        "job_id": uuid4(),
        "api_version": 1,
        "input_hash": spec.input_hash,
        "idempotency_key_hash": "e" * 64,
        "spec_payload": spec_payload,
        "spec_payload_hash": canonical_hash(spec_payload),
        "valid_until": spec.valid_until,
        "created_by": spec.created_by,
        "created_at": NOW,
    }
    assert generation_spec_record_from_row(spec_row).spec == spec
    with pytest.raises(ValueError, match="payload_hash"):
        generation_spec_record_from_row(
            {**spec_row, "spec_payload_hash": "0" * 64}
        )


def test_command_and_model_child_rows_reject_changed_lineage() -> None:
    application, _ = _application()
    workflow = _approved_workflow(application)
    result_kind, result_payload = command_result_payload(workflow)
    row = {
        "project_id": workflow.recommendation.project_id,
        "idempotency_key_hash": "a" * 64,
        "operation": "create",
        "request_hash": "b" * 64,
        "result_kind": result_kind,
        "result_payload": result_payload,
        "result_payload_hash": canonical_hash(result_payload),
    }
    assert command_record_from_row(row).result == workflow

    task = _task()
    prompt = task.prompt
    route_value = prompt.route
    task_row = {
        "project_id": task.project_id,
        "parent_job_id": task.parent_job_id,
        "child_job_id": task.child_job_id,
        "role": task.role.value,
        "parent_input_hash": task.parent_input_hash,
        "runtime_selection_id": task.runtime_selection_id,
        "runtime_manifest_id": task.runtime_manifest_id,
        "runtime_manifest_hash": task.runtime_manifest_hash,
        "runtime_option_id": task.runtime_option_id,
        "runtime_option_hash": task.runtime_option_hash,
        "prompt_binding_id": prompt.binding.binding_id,
        "prompt_binding_version": prompt.binding.binding_version,
        "prompt_frozen_state_id": prompt.binding.frozen_state_id,
        "prompt_state_version": prompt.binding.frozen_state_version,
        "prompt_release_id": prompt.binding.release_id,
        "prompt_release_version": prompt.binding.release_version,
        "prompt_release_hash": prompt.binding.release_hash,
        "prompt_purpose": prompt.binding.purpose,
        "provider": route_value.provider,
        "adapter_release_id": route_value.adapter_release_id,
        "adapter_release_hash": route_value.adapter_release_hash,
        "model_release_id": route_value.model_release_id,
        "model_release_hash": route_value.model_release_hash,
        "configured_model": prompt.configured_model,
        "capture_method": prompt.capture_method.value,
        "search_mode": prompt.search_mode,
        "prompt_bundle_hash": prompt.prompt_bundle_hash,
        "structured_input_hash": prompt.structured_input_hash,
        "output_schema_hash": canonical_hash(prompt.output_schema),
        "application_output_schema_hash": canonical_hash(
            prompt.application_output_schema
        ),
        "task_artifact_expires_at": task.artifact_expires_at,
        "admitted_by": task.admitted_by,
    }
    assert_model_task_row(task_row, task)
    with pytest.raises(ValueError, match="encrypted artifact"):
        assert_model_task_row(
            {**task_row, "prompt_purpose": "evil.recommendations.recommendation"},
            task,
        )

    result_ref_row = {
        "model_attempt_id": uuid4(),
        "model_call_log_id": uuid4(),
        "response_hash": "1" * 64,
        "output_hash": "2" * 64,
        "derived_artifact_uri": "s3://model-artifacts/derived/manifest.json",
        "derived_artifact_manifest_hash": "3" * 64,
        "derived_artifact_content_hash": "4" * 64,
    }
    assert model_result_ref_from_row(result_ref_row).artifact_uri.startswith("s3://")


def _authorized_check(workflow):
    from geo_core.recommendations.models import DraftActionCheck

    return DraftActionCheck(workflow, workflow.drafts[0], True, None, None)
