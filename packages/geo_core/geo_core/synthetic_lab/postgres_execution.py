"""Lease-owned PostgreSQL persistence for frozen Synthetic execution tasks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.jobs.postgres import WorkerLease
from geo_core.project_scope import set_project_scope
from geo_core.synthetic_lab.execution_contracts import (
    CorpusFinalizeOutput,
    CorpusFinalizeTask,
    OfflineExperimentRunOutput,
    OfflineExperimentRunTask,
    ReviewCaseRunOutput,
    ReviewCaseRunTask,
    StyleProfileBuildOutput,
    StyleProfileBuildTask,
    SyntheticExecutionError,
    SyntheticExecutionOutput,
    SyntheticExecutionTask,
    SyntheticExecutionTaskStagingPort,
)
from geo_core.synthetic_lab.ports import JobTerminalResult, RuntimeInputSnapshot
from geo_core.synthetic_lab.postgres_codec import decode_object, encode_object, payload_hash


_TASK_KIND = {
    StyleProfileBuildTask: "style.profile.build",
    ReviewCaseRunTask: "review.case.run",
    CorpusFinalizeTask: "corpus.finalize",
    OfflineExperimentRunTask: "offline_experiment.run",
}
_OUTPUT_FOR_TASK = {
    StyleProfileBuildTask: StyleProfileBuildOutput,
    ReviewCaseRunTask: ReviewCaseRunOutput,
    CorpusFinalizeTask: CorpusFinalizeOutput,
    OfflineExperimentRunTask: OfflineExperimentRunOutput,
}
_DOMAIN_KIND = {
    StyleProfileBuildTask: "style_profile_build",
    ReviewCaseRunTask: "candidate_generation",
    CorpusFinalizeTask: "corpus_finalize",
    OfflineExperimentRunTask: "offline_experiment",
}


class PostgresSyntheticExecutionTaskRepository(SyntheticExecutionTaskStagingPort):
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection, self._project_id = connection, project_id

    def stage(
        self,
        task: SyntheticExecutionTask,
        expected_job_input_hash: str,
    ) -> None:
        if task.project_id != self._project_id:
            raise SyntheticExecutionError("execution task belongs to another Project")
        execution_kind = _TASK_KIND.get(type(task))
        if execution_kind is None:
            raise SyntheticExecutionError("unsupported Synthetic execution task type")
        task_type, task_payload, content_hash = encode_object(task)
        existing = self._connection.execute(
            """SELECT task_type, task_payload, task_payload_hash,
                      expected_job_input_hash, requested_by
               FROM synthetic_lab_execution_tasks
               WHERE project_id = %s AND job_id = %s""",
            (task.project_id, task.job_id),
        ).fetchone()
        if existing is not None:
            row = _mapping(existing, self._connection)
            if (
                row["task_type"] != task_type
                or row["task_payload"] != task_payload
                or row["task_payload_hash"] != content_hash
                or row["expected_job_input_hash"] != expected_job_input_hash
                or row["requested_by"] != task.requested_by
            ):
                raise SyntheticExecutionError("execution task identity already has other content")
            return
        try:
            self._connection.execute(
                """INSERT INTO synthetic_lab_execution_tasks(
                       project_id, job_id, execution_kind, expected_job_input_hash,
                       requested_by, task_input_hash, task_type, task_payload,
                       task_payload_hash
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    task.project_id,
                    task.job_id,
                    execution_kind,
                    expected_job_input_hash,
                    task.requested_by,
                    task.input_hash,
                    task_type,
                    Jsonb(task_payload),
                    content_hash,
                ),
            )
        except psycopg.Error as error:
            raise SyntheticExecutionError(
                "PostgreSQL rejected the frozen Synthetic execution task"
            ) from error


class PostgresSyntheticExecutionRepository:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def load(self, lease: WorkerLease) -> SyntheticExecutionTask:
        connection = self._connection_factory()
        try:
            set_project_scope(connection, lease.project_id)
            cursor = connection.execute(
                """SELECT task.task_type, task.task_payload, task.task_payload_hash,
                          task.task_input_hash, task.execution_kind,
                          task.requested_by,
                          job.status, job.lease_owner, job.lease_token,
                          job.fencing_generation, job.lease_expires_at,
                          job.cancel_requested_at
                   FROM synthetic_lab_execution_tasks AS task
                   JOIN durable_jobs AS job
                     ON job.id = task.job_id AND job.project_id = task.project_id
                   WHERE task.project_id = %s AND task.job_id = %s""",
                (lease.project_id, lease.job_id),
            )
            row = _one(cursor)
            if row is None:
                raise SyntheticExecutionError(
                    "claimed Synthetic Job has no frozen executable task"
                )
            if (
                row["status"] not in {"running", "finalizing"}
                or row["lease_owner"] != lease.worker_id
                or row["lease_token"] != lease.lease_token
                or row["fencing_generation"] != lease.fencing_generation
                or row["lease_expires_at"] is None
                or row["lease_expires_at"] <= datetime.now(UTC)
                or row["cancel_requested_at"] is not None
                or row["execution_kind"] != lease.kind
            ):
                raise SyntheticExecutionError("Synthetic execution lease is stale or cancelled")
            if payload_hash(row["task_payload"]) != row["task_payload_hash"]:
                raise SyntheticExecutionError("Synthetic execution task payload hash changed")
            task = decode_object(row["task_type"], row["task_payload"])
            if not isinstance(
                task,
                (
                    StyleProfileBuildTask,
                    ReviewCaseRunTask,
                    CorpusFinalizeTask,
                    OfflineExperimentRunTask,
                ),
            ):
                raise SyntheticExecutionError("stored Synthetic execution task type is invalid")
            if (
                task.project_id != lease.project_id
                or task.job_id != lease.job_id
                or task.input_hash != row["task_input_hash"]
                or _TASK_KIND[type(task)] != row["execution_kind"]
                or task.requested_by != row["requested_by"]
            ):
                raise SyntheticExecutionError("stored Synthetic execution task lineage changed")
            return task
        finally:
            connection.rollback()
            connection.close()

    def finalize(
        self,
        *,
        connection: object,
        lease: WorkerLease,
        task: SyntheticExecutionTask,
        output: SyntheticExecutionOutput,
        runtime: RuntimeInputSnapshot,
    ) -> None:
        database = cast(Any, connection)
        expected_output = _OUTPUT_FOR_TASK.get(type(task))
        if expected_output is None or not isinstance(output, expected_output):
            raise SyntheticExecutionError("execution output does not match the frozen task type")
        if (
            task.project_id != lease.project_id
            or task.job_id != lease.job_id
            or output.project_id != lease.project_id
            or runtime != task.runtime_inputs
        ):
            raise SyntheticExecutionError("execution finalization changed Project or runtime lineage")
        if isinstance(task, StyleProfileBuildTask) and (
            not isinstance(output, StyleProfileBuildOutput)
            or output.profile_version_id != task.profile_version_id
            or output.profile_hash != task.runtime_inputs.profile_hash
        ):
            raise SyntheticExecutionError(
                "Style Profile output does not match the frozen build target"
            )
        result_type, result_payload, result_payload_hash = encode_object(output)
        terminal = JobTerminalResult(
            project_id=lease.project_id,
            job_id=lease.job_id,
            job_kind=_DOMAIN_KIND[type(task)],
            result=output,
            result_hash=output.result_hash,
        )
        terminal_type, terminal_payload, _ = encode_object(terminal)
        try:
            database.execute(
                """INSERT INTO synthetic_lab_execution_results(
                       project_id, job_id, result_type, result_payload,
                       result_payload_hash, result_hash, lease_token,
                       fencing_generation, fact_snapshot_id, fact_snapshot_hash,
                       profile_version_id, profile_hash, prompt_release_id,
                       prompt_release_hash
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s
                   )""",
                (
                    lease.project_id,
                    lease.job_id,
                    result_type,
                    Jsonb(result_payload),
                    result_payload_hash,
                    output.result_hash,
                    lease.lease_token,
                    lease.fencing_generation,
                    runtime.fact_snapshot_id,
                    runtime.fact_snapshot_hash,
                    runtime.profile_version_id,
                    runtime.profile_hash,
                    runtime.prompt_release_id,
                    runtime.prompt_release_hash,
                ),
            )
            database.execute(
                """INSERT INTO synthetic_lab_terminal_results(
                       project_id, job_id, job_kind, result_type, result_payload,
                       result_hash, lease_token, fencing_generation,
                       fact_snapshot_id, fact_snapshot_hash, profile_version_id,
                       profile_hash, prompt_release_id, prompt_release_hash
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s
                   )""",
                (
                    lease.project_id,
                    lease.job_id,
                    terminal.job_kind,
                    terminal_type,
                    Jsonb(terminal_payload),
                    terminal.result_hash,
                    lease.lease_token,
                    lease.fencing_generation,
                    runtime.fact_snapshot_id,
                    runtime.fact_snapshot_hash,
                    runtime.profile_version_id,
                    runtime.profile_hash,
                    runtime.prompt_release_id,
                    runtime.prompt_release_hash,
                ),
            )
            changed = database.execute(
                """UPDATE synthetic_lab_job_metadata
                   SET metadata_version = metadata_version + 1,
                       updated_at = clock_timestamp()
                   WHERE project_id = %s AND job_id = %s""",
                (lease.project_id, lease.job_id),
            ).rowcount
            if changed != 1:
                raise SyntheticExecutionError("Synthetic Job metadata completion CAS failed")
        except psycopg.Error as error:
            raise SyntheticExecutionError(
                "PostgreSQL rejected Synthetic execution finalization"
            ) from error


def build_synthetic_execution_repository(
    database_url: str,
) -> PostgresSyntheticExecutionRepository:
    normalized = database_url.strip()
    if not normalized:
        raise ValueError("Synthetic execution database URL cannot be empty")

    def connect() -> Any:
        return psycopg.connect(normalized, row_factory=dict_row)

    return PostgresSyntheticExecutionRepository(connect)


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    return _mapping(row, cursor)


def _mapping(row: object, cursor: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    names = [column.name for column in cursor.description]
    return dict(zip(names, cast(tuple[object, ...], row), strict=True))


__all__ = [
    "PostgresSyntheticExecutionRepository",
    "PostgresSyntheticExecutionTaskRepository",
    "build_synthetic_execution_repository",
]
