"""Frozen-lineage helpers used by Recommendation durable generation handlers."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid5

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LostJobLease,
    WorkerLease,
)
from geo_core.model_gateway.application import ModelCallExecution
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.recommendations.generation_contracts import (
    RecommendationGenerationOutputError,
    RecommendationGenerationSpec,
    RecommendationGenerationStale,
    ResolvedGenerationPrompt,
)
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationModelResultRef,
    RecommendationModelRole,
    RecommendationModelTask,
)


def model_task(
    lease: WorkerLease,
    spec: RecommendationGenerationSpec,
    role: RecommendationModelRole,
    prompt: ResolvedGenerationPrompt,
) -> RecommendationModelTask:
    primary = role is RecommendationModelRole.PRIMARY
    return RecommendationModelTask(
        child_job_id=uuid5(lease.job_id, f"recommendation-model:{role.value}"),
        parent_job_id=lease.job_id,
        project_id=lease.project_id,
        parent_input_hash=spec.input_hash,
        role=role,
        runtime_selection_id=(
            spec.runtime_selection_id
            if primary
            else required_uuid(spec.arbiter_runtime_selection_id)
        ),
        runtime_manifest_id=(
            spec.runtime_manifest_id
            if primary
            else required_uuid(spec.arbiter_runtime_manifest_id)
        ),
        runtime_manifest_hash=(
            spec.runtime_manifest_hash
            if primary
            else required_text(spec.arbiter_runtime_manifest_hash)
        ),
        runtime_option_id=(
            spec.runtime_option_id
            if primary
            else required_uuid(spec.arbiter_runtime_option_id)
        ),
        runtime_option_hash=(
            spec.runtime_option_hash
            if primary
            else required_text(spec.arbiter_runtime_option_hash)
        ),
        prompt=prompt,
        admitted_by=UUID(spec.created_by),
        artifact_expires_at=spec.valid_until,
    )


def assert_task_lease(task: RecommendationModelTask, lease: WorkerLease) -> None:
    if (
        task.child_job_id != lease.job_id
        or task.project_id != lease.project_id
        or task.role.job_kind != lease.kind
    ):
        raise RecommendationGenerationStale("model task differs from claimed child Job")


def assert_admitted_lineage(task: RecommendationModelTask, job: Any) -> None:
    prompt = task.prompt
    if (
        job.runtime_manifest_id != task.runtime_manifest_id
        or job.runtime_manifest_hash != task.runtime_manifest_hash
        or job.runtime_option_id != task.runtime_option_id
        or job.runtime_option_hash != task.runtime_option_hash
        or job.route != prompt.route
        or job.prompt_binding_id != prompt.binding.binding_id
        or job.prompt_release_id != prompt.binding.release_id
        or job.prompt_release_hash != prompt.binding.release_hash
        or job.purpose != prompt.binding.purpose
        or job.prompt_bundle_hash != prompt.prompt_bundle_hash
        or job.output_schema_hash != canonical_json_hash(prompt.output_schema)
        or job.application_output_schema_hash
        != canonical_json_hash(prompt.application_output_schema)
        or job.policy_version_id != prompt.policy.policy_version_id
        or job.policy_version_hash != prompt.policy.policy_version_hash
    ):
        raise RecommendationGenerationStale("Model Gateway admission changed frozen lineage")


def recoverable_result_ref(execution: ModelCallExecution) -> RecommendationModelResultRef:
    result = execution.result
    if result is None or any(
        value is None
        for value in (
            result.derived_artifact_reference,
            result.derived_artifact_manifest_hash,
            result.derived_artifact_content_hash,
            execution.terminal_event.output_hash,
        )
    ):
        raise RecommendationGenerationOutputError(
            "Recommendation model output lacks a governed recoverable artifact"
        )
    assert result is not None
    assert result.derived_artifact_reference is not None
    assert result.derived_artifact_manifest_hash is not None
    assert result.derived_artifact_content_hash is not None
    assert execution.terminal_event.output_hash is not None
    return RecommendationModelResultRef(
        model_attempt_id=execution.attempt.spec.id,
        model_call_log_id=result.call_log_id,
        response_hash=result.response_hash,
        output_hash=execution.terminal_event.output_hash,
        artifact_uri=result.derived_artifact_reference,
        artifact_manifest_hash=result.derived_artifact_manifest_hash,
        artifact_content_hash=result.derived_artifact_content_hash,
    )


def required_uuid(value: UUID | None) -> UUID:
    if value is None:
        raise RecommendationGenerationStale("arbiter runtime UUID is unavailable")
    return value


def required_text(value: str | None) -> str:
    if value is None:
        raise RecommendationGenerationStale("arbiter runtime hash is unavailable")
    return value


def assert_fenced_lease(connection: Any, lease: WorkerLease) -> None:
    row = connection.execute(
        """SELECT cancel_requested_at FROM durable_jobs
           WHERE id = %s AND project_id = %s AND kind = %s
             AND lease_token = %s AND fencing_generation = %s
             AND status IN ('running', 'finalizing')
             AND lease_expires_at > clock_timestamp() FOR UPDATE""",
        (
            lease.job_id,
            lease.project_id,
            lease.kind,
            lease.lease_token,
            lease.fencing_generation,
        ),
    ).fetchone()
    if row is None:
        raise LostJobLease("Recommendation Job lease was fenced")
    if row["cancel_requested_at"] is not None:
        raise JobCancellationRequested("Recommendation Job cancellation was requested")


def enqueue_outbox(
    connection: Any,
    *,
    project_id: UUID,
    job_id: UUID,
    topic: str,
    idempotency_key: str,
) -> None:
    connection.execute(
        """INSERT INTO broker_outbox(project_id, job_id, topic, payload, idempotency_key)
           VALUES (%s, %s, %s, %s::jsonb, %s)
           ON CONFLICT (project_id, idempotency_key) DO NOTHING""",
        (
            project_id,
            job_id,
            topic,
            json.dumps({"job_id": str(job_id), "project_id": str(project_id)}),
            idempotency_key,
        ),
    )


def require_parent_kind(lease: WorkerLease, kind: str) -> None:
    if lease.kind != kind:
        raise RecommendationGenerationStale(
            "Recommendation handler claimed an unsupported Job"
        )


__all__ = [
    "assert_admitted_lineage",
    "assert_fenced_lease",
    "assert_task_lease",
    "enqueue_outbox",
    "model_task",
    "recoverable_result_ref",
    "require_parent_kind",
]
