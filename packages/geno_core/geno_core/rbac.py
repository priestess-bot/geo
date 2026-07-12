from __future__ import annotations

from collections.abc import Iterable, Mapping


Permission = str
Role = str


class RbacContractError(ValueError):
    """Raised when a role or permission is outside the production RBAC contract."""


class UnknownPermissionError(RbacContractError):
    pass


class UnknownRoleError(RbacContractError):
    pass


PERMISSION_VOCABULARY: tuple[Permission, ...] = (
    "tenant.create",
    "tenant.read",
    "tenant.update",
    "tenant.disable",
    "member.invite",
    "member.manage",
    "project.create",
    "project.read",
    "project.update",
    "project.archive",
    "prompt.import",
    "connector.read",
    "connector.manage",
    "connector.secret.manage",
    "collection.run",
    "collection.read",
    "evidence.read_summary",
    "evidence.read_raw",
    "analysis.read",
    "analysis.review",
    "score.read",
    "score.configure",
    "report.read",
    "report.generate",
    "report.approve",
    "report.publish",
    "report.revoke",
    "report.download",
    "action.manage",
    "action.read",
    "retest.run",
    "retest.read",
    "knowledge.read",
    "knowledge.import",
    "knowledge.review",
    "knowledge.read_approved",
    "content.read",
    "content.update",
    "content.generate",
    "content.review",
    "distribution.read",
    "distribution.create",
    "distribution.update",
    "audit.read",
    "cost.read",
    "system.admin",
)
PERMISSION_VOCABULARY_SET: frozenset[Permission] = frozenset(PERMISSION_VOCABULARY)


SUPER_ADMIN_ROLE = "super_admin"
TENANT_ADMIN_ROLE = "tenant_admin"
PROJECT_OWNER_ROLE = "project_owner"
ANALYST_ROLE = "analyst"
REVIEWER_ROLE = "reviewer"
KNOWLEDGE_ARCHITECT_ROLE = "knowledge_architect"
CONTENT_OPERATOR_ROLE = "content_operator"
CLIENT_VIEWER_ROLE = "client_viewer"

PORTAL_ADMIN_ACCESS = "portal.admin.access"
PORTAL_CUSTOMER_ACCESS = "portal.customer.access"
PORTAL_CAPABILITY_VOCABULARY: tuple[str, ...] = (
    PORTAL_ADMIN_ACCESS,
    PORTAL_CUSTOMER_ACCESS,
)


ROLE_ALIASES: Mapping[str, Role] = {
    "super_admin": SUPER_ADMIN_ROLE,
    "superadmin": SUPER_ADMIN_ROLE,
    "tenant_admin": TENANT_ADMIN_ROLE,
    "tenantadmin": TENANT_ADMIN_ROLE,
    "project_owner": PROJECT_OWNER_ROLE,
    "projectowner": PROJECT_OWNER_ROLE,
    "owner": PROJECT_OWNER_ROLE,
    "admin": PROJECT_OWNER_ROLE,
    "analyst": ANALYST_ROLE,
    "reviewer": REVIEWER_ROLE,
    "knowledge_architect": KNOWLEDGE_ARCHITECT_ROLE,
    "knowledgearchitect": KNOWLEDGE_ARCHITECT_ROLE,
    "content_operator": CONTENT_OPERATOR_ROLE,
    "contentoperator": CONTENT_OPERATOR_ROLE,
    "client_viewer": CLIENT_VIEWER_ROLE,
    "clientviewer": CLIENT_VIEWER_ROLE,
    "viewer": CLIENT_VIEWER_ROLE,
}


ROLE_PERMISSION_MATRIX: Mapping[Role, frozenset[Permission]] = {
    SUPER_ADMIN_ROLE: PERMISSION_VOCABULARY_SET,
    TENANT_ADMIN_ROLE: frozenset(
        {
            "tenant.read",
            "tenant.update",
            "member.invite",
            "member.manage",
            "project.create",
            "project.read",
            "project.update",
            "report.read",
            "audit.read",
            "cost.read",
        }
    ),
    PROJECT_OWNER_ROLE: frozenset(
        {
            "project.read",
            "project.update",
            "project.archive",
            "member.invite",
            "prompt.import",
            "connector.read",
            "connector.manage",
            "connector.secret.manage",
            "collection.run",
            "collection.read",
            "evidence.read_summary",
            "analysis.read",
            "analysis.review",
            "score.read",
            "score.configure",
            "report.read",
            "report.generate",
            "report.publish",
            "report.revoke",
            "report.download",
            "action.manage",
            "action.read",
            "retest.run",
            "retest.read",
        }
    ),
    ANALYST_ROLE: frozenset(
        {
            "project.read",
            "prompt.import",
            "collection.run",
            "collection.read",
            "evidence.read_summary",
            "evidence.read_raw",
            "analysis.read",
            "analysis.review",
            "score.read",
            "report.read",
            "report.generate",
            "action.manage",
            "action.read",
        }
    ),
    REVIEWER_ROLE: frozenset(
        {
            "project.read",
            "evidence.read_summary",
            "analysis.read",
            "analysis.review",
            "score.read",
            "report.read",
            "report.approve",
            "report.revoke",
            "content.review",
        }
    ),
    KNOWLEDGE_ARCHITECT_ROLE: frozenset(
        {
            "project.read",
            "knowledge.read",
            "knowledge.import",
            "knowledge.review",
            "knowledge.read_approved",
            "content.read",
        }
    ),
    CONTENT_OPERATOR_ROLE: frozenset(
        {
            "project.read",
            "knowledge.read_approved",
            "content.read",
            "content.generate",
            "content.update",
            "distribution.read",
            "distribution.create",
            "distribution.update",
        }
    ),
    CLIENT_VIEWER_ROLE: frozenset(
        {
            "project.read",
            "score.read",
            "report.read",
            "report.download",
            "action.read",
            "retest.read",
            "knowledge.read_approved",
        }
    ),
}


ROLE_PERMISSION_CONDITIONS: Mapping[tuple[Role, Permission], tuple[str, ...]] = {
    (TENANT_ADMIN_ROLE, "audit.read"): ("tenant-scoped",),
    (ANALYST_ROLE, "evidence.read_raw"): ("internal-only",),
    (CLIENT_VIEWER_ROLE, "project.read"): ("customer-visible",),
    (CLIENT_VIEWER_ROLE, "score.read"): ("published-only",),
    (CLIENT_VIEWER_ROLE, "report.read"): ("published-only",),
    (CLIENT_VIEWER_ROLE, "report.download"): ("published-only",),
    (CLIENT_VIEWER_ROLE, "action.read"): ("customer-visible",),
    (CLIENT_VIEWER_ROLE, "retest.read"): ("published-only",),
    (CLIENT_VIEWER_ROLE, "knowledge.read_approved"): ("customer-visible",),
}


def _normalize_token(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def normalize_role(role: str) -> Role:
    normalized = _normalize_token(role)
    canonical = ROLE_ALIASES.get(normalized, normalized)
    if canonical not in ROLE_PERMISSION_MATRIX:
        raise UnknownRoleError(f"unknown role: {role}")
    return canonical


def normalize_permission(permission: str) -> Permission:
    normalized = permission.strip().lower()
    if normalized not in PERMISSION_VOCABULARY_SET:
        raise UnknownPermissionError(f"unknown permission: {permission}")
    return normalized


def is_permission_declared(permission: str) -> bool:
    return permission.strip().lower() in PERMISSION_VOCABULARY_SET


def permissions_for_role(role: str) -> frozenset[Permission]:
    return ROLE_PERMISSION_MATRIX[normalize_role(role)]


def permissions_for_roles(roles: Iterable[str]) -> frozenset[Permission]:
    permissions: set[Permission] = set()
    for role in roles:
        permissions.update(permissions_for_role(role))
    return frozenset(permissions)


def portal_capabilities_for_role(role: str) -> frozenset[str]:
    canonical = normalize_role(role)
    if canonical == CLIENT_VIEWER_ROLE:
        return frozenset({PORTAL_CUSTOMER_ACCESS})
    return frozenset({PORTAL_ADMIN_ACCESS})


def portal_capabilities_for_roles(roles: Iterable[str]) -> frozenset[str]:
    capabilities: set[str] = set()
    for role in roles:
        capabilities.update(portal_capabilities_for_role(role))
    return frozenset(capabilities)


def permission_conditions(role: str, permission: str) -> tuple[str, ...]:
    canonical_role = normalize_role(role)
    canonical_permission = normalize_permission(permission)
    return ROLE_PERMISSION_CONDITIONS.get((canonical_role, canonical_permission), ())


def role_has_permission(role: str, permission: str) -> bool:
    canonical_permission = normalize_permission(permission)
    return canonical_permission in permissions_for_role(role)


def roles_have_permission(
    roles: Iterable[str],
    permission: str,
    *,
    explicit_permissions: Iterable[str] = (),
) -> bool:
    canonical_permission = normalize_permission(permission)
    for explicit_permission in explicit_permissions:
        if normalize_permission(explicit_permission) == canonical_permission:
            return True
    return canonical_permission in permissions_for_roles(roles)


def validate_permission_matrix() -> None:
    vocabulary = set(PERMISSION_VOCABULARY)
    if len(vocabulary) != len(PERMISSION_VOCABULARY):
        raise RbacContractError("permission vocabulary contains duplicates")
    for role, permissions in ROLE_PERMISSION_MATRIX.items():
        unknown = sorted(set(permissions) - vocabulary)
        if unknown:
            raise RbacContractError(f"role {role} references unknown permissions: {', '.join(unknown)}")
    for role, permission in ROLE_PERMISSION_CONDITIONS:
        if role not in ROLE_PERMISSION_MATRIX:
            raise RbacContractError(f"condition references unknown role: {role}")
        if permission not in vocabulary:
            raise RbacContractError(f"condition references unknown permission: {permission}")
