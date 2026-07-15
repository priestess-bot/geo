from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from geo_core.audit import build_audit_event
from geo_core.models import (
    RuntimeConnectorSecret,
    RuntimeConnectorSecretInput,
    RuntimeCustomerPortalToken,
    RuntimeCustomerPortalTokenActionInput,
    RuntimeCustomerPortalTokenInput,
    RuntimeHttpAccessLogInput,
    RuntimeMembershipScope,
    RuntimeProjectLaunchConfig,
    RuntimeProjectLaunchConfigInput,
    RuntimeSession,
    RuntimeSessionInput,
    RuntimeSessionRevokeInput,
    RuntimeTenantMemberInput,
)
from geo_core.auth import (
    AuthInvitationPreflightResult,
    AuthInvitationRedeemResult,
    AuthSessionV2Repository,
    InvitationSurface,
    assert_auth_writes_enabled,
    build_session_scope_v2,
    reset_auth_connection_context,
)
from geo_core.auth_delivery import AuthDeliveryKeyring, auth_session_cookie_secure
from geo_core.rbac import normalize_role, permissions_for_roles
from geo_core.security.secrets import encrypt_connector_secret


CUSTOMER_PORTAL_TOKEN_COLUMNS = (
    "id",
    "project_id",
    "invitation_id",
    "member_user_id",
    "token_hash",
    "status",
    "issued_by",
    "issued_at",
    "last_used_at",
    "revoked_at",
    "revoked_by",
    "revoke_reason",
    "metadata",
    "created_at",
    "updated_at",
)
PROJECT_LAUNCH_CONFIG_COLUMNS = (
    "id",
    "project_id",
    "config_version",
    "customer_email",
    "primary_domain",
    "competitor_domains",
    "locale",
    "country_code",
    "timezone",
    "collection_mode",
    "schedule",
    "external_connectors",
    "scoring_profile",
    "status",
    "metadata",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
)


def runtime_launch_config_ready(*, collection_mode: str, external_connectors: object) -> bool:
    if collection_mode.strip().lower() == "manual":
        return True
    connectors = external_connectors
    if isinstance(connectors, str):
        try:
            connectors = json.loads(connectors)
        except json.JSONDecodeError:
            return False
    if not isinstance(connectors, dict):
        return False
    for value in connectors.values():
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or "").strip().lower()
        mode = str(value.get("mode") or "").strip().lower()
        if mode != "disabled" and status in {"active", "ready", "manual_ready"}:
            return True
    return False
RUNTIME_HTTP_ACCESS_LOG_COLUMNS = (
    "id",
    "request_id",
    "project_id",
    "actor_id",
    "method",
    "path",
    "route",
    "query_hash",
    "request_headers_hash",
    "request_body_hash",
    "request_body_size",
    "request_body_uri",
    "request_headers_uri",
    "response_headers_hash",
    "response_body_hash",
    "response_body_size",
    "response_body_uri",
    "response_headers_uri",
    "status_code",
    "duration_ms",
    "client_host_hash",
    "user_agent_hash",
    "error_type",
    "capture_status",
    "metadata",
    "created_at",
)
RUNTIME_SESSION_COLUMNS = (
    "id",
    "session_token_hash",
    "actor_id",
    "actor_type",
    "tenant_id",
    "project_ids",
    "roles",
    "permissions",
    "auth_method",
    "status",
    "issued_by",
    "issued_at",
    "expires_at",
    "last_used_at",
    "revoked_at",
    "revoked_by",
    "revoke_reason",
    "metadata",
    "created_at",
    "updated_at",
    "scope_version",
    "authz_policy_version",
    "tenant_roles",
    "project_scopes",
    "redemption_attempt_id",
)
TENANT_MEMBER_COLUMNS = (
    "id",
    "tenant_id",
    "user_id",
    "role",
    "status",
    "invited_by",
    "created_at",
    "updated_at",
)
CONNECTOR_SECRET_REF_COLUMNS = (
    "id",
    "project_id",
    "provider",
    "purpose",
    "secret_ref",
    "encrypted_secret",
    "encryption_version",
    "key_hint",
    "secret_hash",
    "masked_value",
    "status",
    "metadata",
    "created_by",
    "rotated_by",
    "deleted_by",
    "created_at",
    "rotated_at",
    "deleted_at",
    "updated_at",
)


def _json_compatible(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _json_payload(value: object) -> object:
    if is_dataclass(value):
        value = asdict(value)
    payload = _json_compatible(value)
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return payload
    return Jsonb(payload)


def _json_array(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _uuid(value: str | None) -> object | None:
    return value


def _row_dict(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {column: value for column, value in zip(columns, row, strict=False)}


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, "::".join([kind, *(str(part) for part in parts)])))


def _sha256_token_hash(raw_token: str, *, field_name: str) -> str:
    raw_token = raw_token.strip()
    if not raw_token:
        raise ValueError(f"{field_name} is required")
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _is_past_datetime(value: object) -> bool:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized <= datetime.now(UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        normalized = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return normalized <= datetime.now(UTC)
    return False


class RuntimeProjectAccessRepositoryMixin:
    """Repository methods for customer portal access, launch config, and HTTP logs."""

    connection: Any

    def save_audit_events(self, events: object, *, cursor: Any | None = None) -> None: ...

    def _public_connector_secret_ref(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in row.items()
            if key not in {"encrypted_secret", "secret_hash"}
        }

    def save_connector_secret(self, secret_input: RuntimeConnectorSecretInput) -> RuntimeConnectorSecret:
        project_id = secret_input.project_id.strip()
        provider = secret_input.provider.strip().lower()
        purpose = secret_input.purpose.strip().lower() or "api_key"
        updated_by = secret_input.updated_by.strip() or "runtime-console"
        metadata = _json_compatible(secret_input.metadata or {})
        if not project_id:
            raise ValueError("project_id is required")
        if not provider:
            raise ValueError("provider is required")
        if not updated_by:
            raise ValueError("updated_by is required")
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        encrypted = encrypt_connector_secret(
            project_id=project_id,
            provider=provider,
            purpose=purpose,
            raw_secret=secret_input.raw_secret,
        )
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                f"""
                SELECT {", ".join(CONNECTOR_SECRET_REF_COLUMNS)}
                FROM connector_secret_refs
                WHERE project_id = %s AND provider = %s AND purpose = %s AND status = 'active'
                LIMIT 1
                """,
                (_uuid(project_id), provider, purpose),
            )
            existing = _row_dict(cursor.fetchone(), CONNECTOR_SECRET_REF_COLUMNS)
            if existing:
                cursor.execute(
                    """
                    UPDATE connector_secret_refs
                    SET status = 'rotated',
                        rotated_by = %s,
                        rotated_at = now(),
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (updated_by, _uuid(str(existing["id"]))),
                )
            cursor.execute(
                """
                INSERT INTO connector_secret_refs (
                  project_id, provider, purpose, secret_ref, encrypted_secret,
                  encryption_version, key_hint, secret_hash, masked_value,
                  status, metadata, created_by, rotated_by, rotated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s, %s, CASE WHEN %s THEN now() ELSE NULL END)
                RETURNING id
                """,
                (
                    _uuid(project_id),
                    provider,
                    purpose,
                    encrypted.secret_ref,
                    encrypted.encrypted_secret,
                    encrypted.encryption_version,
                    encrypted.key_hint,
                    encrypted.secret_hash,
                    encrypted.masked_value,
                    _json_payload(metadata),
                    updated_by,
                    updated_by if existing else None,
                    bool(existing),
                ),
            )
            inserted = _row_dict(cursor.fetchone(), ("id",))
            cursor.execute(
                f"""
                SELECT {", ".join(CONNECTOR_SECRET_REF_COLUMNS)}
                FROM connector_secret_refs
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(str(inserted["id"])),),
            )
            after = _row_dict(cursor.fetchone(), CONNECTOR_SECRET_REF_COLUMNS)
            public_after = self._public_connector_secret_ref(after)
            public_before = self._public_connector_secret_ref(existing) if existing else None
            event_type = "connector.secret_rotated" if existing else "connector.secret_created"
            audit_event = build_audit_event(
                event_type=event_type,
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="connector_secret",
                target_id=str(after["id"]),
                before=public_before,
                after=public_after,
                input_refs={
                    "project_ids": [project_id],
                    "providers": [provider],
                    "purposes": [purpose],
                    "secret_refs": [str(after["secret_ref"])],
                },
                output_refs={"connector_secret_ref_ids": [str(after["id"])]},
                method_version="connector_secret_storage_v1",
                reason=secret_input.reason.strip() if secret_input.reason else event_type,
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeConnectorSecret(connector_secret=public_after, audit_events=(asdict(audit_event),))

    def list_connector_secrets(
        self,
        *,
        project_id: str,
        provider: str | None = None,
        include_inactive: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        project_id = project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        filters = ["project_id = %s"]
        params: list[object] = [_uuid(project_id)]
        if provider:
            filters.append("provider = %s")
            params.append(provider.strip().lower())
        if not include_inactive:
            filters.append("status = 'active'")
        where_clause = " AND ".join(filters)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(CONNECTOR_SECRET_REF_COLUMNS)}
                FROM connector_secret_refs
                WHERE {where_clause}
                ORDER BY updated_at DESC, created_at DESC, id DESC
                """,
                tuple(params),
            )
            rows = [_row_dict(row, CONNECTOR_SECRET_REF_COLUMNS) for row in (cursor.fetchall() or ())]
        return tuple(self._public_connector_secret_ref(row) for row in rows)

    def resolve_connector_secret(self, *, secret_ref: str) -> str:
        from geo_core.security.secrets import decrypt_connector_secret

        normalized_ref = secret_ref.strip()
        if not normalized_ref:
            raise ValueError("secret_ref is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT encrypted_secret, status
                FROM connector_secret_refs
                WHERE secret_ref = %s
                LIMIT 1
                """,
                (normalized_ref,),
            )
            row = _row_dict(cursor.fetchone(), ("encrypted_secret", "status"))
        if not row:
            raise ValueError("connector secret not found")
        if row.get("status") != "active":
            raise ValueError("connector secret is not active")
        return decrypt_connector_secret(encrypted_secret=str(row["encrypted_secret"]))

    def save_tenant_member(self, member: RuntimeTenantMemberInput) -> dict[str, Any]:
        assert_auth_writes_enabled()
        tenant_id = member.tenant_id.strip()
        user_id = member.user_id.strip().lower()
        role = normalize_role(member.role)
        status = member.status.strip().lower() or "active"
        updated_by = member.updated_by.strip() or "runtime-console"
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not user_id:
            raise ValueError("user_id is required")
        if status not in {"active", "disabled"}:
            raise ValueError("status must be active or disabled")
        member_id = _stable_id("tenant-member", tenant_id, user_id)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(TENANT_MEMBER_COLUMNS)}
                FROM tenant_members
                WHERE tenant_id = %s AND lower(user_id) = %s
                LIMIT 1
                """,
                (_uuid(tenant_id), user_id),
            )
            before = _row_dict(cursor.fetchone(), TENANT_MEMBER_COLUMNS)
            cursor.execute(
                """
                INSERT INTO tenant_members (id, tenant_id, user_id, role, status, invited_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                  role = EXCLUDED.role,
                  status = EXCLUDED.status,
                  invited_by = COALESCE(tenant_members.invited_by, EXCLUDED.invited_by),
                  updated_at = now()
                """,
                (_uuid(member_id), _uuid(tenant_id), user_id, role, status, updated_by),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(TENANT_MEMBER_COLUMNS)}
                FROM tenant_members
                WHERE tenant_id = %s AND lower(user_id) = %s
                LIMIT 1
                """,
                (_uuid(tenant_id), user_id),
            )
            after = _row_dict(cursor.fetchone(), TENANT_MEMBER_COLUMNS)
            audit_event = build_audit_event(
                event_type="membership.created" if not before else "membership.updated",
                project_id="",
                actor_type="user",
                actor_id=updated_by,
                target_type="tenant_member",
                target_id=str(after.get("id") or member_id),
                before=before or None,
                after=after,
                input_refs={"tenant_ids": [tenant_id], "user_ids": [user_id], "roles": [role]},
                output_refs={"tenant_member_ids": [str(after.get("id") or member_id)], "status": [status]},
                method_version="tenant_membership_scope_v1",
                reason=member.reason.strip() if member.reason else "tenant_membership_save",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return {**after, "audit_events": [asdict(audit_event)]}

    def get_runtime_membership_scope(
        self,
        *,
        actor_id: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> RuntimeMembershipScope:
        actor_id = actor_id.strip().lower()
        tenant_id = tenant_id.strip() if tenant_id else None
        project_id = project_id.strip() if project_id else None
        if not actor_id:
            raise ValueError("actor_id is required")
        filters = ["lower(tm.user_id) = %s", "tm.status = 'active'"]
        params: list[object] = [actor_id]
        if tenant_id:
            filters.append("tm.tenant_id = %s")
            params.append(_uuid(tenant_id))
        tenant_where = " AND ".join(filters)
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT tm.tenant_id, tm.role
                FROM tenant_members tm
                WHERE {tenant_where}
                ORDER BY tm.created_at ASC, tm.id ASC
                """,
                tuple(params),
            )
            tenant_rows = [_row_dict(row, ("tenant_id", "role")) for row in (cursor.fetchall() or ())]
            cursor.execute(
                """
                WITH requested(actor_id, tenant_id, project_id) AS (
                  VALUES (%s::text, %s::uuid, %s::uuid)
                )
                SELECT
                  pm.project_id,
                  pm.role,
                  pm.tenant_id,
                  ARRAY[]::text[] AS permissions,
                  'direct_member'::text AS scope_source
                FROM requested requested_scope
                JOIN project_members pm
                  ON lower(btrim(pm.user_id)) = requested_scope.actor_id
                 AND pm.status = 'active'
                 AND (requested_scope.tenant_id IS NULL OR pm.tenant_id = requested_scope.tenant_id)
                 AND (requested_scope.project_id IS NULL OR pm.project_id = requested_scope.project_id)
                -- Legacy query removed its JOIN projects p ON p.id = pm.project_id.
                UNION ALL
                SELECT
                  grant_row.project_id,
                  grant_row.canonical_role AS role,
                  grant_row.tenant_id,
                  grant_row.permissions,
                  'tenant_role'::text AS scope_source
                FROM requested requested_scope
                JOIN runtime_project_access_grants grant_row
                  ON lower(btrim(grant_row.actor_id)) = requested_scope.actor_id
                 AND grant_row.status = 'active'
                 AND (requested_scope.tenant_id IS NULL OR grant_row.tenant_id = requested_scope.tenant_id)
                 AND (requested_scope.project_id IS NULL OR grant_row.project_id = requested_scope.project_id)
                ORDER BY project_id, scope_source
                """,
                (
                    actor_id,
                    _uuid(tenant_id) if tenant_id else None,
                    _uuid(project_id) if project_id else None,
                ),
            )
            project_rows = [
                _row_dict(row, ("project_id", "role", "tenant_id", "permissions", "scope_source"))
                for row in (cursor.fetchall() or ())
            ]
        visible_tenant_ids = {
            str(row["tenant_id"])
            for row in (*tenant_rows, *project_rows)
            if row.get("tenant_id")
        }
        if tenant_id is None and len(visible_tenant_ids) > 1:
            raise PermissionError("actor has access to multiple tenants; tenant_id is required")
        if project_id and not any(str(row.get("project_id")) == project_id for row in project_rows):
            raise PermissionError("actor does not have access to project")
        if tenant_id and not tenant_rows and not project_rows:
            raise PermissionError("actor does not have access to tenant")
        effective_tenant_id = tenant_id
        if effective_tenant_id is None:
            for row in (*tenant_rows, *project_rows):
                value = row.get("tenant_id")
                if value:
                    effective_tenant_id = str(value)
                    break
        tenant_roles = tuple(dict.fromkeys(normalize_role(str(row["role"])) for row in tenant_rows if row.get("role")))
        direct_rows = [row for row in project_rows if row.get("scope_source") in {None, "direct_member"}]
        grant_rows = [
            {
                "project_id": row.get("project_id"),
                "canonical_role": row.get("role"),
                "permissions": row.get("permissions") or (),
            }
            for row in project_rows
            if row.get("scope_source") == "tenant_role"
        ]
        project_roles: dict[str, str] = {}
        for row in project_rows:
            if row.get("project_id") and row.get("role"):
                project_roles.setdefault(str(row["project_id"]), normalize_role(str(row["role"])))
        roles = tuple(dict.fromkeys((*tenant_roles, *project_roles.values())))
        permissions = tuple(sorted(permissions_for_roles(roles))) if roles else ()
        scope_v2 = build_session_scope_v2(
            actor_id=actor_id,
            tenant_id=effective_tenant_id or "",
            tenant_roles=tenant_roles,
            direct_memberships=direct_rows,
            grants=grant_rows,
        )
        return RuntimeMembershipScope(
            actor_id=actor_id,
            tenant_id=effective_tenant_id,
            tenant_roles=tenant_roles,
            project_ids=scope_v2.project_ids,
            project_roles=project_roles,
            permissions=permissions,
            project_scopes=scope_v2.project_scopes,
        )

    def save_project_launch_config(self, config: RuntimeProjectLaunchConfigInput) -> RuntimeProjectLaunchConfig:
        project_id = config.project_id.strip()
        customer_email = config.customer_email.strip().lower()
        primary_domain = config.primary_domain.strip().lower()
        config_version = config.config_version.strip() or "project_launch_config_v1"
        created_by = config.created_by.strip() or "runtime-console"
        updated_by = config.updated_by.strip() or created_by
        requested_status = config.status.strip().lower() or "draft"
        if not project_id:
            raise ValueError("project_id is required")
        if not customer_email or "@" not in customer_email:
            raise ValueError("customer_email is required")
        if not primary_domain:
            raise ValueError("primary_domain is required")
        if requested_status not in {"draft", "ready", "active", "paused"}:
            raise ValueError("status must be draft, ready, active, or paused")
        competitor_domains = tuple(
            dict.fromkeys(domain.strip().lower() for domain in config.competitor_domains if domain.strip())
        )
        launch_config_id = _stable_id("project-launch-config", project_id, config_version)
        metadata = _json_compatible(config.metadata or {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        schedule = _json_compatible(config.schedule or {})
        if not isinstance(schedule, dict):
            raise ValueError("schedule must be an object")
        external_connectors = _json_compatible(config.external_connectors or {})
        if not isinstance(external_connectors, dict):
            raise ValueError("external_connectors must be an object")
        after_candidate = {
            "locale": config.locale.strip() or "en",
            "country_code": config.country_code.strip().upper() or "GLOBAL",
            "timezone": config.timezone.strip() or "UTC",
            "collection_mode": config.collection_mode.strip().lower() or "api",
            "scoring_profile": config.scoring_profile.strip() or "visibility_v1.0",
        }
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id, status FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            project_row = cursor.fetchone()
            if not project_row:
                raise ValueError("project not found")
            project_status_value = (
                project_row.get("status")
                if isinstance(project_row, dict)
                else project_row[1]
                if len(project_row) > 1
                else "paused"
            )
            project_status = str(project_status_value or "paused").strip().lower()
            config_ready = runtime_launch_config_ready(
                collection_mode=after_candidate["collection_mode"],
                external_connectors=external_connectors,
            )
            if project_status == "archived":
                status = "paused"
            elif project_status == "active" and config_ready:
                status = "active"
            else:
                status = "ready" if config_ready else "draft"
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_LAUNCH_CONFIG_COLUMNS)}
                FROM project_launch_configs
                WHERE project_id = %s AND config_version = %s
                LIMIT 1
                """,
                (_uuid(project_id), config_version),
            )
            existing = cursor.fetchone()
            before = _row_dict(existing, PROJECT_LAUNCH_CONFIG_COLUMNS) if existing else None
            cursor.execute(
                """
                INSERT INTO project_launch_configs (
                  id, project_id, config_version, customer_email, primary_domain,
                  competitor_domains, locale, country_code, timezone, collection_mode,
                  schedule, external_connectors, scoring_profile, status, metadata,
                  created_by, updated_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, config_version) DO UPDATE SET
                  customer_email = EXCLUDED.customer_email,
                  primary_domain = EXCLUDED.primary_domain,
                  competitor_domains = EXCLUDED.competitor_domains,
                  locale = EXCLUDED.locale,
                  country_code = EXCLUDED.country_code,
                  timezone = EXCLUDED.timezone,
                  collection_mode = EXCLUDED.collection_mode,
                  schedule = EXCLUDED.schedule,
                  external_connectors = EXCLUDED.external_connectors,
                  scoring_profile = EXCLUDED.scoring_profile,
                  status = EXCLUDED.status,
                  metadata = EXCLUDED.metadata,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = now()
                """,
                (
                    _uuid(launch_config_id),
                    _uuid(project_id),
                    config_version,
                    customer_email,
                    primary_domain,
                    _json_payload(list(competitor_domains)),
                    after_candidate["locale"],
                    after_candidate["country_code"],
                    after_candidate["timezone"],
                    after_candidate["collection_mode"],
                    _json_payload(schedule),
                    _json_payload(external_connectors),
                    after_candidate["scoring_profile"],
                    status,
                    _json_payload(metadata),
                    created_by,
                    updated_by,
                ),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_LAUNCH_CONFIG_COLUMNS)}
                FROM project_launch_configs
                WHERE project_id = %s AND config_version = %s
                LIMIT 1
                """,
                (_uuid(project_id), config_version),
            )
            after = _row_dict(cursor.fetchone(), PROJECT_LAUNCH_CONFIG_COLUMNS)
            audit_event = build_audit_event(
                event_type="project_launch_config_saved",
                project_id=project_id,
                actor_type="user",
                actor_id=updated_by,
                target_type="project_launch_config",
                target_id=launch_config_id,
                before=before,
                after=after,
                input_refs={
                    "project_ids": [project_id],
                    "customer_emails": [customer_email],
                    "primary_domains": [primary_domain],
                    "competitor_domains": list(competitor_domains),
                },
                output_refs={"project_launch_config_ids": [launch_config_id]},
                method_version="project_launch_config_v1",
                reason=config.reason.strip() if config.reason else "runtime_project_launch_config_save",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        return RuntimeProjectLaunchConfig(launch_config=after, audit_events=(asdict(audit_event),))

    def get_project_launch_config(
        self,
        *,
        project_id: str,
        config_version: str | None = None,
    ) -> RuntimeProjectLaunchConfig | None:
        project_id = project_id.strip()
        config_version = config_version.strip() if config_version else None
        if not project_id:
            raise ValueError("project_id is required")
        with self.connection.cursor() as cursor:
            if config_version:
                cursor.execute(
                    f"""
                    SELECT {", ".join(PROJECT_LAUNCH_CONFIG_COLUMNS)}
                    FROM project_launch_configs
                    WHERE project_id = %s AND config_version = %s
                    LIMIT 1
                    """,
                    (_uuid(project_id), config_version),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT {", ".join(PROJECT_LAUNCH_CONFIG_COLUMNS)}
                    FROM project_launch_configs
                    WHERE project_id = %s
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT 1
                    """,
                    (_uuid(project_id),),
                )
            row = cursor.fetchone()
        if not row:
            return None
        return RuntimeProjectLaunchConfig(
            launch_config=_row_dict(row, PROJECT_LAUNCH_CONFIG_COLUMNS),
            audit_events=(),
        )

    def create_runtime_session(self, session_input: RuntimeSessionInput) -> RuntimeSession:
        assert_auth_writes_enabled()
        actor_id = session_input.actor_id.strip()
        actor_type = session_input.actor_type.strip().lower() or "user"
        issued_by = session_input.issued_by.strip() or "runtime-auth"
        ttl_seconds = max(60, min(int(session_input.ttl_seconds), 60 * 60 * 24 * 30))
        if not actor_id:
            raise ValueError("actor_id is required")
        if actor_type not in {"user", "system", "service"}:
            raise ValueError("actor_type must be user, system, or service")
        project_ids = tuple(dict.fromkeys(item.strip() for item in session_input.project_ids if item.strip()))
        roles = tuple(dict.fromkeys(item.strip() for item in session_input.roles if item.strip()))
        permissions = tuple(dict.fromkeys(item.strip() for item in session_input.permissions if item.strip()))
        tenant_roles = tuple(dict.fromkeys(item.strip() for item in session_input.tenant_roles if item.strip()))
        project_scopes = tuple(session_input.project_scopes)
        scope_version = session_input.scope_version.strip() or "runtime_session_scope_v1"
        authz_policy_version = session_input.authz_policy_version.strip() if session_input.authz_policy_version else None
        if scope_version != "runtime_session_scope_v2":
            raise ValueError("active runtime_session_scope_v1 creation is disabled")
        if not session_input.tenant_id or authz_policy_version != "auth_surface_policy_v1":
            raise ValueError("scope-v2 session requires tenant_id and current authz_policy_version")
        project_ids = tuple(scope.project_id for scope in project_scopes)
        metadata = _json_compatible(session_input.metadata or {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        raw_session_token = f"geo-session-{uuid4().hex}"
        session_token_hash = _sha256_token_hash(raw_session_token, field_name="session_token")
        session_id = str(uuid4())
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO runtime_sessions (
                  id, session_token_hash, actor_id, actor_type, tenant_id,
                  project_ids, roles, permissions, tenant_roles, project_scopes,
                  scope_version, authz_policy_version, redemption_attempt_id,
                  auth_method, status, issued_by, expires_at, metadata
                )
                VALUES (
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s, %s,
                  'session', 'active', %s, now() + (%s * interval '1 second'), %s
                )
                """,
                (
                    _uuid(session_id),
                    session_token_hash,
                    actor_id,
                    actor_type,
                    _uuid(session_input.tenant_id) if session_input.tenant_id else None,
                    _json_payload(list(project_ids)),
                    _json_payload(list(roles)),
                    _json_payload(list(permissions)),
                    _json_payload(list(tenant_roles)),
                    _json_payload([asdict(scope) for scope in project_scopes]),
                    scope_version,
                    authz_policy_version,
                    _uuid(session_input.redemption_attempt_id) if session_input.redemption_attempt_id else None,
                    issued_by,
                    ttl_seconds,
                    _json_payload(metadata),
                ),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_SESSION_COLUMNS)}
                FROM runtime_sessions
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(session_id),),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_SESSION_COLUMNS)
            audit_event = build_audit_event(
                event_type="runtime_session_created",
                project_id=project_ids[0] if project_ids else "",
                actor_type=actor_type,
                actor_id=actor_id,
                target_type="runtime_session",
                target_id=session_id,
                before=None,
                after={**after, "session_token_hash": session_token_hash},
                input_refs={
                    "actor_ids": [actor_id],
                    "tenant_ids": [session_input.tenant_id] if session_input.tenant_id else [],
                    "project_ids": list(project_ids),
                },
                output_refs={"runtime_session_ids": [session_id], "session_token_hashes": [session_token_hash]},
                method_version="runtime_session_v2" if scope_version == "runtime_session_scope_v2" else "runtime_session_v1",
                reason=session_input.reason.strip() if session_input.reason else "runtime_session_create",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        public_after = {key: value for key, value in after.items() if key != "session_token_hash"}
        return RuntimeSession(
            session=public_after,
            audit_events=(asdict(audit_event),),
            raw_session_token=raw_session_token,
        )

    def validate_runtime_session(self, raw_session_token: str) -> RuntimeSession:
        session_token_hash = _sha256_token_hash(raw_session_token, field_name="session_token")
        reset_auth_connection_context(self.connection)
        try:
            with self.connection.cursor() as cursor:
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
                      set_config('geo.runtime_invitation_token_hash', '', true),
                      set_config('geo.runtime_idempotency_key_hash', '', true),
                      set_config('geo.runtime_requested_surface', '', true),
                      set_config('geo.runtime_portal_token_hash', '', true),
                      set_config('geo.runtime_session_token_hash', %s, true)
                    """,
                    (session_token_hash,),
                )
                cursor.execute(
                    f"""
                    SELECT {", ".join(RUNTIME_SESSION_COLUMNS)}
                    FROM runtime_sessions
                    WHERE session_token_hash = %s AND status = 'active'
                    LIMIT 1
                    """,
                    (session_token_hash,),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError("runtime session not found")
                session = _row_dict(row, RUNTIME_SESSION_COLUMNS)
                if (
                    session.get("scope_version") != "runtime_session_scope_v2"
                    or session.get("authz_policy_version") != "auth_surface_policy_v1"
                    or not session.get("tenant_id")
                ):
                    raise ValueError("runtime session scope-v2 authentication is required")
                if _is_past_datetime(session.get("expires_at")):
                    cursor.execute(
                        """
                        UPDATE runtime_sessions
                        SET status = 'expired',
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (_uuid(str(session["id"])),),
                    )
                    self.connection.commit()
                    raise ValueError("runtime session expired")
                cursor.execute(
                    """
                    UPDATE runtime_sessions
                    SET last_used_at = now(),
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (_uuid(str(session["id"])),),
                )
            self.connection.commit()
            public_session = {key: value for key, value in session.items() if key != "session_token_hash"}
            return RuntimeSession(session=public_session, audit_events=(), raw_session_token=None)
        except Exception:
            self.connection.rollback()
            raise

    def revoke_runtime_session(self, revoke_input: RuntimeSessionRevokeInput) -> RuntimeSession:
        session_id = revoke_input.session_id.strip()
        revoked_by = revoke_input.revoked_by.strip() or "runtime-auth"
        if not session_id:
            raise ValueError("session_id is required")
        reset_auth_connection_context(self.connection)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  set_config('app.rls_enabled', '1', true),
                  set_config('app.actor_id', %s, true),
                  set_config('geo.runtime_project_access_control', '1', true),
                  set_config('geo.runtime_actor_id', %s, true),
                  set_config('geo.runtime_session_token_hash', '', true)
                """,
                (revoked_by, revoked_by),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_SESSION_COLUMNS)}
                FROM runtime_sessions
                WHERE id = %s
                FOR UPDATE
                """,
                (_uuid(session_id),),
            )
            existing = cursor.fetchone()
            if not existing:
                raise ValueError("runtime session not found")
            before = _row_dict(existing, RUNTIME_SESSION_COLUMNS)
            tenant_id = str(before.get("tenant_id") or "").strip()
            project_ids = tuple(
                str(value).strip()
                for value in _json_array(before.get("project_ids"))
                if str(value).strip()
            )
            cursor.execute(
                """
                SELECT
                  set_config('app.tenant_id', %s, true),
                  set_config('app.project_ids', %s, true),
                  set_config('geo.runtime_tenant_id', %s, true)
                """,
                (tenant_id, ",".join(project_ids), tenant_id),
            )
            cursor.execute(
                """
                UPDATE runtime_sessions
                SET status = 'revoked',
                    revoked_at = now(),
                    revoked_by = %s,
                    revoke_reason = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    revoked_by,
                    revoke_input.reason.strip() if revoke_input.reason else None,
                    _uuid(session_id),
                ),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(RUNTIME_SESSION_COLUMNS)}
                FROM runtime_sessions
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(session_id),),
            )
            after = _row_dict(cursor.fetchone(), RUNTIME_SESSION_COLUMNS)
            audit_event = build_audit_event(
                event_type="runtime_session_revoked",
                project_id=project_ids[0] if project_ids else "",
                actor_type="user",
                actor_id=revoked_by,
                target_type="runtime_session",
                target_id=session_id,
                before=before,
                after=after,
                input_refs={"runtime_session_ids": [session_id]},
                output_refs={"runtime_session_ids": [session_id], "status": ["revoked"]},
                method_version="runtime_session_v1",
                reason=revoke_input.reason.strip() if revoke_input.reason else "runtime_session_revoke",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        public_after = {key: value for key, value in after.items() if key != "session_token_hash"}
        return RuntimeSession(session=public_after, audit_events=(asdict(audit_event),), raw_session_token=None)

    def _auth_session_v2_repository(self, *, require_delivery_key: bool = True) -> AuthSessionV2Repository:
        return AuthSessionV2Repository(
            self.connection,
            keyring=AuthDeliveryKeyring.from_env() if require_delivery_key else None,
            cookie_secure=auth_session_cookie_secure(),
            session_ttl_seconds=int(os.getenv("GEO_RUNTIME_SESSION_TTL_SECONDS", "604800")),
        )

    def preflight_auth_invitation(
        self,
        *,
        invitation_id: str,
        invite_token: str,
        requested_surface: InvitationSurface,
    ) -> AuthInvitationPreflightResult:
        return self._auth_session_v2_repository(require_delivery_key=False).preflight(
            invitation_id=invitation_id,
            invite_token=invite_token,
            requested_surface=requested_surface,
        )

    def consume_auth_preflight_rate_limit(
        self,
        *,
        bucket_key: str,
        limit: int,
        window_seconds: int,
    ) -> int:
        normalized_key = bucket_key.strip()
        if len(normalized_key) != 64:
            raise ValueError("preflight rate-limit bucket_key must be a SHA-256 digest")
        limit = int(limit)
        if limit < 1 or limit > 5000:
            raise ValueError("preflight rate-limit limit must be between 1 and 5000")
        window_seconds = max(1, min(int(window_seconds), 3600))
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO auth_preflight_rate_limits(
                      bucket_key, window_started_at, request_count, expires_at, updated_at
                    )
                    VALUES (%s, now(), 1, now() + (%s * interval '1 second'), now())
                    ON CONFLICT (bucket_key) DO UPDATE SET
                      window_started_at = CASE
                        WHEN auth_preflight_rate_limits.expires_at <= now() THEN now()
                        ELSE auth_preflight_rate_limits.window_started_at
                      END,
                      request_count = CASE
                        WHEN auth_preflight_rate_limits.expires_at <= now() THEN 1
                        ELSE auth_preflight_rate_limits.request_count + 1
                      END,
                      expires_at = CASE
                        WHEN auth_preflight_rate_limits.expires_at <= now()
                          THEN now() + (%s * interval '1 second')
                        ELSE auth_preflight_rate_limits.expires_at
                      END,
                      updated_at = now()
                    RETURNING request_count
                    """,
                    (normalized_key, window_seconds, window_seconds),
                )
                row = cursor.fetchone()
                count = int(row.get("request_count") if isinstance(row, dict) else row[0])
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return count

    def redeem_auth_invitation_v2(
        self,
        *,
        invitation_id: str,
        invite_token: str,
        requested_surface: InvitationSurface,
        idempotency_key: str,
    ) -> AuthInvitationRedeemResult:
        return self._auth_session_v2_repository().redeem(
            invitation_id=invitation_id,
            invite_token=invite_token,
            requested_surface=requested_surface,
            idempotency_key=idempotency_key,
        )

    def confirm_auth_invitation_delivery(self, *, session_id: str, actor_id: str, tenant_id: str) -> bool:
        return self._auth_session_v2_repository(require_delivery_key=False).confirm_delivery(
            session_id=session_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
        )

    def create_customer_portal_token(
        self,
        token_input: RuntimeCustomerPortalTokenInput,
    ) -> RuntimeCustomerPortalToken:
        project_id = token_input.project_id.strip()
        member_user_id = token_input.member_user_id.strip().lower()
        invitation_id = token_input.invitation_id.strip() if token_input.invitation_id else None
        issued_by = token_input.issued_by.strip() or "runtime-console"
        if not project_id:
            raise ValueError("project_id is required")
        if not member_user_id:
            raise ValueError("member_user_id is required")
        metadata = _json_compatible(token_input.metadata or {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        raw_token = f"geo-portal-{uuid4().hex}"
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token_id = str(uuid4())
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
            cursor.execute(
                """
                SELECT id
                FROM project_members
                WHERE project_id = %s AND lower(user_id) = %s
                LIMIT 1
                """,
                (_uuid(project_id), member_user_id),
            )
            if not cursor.fetchone():
                raise ValueError("project member not found")
            cursor.execute(
                """
                INSERT INTO customer_portal_tokens (
                  id, project_id, invitation_id, member_user_id, token_hash,
                  status, issued_by, metadata
                )
                VALUES (%s, %s, %s, %s, %s, 'active', %s, %s)
                """,
                (
                    _uuid(token_id),
                    _uuid(project_id),
                    _uuid(invitation_id) if invitation_id else None,
                    member_user_id,
                    token_hash,
                    issued_by,
                    _json_payload(metadata),
                ),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(CUSTOMER_PORTAL_TOKEN_COLUMNS)}
                FROM customer_portal_tokens
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(token_id),),
            )
            after = _row_dict(cursor.fetchone(), CUSTOMER_PORTAL_TOKEN_COLUMNS)
            audit_event = build_audit_event(
                event_type="customer_portal_token_created",
                project_id=project_id,
                actor_type="user",
                actor_id=issued_by,
                target_type="customer_portal_token",
                target_id=token_id,
                before=None,
                after={**after, "token_hash": token_hash},
                input_refs={
                    "project_ids": [project_id],
                    "member_user_ids": [member_user_id],
                    "project_member_invitation_ids": [invitation_id] if invitation_id else [],
                },
                output_refs={"customer_portal_token_ids": [token_id], "token_hashes": [token_hash]},
                method_version="customer_portal_token_v1",
                reason=token_input.reason.strip() if token_input.reason else "customer_portal_token_create",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        public_after = {key: value for key, value in after.items() if key != "token_hash"}
        return RuntimeCustomerPortalToken(
            portal_token=public_after,
            audit_events=(asdict(audit_event),),
            raw_token=raw_token,
        )

    def list_customer_portal_tokens(
        self,
        *,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        project_id = project_id.strip()
        if not project_id:
            raise ValueError("project_id is required")
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM customer_portal_tokens
                WHERE project_id = %s
                """,
                (_uuid(project_id),),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(CUSTOMER_PORTAL_TOKEN_COLUMNS)}
                FROM customer_portal_tokens
                WHERE project_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (_uuid(project_id), limit, offset),
            )
            records = []
            for row in cursor.fetchall():
                token = _row_dict(row, CUSTOMER_PORTAL_TOKEN_COLUMNS)
                records.append({key: value for key, value in token.items() if key != "token_hash"})
        return {
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "records": tuple(records),
        }

    def validate_customer_portal_token(self, raw_token: str) -> RuntimeCustomerPortalToken:
        raw_token = raw_token.strip()
        if not raw_token:
            raise ValueError("portal_token is required")
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(CUSTOMER_PORTAL_TOKEN_COLUMNS)}
                FROM customer_portal_tokens
                WHERE token_hash = %s AND status = 'active'
                LIMIT 1
                """,
                (token_hash,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("customer portal token not found")
            token = _row_dict(row, CUSTOMER_PORTAL_TOKEN_COLUMNS)
            cursor.execute(
                """
                UPDATE customer_portal_tokens
                SET last_used_at = now(),
                    updated_at = now()
                WHERE id = %s
                """,
                (_uuid(str(token["id"])),),
            )
        self.connection.commit()
        public_token = {key: value for key, value in token.items() if key != "token_hash"}
        return RuntimeCustomerPortalToken(portal_token=public_token, audit_events=(), raw_token=None)

    def revoke_customer_portal_token(
        self,
        action_input: RuntimeCustomerPortalTokenActionInput,
    ) -> RuntimeCustomerPortalToken:
        token_id = action_input.token_id.strip()
        project_id = action_input.project_id.strip()
        revoked_by = action_input.revoked_by.strip() or "runtime-console"
        if not token_id:
            raise ValueError("token_id is required")
        if not project_id:
            raise ValueError("project_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(CUSTOMER_PORTAL_TOKEN_COLUMNS)}
                FROM customer_portal_tokens
                WHERE id = %s AND project_id = %s
                FOR UPDATE
                """,
                (_uuid(token_id), _uuid(project_id)),
            )
            existing = cursor.fetchone()
            if not existing:
                raise ValueError("customer portal token not found")
            before = _row_dict(existing, CUSTOMER_PORTAL_TOKEN_COLUMNS)
            cursor.execute(
                """
                UPDATE customer_portal_tokens
                SET status = 'revoked',
                    revoked_at = now(),
                    revoked_by = %s,
                    revoke_reason = %s,
                    updated_at = now()
                WHERE id = %s AND project_id = %s
                """,
                (
                    revoked_by,
                    action_input.reason.strip() if action_input.reason else None,
                    _uuid(token_id),
                    _uuid(project_id),
                ),
            )
            cursor.execute(
                f"""
                SELECT {", ".join(CUSTOMER_PORTAL_TOKEN_COLUMNS)}
                FROM customer_portal_tokens
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(token_id),),
            )
            after = _row_dict(cursor.fetchone(), CUSTOMER_PORTAL_TOKEN_COLUMNS)
            audit_event = build_audit_event(
                event_type="customer_portal_token_revoked",
                project_id=project_id,
                actor_type="user",
                actor_id=revoked_by,
                target_type="customer_portal_token",
                target_id=token_id,
                before=before,
                after=after,
                input_refs={"project_ids": [project_id], "customer_portal_token_ids": [token_id]},
                output_refs={"customer_portal_token_ids": [token_id], "status": ["revoked"]},
                method_version="customer_portal_token_v1",
                reason=action_input.reason.strip() if action_input.reason else "customer_portal_token_revoke",
            )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()
        public_after = {key: value for key, value in after.items() if key != "token_hash"}
        return RuntimeCustomerPortalToken(portal_token=public_after, audit_events=(asdict(audit_event),), raw_token=None)

    def save_runtime_http_access_log(self, log_input: RuntimeHttpAccessLogInput) -> dict[str, Any]:
        request_id = log_input.request_id.strip()
        method = log_input.method.strip().upper()
        path = log_input.path.strip() or "/"
        route = log_input.route.strip() or "__unmatched__"
        if not request_id:
            raise ValueError("request_id is required")
        if not method:
            raise ValueError("method is required")
        log_id = str(uuid4())
        metadata = _json_compatible(log_input.metadata or {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        project_id = None
        if log_input.project_id:
            try:
                project_id = _uuid(log_input.project_id)
            except ValueError:
                project_id = None
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO runtime_http_access_logs (
                  id, request_id, project_id, actor_id, method, path, route,
                  query_hash, request_headers_hash, request_body_hash, request_body_size,
                  request_body_uri, request_headers_uri, response_headers_hash, response_body_hash,
                  response_body_size, response_body_uri, response_headers_uri, status_code,
                  duration_ms, client_host_hash, user_agent_hash, error_type, capture_status, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {", ".join(RUNTIME_HTTP_ACCESS_LOG_COLUMNS)}
                """,
                (
                    _uuid(log_id),
                    request_id,
                    project_id,
                    log_input.actor_id.strip() if log_input.actor_id else None,
                    method,
                    path,
                    route,
                    log_input.query_hash,
                    log_input.request_headers_hash,
                    log_input.request_body_hash,
                    max(0, int(log_input.request_body_size)),
                    log_input.request_body_uri,
                    log_input.request_headers_uri,
                    log_input.response_headers_hash,
                    log_input.response_body_hash,
                    max(0, int(log_input.response_body_size)),
                    log_input.response_body_uri,
                    log_input.response_headers_uri,
                    int(log_input.status_code),
                    float(log_input.duration_ms),
                    log_input.client_host_hash,
                    log_input.user_agent_hash,
                    log_input.error_type,
                    log_input.capture_status.strip() or "metadata_only",
                    _json_payload(metadata),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return _row_dict(row, RUNTIME_HTTP_ACCESS_LOG_COLUMNS)
