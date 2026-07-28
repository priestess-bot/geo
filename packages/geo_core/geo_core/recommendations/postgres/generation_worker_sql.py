"""SQL text and reservation encoding for Recommendation generation workers."""

from __future__ import annotations

from datetime import UTC, datetime

from geo_core.jobs.postgres import WorkerLease
from geo_core.recommendations.generation_contracts import canonical_hash
from geo_core.recommendations.generation_worker_contracts import RecommendationModelTask


def reservation_values(
    lease: WorkerLease, task: RecommendationModelTask
) -> tuple[object, ...]:
    prompt = task.prompt
    route = prompt.route
    return (
        task.project_id,
        task.parent_job_id,
        lease.lease_token,
        lease.fencing_generation,
        task.child_job_id,
        task.parent_input_hash,
        task.role.value,
        task.execution_backend.value,
        task.workflow_release_id,
        task.workflow_release_hash,
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
        datetime.now(UTC),
    )


PARENT_SPEC_SELECT = """
SELECT spec.job_id, spec.project_id, spec.api_version, spec.spec_payload,
       spec.spec_payload_hash, spec.input_hash, spec.idempotency_key_hash,
       spec.valid_until, spec.created_by, spec.created_at
FROM recommendation_generation_specs AS spec
WHERE spec.project_id = %s AND spec.job_id = %s
"""

PARENT_CHILDREN_SELECT = """
SELECT task.*, child.status AS child_status, lineage.status AS lineage_status,
       lineage.error_code,
       lineage.execution_backend AS lineage_execution_backend,
       lineage.model_attempt_id,
       lineage.model_call_log_id,
       lineage.response_hash, lineage.output_hash, lineage.derived_artifact_uri,
       lineage.derived_artifact_manifest_hash, lineage.derived_artifact_content_hash,
       lineage.dify_attempt_id, dify_result.output AS dify_output,
       dify_result.response_hash AS dify_response_hash,
       dify_result.configured_model AS dify_configured_model,
       dify_result.provider_reported_model AS dify_reported_model,
       dify_attempt.release_id AS dify_release_id,
       dify_attempt.dify_task_id, dify_attempt.dify_run_id,
       dify_attempt.prompt_tokens AS dify_prompt_tokens,
       dify_attempt.completion_tokens AS dify_completion_tokens,
       dify_attempt.total_steps AS dify_total_steps,
       dify_attempt.elapsed_seconds AS dify_elapsed_seconds,
       dify_release.release_hash AS dify_release_hash
FROM recommendation_model_tasks AS task
JOIN durable_jobs AS child
  ON child.id = task.child_job_id AND child.project_id = task.project_id
JOIN recommendation_model_call_lineage AS lineage
  ON lineage.project_id = task.project_id AND lineage.child_job_id = task.child_job_id
LEFT JOIN dify_workflow_execution_attempts AS dify_attempt
  ON dify_attempt.id = lineage.dify_attempt_id
 AND dify_attempt.project_id = lineage.project_id
 AND dify_attempt.job_id = lineage.child_job_id
 AND dify_attempt.execution_kind = 'business'
 AND dify_attempt.status = 'succeeded'
LEFT JOIN dify_workflow_execution_results AS dify_result
  ON dify_result.attempt_id = dify_attempt.id
 AND dify_result.project_id = dify_attempt.project_id
 AND dify_result.job_id = dify_attempt.job_id
LEFT JOIN dify_workflow_releases AS dify_release
  ON dify_release.id = dify_attempt.release_id
 AND dify_release.project_id = dify_attempt.project_id
WHERE task.project_id = %s AND task.parent_job_id = %s
ORDER BY task.role
"""

CHILD_TASK_SELECT = """
SELECT task.* FROM recommendation_model_tasks AS task
WHERE task.project_id = %s AND task.child_job_id = %s
"""


__all__ = [
    "CHILD_TASK_SELECT",
    "PARENT_CHILDREN_SELECT",
    "PARENT_SPEC_SELECT",
    "reservation_values",
]
