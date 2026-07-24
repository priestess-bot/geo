"""PostgreSQL admission and frozen-task persistence for Prompt tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.project_scope import set_project_scope
from geo_core.prompts.ports import (
    PromptProgramIdempotencyConflict,
    PromptProgramPersistenceError,
)
from geo_core.prompts.postgres_repository import PsycopgPromptProgramRepository
from geo_core.prompts.postgres_serialization import plain_json
from geo_core.prompts.test_execution_contracts import (
    PROMPT_TEST_JOB_KIND,
    PROMPT_TEST_OUTBOX_TOPIC,
    PromptTestJob,
    PromptTestRunRepository,
    PromptTestRunTask,
    PromptTestUnitOfWork,
    PromptTestUnitOfWorkFactory,
    StoredPromptTestJob,
)


class PostgresPromptTestRunRepository(PromptTestRunRepository):
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection = connection
        self._project_id = project_id

    def enqueue(
        self,
        *,
        task: PromptTestRunTask,
        idempotency_key_hash: str,
        outbox_id: UUID,
    ) -> StoredPromptTestJob:
        if task.project_id != self._project_id:
            raise PromptProgramPersistenceError(
                "Prompt test task belongs to another Project"
            )
        durable_key = f"prompt-test:{idempotency_key_hash}"
        self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"prompt-test-enqueue:{task.project_id}:{idempotency_key_hash}",),
        )
        existing = _one(
            self._connection.execute(
                """SELECT id, project_id, status, input_hash
                   FROM durable_jobs
                   WHERE project_id = %s AND kind = %s
                     AND idempotency_key = %s AND replay_nonce = 0""",
                (task.project_id, PROMPT_TEST_JOB_KIND, durable_key),
            )
        )
        if existing is not None:
            if existing["input_hash"] != task.input_hash:
                raise PromptProgramIdempotencyConflict(
                    "Prompt test idempotency key was reused for different frozen input"
                )
            stored = self._stored_task(
                project_id=task.project_id,
                job_id=cast(UUID, existing["id"]),
            )
            if stored["task_payload_hash"] != task.input_hash:
                raise PromptProgramPersistenceError(
                    "Prompt test replay references different frozen task content"
                )
            return StoredPromptTestJob(
                _job_from_rows(existing, stored),
                replayed=True,
            )

        payload = cast(dict[str, object], plain_json(task.canonical_value()))
        try:
            self._connection.execute(
                """INSERT INTO durable_jobs(
                       id, project_id, kind, input_hash, idempotency_key, max_attempts
                   ) VALUES (%s, %s, %s, %s, %s, 3)""",
                (
                    task.job_id,
                    task.project_id,
                    PROMPT_TEST_JOB_KIND,
                    task.input_hash,
                    durable_key,
                ),
            )
            self._connection.execute(
                """INSERT INTO prompt_program_test_run_tasks(
                       project_id, job_id, program_id, release_id, release_version,
                       release_hash, expected_state_id, expected_state_version,
                       test_set_id, test_set_version, test_set_hash, spec_hash,
                       catalog_hash, requested_by, requested_at, task_payload,
                       task_payload_hash, expected_job_input_hash
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    task.project_id,
                    task.job_id,
                    task.program_id,
                    task.release_id,
                    task.release_version,
                    task.release_hash,
                    task.expected_state_id,
                    task.expected_state_version,
                    task.test_set_id,
                    task.test_set_version,
                    task.test_set_hash,
                    task.spec_hash,
                    task.catalog_hash,
                    task.requested_by,
                    task.requested_at,
                    Jsonb(payload),
                    task.input_hash,
                    task.input_hash,
                ),
            )
            self._connection.execute(
                """INSERT INTO broker_outbox(
                       id, project_id, job_id, topic, payload, idempotency_key
                   ) VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    outbox_id,
                    task.project_id,
                    task.job_id,
                    PROMPT_TEST_OUTBOX_TOPIC,
                    Jsonb(
                        {
                            "project_id": str(task.project_id),
                            "job_id": str(task.job_id),
                            "task_input_hash": task.input_hash,
                        }
                    ),
                    f"prompt-test-wake:{idempotency_key_hash}",
                ),
            )
        except psycopg.errors.UniqueViolation as error:
            raise PromptProgramIdempotencyConflict(
                "Prompt test enqueue identity already exists"
            ) from error
        except psycopg.Error as error:
            raise PromptProgramPersistenceError(
                "PostgreSQL rejected the Prompt test enqueue transaction"
            ) from error
        return StoredPromptTestJob(
            PromptTestJob(
                id=task.job_id,
                project_id=task.project_id,
                release_id=task.release_id,
                release_hash=task.release_hash,
                test_set_id=task.test_set_id,
                test_set_version=task.test_set_version,
                test_set_hash=task.test_set_hash,
                input_hash=task.input_hash,
            ),
            replayed=False,
        )

    def _stored_task(self, *, project_id: UUID, job_id: UUID) -> Mapping[str, object]:
        row = _one(
            self._connection.execute(
                """SELECT release_id, release_hash, test_set_id, test_set_version,
                          test_set_hash, task_payload_hash
                   FROM prompt_program_test_run_tasks
                   WHERE project_id = %s AND job_id = %s""",
                (project_id, job_id),
            )
        )
        if row is None:
            raise PromptProgramPersistenceError(
                "Prompt test durable Job has no frozen execution task"
            )
        return row


class PostgresPromptTestUnitOfWork(PromptTestUnitOfWork):
    def __init__(self, connection_factory: Callable[[], Any], *, project_id: UUID) -> None:
        self._connection_factory = connection_factory
        self._project_id = project_id
        self._connection: Any | None = None
        self._committed = False

    def __enter__(self) -> "PostgresPromptTestUnitOfWork":
        if self._connection is not None:
            raise PromptProgramPersistenceError("Prompt test Unit of Work is already active")
        connection = self._connection_factory()
        try:
            set_project_scope(connection, self._project_id)
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        self.prompts = PsycopgPromptProgramRepository(connection)
        self.test_runs = PostgresPromptTestRunRepository(connection, self._project_id)
        return self

    def commit(self) -> None:
        if self._connection is None:
            raise PromptProgramPersistenceError("Prompt test Unit of Work is not active")
        try:
            self._connection.commit()
            self._committed = True
        except psycopg.Error as error:
            self._connection.rollback()
            raise PromptProgramPersistenceError(
                "PostgreSQL rejected the Prompt test transaction"
            ) from error

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            if exc_type is not None or not self._committed:
                connection.rollback()
        finally:
            connection.close()


class PostgresPromptTestUnitOfWorkFactory(PromptTestUnitOfWorkFactory):
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def __call__(self, *, project_id: UUID) -> PromptTestUnitOfWork:
        return PostgresPromptTestUnitOfWork(
            self._connection_factory,
            project_id=project_id,
        )


def prompt_test_uow_factory(database_url: str) -> PostgresPromptTestUnitOfWorkFactory:
    normalized = database_url.strip()
    if not normalized:
        raise ValueError("Prompt test database URL cannot be empty")

    def connect() -> Any:
        return psycopg.connect(normalized, row_factory=dict_row)

    return PostgresPromptTestUnitOfWorkFactory(connect)


def _job_from_rows(
    durable: Mapping[str, object], task: Mapping[str, object]
) -> PromptTestJob:
    return PromptTestJob(
        id=cast(UUID, durable["id"]),
        project_id=cast(UUID, durable["project_id"]),
        release_id=cast(UUID, task["release_id"]),
        release_hash=str(task["release_hash"]),
        test_set_id=cast(UUID, task["test_set_id"]),
        test_set_version=int(cast(int, task["test_set_version"])),
        test_set_hash=str(task["test_set_hash"]),
        input_hash=str(durable["input_hash"]),
        status=cast(Any, durable["status"]),
    )


def _one(cursor: Any) -> dict[str, object] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((item.name for item in cursor.description), row, strict=True))


__all__ = [
    "PostgresPromptTestRunRepository",
    "PostgresPromptTestUnitOfWork",
    "PostgresPromptTestUnitOfWorkFactory",
    "prompt_test_uow_factory",
]
