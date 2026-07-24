"""PostgreSQL coordination for deterministic Synthetic model-call child Jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import re
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.jobs.postgres import JobCancellationRequested, WorkerLease
from geo_core.project_scope import set_project_scope
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.child_model_calls import (
    SYNTHETIC_MODEL_CHILD_KIND,
    SyntheticChildCallState,
    SyntheticChildCallStatus,
    SyntheticChildModelCallTask,
)
from geo_core.synthetic_lab.child_task_artifacts import (
    SyntheticChildTaskArtifactRef,
    SyntheticChildTaskArtifactStore,
)
from geo_core.synthetic_lab.execution_contracts import (
    SyntheticExecutionError,
    SyntheticModelResult,
)


_REASON = re.compile(r"^[a-z][a-z0-9_.:-]{0,99}$")


class SyntheticChildResultLoader(Protocol):
    def load(
        self,
        *,
        parent_lease: WorkerLease,
        task: SyntheticChildModelCallTask,
        model_attempt_id: UUID,
        model_call_id: UUID,
        output_hash: str,
        response_hash: str,
        configured_model: str,
        reported_model: str | None,
    ) -> SyntheticModelResult: ...


class PostgresSyntheticChildCallRepository:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        artifacts: SyntheticChildTaskArtifactStore,
        results: SyntheticChildResultLoader,
    ) -> None:
        self._connection_factory = connection_factory
        self._artifacts = artifacts
        self._results = results

    def resolve_or_stage(
        self,
        task: SyntheticChildModelCallTask,
        *,
        parent_lease: WorkerLease,
    ) -> SyntheticChildCallState:
        _assert_parent_lease(task, parent_lease)
        current = self._state_row(task.project_id, task.child_job_id)
        if current is not None:
            return self._state(task, current, parent_lease=parent_lease)
        artifact = self._artifacts.put(task)
        connection = self._open(task.project_id)
        try:
            frozen = task.prompt.frozen
            runtime = task.runtime_inputs
            route = frozen.route
            row = connection.execute(
                """SELECT * FROM geo_enqueue_synthetic_model_call_child(
                       %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s
                   )""",
                (
                    task.project_id,
                    task.parent_job_id,
                    parent_lease.lease_token,
                    parent_lease.fencing_generation,
                    task.child_job_id,
                    task.parent_job_kind,
                    task.parent_task_input_hash,
                    task.step_key,
                    task.model_job_version,
                    runtime.fact_snapshot_id,
                    runtime.fact_snapshot_hash,
                    runtime.profile_version_id,
                    runtime.profile_hash,
                    runtime.prompt_release_id,
                    runtime.prompt_release_hash,
                    frozen.binding_id,
                    frozen.binding_version,
                    frozen.frozen_state_id,
                    frozen.frozen_state_version,
                    frozen.release_id,
                    frozen.release_version,
                    frozen.release_hash,
                    frozen.program_kind.value,
                    frozen.purpose,
                    task.admitted_by,
                    frozen.model_policy_hash,
                    route.provider,
                    route.adapter_release_id,
                    route.adapter_release_hash,
                    route.model_release_id,
                    route.model_release_hash,
                    frozen.configured_model,
                    frozen.runtime_manifest_id,
                    frozen.runtime_manifest_hash,
                    frozen.runtime_option_id,
                    frozen.runtime_option_hash,
                    None,
                    task.prompt.prompt_bundle_hash,
                    task.prompt.structured_input_hash,
                    canonical_hash(task.prompt.output_schema),
                    canonical_hash(task.prompt.application_output_schema),
                    artifact.uri,
                    artifact.artifact_hash,
                    task.deterministic_seed,
                    task.max_output_tokens,
                    task.input_hash,
                ),
            ).fetchone()
            if row is None or row["child_job_id"] != task.child_job_id:
                raise SyntheticExecutionError("child model-call enqueue returned no exact Job")
            connection.commit()
        except psycopg.Error as error:
            connection.rollback()
            raise SyntheticExecutionError("PostgreSQL rejected child model-call enqueue") from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        staged = self._state_row(task.project_id, task.child_job_id)
        if staged is None:
            raise SyntheticExecutionError("child model-call state is unavailable after enqueue")
        return self._state(task, staged, parent_lease=parent_lease)

    def load_claimed(self, lease: WorkerLease) -> SyntheticChildModelCallTask:
        if lease.kind != SYNTHETIC_MODEL_CHILD_KIND:
            raise SyntheticExecutionError("worker claimed a non-model Synthetic child")
        connection = self._open(lease.project_id)
        try:
            row = connection.execute(
                """SELECT child.task_artifact_uri, child.task_artifact_hash,
                          child.child_input_hash, child.parent_job_id,
                          child.prompt_state_version, child.admitted_by,
                          durable.status, durable.lease_owner, durable.lease_token,
                          durable.lease_expires_at, durable.fencing_generation,
                          durable.cancel_requested_at, parent.status AS parent_status,
                          parent.error_code AS parent_error_code,
                          parent.cancel_requested_at AS parent_cancel_requested_at
                   FROM synthetic_lab_model_call_children AS child
                   JOIN durable_jobs AS durable
                     ON durable.id = child.child_job_id
                    AND durable.project_id = child.project_id
                   JOIN durable_jobs AS parent
                     ON parent.id = child.parent_job_id
                    AND parent.project_id = child.project_id
                   WHERE child.project_id = %s AND child.child_job_id = %s""",
                (lease.project_id, lease.job_id),
            ).fetchone()
            if row is None:
                raise SyntheticExecutionError("claimed child model-call task is unavailable")
            _assert_claimed_row(row, lease)
            task = self._artifacts.load(
                SyntheticChildTaskArtifactRef(
                    uri=row["task_artifact_uri"],
                    artifact_hash=row["task_artifact_hash"],
                ),
                project_id=lease.project_id,
                child_job_id=lease.job_id,
                expected_input_hash=row["child_input_hash"],
            )
            _assert_child_task_row_lineage(task, row)
            return task
        finally:
            connection.rollback()
            connection.close()

    def block_unstarted(self, *, project_id: UUID, parent_job_id: UUID, reason: str) -> None:
        if _REASON.fullmatch(reason) is None:
            raise SyntheticExecutionError("child cancellation reason is invalid")
        connection = self._open(project_id)
        try:
            connection.execute(
                "SELECT geo_block_synthetic_unstarted_model_call_children(%s, %s, %s)",
                (project_id, parent_job_id, reason),
            ).fetchone()
            connection.commit()
        except psycopg.Error as error:
            connection.rollback()
            raise SyntheticExecutionError("PostgreSQL rejected child cancellation") from error
        finally:
            connection.close()

    def assert_parent_active(self, lease: WorkerLease) -> None:
        connection = self._open(lease.project_id)
        try:
            row = connection.execute(
                """SELECT child.cancel_requested_at,
                          parent.status AS parent_status,
                          parent.error_code AS parent_error_code,
                          parent.cancel_requested_at AS parent_cancel_requested_at
                   FROM durable_jobs AS child
                   JOIN durable_jobs AS parent
                     ON parent.id = child.parent_job_id
                    AND parent.project_id = child.project_id
                   WHERE child.id = %s AND child.project_id = %s""",
                (lease.job_id, lease.project_id),
            ).fetchone()
            if row is None:
                raise SyntheticExecutionError("child parent lineage is unavailable")
            parent_active = row["parent_status"] in {"running", "finalizing"} or (
                row["parent_status"] == "retry_wait"
                and row["parent_error_code"] == "synthetic_child_pending"
            )
            if (
                row["cancel_requested_at"] is not None
                or row["parent_cancel_requested_at"] is not None
                or not parent_active
            ):
                raise JobCancellationRequested("Synthetic child parent is inactive")
        finally:
            connection.rollback()
            connection.close()

    def _state(
        self,
        expected: SyntheticChildModelCallTask,
        row: Mapping[str, Any],
        *,
        parent_lease: WorkerLease,
    ) -> SyntheticChildCallState:
        task = self._artifacts.load(
            SyntheticChildTaskArtifactRef(
                uri=row["task_artifact_uri"],
                artifact_hash=row["task_artifact_hash"],
            ),
            project_id=expected.project_id,
            child_job_id=expected.child_job_id,
            expected_input_hash=row["child_input_hash"],
        )
        _assert_child_task_row_lineage(task, row)
        if task.input_hash != expected.input_hash:
            return SyntheticChildCallState(
                task=task,
                status=SyntheticChildCallStatus.FAILED,
                failure_code="immutable_input_changed",
            )
        status = SyntheticChildCallStatus(row["status"])
        result = None
        if status is SyntheticChildCallStatus.SUCCEEDED:
            attempt_id = row["model_attempt_id"]
            model_call_id = row["gateway_call_log_id"]
            output_hash = row["output_hash"]
            response_hash = row["response_hash"]
            configured_model = row["model_configured_model"]
            reported_model = row["model_reported_model"]
            if (
                not isinstance(attempt_id, UUID)
                or not isinstance(model_call_id, UUID)
                or not isinstance(output_hash, str)
                or not isinstance(response_hash, str)
                or not isinstance(configured_model, str)
                or (reported_model is not None and not isinstance(reported_model, str))
            ):
                raise SyntheticExecutionError("successful child lacks governed result lineage")
            result = self._results.load(
                parent_lease=parent_lease,
                task=task,
                model_attempt_id=attempt_id,
                model_call_id=model_call_id,
                output_hash=output_hash,
                response_hash=response_hash,
                configured_model=configured_model,
                reported_model=reported_model,
            )
        return SyntheticChildCallState(
            task=task,
            status=status,
            result=result,
            failure_code=(
                str(row["failure_code"])
                if status
                in {
                    SyntheticChildCallStatus.FAILED,
                    SyntheticChildCallStatus.CANCELLED,
                    SyntheticChildCallStatus.UNKNOWN_OUTCOME,
                }
                else None
            ),
        )

    def _state_row(self, project_id: UUID, child_job_id: UUID) -> Mapping[str, Any] | None:
        connection = self._open(project_id)
        try:
            return connection.execute(
                """SELECT status.*, child.task_artifact_uri, child.task_artifact_hash,
                          child.child_input_hash, child.prompt_state_version,
                          child.admitted_by
                   FROM synthetic_lab_model_call_child_status AS status
                   JOIN synthetic_lab_model_call_children AS child
                     ON child.project_id = status.project_id
                    AND child.child_job_id = status.child_job_id
                   WHERE status.project_id = %s AND status.child_job_id = %s""",
                (project_id, child_job_id),
            ).fetchone()
        finally:
            connection.rollback()
            connection.close()

    def _open(self, project_id: UUID) -> Any:
        connection = self._connection_factory()
        set_project_scope(connection, project_id)
        return connection


def build_synthetic_child_repository(
    database_url: str,
    *,
    artifacts: SyntheticChildTaskArtifactStore,
    results: SyntheticChildResultLoader,
) -> PostgresSyntheticChildCallRepository:
    normalized = database_url.strip()
    if not normalized:
        raise ValueError("Synthetic child PostgreSQL URL is required")

    def connect() -> Any:
        return psycopg.connect(normalized, row_factory=dict_row)

    return PostgresSyntheticChildCallRepository(connect, artifacts=artifacts, results=results)


def _assert_parent_lease(task: SyntheticChildModelCallTask, lease: WorkerLease) -> None:
    if (
        lease.project_id != task.project_id
        or lease.job_id != task.parent_job_id
        or lease.kind != task.parent_job_kind
    ):
        raise SyntheticExecutionError("child task does not match its parent lease")


def _assert_claimed_row(row: Mapping[str, Any], lease: WorkerLease) -> None:
    parent_active = row["parent_status"] in {"running", "finalizing"} or (
        row["parent_status"] == "retry_wait"
        and row["parent_error_code"] == "synthetic_child_pending"
    )
    if (
        row["status"] not in {"running", "finalizing"}
        or row["lease_owner"] != lease.worker_id
        or row["lease_token"] != lease.lease_token
        or row["fencing_generation"] != lease.fencing_generation
        or row["lease_expires_at"] is None
        or row["lease_expires_at"] <= datetime.now(UTC)
        or row["cancel_requested_at"] is not None
        or row["parent_cancel_requested_at"] is not None
        or not parent_active
    ):
        raise SyntheticExecutionError("child model-call lease or parent is inactive")


def _assert_child_task_row_lineage(
    task: SyntheticChildModelCallTask,
    row: Mapping[str, Any],
) -> None:
    if (
        row.get("prompt_state_version") != task.prompt.frozen.frozen_state_version
        or row.get("admitted_by") != task.admitted_by
    ):
        raise SyntheticExecutionError(
            "child task artifact differs from frozen Prompt state or admission actor"
        )


__all__ = [
    "PostgresSyntheticChildCallRepository",
    "SyntheticChildResultLoader",
    "build_synthetic_child_repository",
]
