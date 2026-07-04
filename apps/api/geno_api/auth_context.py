from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal


ActorType = Literal["anonymous", "user", "system", "service"]
AuthMethod = Literal["anonymous", "header", "jwt", "jwks", "session", "system"]


class AuthContextError(ValueError):
    pass


@dataclass(frozen=True)
class AuthContext:
    actor_id: str | None
    actor_type: ActorType
    tenant_id: str | None
    project_ids: tuple[str, ...]
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    session_id: str | None
    request_id: str | None
    ip_hash: str | None
    user_agent_hash: str | None
    auth_method: AuthMethod
    reason: str | None = None

    @property
    def is_authenticated(self) -> bool:
        return self.actor_id is not None and self.actor_type != "anonymous"

    @property
    def is_system_actor(self) -> bool:
        return self.actor_type in {"system", "service"}


def hash_context_value(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_items(values: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(str(item).strip() for item in values if str(item).strip())


def build_anonymous_auth_context(*, auth_method: AuthMethod = "anonymous", request_id: str | None = None) -> AuthContext:
    return AuthContext(
        actor_id=None,
        actor_type="anonymous",
        tenant_id=None,
        project_ids=(),
        roles=(),
        permissions=(),
        session_id=None,
        request_id=request_id.strip() if request_id else None,
        ip_hash=None,
        user_agent_hash=None,
        auth_method=auth_method,
    )


def build_user_auth_context(
    *,
    actor_id: str,
    auth_method: AuthMethod,
    tenant_id: str | None = None,
    project_ids: tuple[str, ...] | list[str] | None = None,
    roles: tuple[str, ...] | list[str] | None = None,
    permissions: tuple[str, ...] | list[str] | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    client_host: str | None = None,
    user_agent: str | None = None,
) -> AuthContext:
    normalized_actor_id = actor_id.strip()
    if not normalized_actor_id:
        raise AuthContextError("actor_id is required for user AuthContext")
    if auth_method not in {"header", "jwt", "jwks", "session"}:
        raise AuthContextError("user AuthContext requires header, jwt, jwks, or session auth_method")
    return AuthContext(
        actor_id=normalized_actor_id,
        actor_type="user",
        tenant_id=tenant_id.strip() if tenant_id else None,
        project_ids=_normalize_items(project_ids),
        roles=_normalize_items(roles),
        permissions=_normalize_items(permissions),
        session_id=session_id.strip() if session_id else None,
        request_id=request_id.strip() if request_id else None,
        ip_hash=hash_context_value(client_host),
        user_agent_hash=hash_context_value(user_agent),
        auth_method=auth_method,
    )


def build_system_auth_context(
    *,
    service_name: str,
    reason: str,
    tenant_id: str | None = None,
    project_ids: tuple[str, ...] | list[str] | None = None,
    roles: tuple[str, ...] | list[str] | None = None,
    permissions: tuple[str, ...] | list[str] | None = None,
    request_id: str | None = None,
) -> AuthContext:
    normalized_service_name = service_name.strip()
    normalized_reason = reason.strip()
    if not normalized_service_name:
        raise AuthContextError("service_name is required for system AuthContext")
    if not normalized_reason:
        raise AuthContextError("reason is required for system AuthContext")
    return AuthContext(
        actor_id=f"system:{normalized_service_name}",
        actor_type="system",
        tenant_id=tenant_id.strip() if tenant_id else None,
        project_ids=_normalize_items(project_ids),
        roles=_normalize_items(roles),
        permissions=_normalize_items(permissions),
        session_id=None,
        request_id=request_id.strip() if request_id else None,
        ip_hash=None,
        user_agent_hash=None,
        auth_method="system",
        reason=normalized_reason,
    )


def auth_context_scope(context: AuthContext) -> dict[str, object]:
    return {
        "actor_id": context.actor_id,
        "actor_type": context.actor_type,
        "tenant_id": context.tenant_id,
        "project_ids": context.project_ids,
        "roles": context.roles,
        "permissions": context.permissions,
        "session_id": context.session_id,
        "auth_method": context.auth_method,
        "is_system_actor": context.is_system_actor,
    }
