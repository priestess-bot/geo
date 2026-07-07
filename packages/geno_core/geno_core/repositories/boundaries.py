from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RepositoryBoundary:
    """Frozen repository split target used to keep future SQL moves scoped."""

    boundary_id: str
    module: str
    protocol_name: str
    methods: tuple[str, ...]
    scope_required: bool
    compatibility_owner: str = "geno_core.repository.PostgresEvidenceRepository"


AUDIT_REPOSITORY_BOUNDARY = RepositoryBoundary(
    boundary_id="audit",
    module="geno_core.repositories.audit_repository",
    protocol_name="AuditRepository",
    methods=(
        "save_audit_events",
        "list_runtime_audit_events",
        "export_runtime_audit_events_csv",
    ),
    scope_required=True,
)

PROJECT_REPOSITORY_BOUNDARY = RepositoryBoundary(
    boundary_id="project",
    module="geno_core.repositories.project_repository",
    protocol_name="ProjectRepository",
    methods=(
        "list_runtime_projects",
        "update_runtime_project",
        "apply_runtime_project_action",
        "save_project_bootstrap",
        "list_runtime_project_lifecycle_events",
        "export_runtime_project_lifecycle_events_csv",
    ),
    scope_required=True,
)

ACCESS_CONTROL_REPOSITORY_BOUNDARY = RepositoryBoundary(
    boundary_id="access_control",
    module="geno_core.repositories.access_control_repository",
    protocol_name="AccessControlRepository",
    methods=(
        "set_runtime_project_access_context",
        "set_runtime_project_invitation_accept_context",
        "set_runtime_project_portal_token_context",
        "user_can_access_project",
        "get_project_member_role",
        "get_runtime_membership_scope",
        "create_runtime_session",
        "validate_runtime_session",
        "revoke_runtime_session",
        "create_runtime_project_member_invitation",
        "accept_runtime_project_member_invitation",
        "save_connector_secret",
        "list_connector_secrets",
        "resolve_connector_secret",
    ),
    scope_required=True,
)

REPOSITORY_BOUNDARIES = (
    AUDIT_REPOSITORY_BOUNDARY,
    PROJECT_REPOSITORY_BOUNDARY,
    ACCESS_CONTROL_REPOSITORY_BOUNDARY,
)


def repository_boundaries() -> tuple[RepositoryBoundary, ...]:
    return REPOSITORY_BOUNDARIES


def missing_repository_boundary_methods(repository: Any) -> dict[str, tuple[str, ...]]:
    missing: dict[str, tuple[str, ...]] = {}
    for boundary in REPOSITORY_BOUNDARIES:
        missing_methods = tuple(
            method_name
            for method_name in boundary.methods
            if not callable(getattr(repository, method_name, None))
        )
        if missing_methods:
            missing[boundary.boundary_id] = missing_methods
    return missing


def assert_repository_boundary_compatibility(repository: Any) -> None:
    missing = missing_repository_boundary_methods(repository)
    if missing:
        formatted = "; ".join(f"{boundary}: {', '.join(methods)}" for boundary, methods in sorted(missing.items()))
        raise AssertionError(f"Repository boundary compatibility failed: {formatted}")


__all__ = [
    "ACCESS_CONTROL_REPOSITORY_BOUNDARY",
    "AUDIT_REPOSITORY_BOUNDARY",
    "PROJECT_REPOSITORY_BOUNDARY",
    "REPOSITORY_BOUNDARIES",
    "RepositoryBoundary",
    "assert_repository_boundary_compatibility",
    "missing_repository_boundary_methods",
    "repository_boundaries",
]
