"""PostgreSQL implementation of the durable Recommendation parent/child contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from geo_core.jobs.postgres import LostJobLease, WorkerLease
from geo_core.project_scope import set_project_scope
from geo_core.recommendations.errors import RecommendationSourceStale
from geo_core.recommendations.generation_artifact_contracts import (
    RecommendationTaskArtifactStore,
)
from geo_core.recommendations.generation_artifacts import RecommendationTaskArtifactRef
from geo_core.recommendations.generation_contracts import (
    RecommendationGenerationResult,
    RecommendationGenerationSpec,
    RecommendationGenerationStale,
    ResolvedGenerationPrompt,
    canonical_hash,
)
from geo_core.recommendations.generation_ports import (
    RecommendationPromptResolverPort,
)
from geo_core.recommendations.generation_result_recovery import (
    GovernedRecommendationModelResultLoader,
)
from geo_core.recommendations.generation_worker_contracts import (
    RECOMMENDATION_PARENT_JOB_KIND,
    RecommendationChildStatus,
    RecommendationModelOutcome,
    RecommendationModelResultRef,
    RecommendationModelRole,
    RecommendationModelTask,
    RecommendationParentClaim,
)
from geo_core.recommendations.postgres.generation_codec import (
    generation_result_payload,
)
from geo_core.recommendations.postgres.generation_worker_support import (
    assert_fenced_lease as _assert_lease,
    enqueue_outbox as _enqueue_outbox,
    require_parent_kind as _require_kind,
)
from geo_core.recommendations.postgres.rows import (
    assert_model_task_row,
    generation_spec_record_from_row,
    model_result_ref_from_row,
    task_artifact_from_row,
)
from geo_core.recommendations.postgres.evidence import (
    PostgresRecommendationEvidenceResolver,
)
from geo_core.recommendations.resolution import (
    RecommendationEvidenceKind,
    RecommendationEvidenceSelector,
)


class PostgresRecommendationGenerationWorkerRepository:
    """Keep every parent/child mutation in the durable Job's fenced transaction."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        prompts: RecommendationPromptResolverPort,
        artifacts: RecommendationTaskArtifactStore,
        model_results: GovernedRecommendationModelResultLoader,
    ) -> None:
        self._connect = connection_factory
        self._prompts = prompts
        self._artifacts = artifacts
        self._model_results = model_results

    def load_parent(self, lease: WorkerLease) -> RecommendationParentClaim:
        _require_kind(lease, RECOMMENDATION_PARENT_JOB_KIND)
        connection = self._open(lease.project_id)
        try:
            _assert_lease(connection, lease)
            row = connection.execute(
                _PARENT_SPEC_SELECT,
                (lease.project_id, lease.job_id),
            ).fetchone()
            if row is None:
                raise RecommendationGenerationStale(
                    "Recommendation parent specification is unavailable"
                )
            record = generation_spec_record_from_row(row)
            tasks = tuple(
                connection.execute(
                    _PARENT_CHILDREN_SELECT,
                    (lease.project_id, lease.job_id),
                ).fetchall()
            )
            outcomes = {
                RecommendationModelRole(str(item["role"])): self._outcome(
                    lease, item
                )
                for item in tasks
            }
            if len(outcomes) != len(tasks):
                raise RecommendationGenerationStale(
                    "Recommendation parent has duplicate model child roles"
                )
            connection.rollback()
            return RecommendationParentClaim(
                spec=record.spec,
                primary=outcomes.get(RecommendationModelRole.PRIMARY),
                arbiter=outcomes.get(RecommendationModelRole.ARBITER),
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def assert_current_inputs(self, spec: RecommendationGenerationSpec) -> None:
        connection = self._open(spec.project_id)
        try:
            resolver = PostgresRecommendationEvidenceResolver(connection, spec.project_id)
            selectors = tuple(
                RecommendationEvidenceSelector(
                    RecommendationEvidenceKind(item.ref_kind), item.resource_id
                )
                for item in spec.evidence.all_refs
            )
            current = resolver.resolve_current(
                project_id=spec.project_id,
                selectors=selectors,
            )
            expected = tuple(item.canonical_value() for item in spec.evidence.all_refs)
            observed = tuple(item.canonical_value() for item in current)
            if observed != expected:
                raise RecommendationGenerationStale(
                    "Recommendation evidence identity or validity changed"
                )
            self._assert_scope_locators(connection, spec, current)
            connection.rollback()
        except RecommendationSourceStale as error:
            connection.rollback()
            raise RecommendationGenerationStale(
                "Recommendation evidence is no longer current"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def resolve_prompt(
        self,
        *,
        spec: RecommendationGenerationSpec,
        role: RecommendationModelRole,
        structured_input: Mapping[str, object],
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> ResolvedGenerationPrompt:
        primary = role is RecommendationModelRole.PRIMARY
        binding = spec.prompt_binding if primary else spec.arbiter_binding
        if binding is None:
            raise RecommendationGenerationStale("Recommendation arbiter binding is absent")
        route = spec.route if primary else spec.arbiter_route
        configured_model = spec.configured_model if primary else spec.arbiter_configured_model
        policy = spec.model_policy if primary else spec.arbiter_model_policy
        capture = spec.capture_method if primary else spec.arbiter_capture_method
        search_mode = spec.search_mode if primary else spec.arbiter_search_mode
        if (
            route is None
            or configured_model is None
            or policy is None
            or capture is None
        ):
            raise RecommendationGenerationStale("Recommendation model lineage is incomplete")
        resolved = self._prompts.resolve(
            binding=binding,
            route=route,
            configured_model=configured_model,
            model_policy=policy,
            capture_method=capture,
            search_mode=search_mode,
            structured_input=structured_input,
            output_schema=output_schema,
            application_output_schema=application_output_schema,
        )
        if (
            resolved.binding != binding
            or resolved.route != route
            or resolved.configured_model != configured_model
            or resolved.policy != policy
            or resolved.capture_method != capture
            or resolved.search_mode != search_mode
            or resolved.structured_input_hash != canonical_hash(structured_input)
            or canonical_hash(resolved.output_schema) != canonical_hash(output_schema)
            or canonical_hash(resolved.application_output_schema)
            != canonical_hash(application_output_schema)
        ):
            raise RecommendationGenerationStale("Recommendation Prompt lineage changed")
        return resolved

    def prepare_model_task(
        self, task: RecommendationModelTask
    ) -> RecommendationTaskArtifactRef:
        return self._artifacts.put(task)

    def reserve_model_task(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
    ) -> None:
        self._assert_parent_task(connection, lease, task)
        connection.execute(
            "SELECT geo_reserve_recommendation_model_task(" + ", ".join(["%s"] * 35) + ")",
            _reservation_values(lease, task),
        )

    def activate_model_task(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
        artifact: RecommendationTaskArtifactRef,
    ) -> None:
        self._assert_parent_task(connection, lease, task)
        connection.execute(
            "SELECT geo_activate_recommendation_model_task(" + ", ".join(["%s"] * 12) + ")",
            (
                task.project_id,
                task.parent_job_id,
                lease.lease_token,
                lease.fencing_generation,
                task.child_job_id,
                artifact.uri,
                artifact.manifest_hash,
                artifact.payload_uri,
                artifact.payload_hash,
                artifact.content_hash,
                artifact.byte_size,
                datetime.now(UTC),
            ),
        )

    def load_model_task(self, lease: WorkerLease) -> RecommendationModelTask:
        expected_roles = {
            "recommendation.model.primary": RecommendationModelRole.PRIMARY,
            "recommendation.model.arbiter": RecommendationModelRole.ARBITER,
        }
        expected_role = expected_roles.get(lease.kind)
        if expected_role is None:
            raise RecommendationGenerationStale("Recommendation child has unsupported Job kind")
        connection = self._open(lease.project_id)
        try:
            _assert_lease(connection, lease)
            row = connection.execute(
                _CHILD_TASK_SELECT,
                (lease.project_id, lease.job_id),
            ).fetchone()
            if row is None or row["task_artifact_status"] != "active":
                raise RecommendationGenerationStale(
                    "Recommendation child task is absent or not active"
                )
            artifact = task_artifact_from_row(row)
            task = self._artifacts.load(
                artifact,
                project_id=lease.project_id,
                child_job_id=lease.job_id,
                expected_parent_input_hash=str(row["parent_input_hash"]),
            )
            assert_model_task_row(row, task)
            if task.role is not expected_role:
                raise RecommendationGenerationStale("Recommendation child task role changed")
            connection.rollback()
            return task
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_model_success(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
        reference: RecommendationModelResultRef,
    ) -> None:
        self._assert_child(connection, lease, task)
        changed = connection.execute(
            """UPDATE recommendation_model_call_lineage
               SET status = 'succeeded', model_attempt_id = %s, model_call_log_id = %s,
                   response_hash = %s, output_hash = %s,
                   derived_artifact_uri = %s,
                   derived_artifact_manifest_hash = %s,
                   derived_artifact_content_hash = %s, error_code = NULL,
                   updated_at = clock_timestamp()
               WHERE project_id = %s AND child_job_id = %s
                 AND role = %s AND status IN ('queued', 'running', 'retry_wait')""",
            (
                reference.model_attempt_id,
                reference.model_call_log_id,
                reference.response_hash,
                reference.output_hash,
                reference.artifact_uri,
                reference.artifact_manifest_hash,
                reference.artifact_content_hash,
                task.project_id,
                task.child_job_id,
                task.role.value,
            ),
        ).rowcount
        if changed != 1:
            raise LostJobLease("Recommendation model success was fenced or replay changed")

    def record_model_failure(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
        status: str,
        error_code: str,
    ) -> None:
        self._assert_child(connection, lease, task)
        if status not in {"retry_wait", "failed", "dead_lettered"} or not error_code:
            raise RecommendationGenerationStale("Recommendation child failure state is invalid")
        changed = connection.execute(
            """UPDATE recommendation_model_call_lineage
               SET status = %s, error_code = %s, updated_at = clock_timestamp()
               WHERE project_id = %s AND child_job_id = %s AND role = %s
                 AND status IN ('queued', 'running', 'retry_wait')""",
            (status, error_code, task.project_id, task.child_job_id, task.role.value),
        ).rowcount
        if changed != 1:
            raise LostJobLease("Recommendation model failure was fenced or replay changed")

    def wake_parent(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
    ) -> None:
        self._assert_child(connection, lease, task)
        connection.execute(
            """UPDATE durable_jobs SET next_run_at = LEAST(next_run_at, clock_timestamp()),
                       updated_at = clock_timestamp()
               WHERE id = %s AND project_id = %s
                 AND kind = %s AND status IN ('queued', 'retry_wait')""",
            (task.parent_job_id, task.project_id, RECOMMENDATION_PARENT_JOB_KIND),
        )
        _enqueue_outbox(
            connection,
            project_id=task.project_id,
            job_id=task.parent_job_id,
            topic=RECOMMENDATION_PARENT_JOB_KIND,
            idempotency_key=(
                f"recommendation-parent-wake:{task.parent_job_id}:{task.child_job_id}:"
                f"{lease.fencing_generation}"
            ),
        )

    def finalize_parent(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        result: RecommendationGenerationResult,
    ) -> None:
        _require_kind(lease, RECOMMENDATION_PARENT_JOB_KIND)
        _assert_lease(connection, lease)
        payload = generation_result_payload(result)
        changed = connection.execute(
            """INSERT INTO recommendation_generation_results(
                   project_id, job_id, recommendation_id, result_payload, result_hash
               ) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (project_id, job_id) DO NOTHING""",
            (
                lease.project_id,
                lease.job_id,
                result.recommendation.id,
                Jsonb(payload),
                canonical_hash(payload),
            ),
        ).rowcount
        if changed == 1:
            return
        row = connection.execute(
            """SELECT recommendation_id, result_hash FROM recommendation_generation_results
               WHERE project_id = %s AND job_id = %s""",
            (lease.project_id, lease.job_id),
        ).fetchone()
        if (
            row is None
            or row["recommendation_id"] != result.recommendation.id
            or row["result_hash"] != canonical_hash(payload)
        ):
            raise LostJobLease("Recommendation parent result replay changed")

    def _outcome(self, parent_lease: WorkerLease, row: Mapping[str, Any]) -> RecommendationModelOutcome:
        role = RecommendationModelRole(str(row["role"]))
        status = RecommendationChildStatus(str(row["child_status"]))
        lineage_status = RecommendationChildStatus(str(row["lineage_status"]))
        if not (
            status == lineage_status
            or (
                status is RecommendationChildStatus.RUNNING
                and lineage_status is RecommendationChildStatus.QUEUED
            )
        ):
            raise RecommendationGenerationStale("Recommendation child durable status differs from lineage")
        if status is not RecommendationChildStatus.SUCCEEDED:
            return RecommendationModelOutcome(
                child_job_id=_uuid(row, "child_job_id"),
                role=role,
                status=status,
                error_code=(str(row["error_code"]) if row["error_code"] is not None else None),
            )
        if row["task_artifact_status"] != "active":
            raise RecommendationGenerationStale("Recommendation result artifact is unavailable")
        task = self._task_from_row(row)
        reference = model_result_ref_from_row(row)
        return RecommendationModelOutcome(
            child_job_id=task.child_job_id,
            role=role,
            status=status,
            result=self._model_results.load(
                parent_lease=parent_lease,
                task=task,
                reference=reference,
            ),
        )

    def _task_from_row(self, row: Mapping[str, Any]) -> RecommendationModelTask:
        artifact = task_artifact_from_row(row)
        task = self._artifacts.load(
            artifact,
            project_id=_uuid(row, "project_id"),
            child_job_id=_uuid(row, "child_job_id"),
            expected_parent_input_hash=str(row["parent_input_hash"]),
        )
        assert_model_task_row(row, task)
        return task

    def _assert_child(self, connection: Any, lease: WorkerLease, task: RecommendationModelTask) -> None:
        if task.child_job_id != lease.job_id or task.project_id != lease.project_id:
            raise RecommendationGenerationStale("Recommendation child lease crosses task")
        _assert_lease(connection, lease)

    def _assert_parent_task(self, connection: Any, lease: WorkerLease, task: RecommendationModelTask) -> None:
        _require_kind(lease, RECOMMENDATION_PARENT_JOB_KIND)
        if task.project_id != lease.project_id or task.parent_job_id != lease.job_id:
            raise RecommendationGenerationStale("Recommendation child task crosses parent lease")
        _assert_lease(connection, lease)

    def _assert_scope_locators(self, connection: Any, spec: RecommendationGenerationSpec, current) -> None:
        by_identity = {(item.ref_kind, item.resource_id): item for item in current}
        for locator in spec.evidence.scope_locators:
            if locator.field_name == "campaign_id":
                row = connection.execute(
                    "SELECT 1 FROM geo_campaigns WHERE project_id = %s AND id = %s",
                    (spec.project_id, UUID(locator.resource_id)),
                ).fetchone()
                if row is None:
                    raise RecommendationGenerationStale("Recommendation Campaign scope changed")
                continue
            candidates = tuple(
                item for item in by_identity.values() if dict(item.locator) == dict(locator.locator)
            )
            if locator.field_name == "url_ref":
                valid = any(locator.resource_id in item.locator.values() for item in candidates)
            else:
                valid = any(item.resource_id == locator.resource_id for item in candidates)
            if not valid:
                raise RecommendationGenerationStale("Recommendation scope locator changed")

    def _open(self, project_id: UUID) -> Any:
        connection = self._connect()
        set_project_scope(connection, project_id)
        return connection
def _reservation_values(
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


def _uuid(row: Mapping[str, Any], key: str) -> UUID:
    value = row.get(key)
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as error:
        raise RecommendationGenerationStale(
            f"Recommendation row {key} is not a UUID"
        ) from error


_PARENT_SPEC_SELECT = """
SELECT spec.job_id, spec.project_id, spec.api_version, spec.spec_payload,
       spec.spec_payload_hash, spec.input_hash, spec.idempotency_key_hash,
       spec.valid_until, spec.created_by, spec.created_at
FROM recommendation_generation_specs AS spec
WHERE spec.project_id = %s AND spec.job_id = %s
"""

_PARENT_CHILDREN_SELECT = """
SELECT task.*, child.status AS child_status, lineage.status AS lineage_status,
       lineage.error_code, lineage.model_attempt_id, lineage.model_call_log_id,
       lineage.response_hash, lineage.output_hash, lineage.derived_artifact_uri,
       lineage.derived_artifact_manifest_hash, lineage.derived_artifact_content_hash
FROM recommendation_model_tasks AS task
JOIN durable_jobs AS child
  ON child.id = task.child_job_id AND child.project_id = task.project_id
JOIN recommendation_model_call_lineage AS lineage
  ON lineage.project_id = task.project_id AND lineage.child_job_id = task.child_job_id
WHERE task.project_id = %s AND task.parent_job_id = %s
ORDER BY task.role
"""

_CHILD_TASK_SELECT = """
SELECT task.* FROM recommendation_model_tasks AS task
WHERE task.project_id = %s AND task.child_job_id = %s
"""


__all__ = ["PostgresRecommendationGenerationWorkerRepository"]
