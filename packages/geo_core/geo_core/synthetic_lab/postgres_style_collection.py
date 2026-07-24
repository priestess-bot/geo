"""PostgreSQL task and result persistence for Style Collection."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.jobs.postgres import WorkerLease
from geo_core.project_scope import set_project_scope
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.collection_execution_contracts import (
    StyleCollectionExecutionError,
    StyleCollectionOutput,
    StyleCollectionRepositoryPort,
    StyleCollectionTask,
    StyleCollectionTaskStagingPort,
)
from geo_core.synthetic_lab.postgres_codec import decode_object, encode_object, payload_hash


class PostgresStyleCollectionTaskRepository(StyleCollectionTaskStagingPort):
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection, self._project_id = connection, project_id

    def stage(
        self,
        task: StyleCollectionTask,
        *,
        expected_job_input_hash: str,
    ) -> None:
        if task.project_id != self._project_id:
            raise StyleCollectionExecutionError("Style Collection task crosses Project scope")
        if task.input_hash != expected_job_input_hash:
            raise StyleCollectionExecutionError(
                "Style Collection task and Durable Job input hashes differ"
            )
        task_type, task_payload, task_payload_hash = encode_object(task)
        existing = _one(
            self._connection.execute(
                """SELECT task_type, task_payload, task_payload_hash, task_input_hash
                   FROM synthetic_lab_style_collection_tasks
                   WHERE project_id = %s AND job_id = %s""",
                (task.project_id, task.job_id),
            )
        )
        if existing is not None:
            if existing != {
                "task_type": task_type,
                "task_payload": task_payload,
                "task_payload_hash": task_payload_hash,
                "task_input_hash": task.input_hash,
            }:
                raise StyleCollectionExecutionError(
                    "Style Collection task identity already has different content"
                )
            return
        secret = task.login_secret
        try:
            self._connection.execute(
                """INSERT INTO synthetic_lab_style_collection_tasks(
                       project_id, job_id, collection_run_id, style_source_revision_id,
                       source_revision_number, channel, locale, access_mode, source_url,
                       source_locator_hash, adapter_release, authorization_id,
                       authorization_version, authorization_hash, authorization_purpose,
                       authorization_expires_at, login_secret_reference_id,
                       login_secret_version, login_secret_handle_hash,
                       allowed_redirect_hosts, robots_user_agent, raw_artifact_id,
                       derived_artifact_id, tmpfs_mount_path, tmpfs_maximum_bytes,
                       maximum_redirects, task_input_hash, task_type, task_payload,
                       task_payload_hash
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    task.project_id,
                    task.job_id,
                    task.collection_run_id,
                    task.style_source_revision_id,
                    task.source_revision_number,
                    task.channel,
                    task.locale,
                    task.access_mode.value,
                    task.source_url,
                    task.source_locator_hash,
                    task.adapter_release,
                    task.authorization.authorization_id,
                    task.authorization.version_number,
                    task.authorization.authorization_hash,
                    task.authorization.purpose,
                    task.authorization.expires_at,
                    secret.reference_id if secret else None,
                    secret.version if secret else None,
                    canonical_hash(secret.as_job_payload()) if secret else None,
                    list(task.allowed_redirect_hosts),
                    task.robots_user_agent,
                    task.raw_artifact_id,
                    task.derived_artifact_id,
                    task.tmpfs.mount_path,
                    task.tmpfs.maximum_bytes,
                    task.maximum_redirects,
                    task.input_hash,
                    task_type,
                    Jsonb(task_payload),
                    task_payload_hash,
                ),
            )
        except psycopg.Error as error:
            raise StyleCollectionExecutionError(
                "PostgreSQL rejected the frozen Style Collection task"
            ) from error


class PostgresStyleCollectionRepository(StyleCollectionRepositoryPort):
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def load(self, lease: WorkerLease) -> StyleCollectionTask:
        connection = self._connection_factory()
        try:
            set_project_scope(connection, lease.project_id)
            row = _one(
                connection.execute(
                    """SELECT task.*, job.status, job.lease_owner, job.lease_token,
                              job.fencing_generation AS job_fencing_generation,
                              job.lease_expires_at, job.cancel_requested_at,
                              job.kind AS durable_kind
                       FROM synthetic_lab_style_collection_tasks AS task
                       JOIN durable_jobs AS job
                         ON job.id = task.job_id AND job.project_id = task.project_id
                       WHERE task.project_id = %s AND task.job_id = %s""",
                    (lease.project_id, lease.job_id),
                )
            )
            if row is None:
                raise StyleCollectionExecutionError(
                    "claimed Style Collection Job has no frozen executable task"
                )
            _assert_live_lease(row, lease)
            if payload_hash(row["task_payload"]) != row["task_payload_hash"]:
                raise StyleCollectionExecutionError("Style Collection task payload hash changed")
            task = decode_object(row["task_type"], row["task_payload"])
            if not isinstance(task, StyleCollectionTask):
                raise StyleCollectionExecutionError("stored Style Collection task type changed")
            _assert_task_row(task, row, lease)
            return task
        finally:
            connection.rollback()
            connection.close()

    def finalize(
        self,
        *,
        connection: object,
        lease: WorkerLease,
        task: StyleCollectionTask,
        output: StyleCollectionOutput,
    ) -> None:
        database = cast(Any, connection)
        if (
            task.project_id != lease.project_id
            or task.job_id != lease.job_id
            or output.project_id != lease.project_id
            or output.collection_run_id != task.collection_run_id
        ):
            raise StyleCollectionExecutionError("Style Collection result lineage changed")
        result_type, result_payload, result_payload_hash = encode_object(output)
        try:
            database.execute(
                """INSERT INTO synthetic_lab_style_collection_results(
                       id, project_id, job_id, collection_run_id, outcome,
                       final_url_hash, navigation_chain_hash, raw_manifest_hash,
                       derived_manifest_hash, derived_content_hash,
                       extracted_record_count, block_reason, result_hash, result_type,
                       result_payload, result_payload_hash, lease_token,
                       fencing_generation
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    uuid4(),
                    lease.project_id,
                    lease.job_id,
                    task.collection_run_id,
                    output.outcome.value,
                    output.final_url_hash,
                    output.navigation_chain_hash,
                    output.raw_manifest_hash,
                    output.derived_manifest_hash,
                    output.derived_content_hash,
                    output.extracted_record_count,
                    output.block_reason.value if output.block_reason else None,
                    output.result_hash,
                    result_type,
                    Jsonb(result_payload),
                    result_payload_hash,
                    lease.lease_token,
                    lease.fencing_generation,
                ),
            )
        except psycopg.Error as error:
            raise StyleCollectionExecutionError(
                "PostgreSQL rejected the fenced Style Collection result"
            ) from error

    def mark_attempt_orphaned(self, *, lease: WorkerLease, reason: str) -> None:
        connection = self._connection_factory()
        try:
            set_project_scope(connection, lease.project_id)
            connection.execute(
                "SELECT geo_mark_synthetic_artifact_attempt_orphaned(%s, %s, %s, %s)",
                (lease.project_id, lease.job_id, lease.fencing_generation, reason),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def build_style_collection_repository(database_url: str) -> PostgresStyleCollectionRepository:
    normalized = database_url.strip()
    if not normalized:
        raise ValueError("Style Collection database URL cannot be empty")

    def connect() -> Any:
        return psycopg.connect(normalized, row_factory=dict_row)

    return PostgresStyleCollectionRepository(connect)


def _assert_live_lease(row: Mapping[str, Any], lease: WorkerLease) -> None:
    if (
        row["status"] not in {"running", "finalizing"}
        or row["lease_owner"] != lease.worker_id
        or row["lease_token"] != lease.lease_token
        or row["job_fencing_generation"] != lease.fencing_generation
        or row["lease_expires_at"] is None
        or row["lease_expires_at"] <= datetime.now(UTC)
        or row["cancel_requested_at"] is not None
        or row["durable_kind"] != "style.collect"
    ):
        raise StyleCollectionExecutionError("Style Collection lease is stale or cancelled")


def _assert_task_row(
    task: StyleCollectionTask,
    row: Mapping[str, Any],
    lease: WorkerLease,
) -> None:
    normalized = (
        task.project_id,
        task.job_id,
        task.collection_run_id,
        task.style_source_revision_id,
        task.channel,
        task.locale,
        task.source_url,
        task.source_locator_hash,
        task.adapter_release,
        task.raw_artifact_id,
        task.derived_artifact_id,
        task.input_hash,
    )
    persisted = tuple(
        row[name]
        for name in (
            "project_id",
            "job_id",
            "collection_run_id",
            "style_source_revision_id",
            "channel",
            "locale",
            "source_url",
            "source_locator_hash",
            "adapter_release",
            "raw_artifact_id",
            "derived_artifact_id",
            "task_input_hash",
        )
    )
    if normalized != persisted or task.project_id != lease.project_id or task.job_id != lease.job_id:
        raise StyleCollectionExecutionError("stored Style Collection task lineage changed")


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    names = [column.name for column in cursor.description]
    return dict(zip(names, row, strict=True))


__all__ = [
    "PostgresStyleCollectionRepository",
    "PostgresStyleCollectionTaskRepository",
    "build_style_collection_repository",
]
