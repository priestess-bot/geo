from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

from geo_core.auth_delivery import (
    AuthDeliveryKeyring,
    FrozenAuthDelivery,
    auth_delivery_max_replay,
    auth_delivery_recovery_ttl_seconds,
    build_frozen_auth_delivery,
)
from geo_core.models import RuntimeProjectSessionScope, RuntimeSessionScopeV2
from geo_core.rbac import (
    PORTAL_ADMIN_ACCESS,
    PORTAL_CUSTOMER_ACCESS,
    normalize_role,
    permissions_for_roles,
    portal_capabilities_for_roles,
)


AUTH_SURFACE_POLICY_VERSION = "auth_surface_policy_v1"
RUNTIME_SESSION_SCOPE_VERSION = "runtime_session_scope_v2"
AUTH_WRITES_ENABLED_ENV = "AUTH_WRITES_ENABLED"


class InvitationSurface(str, Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"


class InvitationSurfaceCompatibility(str, Enum):
    COMPATIBLE = "compatible"
    SURFACE_MISMATCH = "surface_mismatch"
    POLICY_STALE = "policy_stale"
    INVALID = "invalid"


class InvitationRedeemRecoveryStatus(str, Enum):
    CREATED = "created"
    REPLAYED = "replayed"
    CONFIRMED = "confirmed"
    RECOVERY_EXPIRED = "recovery_expired"
    REPLAY_LIMIT_EXCEEDED = "replay_limit_exceeded"


class AuthContractError(Exception):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        http_status: int,
        correlation_id: str | None = None,
        recommended_surface: str | None = None,
        commit_state: bool = False,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.http_status = http_status
        self.correlation_id = correlation_id or str(uuid4())
        self.recommended_surface = recommended_surface
        self.commit_state = commit_state


class AuthWritesDisabledError(AuthContractError):
    def __init__(self) -> None:
        super().__init__(
            "auth_writes_temporarily_disabled",
            "Authentication writes are temporarily disabled.",
            http_status=503,
        )


@dataclass(frozen=True)
class AuthInvitationPreflightResult:
    compatibility: InvitationSurfaceCompatibility
    requested_surface: InvitationSurface
    recommended_surface: InvitationSurface | None
    invitation_role: str | None
    policy_version: str
    correlation_id: str


@dataclass(frozen=True)
class AuthInvitationRedeemResult:
    recovery_status: InvitationRedeemRecoveryStatus
    session: RuntimeSessionScopeV2
    cookie_delivery: FrozenAuthDelivery
    correlation_id: str


class Cursor(Protocol):
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> Any: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> Any: ...

    def __enter__(self) -> "Cursor": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


INVITATION_COLUMNS = (
    "id",
    "project_id",
    "tenant_id",
    "email",
    "role",
    "status",
    "invite_token_hash",
    "expires_at",
    "audience",
    "allowed_surfaces",
    "policy_version",
    "accepted_by_attempt_id",
)
ATTEMPT_COLUMNS = (
    "id",
    "invitation_id",
    "requested_surface",
    "idempotency_key_hash",
    "request_hash",
    "token_fingerprint",
    "session_id",
    "status",
    "replay_count",
    "delivery_ciphertext",
    "delivery_key_id",
    "delivery_nonce",
    "delivery_expires_at",
    "delivery_confirmed_at",
    "secret_erased_at",
    "created_at",
    "updated_at",
)
SESSION_SCOPE_COLUMNS = (
    "id",
    "actor_id",
    "tenant_id",
    "scope_version",
    "authz_policy_version",
    "tenant_roles",
    "project_scopes",
    "project_ids",
)


def assert_auth_writes_enabled(env: Mapping[str, str] | None = None) -> None:
    runtime_env = os.environ if env is None else env
    value = runtime_env.get(AUTH_WRITES_ENABLED_ENV, "1").strip().lower()
    if value not in {"1", "true", "yes", "on"}:
        raise AuthWritesDisabledError()


def surface_for_role(role: str) -> InvitationSurface:
    canonical = normalize_role(role)
    return InvitationSurface.CUSTOMER if canonical == "client_viewer" else InvitationSurface.ADMIN


def surfaces_for_role(role: str) -> frozenset[InvitationSurface]:
    return frozenset({surface_for_role(role)})


def effective_invitation_surfaces(
    *,
    role: str,
    issued_surfaces: object,
) -> frozenset[InvitationSurface]:
    current = surfaces_for_role(role)
    snapshot: set[InvitationSurface] = set()
    for value in _sequence(issued_surfaces):
        try:
            snapshot.add(InvitationSurface(str(value).strip().lower()))
        except ValueError:
            continue
    return frozenset(snapshot & current)


def canonical_redeem_request_hash(
    *,
    invitation_id: str,
    token_fingerprint: str,
    requested_surface: InvitationSurface,
) -> str:
    payload = {
        "invitation_id": invitation_id,
        "requested_surface": requested_surface.value,
        "token_fingerprint": token_fingerprint,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_session_scope_v2(
    *,
    actor_id: str,
    tenant_id: str,
    tenant_roles: tuple[str, ...],
    direct_memberships: list[dict[str, Any]],
    grants: list[dict[str, Any]],
) -> RuntimeSessionScopeV2:
    project_roles: dict[str, set[str]] = {}
    project_permissions: dict[str, set[str]] = {}
    project_sources: dict[str, set[str]] = {}

    for membership in direct_memberships:
        project_id = str(membership.get("project_id") or "").strip()
        role = str(membership.get("role") or "").strip()
        if not project_id or not role:
            continue
        canonical_role = normalize_role(role)
        project_roles.setdefault(project_id, set()).add(canonical_role)
        project_permissions.setdefault(project_id, set()).update(permissions_for_roles((canonical_role,)))
        project_sources.setdefault(project_id, set()).add("direct_member")

    for grant in grants:
        project_id = str(grant.get("project_id") or "").strip()
        role = str(grant.get("canonical_role") or "").strip()
        if not project_id or not role:
            continue
        canonical_role = normalize_role(role)
        project_roles.setdefault(project_id, set()).add(canonical_role)
        project_permissions.setdefault(project_id, set()).update(
            str(item).strip() for item in _sequence(grant.get("permissions")) if str(item).strip()
        )
        project_sources.setdefault(project_id, set()).add("tenant_role")

    scopes: list[RuntimeProjectSessionScope] = []
    for project_id in sorted(project_roles):
        roles = tuple(sorted(project_roles[project_id]))
        scopes.append(
            RuntimeProjectSessionScope(
                project_id=project_id,
                roles=roles,
                permissions=tuple(sorted(project_permissions.get(project_id, set()))),
                portal_capabilities=tuple(sorted(portal_capabilities_for_roles(roles))),
                scope_sources=tuple(sorted(project_sources.get(project_id, set()))),
            )
        )
    project_scopes = tuple(scopes)
    return RuntimeSessionScopeV2(
        actor_id=actor_id,
        tenant_id=tenant_id,
        tenant_roles=tuple(dict.fromkeys(normalize_role(role) for role in tenant_roles)),
        project_scopes=project_scopes,
        project_ids=tuple(scope.project_id for scope in project_scopes),
    )


def project_scope_for_surface(
    scope: RuntimeSessionScopeV2,
    surface: InvitationSurface,
) -> tuple[RuntimeProjectSessionScope, ...]:
    capability = PORTAL_ADMIN_ACCESS if surface is InvitationSurface.ADMIN else PORTAL_CUSTOMER_ACCESS
    return tuple(item for item in scope.project_scopes if capability in item.portal_capabilities)


class AuthSessionV2Repository:
    def __init__(
        self,
        connection: Connection,
        *,
        keyring: AuthDeliveryKeyring | None,
        session_cookie_name: str = "GEO_RUNTIME_SESSION",
        csrf_cookie_name: str = "GEO_CSRF_TOKEN",
        cookie_secure: bool = True,
        session_ttl_seconds: int = 604800,
        recovery_ttl_seconds: int | None = None,
        max_replay: int | None = None,
    ) -> None:
        self.connection = connection
        self.keyring = keyring
        self.session_cookie_name = session_cookie_name
        self.csrf_cookie_name = csrf_cookie_name
        self.cookie_secure = cookie_secure
        self.session_ttl_seconds = max(60, min(int(session_ttl_seconds), 60 * 60 * 24 * 30))
        self.recovery_ttl_seconds = recovery_ttl_seconds or auth_delivery_recovery_ttl_seconds()
        self.max_replay = max_replay or auth_delivery_max_replay()

    def preflight(
        self,
        *,
        invitation_id: str,
        invite_token: str,
        requested_surface: InvitationSurface,
    ) -> AuthInvitationPreflightResult:
        reset_auth_connection_context(self.connection)
        correlation_id = str(uuid4())
        token_hash = _token_hash(invite_token, field="invite_token")
        invitation_id = _required(invitation_id, field="invitation_id")
        try:
            with self.connection.cursor() as cursor:
                _set_invitation_context(cursor, token_hash=token_hash)
                cursor.execute(
                    f"""
                    SELECT {", ".join(INVITATION_COLUMNS)}
                    FROM project_member_invitations
                    WHERE id = %s AND invite_token_hash = %s
                    LIMIT 1
                    """,
                    (_uuid(invitation_id), token_hash),
                )
                invitation = _row(cursor.fetchone(), INVITATION_COLUMNS)
            if not _invitation_is_pending_and_current(invitation):
                return AuthInvitationPreflightResult(
                    compatibility=InvitationSurfaceCompatibility.INVALID,
                    requested_surface=requested_surface,
                    recommended_surface=None,
                    invitation_role=None,
                    policy_version=AUTH_SURFACE_POLICY_VERSION,
                    correlation_id=correlation_id,
                )
            role = normalize_role(str(invitation["role"]))
            if not _invitation_policy_is_current(invitation, role=role):
                return AuthInvitationPreflightResult(
                    compatibility=InvitationSurfaceCompatibility.POLICY_STALE,
                    requested_surface=requested_surface,
                    recommended_surface=None,
                    invitation_role=role,
                    policy_version=AUTH_SURFACE_POLICY_VERSION,
                    correlation_id=correlation_id,
                )
            effective = effective_invitation_surfaces(role=role, issued_surfaces=invitation.get("allowed_surfaces"))
            if not effective:
                compatibility = InvitationSurfaceCompatibility.POLICY_STALE
                recommended = None
            elif requested_surface not in effective:
                compatibility = InvitationSurfaceCompatibility.SURFACE_MISMATCH
                recommended = sorted(effective, key=lambda item: item.value)[0]
            else:
                compatibility = InvitationSurfaceCompatibility.COMPATIBLE
                recommended = requested_surface
            return AuthInvitationPreflightResult(
                compatibility=compatibility,
                requested_surface=requested_surface,
                recommended_surface=recommended,
                invitation_role=role,
                policy_version=AUTH_SURFACE_POLICY_VERSION,
                correlation_id=correlation_id,
            )
        finally:
            _rollback(self.connection)

    def redeem(
        self,
        *,
        invitation_id: str,
        invite_token: str,
        requested_surface: InvitationSurface,
        idempotency_key: str,
    ) -> AuthInvitationRedeemResult:
        assert_auth_writes_enabled()
        if self.keyring is None:
            raise AuthContractError(
                "auth_writes_temporarily_disabled",
                "Authentication delivery encryption is unavailable.",
                http_status=503,
            )
        reset_auth_connection_context(self.connection)
        invitation_id = _required(invitation_id, field="invitation_id")
        idempotency_key = _required(idempotency_key, field="Idempotency-Key")
        token_hash = _token_hash(invite_token, field="invite_token")
        token_fingerprint = hashlib.sha256(invite_token.strip().encode("utf-8")).hexdigest()
        idempotency_key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        request_hash = canonical_redeem_request_hash(
            invitation_id=invitation_id,
            token_fingerprint=token_fingerprint,
            requested_surface=requested_surface,
        )
        correlation_id = str(uuid4())
        try:
            with self.connection.cursor() as cursor:
                _set_invitation_context(
                    cursor,
                    token_hash=token_hash,
                    idempotency_key_hash=idempotency_key_hash,
                    requested_surface=requested_surface.value,
                )
                cursor.execute(
                    f"""
                    SELECT {", ".join(INVITATION_COLUMNS)}
                    FROM project_member_invitations
                    WHERE id = %s AND invite_token_hash = %s
                    FOR UPDATE
                    """,
                    (_uuid(invitation_id), token_hash),
                )
                invitation = _row(cursor.fetchone(), INVITATION_COLUMNS)
                if not invitation:
                    # A concurrent winner may have changed pending -> accepted while
                    # this command waited on its row lock. Start a fresh snapshot so
                    # the exact key/surface recovery helper can see the committed attempt.
                    self.connection.rollback()
                    _set_invitation_context(
                        cursor,
                        token_hash=token_hash,
                        idempotency_key_hash=idempotency_key_hash,
                        requested_surface=requested_surface.value,
                    )
                    cursor.execute(
                        f"""
                        SELECT {", ".join(INVITATION_COLUMNS)}
                        FROM project_member_invitations
                        WHERE id = %s AND invite_token_hash = %s
                        FOR UPDATE
                        """,
                        (_uuid(invitation_id), token_hash),
                    )
                    invitation = _row(cursor.fetchone(), INVITATION_COLUMNS)
                if not invitation:
                    raise AuthContractError(
                        "invitation_invalid",
                        "The invitation is invalid or unavailable.",
                        http_status=404,
                        correlation_id=correlation_id,
                    )

                attempt_id = str(uuid4())
                cursor.execute(
                    """
                    INSERT INTO auth_invitation_redemption_attempts (
                      id, invitation_id, requested_surface, idempotency_key_hash,
                      request_hash, token_fingerprint, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'preparing')
                    ON CONFLICT (invitation_id, requested_surface, idempotency_key_hash)
                    DO NOTHING
                    """,
                    (
                        _uuid(attempt_id),
                        _uuid(invitation_id),
                        requested_surface.value,
                        idempotency_key_hash,
                        request_hash,
                        token_fingerprint,
                    ),
                )
                cursor.execute(
                    f"""
                    SELECT {", ".join(ATTEMPT_COLUMNS)}
                    FROM auth_invitation_redemption_attempts
                    WHERE invitation_id = %s
                      AND requested_surface = %s
                      AND idempotency_key_hash = %s
                    FOR UPDATE
                    """,
                    (_uuid(invitation_id), requested_surface.value, idempotency_key_hash),
                )
                attempt = _row(cursor.fetchone(), ATTEMPT_COLUMNS)
                if not attempt:
                    raise RuntimeError("auth redemption attempt was not created")
                attempt_id = str(attempt["id"])
                correlation_id = attempt_id
                self._validate_attempt_binding(
                    attempt,
                    request_hash=request_hash,
                    token_fingerprint=token_fingerprint,
                )

                if attempt.get("status") == "succeeded":
                    actor_id = _normalize_actor(str(invitation.get("email") or ""))
                    tenant_id = str(invitation.get("tenant_id") or "")
                    _set_actor_context(cursor, actor_id=actor_id, tenant_id=tenant_id)
                    result = self._replay_attempt(cursor, attempt=attempt, correlation_id=correlation_id)
                    self.connection.commit()
                    return result

                self._assert_db_writes_enabled(cursor)
                self._validate_new_redemption(
                    invitation,
                    requested_surface=requested_surface,
                    correlation_id=correlation_id,
                )
                actor_id = _normalize_actor(str(invitation["email"]))
                tenant_id = str(invitation["tenant_id"])
                project_id = str(invitation["project_id"])
                canonical_role = normalize_role(str(invitation["role"]))

                _set_actor_context(cursor, actor_id=actor_id, tenant_id=tenant_id)

                cursor.execute(
                    """
                    SELECT id, role, status
                    FROM geo_runtime_lock_invited_member(%s, %s, %s)
                    """,
                    (_uuid(project_id), _uuid(tenant_id), actor_id),
                )
                member = _row(cursor.fetchone(), ("id", "role", "status"))
                if member and (member.get("status") != "active" or normalize_role(str(member["role"])) != canonical_role):
                    raise AuthContractError(
                        "invitation_invalid",
                        "The invitation is invalid or unavailable.",
                        http_status=409,
                        correlation_id=correlation_id,
                    )
                if not member:
                    cursor.execute(
                        """
                        INSERT INTO project_members (
                          id, project_id, tenant_id, user_id, role, status, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, 'active', now())
                        """,
                        (_uuid(str(uuid4())), _uuid(project_id), _uuid(tenant_id), actor_id, str(invitation["role"]).lower()),
                    )

                scope = self._load_scope(cursor, actor_id=actor_id, tenant_id=tenant_id)
                if project_id not in scope.project_ids:
                    raise RuntimeError("redeemed project is missing from runtime session scope")

                now = datetime.now(UTC)
                session_expires_at = now + timedelta(seconds=self.session_ttl_seconds)
                delivery_expires_at = now + timedelta(seconds=self.recovery_ttl_seconds)
                raw_session_token = f"geo-session-{secrets.token_urlsafe(32)}"
                csrf_token = secrets.token_urlsafe(32)
                delivery = build_frozen_auth_delivery(
                    session_cookie_name=self.session_cookie_name,
                    session_token=raw_session_token,
                    csrf_cookie_name=self.csrf_cookie_name,
                    csrf_token=csrf_token,
                    session_expires_at=session_expires_at,
                    secure=self.cookie_secure,
                )
                encrypted = self.keyring.encrypt(delivery, attempt_id=attempt_id)
                session_id = str(uuid4())
                flat_roles = tuple(
                    dict.fromkeys((*scope.tenant_roles, *(role for item in scope.project_scopes for role in item.roles)))
                )
                flat_permissions = tuple(
                    sorted({permission for item in scope.project_scopes for permission in item.permissions})
                )
                cursor.execute(
                    """
                    INSERT INTO runtime_sessions (
                      id, session_token_hash, actor_id, actor_type, tenant_id,
                      project_ids, roles, permissions, tenant_roles, project_scopes,
                      scope_version, authz_policy_version, redemption_attempt_id,
                      auth_method, status, issued_by, issued_at, expires_at, metadata
                    )
                    VALUES (
                      %s, %s, %s, 'user', %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s,
                      'session', 'active', 'auth.invitation.redeem', %s, %s, %s
                    )
                    """,
                    (
                        _uuid(session_id),
                        hashlib.sha256(raw_session_token.encode("utf-8")).hexdigest(),
                        actor_id,
                        _uuid(tenant_id),
                        _json_payload(list(scope.project_ids)),
                        _json_payload(list(flat_roles)),
                        _json_payload(list(flat_permissions)),
                        _json_payload(list(scope.tenant_roles)),
                        _json_payload([asdict(item) for item in scope.project_scopes]),
                        RUNTIME_SESSION_SCOPE_VERSION,
                        AUTH_SURFACE_POLICY_VERSION,
                        _uuid(attempt_id),
                        now,
                        session_expires_at,
                        _json_payload({"source": "invitation_redeem", "invitation_id": invitation_id}),
                    ),
                )
                cursor.execute(
                    """
                    UPDATE project_member_invitations
                    SET status = 'accepted',
                        accepted_at = now(),
                        accepted_by_attempt_id = %s,
                        updated_at = now()
                    WHERE id = %s AND status = 'pending'
                    """,
                    (_uuid(attempt_id), _uuid(invitation_id)),
                )
                cursor.execute(
                    """
                    UPDATE auth_invitation_redemption_attempts
                    SET session_id = %s,
                        status = 'succeeded',
                        delivery_ciphertext = %s,
                        delivery_key_id = %s,
                        delivery_nonce = %s,
                        delivery_expires_at = %s,
                        updated_at = now()
                    WHERE id = %s AND status = 'preparing'
                    """,
                    (
                        _uuid(session_id),
                        encrypted.ciphertext,
                        encrypted.key_id,
                        encrypted.nonce,
                        delivery_expires_at,
                        _uuid(attempt_id),
                    ),
                )
                self._write_accept_audit(
                    cursor,
                    project_id=project_id,
                    actor_id=actor_id,
                    invitation_id=invitation_id,
                    attempt_id=attempt_id,
                    session_id=session_id,
                    token_fingerprint=token_fingerprint,
                    idempotency_key_hash=idempotency_key_hash,
                )
            self.connection.commit()
            return AuthInvitationRedeemResult(
                recovery_status=InvitationRedeemRecoveryStatus.CREATED,
                session=scope,
                cookie_delivery=delivery,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            if isinstance(exc, AuthContractError) and exc.commit_state:
                self.connection.commit()
            else:
                _rollback(self.connection)
            raise

    def confirm_delivery(self, *, session_id: str, actor_id: str, tenant_id: str) -> bool:
        reset_auth_connection_context(self.connection)
        try:
            with self.connection.cursor() as cursor:
                _set_actor_context(cursor, actor_id=_normalize_actor(actor_id), tenant_id=tenant_id)
                cursor.execute(
                    """
                    SELECT redemption_attempt_id
                    FROM runtime_sessions
                    WHERE id = %s AND status = 'active' AND lower(btrim(actor_id)) = %s
                    FOR UPDATE
                    """,
                    (_uuid(session_id), _normalize_actor(actor_id)),
                )
                row = cursor.fetchone()
                attempt_id = row.get("redemption_attempt_id") if isinstance(row, dict) else (row[0] if row else None)
                if not attempt_id:
                    self.connection.commit()
                    return False
                cursor.execute(
                    """
                    UPDATE auth_invitation_redemption_attempts
                    SET delivery_confirmed_at = coalesce(delivery_confirmed_at, now()),
                        delivery_ciphertext = NULL,
                        delivery_key_id = NULL,
                        delivery_nonce = NULL,
                        secret_erased_at = coalesce(secret_erased_at, now()),
                        updated_at = now()
                    WHERE id = %s
                      AND session_id = %s
                      AND status = 'succeeded'
                    """,
                    (_uuid(str(attempt_id)), _uuid(session_id)),
                )
            self.connection.commit()
            return True
        except Exception:
            _rollback(self.connection)
            raise

    def _load_scope(self, cursor: Cursor, *, actor_id: str, tenant_id: str) -> RuntimeSessionScopeV2:
        cursor.execute(
            """
            SELECT role
            FROM tenant_members
            WHERE tenant_id = %s AND lower(btrim(user_id)) = %s AND status = 'active'
            ORDER BY created_at, id
            FOR SHARE
            """,
            (_uuid(tenant_id), actor_id),
        )
        tenant_roles = tuple(
            normalize_role(str(_row(row, ("role",)).get("role")))
            for row in (cursor.fetchall() or ())
        )
        cursor.execute(
            """
            SELECT project_id, role
            FROM geo_runtime_lock_scope_members(%s, %s)
            """,
            (actor_id, _uuid(tenant_id)),
        )
        direct_memberships = [_row(row, ("project_id", "role")) for row in (cursor.fetchall() or ())]
        cursor.execute(
            """
            SELECT project_id, canonical_role, permissions
            FROM geo_runtime_lock_scope_grants(%s, %s)
            """,
            (actor_id, _uuid(tenant_id)),
        )
        grants = [
            _row(row, ("project_id", "canonical_role", "permissions"))
            for row in (cursor.fetchall() or ())
        ]
        scope = build_session_scope_v2(
            actor_id=actor_id,
            tenant_id=tenant_id,
            tenant_roles=tenant_roles,
            direct_memberships=direct_memberships,
            grants=grants,
        )
        if scope.project_ids:
            cursor.execute(
                """
                SELECT id
                FROM projects
                WHERE tenant_id = %s
                  AND id = ANY(%s::uuid[])
                  AND status <> 'archived'
                ORDER BY id
                FOR SHARE
                """,
                (_uuid(tenant_id), list(scope.project_ids)),
            )
            locked_project_ids = {str(_row(row, ("id",)).get("id")) for row in (cursor.fetchall() or ())}
            if locked_project_ids != set(scope.project_ids):
                raise AuthContractError(
                    "invitation_policy_stale",
                    "The invitation project scope changed during redemption.",
                    http_status=409,
                )
        return scope

    def _replay_attempt(
        self,
        cursor: Cursor,
        *,
        attempt: dict[str, Any],
        correlation_id: str,
    ) -> AuthInvitationRedeemResult:
        if attempt.get("delivery_confirmed_at") is not None or attempt.get("secret_erased_at") is not None:
            raise AuthContractError(
                "redeem_recovery_expired",
                "The invitation delivery recovery window is no longer available.",
                http_status=410,
                correlation_id=correlation_id,
                commit_state=True,
            )
        expires_at = _datetime(attempt.get("delivery_expires_at"))
        if expires_at is None or expires_at <= datetime.now(UTC):
            cursor.execute(
                """
                UPDATE auth_invitation_redemption_attempts
                SET delivery_ciphertext = NULL, delivery_key_id = NULL, delivery_nonce = NULL,
                    secret_erased_at = coalesce(secret_erased_at, now()), updated_at = now()
                WHERE id = %s
                """,
                (_uuid(str(attempt["id"])),),
            )
            raise AuthContractError(
                "redeem_recovery_expired",
                "The invitation delivery recovery window has expired.",
                http_status=410,
                correlation_id=correlation_id,
                commit_state=True,
            )
        if int(attempt.get("replay_count") or 0) >= self.max_replay:
            raise AuthContractError(
                "redeem_replay_limit_exceeded",
                "The invitation delivery replay limit has been exceeded.",
                http_status=429,
                correlation_id=correlation_id,
            )
        if not attempt.get("delivery_ciphertext") or not attempt.get("delivery_key_id") or not attempt.get("delivery_nonce"):
            raise AuthContractError(
                "redeem_recovery_expired",
                "The invitation delivery recovery material is unavailable.",
                http_status=410,
                correlation_id=correlation_id,
            )
        if self.keyring is None:
            raise AuthContractError(
                "auth_writes_temporarily_disabled",
                "Authentication delivery encryption is unavailable.",
                http_status=503,
                correlation_id=correlation_id,
            )
        delivery = self.keyring.decrypt(
            ciphertext=bytes(attempt["delivery_ciphertext"]),
            key_id=str(attempt["delivery_key_id"]),
            nonce=bytes(attempt["delivery_nonce"]),
            attempt_id=str(attempt["id"]),
        )
        cursor.execute(
            """
            UPDATE auth_invitation_redemption_attempts
            SET replay_count = replay_count + 1, updated_at = now()
            WHERE id = %s
            """,
            (_uuid(str(attempt["id"])),),
        )
        cursor.execute(
            f"""
            SELECT {", ".join(SESSION_SCOPE_COLUMNS)}
            FROM runtime_sessions
            WHERE id = %s AND status = 'active'
            LIMIT 1
            """,
            (_uuid(str(attempt["session_id"])),),
        )
        session = _row(cursor.fetchone(), SESSION_SCOPE_COLUMNS)
        if not session:
            raise AuthContractError(
                "invitation_already_consumed",
                "The invitation has already been consumed.",
                http_status=409,
                correlation_id=correlation_id,
            )
        return AuthInvitationRedeemResult(
            recovery_status=InvitationRedeemRecoveryStatus.REPLAYED,
            session=_session_scope_from_record(session),
            cookie_delivery=delivery,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _validate_attempt_binding(
        attempt: dict[str, Any],
        *,
        request_hash: str,
        token_fingerprint: str,
    ) -> None:
        if not secrets.compare_digest(str(attempt.get("request_hash") or ""), request_hash) or not secrets.compare_digest(
            str(attempt.get("token_fingerprint") or ""), token_fingerprint
        ):
            raise AuthContractError(
                "idempotency_key_reused",
                "The Idempotency-Key was already used for a different request.",
                http_status=409,
                correlation_id=str(attempt.get("id") or uuid4()),
            )

    @staticmethod
    def _assert_db_writes_enabled(cursor: Cursor) -> None:
        cursor.execute("SELECT writes_enabled FROM auth_runtime_write_controls WHERE singleton")
        row = cursor.fetchone()
        enabled = row.get("writes_enabled") if isinstance(row, dict) else (row[0] if row else False)
        if enabled is not True:
            raise AuthWritesDisabledError()

    @staticmethod
    def _validate_new_redemption(
        invitation: dict[str, Any],
        *,
        requested_surface: InvitationSurface,
        correlation_id: str,
    ) -> None:
        if invitation.get("status") != "pending":
            raise AuthContractError(
                "invitation_already_consumed",
                "The invitation has already been consumed.",
                http_status=409,
                correlation_id=correlation_id,
            )
        expires_at = _datetime(invitation.get("expires_at"))
        if expires_at is not None and expires_at <= datetime.now(UTC):
            raise AuthContractError(
                "invitation_invalid",
                "The invitation is invalid or unavailable.",
                http_status=404,
                correlation_id=correlation_id,
            )
        role = normalize_role(str(invitation.get("role") or ""))
        if not _invitation_policy_is_current(invitation, role=role):
            raise AuthContractError(
                "invitation_policy_stale",
                "The invitation policy is no longer valid.",
                http_status=409,
                correlation_id=correlation_id,
            )
        effective = effective_invitation_surfaces(role=role, issued_surfaces=invitation.get("allowed_surfaces"))
        if not effective:
            raise AuthContractError(
                "invitation_policy_stale",
                "The invitation policy is no longer valid.",
                http_status=409,
                correlation_id=correlation_id,
            )
        if requested_surface not in effective:
            recommended = sorted(effective, key=lambda item: item.value)[0]
            raise AuthContractError(
                "invitation_surface_mismatch",
                "This invitation cannot open the requested surface.",
                http_status=409,
                correlation_id=correlation_id,
                recommended_surface=recommended.value,
            )

    @staticmethod
    def _write_accept_audit(
        cursor: Cursor,
        *,
        project_id: str,
        actor_id: str,
        invitation_id: str,
        attempt_id: str,
        session_id: str,
        token_fingerprint: str,
        idempotency_key_hash: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO audit_events (
              id, event_type, project_id, actor_type, actor_id, target_type,
              target_id, input_refs, output_refs, method_version, reason
            )
            VALUES (%s, 'project_member_invitation_accepted', %s, 'user', %s,
                    'project_member_invitation', %s, %s, %s,
                    'auth_invitation_redeem_v2', 'auth_invitation_redeem')
            """,
            (
                _uuid(str(uuid4())),
                _uuid(project_id),
                actor_id,
                invitation_id,
                _json_payload(
                    {
                        "project_member_invitation_ids": [invitation_id],
                        "token_fingerprints": [token_fingerprint],
                        "idempotency_key_hashes": [idempotency_key_hash],
                    }
                ),
                _json_payload(
                    {
                        "redemption_attempt_ids": [attempt_id],
                        "runtime_session_ids": [session_id],
                        "status": ["accepted"],
                    }
                ),
            ),
        )


def _session_scope_from_record(record: dict[str, Any]) -> RuntimeSessionScopeV2:
    project_scopes_value = _json_value(record.get("project_scopes"), default=[])
    tenant_roles_value = _json_value(record.get("tenant_roles"), default=[])
    scopes = tuple(
        RuntimeProjectSessionScope(
            project_id=str(item.get("project_id") or ""),
            roles=tuple(str(value) for value in _sequence(item.get("roles"))),
            permissions=tuple(str(value) for value in _sequence(item.get("permissions"))),
            portal_capabilities=tuple(str(value) for value in _sequence(item.get("portal_capabilities"))),
            scope_sources=tuple(str(value) for value in _sequence(item.get("scope_sources"))),
        )
        for item in project_scopes_value
        if isinstance(item, dict) and item.get("project_id")
    )
    return RuntimeSessionScopeV2(
        actor_id=str(record["actor_id"]),
        tenant_id=str(record["tenant_id"]),
        tenant_roles=tuple(str(value) for value in _sequence(tenant_roles_value)),
        project_scopes=scopes,
        project_ids=tuple(item.project_id for item in scopes),
        scope_version=str(record.get("scope_version") or RUNTIME_SESSION_SCOPE_VERSION),
        authz_policy_version=str(record.get("authz_policy_version") or AUTH_SURFACE_POLICY_VERSION),
    )


def _set_invitation_context(
    cursor: Cursor,
    *,
    token_hash: str,
    idempotency_key_hash: str = "",
    requested_surface: str = "",
) -> None:
    cursor.execute(
        """
        SELECT
          set_config('app.rls_enabled', '1', true),
          set_config('app.actor_id', '', true),
          set_config('app.project_id', '', true),
          set_config('app.project_ids', '', true),
          set_config('app.tenant_id', '', true),
          set_config('geo.runtime_project_access_control', '1', true),
          set_config('geo.runtime_actor_id', '', true),
          set_config('geo.runtime_project_id', '', true),
          set_config('geo.runtime_tenant_id', '', true),
          set_config('geo.runtime_invitation_token_hash', %s, true),
          set_config('geo.runtime_idempotency_key_hash', %s, true),
          set_config('geo.runtime_requested_surface', %s, true)
        """,
        (token_hash, idempotency_key_hash, requested_surface),
    )


def reset_auth_connection_context(connection: Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              set_config('app.rls_enabled', '1', false),
              set_config('app.actor_id', '', false),
              set_config('app.project_id', '', false),
              set_config('app.project_ids', '', false),
              set_config('app.tenant_id', '', false),
              set_config('geo.runtime_project_access_control', '1', false),
              set_config('geo.runtime_actor_id', '', false),
              set_config('geo.runtime_project_id', '', false),
              set_config('geo.runtime_tenant_id', '', false),
              set_config('geo.runtime_invitation_token_hash', '', false),
              set_config('geo.runtime_idempotency_key_hash', '', false),
              set_config('geo.runtime_requested_surface', '', false),
              set_config('geo.runtime_portal_token_hash', '', false),
              set_config('geo.runtime_session_token_hash', '', false)
            """
        )
    connection.commit()


def _set_actor_context(cursor: Cursor, *, actor_id: str, tenant_id: str) -> None:
    cursor.execute(
        """
        SELECT
          set_config('app.actor_id', %s, true),
          set_config('app.project_id', '', true),
          set_config('app.project_ids', '', true),
          set_config('app.tenant_id', %s, true),
          set_config('geo.runtime_actor_id', %s, true),
          set_config('geo.runtime_project_id', '', true),
          set_config('geo.runtime_tenant_id', %s, true)
        """,
        (actor_id, tenant_id, actor_id, tenant_id),
    )


def _invitation_is_pending_and_current(invitation: dict[str, Any]) -> bool:
    if not invitation or invitation.get("status") != "pending":
        return False
    expires_at = _datetime(invitation.get("expires_at"))
    return expires_at is None or expires_at > datetime.now(UTC)


def _invitation_policy_is_current(invitation: dict[str, Any], *, role: str) -> bool:
    if str(invitation.get("policy_version") or "").strip() != AUTH_SURFACE_POLICY_VERSION:
        return False
    try:
        audience = InvitationSurface(str(invitation.get("audience") or "").strip().lower())
    except ValueError:
        return False
    issued = {
        surface
        for value in _sequence(invitation.get("allowed_surfaces"))
        if (surface := _as_invitation_surface(value)) is not None
    }
    current = surfaces_for_role(role)
    return audience in issued and audience in current


def _as_invitation_surface(value: object) -> InvitationSurface | None:
    try:
        return InvitationSurface(str(value).strip().lower())
    except ValueError:
        return None


def _normalize_actor(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized:
        raise AuthContractError(
            "invitation_invalid",
            "The invitation is invalid or unavailable.",
            http_status=404,
        )
    return normalized


def _token_hash(value: str, *, field: str) -> str:
    normalized = _required(value, field=field)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _required(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise AuthContractError("invitation_invalid", f"{field} is required.", http_status=422)
    return normalized


def _row(value: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return {column: item for column, item in zip(columns, value, strict=False)}


def _json_payload(value: object) -> object:
    if is_dataclass(value):
        value = asdict(value)
    payload = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return payload
    return Jsonb(payload)


def _json_value(value: object, *, default: object) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _sequence(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parsed = _json_value(value, default=None)
        if isinstance(parsed, list):
            return tuple(parsed)
        return (value,)
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return ()


def _datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _uuid(value: str) -> object:
    try:
        from psycopg.types import TypeInfo  # noqa: F401
    except ModuleNotFoundError:
        return value
    return UUID(value)


def _rollback(connection: Connection) -> None:
    rollback = getattr(connection, "rollback", None)
    if callable(rollback):
        rollback()
