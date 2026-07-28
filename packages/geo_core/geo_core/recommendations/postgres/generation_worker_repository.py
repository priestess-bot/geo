"""PostgreSQL implementation of the durable Recommendation parent/child contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
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
from geo_core.recommendations.generation_evidence import (
    GENERATION_EVIDENCE_CONTRACT_V1,
)
from geo_core.recommendations.generation_result_recovery import (
    GovernedRecommendationModelResultLoader,
)
from geo_core.recommendations.generation_worker_contracts import (
    RECOMMENDATION_PARENT_JOB_KIND,
    RecommendationChildStatus,
    RecommendationDifyResultRef,
    RecommendationExecutionBackend,
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
from geo_core.recommendations.postgres.generation_worker_sql import (
    CHILD_TASK_SELECT,
    PARENT_CHILDREN_SELECT,
    PARENT_SPEC_SELECT,
    reservation_values,
)
from geo_core.recommendations.postgres.generation_worker_rows import row_uuid
from geo_core.recommendations.postgres.rows import (
    assert_model_task_row,
    dify_result_from_row,
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
from geo_core.workflow_runtime import WorkflowRuntimeRelease


class RecommendationWorkflowReleaseResolver(Protocol):
    def resolve_active(
        self, *, project_id: UUID, purpose: str
    ) -> WorkflowRuntimeRelease | None: ...


class PostgresRecommendationGenerationWorkerRepository:
    """Keep every parent/child mutation in the durable Job's fenced transaction."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        prompts: RecommendationPromptResolverPort,
        artifacts: RecommendationTaskArtifactStore,
        model_results: GovernedRecommendationModelResultLoader,
        workflow_releases: RecommendationWorkflowReleaseResolver | None = None,
    ) -> None:
        self._connect = connection_factory
        self._prompts = prompts
        self._artifacts = artifacts
        self._model_results = model_results
        self._workflow_releases = workflow_releases

    def load_parent(self, lease: WorkerLease) -> RecommendationParentClaim:
        _require_kind(lease, RECOMMENDATION_PARENT_JOB_KIND)
        connection = self._open(lease.project_id)
        try:
            _assert_lease(connection, lease)
            row = connection.execute(
                PARENT_SPEC_SELECT,
                (lease.project_id, lease.job_id),
            ).fetchone()
            if row is None:
                raise RecommendationGenerationStale(
                    "Recommendation parent specification is unavailable"
                )
            record = generation_spec_record_from_row(row)
            tasks = tuple(
                connection.execute(
                    PARENT_CHILDREN_SELECT,
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
            legacy = (
                spec.evidence.contract_version == GENERATION_EVIDENCE_CONTRACT_V1
            )
            expected = tuple(spec.evidence.canonical_ref_values())
            observed = tuple(
                item.legacy_canonical_value() if legacy else item.canonical_value()
                for item in current
            )
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

    def resolve_workflow_release(
        self,
        *,
        task_role: RecommendationModelRole,
        prompt: ResolvedGenerationPrompt,
    ) -> tuple[UUID, str] | None:
        if task_role is RecommendationModelRole.ARBITER:
            return None
        if self._workflow_releases is None:
            raise RecommendationGenerationStale(
                "Recommendation Dify release resolver is unavailable"
            )
        release = self._workflow_releases.resolve_active(
            project_id=prompt.binding.project_id,
            purpose=prompt.binding.purpose,
        )
        if release is None:
            raise RecommendationGenerationStale(
                "Recommendation Dify workflow has no active release"
            )
        if (
            release.prompt_release_id != prompt.binding.release_id
            or release.prompt_release_hash != prompt.binding.release_hash
            or release.configured_model != prompt.configured_model
        ):
            raise RecommendationGenerationStale(
                "Recommendation Dify release differs from frozen Prompt lineage"
            )
        return release.id, release.release_hash

    def reserve_model_task(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        task: RecommendationModelTask,
    ) -> None:
        self._assert_parent_task(connection, lease, task)
        connection.execute(
            "SELECT geo_reserve_recommendation_model_task(" + ", ".join(["%s"] * 38) + ")",
            reservation_values(lease, task),
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
            "SELECT geo_activate_recommendation_model_task(" + ", ".join(["%s"] * 13) + ")",
            (
                task.project_id,
                task.parent_job_id,
                lease.lease_token,
                lease.fencing_generation,
                task.child_job_id,
                task.execution_backend.value,
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
                CHILD_TASK_SELECT,
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
        reference: RecommendationModelResultRef | RecommendationDifyResultRef,
    ) -> None:
        self._assert_child(connection, lease, task)
        if isinstance(reference, RecommendationDifyResultRef):
            if task.execution_backend is not RecommendationExecutionBackend.DIFY:
                raise RecommendationGenerationStale(
                    "Recommendation Dify result differs from frozen backend"
                )
            changed = connection.execute(
                """UPDATE recommendation_model_call_lineage
                   SET status = 'succeeded', dify_attempt_id = %s,
                       response_hash = %s, output_hash = %s, error_code = NULL,
                       updated_at = clock_timestamp()
                   WHERE project_id = %s AND child_job_id = %s
                     AND role = %s AND execution_backend = 'dify'
                     AND status IN ('queued', 'running', 'retry_wait')""",
                (
                    reference.attempt_id,
                    reference.response_hash,
                    reference.response_hash,
                    task.project_id,
                    task.child_job_id,
                    task.role.value,
                ),
            ).rowcount
            if changed != 1:
                raise LostJobLease(
                    "Recommendation Dify success was fenced or replay changed"
                )
            return
        if task.execution_backend is not RecommendationExecutionBackend.MODEL_GATEWAY:
            raise RecommendationGenerationStale(
                "Recommendation Model Gateway result differs from frozen backend"
            )
        changed = connection.execute(
            """UPDATE recommendation_model_call_lineage
               SET status = 'succeeded', model_attempt_id = %s, model_call_log_id = %s,
                   response_hash = %s, output_hash = %s,
                   derived_artifact_uri = %s,
                   derived_artifact_manifest_hash = %s,
                   derived_artifact_content_hash = %s, error_code = NULL,
                   updated_at = clock_timestamp()
               WHERE project_id = %s AND child_job_id = %s
                 AND role = %s AND execution_backend = 'model_gateway'
                 AND status IN ('queued', 'running', 'retry_wait')""",
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
                child_job_id=row_uuid(row, "child_job_id"),
                role=role,
                status=status,
                error_code=(str(row["error_code"]) if row["error_code"] is not None else None),
            )
        if row["task_artifact_status"] != "active":
            raise RecommendationGenerationStale("Recommendation result artifact is unavailable")
        task = self._task_from_row(row)
        backend = RecommendationExecutionBackend(str(row["lineage_execution_backend"]))
        if task.execution_backend is not backend:
            raise RecommendationGenerationStale(
                "Recommendation result backend differs from encrypted task"
            )
        if backend is RecommendationExecutionBackend.DIFY:
            dify_result = self._model_results.load_dify(
                parent_lease=parent_lease,
                task=task,
                result=dify_result_from_row(row),
            )
            return RecommendationModelOutcome(
                child_job_id=task.child_job_id,
                role=role,
                status=status,
                result=dify_result,
            )
        reference = model_result_ref_from_row(row)
        native_result = self._model_results.load(
            parent_lease=parent_lease,
            task=task,
            reference=reference,
        )
        return RecommendationModelOutcome(
            child_job_id=task.child_job_id,
            role=role,
            status=status,
            result=native_result,
        )

    def _task_from_row(self, row: Mapping[str, Any]) -> RecommendationModelTask:
        artifact = task_artifact_from_row(row)
        task = self._artifacts.load(
            artifact,
            project_id=row_uuid(row, "project_id"),
            child_job_id=row_uuid(row, "child_job_id"),
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
__all__ = ["PostgresRecommendationGenerationWorkerRepository"]
