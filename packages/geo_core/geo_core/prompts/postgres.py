"""Compatibility facade for Prompt Program PostgreSQL persistence."""

from geo_core.prompts.postgres_api import (
    PsycopgPromptProgramApi,
    build_prompt_program_api,
)
from geo_core.prompts.postgres_repository import PsycopgPromptProgramRepository
from geo_core.prompts.postgres_uow import (
    PsycopgPromptProgramUnitOfWork,
    prompt_program_uow_factory,
)

__all__ = [
    "PsycopgPromptProgramRepository",
    "PsycopgPromptProgramUnitOfWork",
    "PsycopgPromptProgramApi",
    "build_prompt_program_api",
    "prompt_program_uow_factory",
]
