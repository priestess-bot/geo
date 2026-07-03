from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from geno_core.audit import build_audit_event
from geno_core.models import (
    RuntimeCustomerPortalToken,
    RuntimeCustomerPortalTokenActionInput,
    RuntimeCustomerPortalTokenInput,
    RuntimeHttpAccessLogInput,
    RuntimeProjectLaunchConfig,
    RuntimeProjectLaunchConfigInput,
)


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


def _uuid(value: str | None) -> object | None:
    if value is None:
        return None
    try:
        from psycopg.types import TypeInfo  # noqa: F401
    except ModuleNotFoundError:
        return value
    from uuid import UUID

    return UUID(value)


def _row_dict(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {column: value for column, value in zip(columns, row, strict=False)}


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, "::".join([kind, *(str(part) for part in parts)])))


class RuntimeProjectAccessRepositoryMixin:
    """Repository methods for customer portal access, launch config, and HTTP logs."""

    connection: Any

    def save_audit_events(self, events: object, *, cursor: Any | None = None) -> None: ...

    def save_project_launch_config(self, config: RuntimeProjectLaunchConfigInput) -> RuntimeProjectLaunchConfig:
        project_id = config.project_id.strip()
        customer_email = config.customer_email.strip().lower()
        primary_domain = config.primary_domain.strip().lower()
        config_version = config.config_version.strip() or "au_launch_config_v1"
        created_by = config.created_by.strip() or "runtime-console"
        updated_by = config.updated_by.strip() or created_by
        status = config.status.strip().lower() or "draft"
        if not project_id:
            raise ValueError("project_id is required")
        if not customer_email or "@" not in customer_email:
            raise ValueError("customer_email is required")
        if not primary_domain:
            raise ValueError("primary_domain is required")
        if status not in {"draft", "ready", "active", "paused"}:
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
            "locale": config.locale.strip() or "en-AU",
            "country_code": config.country_code.strip().upper() or "AU",
            "timezone": config.timezone.strip() or "Australia/Sydney",
            "collection_mode": config.collection_mode.strip().lower() or "fixture",
            "scoring_profile": config.scoring_profile.strip() or "au_visibility_v1",
        }
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (_uuid(project_id),))
            if not cursor.fetchone():
                raise ValueError("project not found")
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
        config_version: str = "au_launch_config_v1",
    ) -> RuntimeProjectLaunchConfig | None:
        project_id = project_id.strip()
        config_version = config_version.strip() or "au_launch_config_v1"
        if not project_id:
            raise ValueError("project_id is required")
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {", ".join(PROJECT_LAUNCH_CONFIG_COLUMNS)}
                FROM project_launch_configs
                WHERE project_id = %s AND config_version = %s
                LIMIT 1
                """,
                (_uuid(project_id), config_version),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return RuntimeProjectLaunchConfig(
            launch_config=_row_dict(row, PROJECT_LAUNCH_CONFIG_COLUMNS),
            audit_events=(),
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
        raw_token = f"geno-portal-{uuid4().hex}"
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
