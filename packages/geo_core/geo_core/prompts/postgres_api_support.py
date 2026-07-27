"""Shared identity and lookup helpers for Prompt PostgreSQL API facades."""

from __future__ import annotations

from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.prompts.application import (
    PromptProgramForbidden,
    PromptProgramNotFound,
)
from geo_core.prompts.ports import (
    PromptProgramRepository,
    PromptReleaseRead,
)
from geo_core.prompts.program import PromptProgram


READ_ROLES = frozenset({"owner", "admin", "analyst"})


def required_program(
    repository: PromptProgramRepository,
    project_id: UUID,
    program_id: UUID,
) -> PromptProgram:
    program = repository.get_program(project_id=project_id, program_id=program_id)
    if program is None:
        raise PromptProgramNotFound("The Prompt Program does not exist.")
    return program


def required_release(
    repository: PromptProgramRepository,
    *,
    project_id: UUID,
    program_id: UUID,
    release_id: UUID,
) -> PromptReleaseRead:
    release = repository.get_release(project_id=project_id, release_id=release_id)
    state = repository.get_current_release_state(
        project_id=project_id, release_id=release_id
    )
    if release is None or state is None or release.program_id != program_id:
        raise PromptProgramNotFound("The Prompt Program Release does not exist.")
    return PromptReleaseRead(release, state)


def require_read_role(principal: AccessPrincipal, project_id: UUID) -> None:
    membership = next(
        (
            item
            for item in principal.memberships
            if item.project_id == project_id and item.tenant_id == principal.tenant_id
        ),
        None,
    )
    if membership is None:
        raise PromptProgramNotFound(
            "The project does not exist in the authenticated Prompt Program scope."
        )
    if membership.role not in READ_ROLES:
        raise PromptProgramForbidden(
            "The project role cannot read this Prompt Program resource."
        )


def child_key(value: str, operation: str) -> str:
    normalized = value.strip()
    suffix = f":{operation}"
    return f"{normalized[: 200 - len(suffix)]}{suffix}"


__all__ = ["child_key", "required_program", "required_release", "require_read_role"]
