"""psycopg Unit of Work for placement application services."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any
from uuid import UUID

from geo_core.placements.postgres_repository import PsycopgPlacementRepository
from geo_core.project_scope import set_project_scope


class PsycopgPlacementUnitOfWork:
    def __init__(self, *, connection_factory: Callable[[], Any], project_id: UUID) -> None:
        self._connection_factory = connection_factory
        self._project_id = project_id
        self._connection: Any | None = None
        self.placements: PsycopgPlacementRepository
        self._committed = False

    def __enter__(self) -> "PsycopgPlacementUnitOfWork":
        self._connection = self._connection_factory()
        set_project_scope(self._connection, self._project_id)
        self.placements = PsycopgPlacementRepository(self._connection)
        return self

    def commit(self) -> None:
        if self._connection is None:
            raise RuntimeError("Unit of Work has not started")
        self._connection.commit()
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del traceback
        if self._connection is None:
            return
        try:
            if exc_type is not None or not self._committed:
                self._connection.rollback()
        finally:
            self._connection.close()


def placement_uow_factory(
    connection_factory: Callable[[], Any],
) -> Callable[[UUID], PsycopgPlacementUnitOfWork]:
    return lambda project_id: PsycopgPlacementUnitOfWork(
        connection_factory=connection_factory, project_id=project_id
    )
