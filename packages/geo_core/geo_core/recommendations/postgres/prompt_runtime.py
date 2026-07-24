"""Short-lived project-scoped Prompt Runtime reads for Recommendation workers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.prompts.application import PromptProgramApplication
from geo_core.prompts.application_models import RuntimePromptProgram
from geo_core.prompts.postgres_repository import PsycopgPromptProgramRepository
from geo_core.recommendations.generation_prompt import (
    RecommendationPromptProgramResolver,
)


class PostgresRecommendationPromptRuntime:
    """Resolve Prompt runtime state in a fresh RLS-scoped read transaction."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connect = connection_factory

    def resolve_runtime_binding(
        self, *, project_id: UUID, purpose: str
    ) -> RuntimePromptProgram:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            runtime = PromptProgramApplication(
                PsycopgPromptProgramRepository(connection)
            ).resolve_runtime_binding(project_id=project_id, purpose=purpose)
            connection.rollback()
            return runtime
        except psycopg.Error as error:
            connection.rollback()
            raise RuntimeError(
                "Recommendation Prompt runtime PostgreSQL read failed"
            ) from error
        finally:
            connection.close()


def build_recommendation_prompt_resolver(
    *, connection_factory: Callable[[], Any]
) -> RecommendationPromptProgramResolver:
    return RecommendationPromptProgramResolver(
        PostgresRecommendationPromptRuntime(connection_factory)
    )


__all__ = [
    "PostgresRecommendationPromptRuntime",
    "build_recommendation_prompt_resolver",
]
