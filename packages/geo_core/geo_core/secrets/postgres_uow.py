"""PostgreSQL Unit of Work for one project-scoped Secret Store transaction."""

from __future__ import annotations

from types import TracebackType
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope

from .errors import SecretStateConflict
from .models import require_uuid
from .ports import (
    SecretAuditRepository,
    SecretCommandRepository,
    SecretRepository,
    SecretUnitOfWork,
)
from .postgres_repository import (
    PsycopgSecretAuditRepository,
    PsycopgSecretCommandRepository,
    PsycopgSecretRepository,
)


class PostgresSecretUnitOfWork:
    __secret_bearing__ = True

    def __init__(self, factory: "PostgresSecretUnitOfWorkFactory", project_id: UUID) -> None:
        require_uuid(project_id, "Secret Store Unit of Work project ID")
        self._factory = factory
        self.project_id = project_id
        self._connection: Any | None = None
        self._completed = False
        self.secrets: SecretRepository
        self.commands: SecretCommandRepository
        self.audits: SecretAuditRepository

    @property
    def connection(self) -> Any:
        if self._connection is None:
            raise SecretStateConflict("Secret Store Unit of Work has not started")
        return self._connection

    def __enter__(self) -> "PostgresSecretUnitOfWork":
        if self._completed or self._connection is not None:
            raise SecretStateConflict("Secret Store Unit of Work is already completed")
        self._connection = self._factory.connect()
        set_project_scope(self._connection, self.project_id)
        self.secrets = PsycopgSecretRepository(self._connection, self.project_id)
        self.commands = PsycopgSecretCommandRepository(self._connection, self.project_id)
        self.audits = PsycopgSecretAuditRepository(self._connection, self.project_id)
        return self

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
            if exc_type is not None or not self._completed:
                self._connection.rollback()
        finally:
            self._connection.close()
            self._connection = None
            self._completed = True
        return None

    def commit(self) -> None:
        if self._connection is None or self._completed:
            raise SecretStateConflict("Secret Store Unit of Work is already completed")
        try:
            self._connection.commit()
        except psycopg.Error:
            self._connection.rollback()
            self._completed = True
            raise SecretStateConflict(
                "PostgreSQL rejected the Secret Store transaction"
            ) from None
        self._completed = True

    def rollback(self) -> None:
        if self._connection is not None and not self._completed:
            self._connection.rollback()
        self._completed = True


class PostgresSecretUnitOfWorkFactory:
    __secret_bearing__ = True

    def __init__(self, database_url: str, *, connect_timeout: int = 5) -> None:
        normalized = database_url.strip()
        if not normalized:
            raise ValueError("database_url is required")
        self._database_url = normalized
        self._connect_timeout = connect_timeout

    def create(self, project_id: UUID) -> SecretUnitOfWork:
        return PostgresSecretUnitOfWork(self, project_id)

    def create_postgres(self, project_id: UUID) -> PostgresSecretUnitOfWork:
        return PostgresSecretUnitOfWork(self, project_id)

    def connect(self) -> psycopg.Connection[tuple[Any, ...]]:
        return psycopg.connect(
            self._database_url,
            connect_timeout=self._connect_timeout,
        )


__all__ = ["PostgresSecretUnitOfWork", "PostgresSecretUnitOfWorkFactory"]
