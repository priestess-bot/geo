"""Project-role checks shared by Prompt Program application operations."""

from __future__ import annotations

from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.prompts.application_models import (
    PromptProgramForbidden,
    PromptProgramNotFound,
)


CONTRIBUTOR_ROLES = frozenset({"owner", "admin", "analyst"})
APPROVER_ROLES = frozenset({"owner", "admin"})


def require_project_role(
    principal: AccessPrincipal, project_id: UUID, *, allowed: frozenset[str]
) -> str:
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
    if membership.role not in allowed:
        raise PromptProgramForbidden(
            "The project role cannot perform this Prompt Program operation."
        )
    return membership.role
