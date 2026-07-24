"""PostgreSQL Unit of Work for one project-scoped Model Gateway transaction."""

from __future__ import annotations

from types import TracebackType
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.model_gateway.ports import (
    ModelCallPersistenceError,
    ModelCallRepository,
    ModelCallUnitOfWork,
    ModelCallUnitOfWorkFactory,
)
from geo_core.model_gateway.postgres_repository import PsycopgModelCallRepository
from geo_core.project_scope import set_project_scope


class PostgresModelCallUnitOfWork(ModelCallUnitOfWork):
    def __init__(
        self, factory: "PostgresModelCallUnitOfWorkFactory", *, project_id: UUID
    ) -> None:
        self._factory = factory
        self._project_id = project_id
        self._connection: Any | None = None
        self._committed = False
        self.calls: ModelCallRepository

    def __enter__(self) -> "PostgresModelCallUnitOfWork":
        if self._connection is not None:
            raise ModelCallPersistenceError("model-call Unit of Work is already active")
        self._connection = self._factory.connect()
        set_project_scope(self._connection, self._project_id)
        self.calls = PsycopgModelCallRepository(
            self._connection, project_id=self._project_id
        )
        return self

    def commit(self) -> None:
        if self._connection is None:
            raise ModelCallPersistenceError("model-call Unit of Work has not started")
        try:
            self._connection.commit()
        except psycopg.Error:
            self._connection.rollback()
            raise ModelCallPersistenceError(
                "PostgreSQL rejected the model-call transaction"
            ) from None
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        del exc_value, traceback
        if self._connection is None:
            return None
        try:
            if exc_type is not None or not self._committed:
                self._connection.rollback()
        finally:
            self._connection.close()
            self._connection = None
        return None


class PostgresModelCallUnitOfWorkFactory(ModelCallUnitOfWorkFactory):
    def __init__(self, database_url: str, *, connect_timeout: int = 5) -> None:
        normalized = database_url.strip()
        if not normalized:
            raise ValueError("database_url is required")
        self._database_url = normalized
        self._connect_timeout = connect_timeout

    def __call__(self, *, project_id: UUID) -> ModelCallUnitOfWork:
        return PostgresModelCallUnitOfWork(self, project_id=project_id)

    def connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(
            self._database_url,
            connect_timeout=self._connect_timeout,
            row_factory=dict_row,
        )


__all__ = ["PostgresModelCallUnitOfWork", "PostgresModelCallUnitOfWorkFactory"]
