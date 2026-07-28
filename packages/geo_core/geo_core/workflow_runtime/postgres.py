"""Project-scoped persistence for Dify releases and execution attempts."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from geo_core.jobs.postgres import LostJobLease, PostgresDurableJobStore, WorkerLease
from geo_core.secrets import SecretVersionHandle

from .contracts import WorkflowExecutionResult, WorkflowRuntimeRelease, canonical_json_hash
from .errors import WorkflowConfigurationError
from .published import PublishedWorkflowSnapshot, PublishedWorkflowSnapshotPin


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
        if row["current_prompt_release_id"] != row["prompt_release_id"]:
            raise WorkflowConfigurationError(
                "active Dify Workflow Release no longer matches the current Prompt Release",
                code="dify_prompt_binding_stale",
            )
        if row["prompt_release_status"] != "frozen":
            raise WorkflowConfigurationError(
                "active Dify Workflow Release Prompt is no longer frozen",
                code="dify_prompt_release_not_frozen",
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
        connection = self._store.open_project(lease.project_id)
        try:
            connection.execute(
                "SELECT geo_finish_dify_business_attempt(%s, %s, %s, %s, %s, %s)",
                (
                    lease.project_id,
                    lease.job_id,
                    lease.lease_token,
                    lease.fencing_generation,
                    attempt_id,
                    Jsonb(dict(values)),
                ),
            )
            connection.commit()
        except BaseException as error:
            connection.rollback()
            primary_message = getattr(getattr(error, "diag", None), "message_primary", None)
            if (
                getattr(error, "sqlstate", None) == "23514"
                and primary_message == "Dify business attempt is already finalized"
            ):
                raise WorkflowConfigurationError(
                    primary_message,
                    code="dify_attempt_already_finalized",
                ) from error
            if getattr(error, "sqlstate", None) == "40001":
                raise LostJobLease("Dify business attempt finish was fenced") from error
            raise
        finally:
            connection.close()

    def load_published_snapshot_pin(
        self,
        *,
        release: WorkflowRuntimeRelease,
    ) -> PublishedWorkflowSnapshotPin | None:
        connection = self._store.open_project(release.project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT project_id, release_id, published_snapshot_id,
                              dify_workflow_id, workflow_hash, snapshot_hash, pin_source
                       FROM dify_workflow_release_snapshot_pins
                       WHERE project_id = %s AND release_id = %s""",
                    (release.project_id, release.id),
                )
            )
            connection.rollback()
        finally:
            connection.close()
        if row is None:
            return None
        return PublishedWorkflowSnapshotPin(
            project_id=row["project_id"],
            release_id=row["release_id"],
            published_snapshot_id=row["published_snapshot_id"],
            workflow_id=str(row["dify_workflow_id"]),
            workflow_hash=str(row["workflow_hash"]),
            snapshot_hash=str(row["snapshot_hash"]),
            pin_source=str(row["pin_source"]),
        )

    def find_unresolved_business_attempt(
        self,
        lease: WorkerLease,
        *,
        release: WorkflowRuntimeRelease,
        context_hash: str,
        request_hash: str,
    ) -> UUID | None:
        connection = self._store.open_project(lease.project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT id FROM dify_workflow_execution_attempts
                       WHERE project_id = %s AND job_id = %s AND release_id = %s
                         AND execution_kind = 'business'
                         AND (
                              status = 'running'
                              OR (status = 'failed'
                                  AND error_classification = 'unknown_outcome')
                         )
                         AND context_hash = %s AND request_hash = %s
                       ORDER BY attempt_number DESC LIMIT 1""",
                    (
                        lease.project_id,
                        lease.job_id,
                        release.id,
                        context_hash,
                        request_hash,
                    ),
                )
            )
            connection.rollback()
        finally:
            connection.close()
        return row["id"] if row is not None else None

    def load_successful_business_result(
        self,
        lease: WorkerLease,
        *,
        release: WorkflowRuntimeRelease,
        context_hash: str,
        request_hash: str,
    ) -> WorkflowExecutionResult | None:
        connection = self._store.open_project(lease.project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT attempt.id, attempt.release_id, attempt.dify_task_id,
                              attempt.dify_run_id, attempt.prompt_tokens,
                              attempt.completion_tokens, attempt.total_steps,
                              attempt.elapsed_seconds, result.output,
                              result.response_hash, result.configured_model,
                              result.provider_reported_model,
                              attempt.published_snapshot_id, attempt.request_hash,
                              snapshot.dify_workflow_id AS published_workflow_id,
                              snapshot.snapshot_hash AS published_snapshot_hash
                       FROM dify_workflow_execution_attempts attempt
                       JOIN dify_workflow_execution_results result
                         ON result.attempt_id = attempt.id
                        AND result.project_id = attempt.project_id
                        AND result.job_id = attempt.job_id
                       LEFT JOIN dify_workflow_published_snapshots snapshot
                         ON snapshot.id = attempt.published_snapshot_id
                        AND snapshot.project_id = attempt.project_id
                        AND snapshot.release_id = attempt.release_id
                       WHERE attempt.project_id = %s AND attempt.job_id = %s
                         AND attempt.release_id = %s AND attempt.execution_kind = 'business'
                         AND attempt.status = 'succeeded'
                         AND attempt.context_hash = %s
                         AND (
                              attempt.request_hash = %s
                              OR EXISTS (
                                  SELECT 1 FROM dify_workflow_release_snapshot_pins pin
                                  WHERE pin.project_id = attempt.project_id
                                    AND pin.release_id = attempt.release_id
                                    AND pin.pin_source = 'migration_backfill'
                              )
                         )
                       ORDER BY (attempt.request_hash = %s) DESC,
                                attempt.attempt_number DESC LIMIT 1""",
                    (
                        lease.project_id,
                        lease.job_id,
                        release.id,
                        context_hash,
                        request_hash,
                        request_hash,
                    ),
                )
            )
            connection.rollback()
        finally:
            connection.close()
        if row is None:
            return None
        return _business_result(row, release)

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
            connection.execute(
                "SELECT geo_finish_dify_canary_attempt(%s, %s, %s)",
                (project_id, attempt_id, Jsonb(dict(values))),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _release(row: Mapping[str, Any]) -> WorkflowRuntimeRelease:
    if (
        row.get("registered_workflow_hash") is None
        or row.get("registered_snapshot_hash") is None
        or row.get("registered_identity_source") is None
    ):
        raise WorkflowConfigurationError(
            "legacy Dify release has no trusted published graph identity; "
            "re-enroll it before canary or execution",
            code="dify_release_requires_reenrollment",
        )
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
        registered_workflow_hash=str(row["registered_workflow_hash"]),
        registered_snapshot_hash=str(row["registered_snapshot_hash"]),
        registered_identity_source=str(row["registered_identity_source"]),
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


def _business_result(
    row: Mapping[str, Any], release: WorkflowRuntimeRelease
) -> WorkflowExecutionResult:
    output = _json_object(row["output"])
    response_hash = str(row["response_hash"])
    if canonical_json_hash(output) != response_hash:
        raise WorkflowConfigurationError(
            "stored Dify result hash changed", code="dify_result_hash_mismatch"
        )
    return WorkflowExecutionResult(
        output=output,
        attempt_id=row["id"],
        runtime_release_id=row["release_id"],
        runtime_release_hash=release.release_hash,
        dify_task_id=(str(row["dify_task_id"]) if row["dify_task_id"] else None),
        dify_run_id=str(row["dify_run_id"]),
        configured_model=str(row["configured_model"]),
        provider_reported_model=(
            str(row["provider_reported_model"]) if row["provider_reported_model"] else None
        ),
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        total_steps=row["total_steps"],
        elapsed_seconds=row["elapsed_seconds"],
        response_hash=response_hash,
        published_snapshot_id=row.get("published_snapshot_id"),
        published_snapshot_hash=(
            str(row["published_snapshot_hash"])
            if row.get("published_snapshot_hash") is not None
            else None
        ),
        published_workflow_id=(
            str(row["published_workflow_id"])
            if row.get("published_workflow_id") is not None
            else None
        ),
        request_hash=(str(row["request_hash"]) if row.get("request_hash") is not None else None),
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
