"""Project-scoped persistence for Dify releases and execution attempts."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.secrets import SecretVersionHandle

from .contracts import WorkflowRuntimeRelease
from .errors import WorkflowConfigurationError
from .published import PublishedWorkflowSnapshot


class PostgresWorkflowRuntimeRepository:
    def __init__(self, store: PostgresDurableJobStore) -> None:
        self._store = store

    def resolve_active(self, *, project_id: UUID, purpose: str) -> WorkflowRuntimeRelease | None:
        connection = self._store.open_project(project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT release.*, binding.binding_version,
                              prompt_release.system_template AS prompt_system_template,
                              prompt_release.user_template AS prompt_user_template,
                              secret.status AS secret_status,
                              prompt_binding.release_id AS current_prompt_release_id,
                              prompt_state.status AS prompt_release_status
                       FROM dify_workflow_bindings binding
                       JOIN dify_workflow_releases release
                         ON release.id = binding.release_id
                        AND release.project_id = binding.project_id
                        AND release.purpose = binding.purpose
                        AND release.release_hash = binding.release_hash
                       JOIN secret_versions secret
                         ON secret.reference_id = release.api_secret_reference_id
                        AND secret.project_id = release.project_id
                        AND secret.purpose = release.api_secret_purpose
                        AND secret.version = release.api_secret_version
                       JOIN prompt_program_releases prompt_release
                         ON prompt_release.id = release.prompt_release_id
                        AND prompt_release.project_id = release.project_id
                        AND prompt_release.program_id = release.prompt_program_id
                       LEFT JOIN LATERAL (
                           SELECT item.release_id
                           FROM prompt_program_bindings item
                           WHERE item.project_id = release.project_id
                             AND item.purpose = release.purpose
                           ORDER BY item.binding_version DESC
                           LIMIT 1
                       ) prompt_binding ON true
                       LEFT JOIN LATERAL (
                           SELECT state.status
                           FROM prompt_program_release_states state
                           WHERE state.project_id = release.project_id
                             AND state.release_id = release.prompt_release_id
                           ORDER BY state.version DESC
                           LIMIT 1
                       ) prompt_state ON true
                       WHERE binding.project_id = %s AND binding.purpose = %s
                       ORDER BY binding.binding_version DESC
                       LIMIT 1""",
                    (project_id, purpose),
                )
            )
            connection.rollback()
        finally:
            connection.close()
        if row is None:
            return None
        if row["secret_status"] != "active":
            raise WorkflowConfigurationError(
                "Dify API credential is no longer active; rotate and activate a new workflow release",
                code="dify_secret_inactive",
            )
        return _release(row)

    def get_release(self, *, project_id: UUID, release_id: UUID) -> WorkflowRuntimeRelease:
        connection = self._store.open_project(project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT release.*, 0 AS binding_version,
                              prompt_release.system_template AS prompt_system_template,
                              prompt_release.user_template AS prompt_user_template
                       FROM dify_workflow_releases release
                       JOIN prompt_program_releases prompt_release
                         ON prompt_release.id = release.prompt_release_id
                        AND prompt_release.project_id = release.project_id
                        AND prompt_release.program_id = release.prompt_program_id
                       WHERE release.project_id = %s AND release.id = %s""",
                    (project_id, release_id),
                )
            )
            connection.rollback()
        finally:
            connection.close()
        if row is None:
            raise WorkflowConfigurationError(
                "Dify workflow release was not found", code="dify_release_not_found"
            )
        return _release(row)

    def begin_business_attempt(
        self,
        lease: WorkerLease,
        *,
        release: WorkflowRuntimeRelease,
        published_snapshot_id: UUID | None = None,
        context_hash: str,
        request_hash: str,
    ) -> UUID:
        attempt_id = uuid4()
        with self._store.fenced_transaction(lease) as connection:
            attempt_number_row = _one(
                connection.execute(
                    """SELECT COALESCE(MAX(attempt_number), 0) + 1
                              AS next_attempt_number
                       FROM dify_workflow_execution_attempts
                       WHERE project_id = %s AND job_id = %s""",
                    (lease.project_id, lease.job_id),
                )
            )
            if attempt_number_row is None:
                raise WorkflowConfigurationError("Dify attempt sequence could not be allocated")
            attempt_number = int(attempt_number_row["next_attempt_number"])
            connection.execute(
                """INSERT INTO dify_workflow_execution_attempts (
                       id, project_id, release_id, job_id, execution_kind,
                       attempt_number, fencing_generation, published_snapshot_id,
                       status, context_hash, request_hash
                   ) VALUES (%s, %s, %s, %s, 'business', %s, %s, %s, 'running', %s, %s)""",
                (
                    attempt_id,
                    lease.project_id,
                    release.id,
                    lease.job_id,
                    attempt_number,
                    lease.fencing_generation,
                    published_snapshot_id,
                    context_hash,
                    request_hash,
                ),
            )
        return attempt_id

    def finish_business_attempt(
        self, lease: WorkerLease, *, attempt_id: UUID, values: Mapping[str, object]
    ) -> None:
        with self._store.fenced_transaction(lease) as connection:
            self._finish(
                connection, project_id=lease.project_id, attempt_id=attempt_id, values=values
            )

    def begin_canary_attempt(
        self,
        *,
        release: WorkflowRuntimeRelease,
        published_snapshot_id: UUID | None = None,
        context_hash: str,
        request_hash: str,
    ) -> UUID:
        attempt_id = uuid4()
        connection = self._store.open_project(release.project_id)
        try:
            attempt_number_row = _one(
                connection.execute(
                    """SELECT COALESCE(MAX(attempt_number), 0) + 1
                              AS next_attempt_number
                       FROM dify_workflow_execution_attempts
                       WHERE project_id = %s AND release_id = %s
                         AND execution_kind = 'canary'""",
                    (release.project_id, release.id),
                )
            )
            if attempt_number_row is None:
                raise WorkflowConfigurationError("Dify canary sequence could not be allocated")
            attempt_number = int(attempt_number_row["next_attempt_number"])
            connection.execute(
                """INSERT INTO dify_workflow_execution_attempts (
                       id, project_id, release_id, execution_kind, attempt_number,
                       published_snapshot_id, status, context_hash, request_hash
                   ) VALUES (%s, %s, %s, 'canary', %s, %s, 'running', %s, %s)""",
                (
                    attempt_id,
                    release.project_id,
                    release.id,
                    attempt_number,
                    published_snapshot_id,
                    context_hash,
                    request_hash,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return attempt_id

    def record_published_snapshot(
        self,
        *,
        release: WorkflowRuntimeRelease,
        snapshot: PublishedWorkflowSnapshot,
    ) -> UUID:
        if snapshot.purpose != release.purpose or snapshot.app_id != release.dify_app_id:
            raise WorkflowConfigurationError(
                "published Dify snapshot does not match its runtime release",
                code="dify_snapshot_release_mismatch",
            )
        connection = self._store.open_project(release.project_id)
        try:
            snapshot_id = uuid4()
            inserted = _one(
                connection.execute(
                    """INSERT INTO dify_workflow_published_snapshots (
                       id, project_id, release_id, purpose, dify_app_id,
                       dify_workflow_id, workflow_hash, snapshot_hash,
                       prompt_nodes, input_variables, graph_nodes,
                       published_at, observed_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s)
                   ON CONFLICT (project_id, release_id, purpose,
                                dify_workflow_id, snapshot_hash) DO NOTHING
                   RETURNING id""",
                    (
                        snapshot_id,
                        release.project_id,
                        release.id,
                        release.purpose,
                        snapshot.app_id,
                        snapshot.workflow_id,
                        snapshot.workflow_hash,
                        snapshot.snapshot_hash,
                        Jsonb(list(snapshot.prompt_nodes)),
                        Jsonb(list(snapshot.input_variables)),
                        Jsonb(list(snapshot.graph_nodes)),
                        snapshot.published_at,
                        snapshot.observed_at,
                    ),
                )
            )
            if inserted is None:
                inserted = _one(
                    connection.execute(
                        """SELECT id FROM dify_workflow_published_snapshots
                       WHERE project_id = %s AND release_id = %s AND purpose = %s
                         AND dify_workflow_id = %s AND snapshot_hash = %s""",
                        (
                            release.project_id,
                            release.id,
                            release.purpose,
                            snapshot.workflow_id,
                            snapshot.snapshot_hash,
                        ),
                    )
                )
            if inserted is None:
                raise WorkflowConfigurationError("Dify snapshot could not be persisted")
            connection.commit()
            return inserted["id"]
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finish_canary_attempt(
        self,
        *,
        project_id: UUID,
        attempt_id: UUID,
        values: Mapping[str, object],
    ) -> None:
        connection = self._store.open_project(project_id)
        try:
            self._finish(connection, project_id=project_id, attempt_id=attempt_id, values=values)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _finish(
        connection: Any,
        *,
        project_id: UUID,
        attempt_id: UUID,
        values: Mapping[str, object],
    ) -> None:
        status = str(values["status"])
        if status == "succeeded":
            changed = connection.execute(
                """UPDATE dify_workflow_execution_attempts
                   SET status = 'succeeded', dify_task_id = %s, dify_run_id = %s,
                       reported_workflow_id = %s, output_hash = %s,
                       prompt_tokens = %s, completion_tokens = %s, total_steps = %s,
                       elapsed_seconds = %s, http_status = %s, retryable = false,
                       finished_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s AND status = 'running'""",
                (
                    values.get("dify_task_id"),
                    values.get("dify_run_id"),
                    values.get("reported_workflow_id"),
                    values.get("output_hash"),
                    values.get("prompt_tokens"),
                    values.get("completion_tokens"),
                    values.get("total_steps"),
                    values.get("elapsed_seconds"),
                    values.get("http_status"),
                    attempt_id,
                    project_id,
                ),
            ).rowcount
        else:
            changed = connection.execute(
                """UPDATE dify_workflow_execution_attempts
                   SET status = 'failed', dify_task_id = %s, dify_run_id = %s,
                       reported_workflow_id = %s, http_status = %s,
                       error_classification = %s, error_code = %s,
                       error_message = %s, retryable = %s,
                       finished_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s AND status = 'running'""",
                (
                    values.get("dify_task_id"),
                    values.get("dify_run_id"),
                    values.get("reported_workflow_id"),
                    values.get("http_status"),
                    values.get("error_classification"),
                    values.get("error_code"),
                    str(values.get("error_message", ""))[:2000],
                    bool(values.get("retryable", False)),
                    attempt_id,
                    project_id,
                ),
            ).rowcount
        if changed != 1:
            raise WorkflowConfigurationError(
                "Dify execution attempt was already finalized or disappeared",
                code="dify_attempt_transition_conflict",
            )


def _release(row: Mapping[str, Any]) -> WorkflowRuntimeRelease:
    return WorkflowRuntimeRelease(
        id=row["id"],
        project_id=row["project_id"],
        purpose=str(row["purpose"]),
        version=int(row["version"]),
        prompt_program_id=row["prompt_program_id"],
        prompt_release_id=row["prompt_release_id"],
        prompt_release_hash=str(row["prompt_release_hash"]),
        prompt_system_template=str(row["prompt_system_template"]),
        prompt_user_template=str(row["prompt_user_template"]),
        dify_app_id=str(row["dify_app_id"]),
        dify_workflow_id=str(row["dify_workflow_id"]),
        dsl_hash=str(row["dsl_hash"]),
        context_contract_version=str(row["context_contract_version"]),
        input_schema=_json_object(row["input_schema"]),
        input_schema_hash=str(row["input_schema_hash"]),
        output_schema=_json_object(row["output_schema"]),
        output_schema_hash=str(row["output_schema_hash"]),
        configured_model=str(row["configured_model"]),
        model_provider=str(row["model_provider"]),
        api_secret_handle=SecretVersionHandle(
            reference_id=row["api_secret_reference_id"],
            project_id=row["project_id"],
            purpose=str(row["api_secret_purpose"]),
            version=int(row["api_secret_version"]),
        ),
        release_hash=str(row["release_hash"]),
        binding_version=int(row["binding_version"]),
    )


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((item.name for item in cursor.description), row, strict=True))


def _json_object(value: object) -> Mapping[str, object]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping):
        raise WorkflowConfigurationError("Dify release schema is not a JSON object")
    return dict(parsed)
