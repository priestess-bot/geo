"""Transactional PostgreSQL Unit of Work for Synthetic Lab applications."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.project_scope import set_project_scope
from geo_core.synthetic_lab.ports import (
    SyntheticAggregateRepository,
    SyntheticAuthorizationRepository,
    SyntheticCommandRepository,
    SyntheticDifyReconciliationPort,
    SyntheticImportRepository,
    SyntheticLabIdempotencyConflict,
    SyntheticJobRepository,
    SyntheticLabPersistenceError,
    SyntheticOutboxRepository,
)
from geo_core.workflow_runtime.reconciliation import (
    DifyRecoveryBindingError,
    bind_dify_resubmission,
)
from geo_core.synthetic_lab.execution_contracts import SyntheticExecutionTaskStagingPort
from geo_core.synthetic_lab.collection_execution_contracts import (
    StyleCollectionTaskStagingPort,
)
from geo_core.synthetic_lab.postgres_execution import (
    PostgresSyntheticExecutionTaskRepository,
)
from geo_core.synthetic_lab.postgres_import_repository import (
    PostgresSyntheticImportRepository,
)
from geo_core.synthetic_lab.postgres_profile_build_binding import (
    PostgresStyleProfileBuildBindingRepository,
)
from geo_core.synthetic_lab.profile_build_binding import (
    StyleProfileBuildBindingRepository,
)
from geo_core.synthetic_lab.postgres_style_collection import (
    PostgresStyleCollectionTaskRepository,
)
from geo_core.synthetic_lab.postgres_repository import (
    PostgresSyntheticAggregateRepository,
    PostgresSyntheticAuthorizationRepository,
    PostgresSyntheticCommandRepository,
    PostgresSyntheticJobRepository,
    PostgresSyntheticOutboxRepository,
)


ConnectionFactory = Callable[[], Any]


class _PostgresSyntheticDifyReconciliation:
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection = connection
        self._project_id = project_id

    def bind_resubmission(
        self,
        *,
        project_id: UUID,
        new_parent_job_id: UUID,
        actor_id: UUID,
        recovery_of_attempt_id: UUID | None,
        token: str | None,
    ) -> UUID | None:
        if project_id != self._project_id:
            raise SyntheticLabPersistenceError(
                "Dify reconciliation Project scope mismatch"
            )
        try:
            return bind_dify_resubmission(
                self._connection,
                project_id=project_id,
                new_parent_job_id=new_parent_job_id,
                actor_id=actor_id,
                recovery_of_attempt_id=recovery_of_attempt_id,
                token=token,
            )
        except DifyRecoveryBindingError as error:
            raise SyntheticLabIdempotencyConflict(str(error)) from error


class PostgresSyntheticLabUnitOfWork:
    def __init__(self, connection_factory: ConnectionFactory, *, project_id: UUID) -> None:
        self._connection_factory = connection_factory
        self.project_id = project_id
        self._connection: Any | None = None

    def __enter__(self) -> "PostgresSyntheticLabUnitOfWork":
        if self._connection is not None:
            raise SyntheticLabPersistenceError("Synthetic Lab UoW is already active")
        connection = self._connection_factory()
        try:
            set_project_scope(connection, self.project_id)
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        self.commands: SyntheticCommandRepository = PostgresSyntheticCommandRepository(
            connection, self.project_id
        )
        self.aggregates: SyntheticAggregateRepository = PostgresSyntheticAggregateRepository(
            connection, self.project_id
        )
        self.authorizations: SyntheticAuthorizationRepository = (
            PostgresSyntheticAuthorizationRepository(connection, self.project_id)
        )
        self.imports: SyntheticImportRepository = PostgresSyntheticImportRepository(
            connection, self.project_id
        )
        self.jobs: SyntheticJobRepository = PostgresSyntheticJobRepository(
            connection, self.project_id
        )
        self.outbox: SyntheticOutboxRepository = PostgresSyntheticOutboxRepository(
            connection, self.project_id
        )
        self.execution_tasks: SyntheticExecutionTaskStagingPort = (
            PostgresSyntheticExecutionTaskRepository(connection, self.project_id)
        )
        self.style_collection_tasks: StyleCollectionTaskStagingPort = (
            PostgresStyleCollectionTaskRepository(connection, self.project_id)
        )
        self.profile_build_bindings: StyleProfileBuildBindingRepository = (
            PostgresStyleProfileBuildBindingRepository(connection, self.project_id)
        )
        self.dify_reconciliation: SyntheticDifyReconciliationPort = (
            _PostgresSyntheticDifyReconciliation(connection, self.project_id)
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        del exc_type, exc, traceback
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.rollback()
            connection.close()
        return None

    def commit(self) -> None:
        if self._connection is None:
            raise SyntheticLabPersistenceError("Synthetic Lab UoW is not active")
        try:
            self._connection.commit()
        except psycopg.Error as error:
            self._connection.rollback()
            raise SyntheticLabPersistenceError(
                "PostgreSQL rejected the Synthetic Lab transaction"
            ) from error


class PostgresSyntheticLabUnitOfWorkFactory:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def __call__(self, *, project_id: UUID) -> PostgresSyntheticLabUnitOfWork:
        return PostgresSyntheticLabUnitOfWork(
            self._connection_factory,
            project_id=project_id,
        )


def synthetic_lab_uow_factory(database_url: str) -> PostgresSyntheticLabUnitOfWorkFactory:
    normalized = database_url.strip()
    if not normalized:
        raise ValueError("Synthetic Lab database URL cannot be empty")

    def connect() -> Any:
        return psycopg.connect(normalized, row_factory=dict_row)

    return PostgresSyntheticLabUnitOfWorkFactory(connect)


__all__ = [
    "PostgresSyntheticLabUnitOfWork",
    "PostgresSyntheticLabUnitOfWorkFactory",
    "synthetic_lab_uow_factory",
]
