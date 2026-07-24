"""Project-scoped PostgreSQL Unit of Work for Prompt Programs."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any
from uuid import UUID

from geo_core.project_scope import set_project_scope
from geo_core.prompts.postgres_repository import PsycopgPromptProgramRepository


class PsycopgPromptProgramUnitOfWork:
    """One project-scoped transaction for a Prompt Program command."""

    def __init__(self, *, connection_factory: Callable[[], Any], project_id: UUID) -> None:
        self._connection_factory = connection_factory
        self._project_id = project_id
        self._connection: Any | None = None
        self.prompts: PsycopgPromptProgramRepository
        self._committed = False

    def __enter__(self) -> "PsycopgPromptProgramUnitOfWork":
        self._connection = self._connection_factory()
        set_project_scope(self._connection, self._project_id)
        self.prompts = PsycopgPromptProgramRepository(self._connection)
        return self

    def commit(self) -> None:
        if self._connection is None:
            raise RuntimeError("Prompt Program Unit of Work has not started")
        self._connection.commit()
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        if self._connection is None:
            return
        try:
            if exc_type is not None or not self._committed:
                self._connection.rollback()
        finally:
            self._connection.close()


def prompt_program_uow_factory(
    connection_factory: Callable[[], Any],
) -> Callable[[UUID], PsycopgPromptProgramUnitOfWork]:
    return lambda project_id: PsycopgPromptProgramUnitOfWork(
        connection_factory=connection_factory, project_id=project_id
    )


__all__ = ["PsycopgPromptProgramUnitOfWork", "prompt_program_uow_factory"]
