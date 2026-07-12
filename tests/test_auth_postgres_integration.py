from __future__ import annotations

import base64
import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geno_core.auth import (
    AuthContractError,
    AuthSessionV2Repository,
    InvitationRedeemRecoveryStatus,
    InvitationSurface,
    InvitationSurfaceCompatibility,
)
from geno_core.auth_delivery import AuthDeliveryKeyring
from geno_core.models import RuntimeProjectMemberInvitationEmailInput
from geno_core.repository import PostgresEvidenceRepository


OWNER_URL = os.getenv("AUTH_TEST_DATABASE_URL", "postgresql://geno:geno@localhost:55433/geno")
APP_URL = os.getenv(
    "AUTH_TEST_APP_DATABASE_URL",
    "postgresql://geno_runtime_app:geno_runtime_app@localhost:55433/geno",
)
TEST_KEY = b"auth-core-postgres-test-key-0001"


def _connect(url: str) -> psycopg.Connection[dict[str, object]]:
    return psycopg.connect(url, row_factory=dict_row)


def _database_is_ready() -> bool:
    try:
        with _connect(OWNER_URL) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.auth_invitation_redemption_attempts') AS relation")
            row = cursor.fetchone()
            return bool(row and row["relation"])
    except psycopg.Error:
        return False


pytestmark = pytest.mark.skipif(not _database_is_ready(), reason="Auth Session v2 PostgreSQL is unavailable")


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "GENO_AUTH_DELIVERY_MASTER_KEY",
        base64.urlsafe_b64encode(TEST_KEY).decode("ascii"),
    )
    monkeypatch.setenv("GENO_AUTH_DELIVERY_KEY_ID", "postgres-test-key")
    monkeypatch.setenv("GENO_RUNTIME_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("AUTH_WRITES_ENABLED", "1")
    with _connect(OWNER_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE auth_runtime_write_controls
            SET writes_enabled = true, reason = 'auth_postgres_test', updated_at = now()
            WHERE singleton
            """
        )


def _seed_project(owner: psycopg.Connection[dict[str, object]], *, suffix: str) -> dict[str, str]:
    tenant_id = str(uuid4())
    project_id = str(uuid4())
    with owner.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants(id, name, slug) VALUES (%s, %s, %s)",
            (tenant_id, f"Auth {suffix}", f"auth-{suffix}-{tenant_id[:8]}"),
        )
        cursor.execute(
            """
            INSERT INTO projects(
              id, tenant_id, name, market_code, industry_code,
              target_brand, category, prompt_version, status
            )
            VALUES (%s, %s, %s, 'AU', 'auth_test', 'Auth Brand', 'Auth', 'auth-test-v1', 'active')
            """,
            (project_id, tenant_id, f"Project {suffix}"),
        )
    owner.commit()
    return {"tenant_id": tenant_id, "project_id": project_id}


def _seed_invitation(
    owner: psycopg.Connection[dict[str, object]],
    *,
    project: dict[str, str],
    actor_id: str,
    role: str = "viewer",
    policy_version: str = "auth_surface_policy_v1",
    audience: str = "customer",
    allowed_surfaces: list[str] | None = None,
) -> dict[str, str]:
    invitation_id = str(uuid4())
    token = f"invite-{uuid4()}"
    with owner.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO project_member_invitations(
              id, project_id, tenant_id, email, role, status, invite_token_hash,
              invited_by, expires_at, audience, allowed_surfaces, policy_version
            )
            VALUES (%s, %s, %s, %s, %s, 'pending', %s, 'auth-test', %s, %s, %s, %s)
            """,
            (
                invitation_id,
                project["project_id"],
                project["tenant_id"],
                actor_id,
                role,
                hashlib.sha256(token.encode("utf-8")).hexdigest(),
                datetime.now(UTC) + timedelta(hours=1),
                audience,
                allowed_surfaces or [audience],
                policy_version,
            ),
        )
    owner.commit()
    return {"invitation_id": invitation_id, "token": token, "actor_id": actor_id, **project}


def _repository(connection: psycopg.Connection[dict[str, object]]) -> AuthSessionV2Repository:
    return AuthSessionV2Repository(
        connection,
        keyring=AuthDeliveryKeyring.from_env(),
        cookie_secure=False,
        recovery_ttl_seconds=600,
        max_replay=5,
    )


def _idempotency_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _invitation_token_hash(invitation: dict[str, str]) -> str:
    return hashlib.sha256(invitation["token"].encode("utf-8")).hexdigest()


def _set_redemption_context(
    cursor: psycopg.Cursor[dict[str, object]],
    invitation: dict[str, str],
    *,
    idempotency_key: str,
    surface: str = "customer",
) -> None:
    cursor.execute(
        """
        SELECT set_config('app.rls_enabled', '1', true),
               set_config('app.actor_id', '', true),
               set_config('app.project_id', '', true),
               set_config('app.project_ids', '', true),
               set_config('app.tenant_id', '', true),
               set_config('geno.runtime_project_access_control', '1', true),
               set_config('geno.runtime_actor_id', '', true),
               set_config('geno.runtime_project_id', '', true),
               set_config('geno.runtime_tenant_id', '', true),
               set_config('geno.runtime_invitation_token_hash', %s, true),
               set_config('geno.runtime_idempotency_key_hash', %s, true),
               set_config('geno.runtime_requested_surface', %s, true),
               set_config('geno.runtime_session_token_hash', '', true)
        """,
        (_invitation_token_hash(invitation), _idempotency_hash(idempotency_key), surface),
    )


def _insert_preparing_attempt(
    cursor: psycopg.Cursor[dict[str, object]],
    invitation: dict[str, str],
    *,
    idempotency_key: str,
    surface: str = "customer",
) -> str:
    attempt_id = str(uuid4())
    _set_redemption_context(cursor, invitation, idempotency_key=idempotency_key, surface=surface)
    cursor.execute(
        """
        INSERT INTO auth_invitation_redemption_attempts(
          id, invitation_id, requested_surface, idempotency_key_hash,
          request_hash, token_fingerprint, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'preparing')
        """,
        (
            attempt_id,
            invitation["invitation_id"],
            surface,
            _idempotency_hash(idempotency_key),
            hashlib.sha256(f"request-{attempt_id}".encode("utf-8")).hexdigest(),
            _invitation_token_hash(invitation),
        ),
    )
    return attempt_id


def _insert_scope_session(
    owner: psycopg.Connection[dict[str, object]],
    *,
    actor_id: str,
    tenant_id: str,
    project_id: str,
    role: str,
    source: str,
) -> tuple[str, str]:
    session_id = str(uuid4())
    raw_token = f"session-{uuid4()}"
    scopes = [
        {
            "project_id": project_id,
            "roles": [role],
            "permissions": ["project.read"],
            "portal_capabilities": ["portal.customer.access" if role == "client_viewer" else "portal.admin.access"],
            "scope_sources": [source],
        }
    ]
    with owner.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO runtime_sessions(
              id, session_token_hash, actor_id, actor_type, tenant_id,
              project_ids, roles, permissions, tenant_roles, project_scopes,
              scope_version, authz_policy_version, auth_method, status,
              issued_by, expires_at, metadata
            )
            VALUES (
              %s, %s, %s, 'user', %s,
              %s, %s, %s, %s, %s,
              'runtime_session_scope_v2', 'auth_surface_policy_v1', 'session', 'active',
              'auth-postgres-test', now() + interval '1 hour', '{}'::jsonb
            )
            """,
            (
                session_id,
                hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
                actor_id,
                tenant_id,
                Jsonb([project_id]),
                Jsonb([role]),
                Jsonb(["project.read"]),
                Jsonb([role] if source == "tenant_role" else []),
                Jsonb(scopes),
            ),
        )
    owner.commit()
    return session_id, raw_token


def test_runtime_token_cannot_mutate_pending_invitation_snapshot() -> None:
    with _connect(OWNER_URL) as owner:
        invitation = _seed_invitation(
            owner,
            project=_seed_project(owner, suffix="snapshot-mutation"),
            actor_id=f"snapshot-{uuid4()}@example.com",
        )

    with _connect(APP_URL) as app_connection, app_connection.cursor() as cursor:
        _set_redemption_context(cursor, invitation, idempotency_key=f"snapshot-{uuid4()}")
        with pytest.raises(psycopg.Error):
            cursor.execute(
                """
                UPDATE project_member_invitations
                SET email = %s,
                    role = 'owner',
                    audience = 'admin',
                    allowed_surfaces = ARRAY['admin']::text[]
                WHERE id = %s
                """,
                (f"attacker-{uuid4()}@example.com", invitation["invitation_id"]),
            )
        app_connection.rollback()

    with _connect(OWNER_URL) as owner, owner.cursor() as cursor:
        cursor.execute(
            """
            SELECT email, role, audience, allowed_surfaces, status
            FROM project_member_invitations
            WHERE id = %s
            """,
            (invitation["invitation_id"],),
        )
        assert cursor.fetchone() == {
            "email": invitation["actor_id"],
            "role": "viewer",
            "audience": "customer",
            "allowed_surfaces": ["customer"],
            "status": "pending",
        }


def test_runtime_invitation_accept_cannot_create_arbitrary_owner_member() -> None:
    with _connect(OWNER_URL) as owner:
        invitation = _seed_invitation(
            owner,
            project=_seed_project(owner, suffix="strict-accept"),
            actor_id=f"strict-{uuid4()}@example.com",
        )

    with _connect(APP_URL) as app_connection, app_connection.cursor() as cursor:
        _insert_preparing_attempt(cursor, invitation, idempotency_key=f"strict-{uuid4()}")
        with pytest.raises(psycopg.Error):
            cursor.execute(
                """
                INSERT INTO project_members(id, project_id, tenant_id, user_id, role, status)
                VALUES (%s, %s, %s, %s, 'owner', 'active')
                """,
                (str(uuid4()), invitation["project_id"], invitation["tenant_id"], invitation["actor_id"]),
            )
        app_connection.rollback()

    with _connect(OWNER_URL) as owner, owner.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS count FROM project_members WHERE project_id = %s",
            (invitation["project_id"],),
        )
        assert cursor.fetchone()["count"] == 0


def test_viewer_runtime_context_cannot_update_project_membership() -> None:
    with _connect(OWNER_URL) as owner:
        project = _seed_project(owner, suffix="viewer-update")
        viewer = f"viewer-update-{uuid4()}@example.com"
        with owner.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO project_members(id, project_id, tenant_id, user_id, role, status)
                VALUES (%s, %s, %s, %s, 'viewer', 'active')
                """,
                (str(uuid4()), project["project_id"], project["tenant_id"], viewer),
            )
        owner.commit()

    with _connect(APP_URL) as app_connection, app_connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT set_config('app.rls_enabled', '1', true),
                   set_config('app.actor_id', %s, true),
                   set_config('app.project_id', %s, true),
                   set_config('app.project_ids', %s, true),
                   set_config('app.tenant_id', %s, true),
                   set_config('geno.runtime_project_access_control', '1', true),
                   set_config('geno.runtime_actor_id', %s, true),
                   set_config('geno.runtime_project_id', %s, true),
                   set_config('geno.runtime_tenant_id', %s, true)
            """,
            (
                viewer,
                project["project_id"],
                project["project_id"],
                project["tenant_id"],
                viewer,
                project["project_id"],
                project["tenant_id"],
            ),
        )
        cursor.execute(
            "UPDATE project_members SET role = 'owner' WHERE project_id = %s AND lower(user_id) = %s",
            (project["project_id"], viewer),
        )
        assert cursor.rowcount == 0
        app_connection.rollback()

    with _connect(OWNER_URL) as owner, owner.cursor() as cursor:
        cursor.execute(
            "SELECT role FROM project_members WHERE project_id = %s AND lower(user_id) = %s",
            (project["project_id"], viewer),
        )
        assert cursor.fetchone()["role"] == "viewer"


def test_runtime_app_cannot_forge_project_access_grant() -> None:
    with _connect(OWNER_URL) as owner:
        project = _seed_project(owner, suffix="grant-forge")

    with _connect(APP_URL) as app_connection, app_connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                """
                INSERT INTO runtime_project_access_grants(
                  tenant_id, project_id, actor_id, source_type, source_id,
                  canonical_role, permission_set_version, permissions, status
                )
                VALUES (%s, %s, %s, 'tenant_role', %s, 'super_admin',
                        'auth_surface_policy_v1', ARRAY['system.admin'], 'active')
                """,
                (
                    project["tenant_id"],
                    project["project_id"],
                    f"forged-{uuid4()}@example.com",
                    str(uuid4()),
                ),
            )
        app_connection.rollback()


def test_runtime_app_cannot_forge_or_escalate_session_scope() -> None:
    with _connect(OWNER_URL) as owner:
        project = _seed_project(owner, suffix="session-forge")
        actor = f"session-forge-{uuid4()}@example.com"
        invitation = _seed_invitation(owner, project=project, actor_id=actor)
        with owner.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO project_members(id, project_id, tenant_id, user_id, role, status)
                VALUES (%s, %s, %s, %s, 'viewer', 'active')
                """,
                (str(uuid4()), project["project_id"], project["tenant_id"], actor),
            )
        owner.commit()

    with _connect(APP_URL) as app_connection, app_connection.cursor() as cursor:
        attempt_id = _insert_preparing_attempt(cursor, invitation, idempotency_key=f"session-forge-{uuid4()}")
        with pytest.raises(psycopg.Error):
            cursor.execute(
                """
                INSERT INTO runtime_sessions(
                  id, session_token_hash, actor_id, actor_type, tenant_id,
                  project_ids, roles, permissions, tenant_roles, project_scopes,
                  scope_version, authz_policy_version, redemption_attempt_id,
                  auth_method, status, issued_by, expires_at, metadata
                )
                VALUES (
                  %s, %s, %s, 'user', %s,
                  %s, %s, %s, %s, %s,
                  'runtime_session_scope_v2', 'auth_surface_policy_v1', %s,
                  'session', 'active', 'auth-postgres-test', now() + interval '1 hour', '{}'::jsonb
                )
                """,
                (
                    str(uuid4()),
                    hashlib.sha256(str(uuid4()).encode("utf-8")).hexdigest(),
                    actor,
                    project["tenant_id"],
                    Jsonb([project["project_id"]]),
                    Jsonb(["project_owner"]),
                    Jsonb(["member.manage"]),
                    Jsonb([]),
                    Jsonb(
                        [
                            {
                                "project_id": project["project_id"],
                                "roles": ["project_owner"],
                                "permissions": ["member.manage"],
                                "portal_capabilities": ["portal.admin.access"],
                                "scope_sources": ["direct_member"],
                            }
                        ]
                    ),
                    attempt_id,
                ),
            )
        app_connection.rollback()

    with _connect(APP_URL) as app_connection:
        result = _repository(app_connection).redeem(
            invitation_id=invitation["invitation_id"],
            invite_token=invitation["token"],
            requested_surface=InvitationSurface.CUSTOMER,
            idempotency_key=f"session-valid-{uuid4()}",
        )
    with _connect(OWNER_URL) as owner, owner.cursor() as cursor:
        cursor.execute(
            "SELECT session_id::text AS session_id FROM auth_invitation_redemption_attempts WHERE id = %s",
            (result.correlation_id,),
        )
        session_id = str(cursor.fetchone()["session_id"])
    with _connect(APP_URL) as app_connection, app_connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                "UPDATE runtime_sessions SET roles = %s WHERE id = %s",
                (Jsonb(["project_owner"]), session_id),
            )
        app_connection.rollback()


def test_auth_write_kill_switch_blocks_invitation_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_WRITES_ENABLED", "0")
    with _connect(OWNER_URL) as owner:
        invitation = _seed_invitation(
            owner,
            project=_seed_project(owner, suffix="email-kill-switch"),
            actor_id=f"email-kill-{uuid4()}@example.com",
        )
    with _connect(APP_URL) as app_connection:
        with pytest.raises(AuthContractError) as caught:
            PostgresEvidenceRepository(app_connection).send_runtime_project_member_invitation_email(
                RuntimeProjectMemberInvitationEmailInput(
                    project_id=invitation["project_id"],
                    invitation_id=invitation["invitation_id"],
                    invite_token=invitation["token"],
                    accept_base_url="https://customer.example.test/invite",
                    sent_by="auth-test",
                    smtp_env_prefix="GENO_TEST_SMTP",
                )
            )
        assert caught.value.code == "auth_writes_temporarily_disabled"


def test_stale_policy_and_surface_mismatch_are_zero_side_effects() -> None:
    with _connect(OWNER_URL) as owner:
        project = _seed_project(owner, suffix="policy")
        stale = _seed_invitation(
            owner,
            project=project,
            actor_id=f"stale-{uuid4()}@example.com",
            policy_version="auth_surface_policy_v0",
        )
        mismatch = _seed_invitation(
            owner,
            project=project,
            actor_id=f"viewer-{uuid4()}@example.com",
        )
        with _connect(APP_URL) as app_connection:
            repository = _repository(app_connection)
            preflight = repository.preflight(
                invitation_id=stale["invitation_id"],
                invite_token=stale["token"],
                requested_surface=InvitationSurface.CUSTOMER,
            )
            assert preflight.compatibility is InvitationSurfaceCompatibility.POLICY_STALE
            with pytest.raises(AuthContractError, match="requested surface") as caught:
                repository.redeem(
                    invitation_id=mismatch["invitation_id"],
                    invite_token=mismatch["token"],
                    requested_surface=InvitationSurface.ADMIN,
                    idempotency_key=f"mismatch-{uuid4()}",
                )
            assert caught.value.code == "invitation_surface_mismatch"

        with owner.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  (SELECT count(*) FROM project_members WHERE project_id = %s) AS members,
                  (SELECT count(*) FROM runtime_sessions WHERE tenant_id = %s) AS sessions,
                  (SELECT count(*) FROM auth_invitation_redemption_attempts
                   WHERE invitation_id IN (%s, %s)) AS attempts
                """,
                (
                    project["project_id"],
                    project["tenant_id"],
                    stale["invitation_id"],
                    mismatch["invitation_id"],
                ),
            )
            assert cursor.fetchone() == {"members": 0, "sessions": 0, "attempts": 0}


def test_redeem_replays_identical_delivery_and_confirm_erases_ciphertext() -> None:
    with _connect(OWNER_URL) as owner:
        invitation = _seed_invitation(
            owner,
            project=_seed_project(owner, suffix="replay"),
            actor_id=f"replay-{uuid4()}@example.com",
        )
        with _connect(APP_URL) as app_connection:
            repository = _repository(app_connection)
            key = f"replay-{uuid4()}"
            created = repository.redeem(
                invitation_id=invitation["invitation_id"],
                invite_token=invitation["token"],
                requested_surface=InvitationSurface.CUSTOMER,
                idempotency_key=key,
            )
            replayed = repository.redeem(
                invitation_id=invitation["invitation_id"],
                invite_token=invitation["token"],
                requested_surface=InvitationSurface.CUSTOMER,
                idempotency_key=key,
            )
            assert created.recovery_status is InvitationRedeemRecoveryStatus.CREATED
            assert replayed.recovery_status is InvitationRedeemRecoveryStatus.REPLAYED
            assert replayed.cookie_delivery.cookie_headers == created.cookie_delivery.cookie_headers

            with owner.cursor() as cursor:
                cursor.execute(
                    "SELECT session_id FROM auth_invitation_redemption_attempts WHERE id = %s",
                    (created.correlation_id,),
                )
                session_id = str(cursor.fetchone()["session_id"])
            assert repository.confirm_delivery(
                session_id=session_id,
                actor_id=invitation["actor_id"],
                tenant_id=invitation["tenant_id"],
            )
            with app_connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT current_setting('app.rls_enabled', true) AS app_rls,
                           current_setting('app.actor_id', true) AS app_actor,
                           current_setting('app.project_id', true) AS app_project,
                           current_setting('app.project_ids', true) AS app_projects,
                           current_setting('app.tenant_id', true) AS app_tenant,
                           current_setting('geno.runtime_project_access_control', true) AS runtime_rls,
                           current_setting('geno.runtime_actor_id', true) AS runtime_actor,
                           current_setting('geno.runtime_project_id', true) AS runtime_project,
                           current_setting('geno.runtime_tenant_id', true) AS runtime_tenant,
                           current_setting('geno.runtime_session_token_hash', true) AS session_hash
                    """
                )
                assert cursor.fetchone() == {
                    "app_rls": "1",
                    "app_actor": "",
                    "app_project": "",
                    "app_projects": "",
                    "app_tenant": "",
                    "runtime_rls": "1",
                    "runtime_actor": "",
                    "runtime_project": "",
                    "runtime_tenant": "",
                    "session_hash": "",
                }

        with owner.cursor() as cursor:
            cursor.execute(
                """
                SELECT delivery_confirmed_at IS NOT NULL AS confirmed,
                       delivery_ciphertext IS NULL AS erased,
                       replay_count
                FROM auth_invitation_redemption_attempts WHERE id = %s
                """,
                (created.correlation_id,),
            )
            assert cursor.fetchone() == {"confirmed": True, "erased": True, "replay_count": 1}


def test_concurrent_same_key_consumes_once_and_returns_same_cookies() -> None:
    with _connect(OWNER_URL) as owner:
        invitation = _seed_invitation(
            owner,
            project=_seed_project(owner, suffix="concurrent"),
            actor_id=f"concurrent-{uuid4()}@example.com",
        )
    key = f"concurrent-{uuid4()}"

    def redeem() -> tuple[InvitationRedeemRecoveryStatus, tuple[str, ...]]:
        with _connect(APP_URL) as connection:
            result = _repository(connection).redeem(
                invitation_id=invitation["invitation_id"],
                invite_token=invitation["token"],
                requested_surface=InvitationSurface.CUSTOMER,
                idempotency_key=key,
            )
            return result.recovery_status, result.cookie_delivery.cookie_headers

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _item: redeem(), range(2)))

    assert {status for status, _headers in results} == {
        InvitationRedeemRecoveryStatus.CREATED,
        InvitationRedeemRecoveryStatus.REPLAYED,
    }
    assert results[0][1] == results[1][1]
    with _connect(OWNER_URL) as owner, owner.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS count FROM auth_invitation_redemption_attempts WHERE invitation_id = %s",
            (invitation["invitation_id"],),
        )
        assert cursor.fetchone()["count"] == 1


def test_force_rls_tenant_grant_and_scope_change_revocations() -> None:
    with _connect(OWNER_URL) as owner:
        first = _seed_project(owner, suffix="grant-a")
        second_project_id = str(uuid4())
        with owner.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO projects(id, tenant_id, name, market_code, industry_code, target_brand, category, prompt_version, status)
                VALUES (%s, %s, 'Grant B', 'AU', 'auth_test', 'Brand', 'Auth', 'auth-test-v1', 'active')
                """,
                (second_project_id, first["tenant_id"]),
            )
            tenant_member_id = str(uuid4())
            actor = f"tenant-admin-{uuid4()}@example.com"
            cursor.execute(
                """
                INSERT INTO tenant_members(id, tenant_id, user_id, role, status, invited_by)
                VALUES (%s, %s, %s, 'tenant_admin', 'active', 'auth-test')
                """,
                (tenant_member_id, first["tenant_id"], actor),
            )
        owner.commit()

        with _connect(APP_URL) as app_connection, app_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT set_config('app.rls_enabled', '1', true),
                       set_config('app.tenant_id', %s, true),
                       set_config('app.actor_id', %s, true),
                       set_config('geno.runtime_project_access_control', '1', true),
                       set_config('geno.runtime_tenant_id', %s, true),
                       set_config('geno.runtime_actor_id', %s, true)
                """,
                (first["tenant_id"], actor, first["tenant_id"], actor),
            )
            cursor.execute("SELECT id::text AS id FROM projects ORDER BY id")
            visible = {str(row["id"]) for row in cursor.fetchall()}
            assert visible == {first["project_id"], second_project_id}
            app_connection.rollback()

        session_id, raw_token = _insert_scope_session(
            owner,
            actor_id=actor,
            tenant_id=first["tenant_id"],
            project_id=first["project_id"],
            role="tenant_admin",
            source="tenant_role",
        )
        with owner.cursor() as cursor:
            cursor.execute("UPDATE tenant_members SET status = 'disabled' WHERE id = %s", (tenant_member_id,))
        owner.commit()
        with owner.cursor() as cursor:
            cursor.execute("SELECT status, revoke_reason FROM runtime_sessions WHERE id = %s", (session_id,))
            assert cursor.fetchone() == {"status": "revoked", "revoke_reason": "tenant_membership_changed"}
            cursor.execute("SELECT reason_code FROM runtime_session_reauth_queue WHERE session_id = %s", (session_id,))
            assert cursor.fetchone()["reason_code"] in {
                "tenant_membership_changed",
                "project_access_grant_changed",
            }

        with _connect(APP_URL) as app_connection:
            with pytest.raises(ValueError, match="runtime session not found"):
                PostgresEvidenceRepository(app_connection).validate_runtime_session(raw_token)


def test_direct_member_delete_and_project_archive_revoke_existing_sessions() -> None:
    with _connect(OWNER_URL) as owner:
        project = _seed_project(owner, suffix="direct-revoke")
        delete_actor = f"delete-member-{uuid4()}@example.com"
        archive_actor = f"archive-project-{uuid4()}@example.com"
        with owner.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO project_members(id, project_id, tenant_id, user_id, role, status)
                VALUES (%s, %s, %s, %s, 'viewer', 'active'),
                       (%s, %s, %s, %s, 'viewer', 'active')
                """,
                (
                    str(uuid4()),
                    project["project_id"],
                    project["tenant_id"],
                    delete_actor,
                    str(uuid4()),
                    project["project_id"],
                    project["tenant_id"],
                    archive_actor,
                ),
            )
        owner.commit()
        delete_session, delete_token = _insert_scope_session(
            owner,
            actor_id=delete_actor,
            tenant_id=project["tenant_id"],
            project_id=project["project_id"],
            role="client_viewer",
            source="direct_member",
        )
        archive_session, archive_token = _insert_scope_session(
            owner,
            actor_id=archive_actor,
            tenant_id=project["tenant_id"],
            project_id=project["project_id"],
            role="client_viewer",
            source="direct_member",
        )

        with owner.cursor() as cursor:
            cursor.execute(
                "DELETE FROM project_members WHERE project_id = %s AND lower(user_id) = %s",
                (project["project_id"], delete_actor),
            )
        owner.commit()
        with owner.cursor() as cursor:
            cursor.execute("SELECT status, revoke_reason FROM runtime_sessions WHERE id = %s", (delete_session,))
            assert cursor.fetchone() == {"status": "revoked", "revoke_reason": "project_membership_changed"}

        with owner.cursor() as cursor:
            cursor.execute("UPDATE projects SET status = 'archived' WHERE id = %s", (project["project_id"],))
        owner.commit()
        with owner.cursor() as cursor:
            cursor.execute("SELECT status, revoke_reason FROM runtime_sessions WHERE id = %s", (archive_session,))
            assert cursor.fetchone() == {"status": "revoked", "revoke_reason": "project_lifecycle_changed"}

        with _connect(APP_URL) as app_connection:
            repository = PostgresEvidenceRepository(app_connection)
            for raw_token in (delete_token, archive_token):
                with pytest.raises(ValueError, match="runtime session not found"):
                    repository.validate_runtime_session(raw_token)


def test_composite_lineage_constraints_reject_cross_invitation_and_session_links() -> None:
    with _connect(OWNER_URL) as owner:
        project = _seed_project(owner, suffix="lineage")
        first = _seed_invitation(
            owner,
            project=project,
            actor_id=f"lineage-a-{uuid4()}@example.com",
        )
        second = _seed_invitation(
            owner,
            project=project,
            actor_id=f"lineage-b-{uuid4()}@example.com",
        )
        with _connect(APP_URL) as app_connection:
            result = _repository(app_connection).redeem(
                invitation_id=first["invitation_id"],
                invite_token=first["token"],
                requested_surface=InvitationSurface.CUSTOMER,
                idempotency_key=f"lineage-{uuid4()}",
            )

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with owner.cursor() as cursor:
                cursor.execute(
                    "UPDATE project_member_invitations SET accepted_by_attempt_id = %s WHERE id = %s",
                    (result.correlation_id, second["invitation_id"]),
                )
            owner.commit()
        owner.rollback()

        unrelated_session, _raw_token = _insert_scope_session(
            owner,
            actor_id=first["actor_id"],
            tenant_id=first["tenant_id"],
            project_id=first["project_id"],
            role="client_viewer",
            source="direct_member",
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with owner.cursor() as cursor:
                cursor.execute(
                    "UPDATE auth_invitation_redemption_attempts SET session_id = %s WHERE id = %s",
                    (unrelated_session, result.correlation_id),
                )
            owner.commit()
        owner.rollback()


def test_db_kill_switch_maps_generic_member_write_to_stable_http_503(monkeypatch: pytest.MonkeyPatch) -> None:
    with _connect(OWNER_URL) as owner:
        project = _seed_project(owner, suffix="kill-switch")
        with owner.cursor() as cursor:
            cursor.execute(
                "UPDATE auth_runtime_write_controls SET writes_enabled = false, reason = 'http-test' WHERE singleton"
            )
        owner.commit()
        monkeypatch.setenv("DATABASE_URL", APP_URL)
        monkeypatch.setenv("GENO_RUNTIME_PROJECT_ACCESS_CONTROL", "0")
        monkeypatch.setenv("AUTH_WRITES_ENABLED", "1")
        from geno_api.main import app

        try:
            response = TestClient(app).post(
                "/v1/project-members/runtime",
                json={
                    "project_id": project["project_id"],
                    "user_id": f"kill-switch-{uuid4()}@example.com",
                    "role": "viewer",
                },
            )
            assert response.status_code == 503
            assert response.json()["code"] == "auth_writes_temporarily_disabled"
        finally:
            with owner.cursor() as cursor:
                cursor.execute(
                    "UPDATE auth_runtime_write_controls SET writes_enabled = true, reason = 'http-test-reset' WHERE singleton"
                )
            owner.commit()


def test_preflight_with_existing_session_is_csrf_exempt_and_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _connect(OWNER_URL) as owner:
        project = _seed_project(owner, suffix="preflight-http")
        actor = f"preflight-session-{uuid4()}@example.com"
        invitation = _seed_invitation(
            owner,
            project=project,
            actor_id=f"preflight-invite-{uuid4()}@example.com",
        )
        with owner.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO project_members(id, project_id, tenant_id, user_id, role, status)
                VALUES (%s, %s, %s, %s, 'viewer', 'active')
                """,
                (str(uuid4()), project["project_id"], project["tenant_id"], actor),
            )
        owner.commit()
        _session_id, raw_token = _insert_scope_session(
            owner,
            actor_id=actor,
            tenant_id=project["tenant_id"],
            project_id=project["project_id"],
            role="client_viewer",
            source="direct_member",
        )

    monkeypatch.setenv("DATABASE_URL", APP_URL)
    monkeypatch.setenv("GENO_RUNTIME_PROJECT_ACCESS_CONTROL", "1")
    monkeypatch.setenv("GENO_RUNTIME_AUTH_MODE", "session")
    monkeypatch.setenv("GENO_AUTH_PREFLIGHT_RATE_LIMIT", "20")
    from geno_api.main import app

    response = TestClient(app).post(
        "/v1/auth/invitations/preflight",
        headers={"X-GENO-Session-Token": raw_token},
        json={
            "invitation_id": invitation["invitation_id"],
            "invite_token": invitation["token"],
            "requested_surface": "customer",
        },
    )
    assert response.status_code == 200
    assert response.json()["compatibility"] == "compatible"
    assert response.headers["cache-control"] == "no-store"


def test_auth_me_confirms_delivery_only_with_matching_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _connect(OWNER_URL) as owner:
        invitation = _seed_invitation(
            owner,
            project=_seed_project(owner, suffix="me-confirm"),
            actor_id=f"me-confirm-{uuid4()}@example.com",
        )
        with _connect(APP_URL) as app_connection:
            result = _repository(app_connection).redeem(
                invitation_id=invitation["invitation_id"],
                invite_token=invitation["token"],
                requested_surface=InvitationSurface.CUSTOMER,
                idempotency_key=f"me-confirm-{uuid4()}",
            )

        cookies: dict[str, str] = {}
        for header in result.cookie_delivery.cookie_headers:
            parsed = SimpleCookie()
            parsed.load(header)
            cookies.update({name: morsel.value for name, morsel in parsed.items()})
        session_token = cookies["GENO_RUNTIME_SESSION"]
        csrf_token = cookies["GENO_CSRF_TOKEN"]

        def delivery_state() -> dict[str, object]:
            with owner.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT delivery_confirmed_at IS NOT NULL AS confirmed,
                           delivery_ciphertext IS NULL AS erased
                    FROM auth_invitation_redemption_attempts
                    WHERE id = %s
                    """,
                    (result.correlation_id,),
                )
                row = cursor.fetchone()
                assert row is not None
                return row

        assert delivery_state() == {"confirmed": False, "erased": False}

        monkeypatch.setenv("DATABASE_URL", APP_URL)
        monkeypatch.setenv("GENO_RUNTIME_PROJECT_ACCESS_CONTROL", "1")
        monkeypatch.setenv("GENO_RUNTIME_AUTH_MODE", "session")
        from geno_api.main import app

        client = TestClient(app)
        no_csrf = client.get(
            "/v1/auth/me",
            headers={"X-GENO-Session-Token": session_token},
        )
        assert no_csrf.status_code == 200
        assert delivery_state() == {"confirmed": False, "erased": False}

        wrong_csrf = client.get(
            "/v1/auth/me",
            headers={
                "X-GENO-Session-Token": session_token,
                "X-GENO-CSRF-Token": "wrong-token",
            },
            cookies={"GENO_CSRF_TOKEN": csrf_token},
        )
        assert wrong_csrf.status_code == 200
        assert delivery_state() == {"confirmed": False, "erased": False}

        confirmed = client.get(
            "/v1/auth/me",
            headers={
                "X-GENO-Session-Token": session_token,
                "X-GENO-CSRF-Token": csrf_token,
            },
            cookies={"GENO_CSRF_TOKEN": csrf_token},
        )
        assert confirmed.status_code == 200
        assert delivery_state() == {"confirmed": True, "erased": True}


def test_authz_helpers_have_fixed_owner_acl_and_search_path() -> None:
    helper_names = {
        "geno_authz_has_project_permission",
        "geno_runtime_can_recover_project_invitation",
        "geno_runtime_can_recover_redemption_attempt",
    }
    with _connect(OWNER_URL) as owner, owner.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.proname, p.prosecdef, r.rolname AS owner,
                   pg_get_functiondef(p.oid) AS definition,
                   has_function_privilege('public', p.oid, 'EXECUTE') AS public_execute
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            JOIN pg_roles r ON r.oid = p.proowner
            WHERE n.nspname = 'public' AND p.proname = ANY(%s)
            """,
            (list(helper_names),),
        )
        rows = cursor.fetchall()
    assert {str(row["proname"]) for row in rows} == helper_names
    for row in rows:
        assert row["prosecdef"] is True
        assert row["owner"] == "geno_rls_authz_owner"
        assert "SET search_path TO 'pg_catalog'" in str(row["definition"])
        assert row["public_execute"] is False


def test_db_rejects_active_v1_and_cross_tenant_scope_v2_sessions() -> None:
    with _connect(OWNER_URL) as owner:
        first = _seed_project(owner, suffix="session-invariant-a")
        second = _seed_project(owner, suffix="session-invariant-b")
        with pytest.raises(psycopg.errors.RaiseException, match="runtime_session_scope_v2"):
            with owner.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO runtime_sessions(session_token_hash, actor_id, expires_at)
                    VALUES (%s, %s, now() + interval '1 hour')
                    """,
                    (hashlib.sha256(str(uuid4()).encode()).hexdigest(), "v1@example.com"),
                )
            owner.commit()
        owner.rollback()

        with pytest.raises(psycopg.errors.RaiseException, match="active session tenant"):
            _insert_scope_session(
                owner,
                actor_id="cross-tenant@example.com",
                tenant_id=first["tenant_id"],
                project_id=second["project_id"],
                role="client_viewer",
                source="direct_member",
            )
        owner.rollback()


def test_deleting_tenant_member_revokes_grants_and_existing_session() -> None:
    with _connect(OWNER_URL) as owner:
        project = _seed_project(owner, suffix="tenant-delete")
        actor = f"tenant-delete-{uuid4()}@example.com"
        member_id = str(uuid4())
        with owner.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tenant_members(id, tenant_id, user_id, role, status, invited_by)
                VALUES (%s, %s, %s, 'tenant_admin', 'active', 'auth-test')
                """,
                (member_id, project["tenant_id"], actor),
            )
        owner.commit()
        session_id, _raw_token = _insert_scope_session(
            owner,
            actor_id=actor,
            tenant_id=project["tenant_id"],
            project_id=project["project_id"],
            role="tenant_admin",
            source="tenant_role",
        )
        with owner.cursor() as cursor:
            cursor.execute("DELETE FROM tenant_members WHERE id = %s", (member_id,))
        owner.commit()
        with owner.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS count FROM runtime_project_access_grants WHERE source_id = %s AND status = 'active'",
                (member_id,),
            )
            assert cursor.fetchone()["count"] == 0
            cursor.execute("SELECT status FROM runtime_sessions WHERE id = %s", (session_id,))
            assert cursor.fetchone()["status"] == "revoked"


def test_shared_preflight_rate_limit_counter_is_atomic() -> None:
    bucket_key = hashlib.sha256(str(uuid4()).encode()).hexdigest()
    with _connect(APP_URL) as app_connection:
        repository = PostgresEvidenceRepository(app_connection)
        assert repository.consume_auth_preflight_rate_limit(
            bucket_key=bucket_key,
            limit=1,
            window_seconds=600,
        ) == 1
        assert repository.consume_auth_preflight_rate_limit(
            bucket_key=bucket_key,
            limit=1,
            window_seconds=600,
        ) == 2


def test_cleanup_deletes_expired_preflight_rate_limit_buckets() -> None:
    from scripts.cleanup_auth_redemption_attempts import delete_expired_preflight_buckets

    bucket_key = hashlib.sha256(str(uuid4()).encode()).hexdigest()
    with _connect(OWNER_URL) as owner, owner.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO auth_preflight_rate_limits(
              bucket_key, window_started_at, request_count, expires_at
            )
            VALUES (%s, now() - interval '2 hours', 1, now() - interval '1 hour')
            """,
            (bucket_key,),
        )
        owner.commit()
        assert delete_expired_preflight_buckets(owner, batch_size=100) >= 1
        cursor.execute("SELECT count(*) AS count FROM auth_preflight_rate_limits WHERE bucket_key = %s", (bucket_key,))
        assert cursor.fetchone()["count"] == 0


def test_scope_row_locks_make_concurrent_member_delete_revoke_new_session() -> None:
    class BlockingKeyring:
        def __init__(self) -> None:
            self.inner = AuthDeliveryKeyring.from_env()
            self.scope_loaded = Event()
            self.release = Event()

        def encrypt(self, delivery: object, *, attempt_id: str) -> object:
            self.scope_loaded.set()
            if not self.release.wait(timeout=10):
                raise TimeoutError("test did not release redemption")
            return self.inner.encrypt(delivery, attempt_id=attempt_id)  # type: ignore[arg-type]

    with _connect(OWNER_URL) as owner:
        invitation = _seed_invitation(
            owner,
            project=_seed_project(owner, suffix="scope-race"),
            actor_id=f"scope-race-{uuid4()}@example.com",
        )
        with owner.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO project_members(id, project_id, tenant_id, user_id, role, status)
                VALUES (%s, %s, %s, %s, 'viewer', 'active')
                """,
                (str(uuid4()), invitation["project_id"], invitation["tenant_id"], invitation["actor_id"]),
            )
        owner.commit()
    keyring = BlockingKeyring()

    def redeem() -> str:
        with _connect(APP_URL) as connection:
            result = AuthSessionV2Repository(connection, keyring=keyring, cookie_secure=False).redeem(  # type: ignore[arg-type]
                invitation_id=invitation["invitation_id"],
                invite_token=invitation["token"],
                requested_surface=InvitationSurface.CUSTOMER,
                idempotency_key=f"scope-race-{uuid4()}",
            )
            return result.correlation_id

    def delete_member() -> None:
        with _connect(OWNER_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM project_members WHERE project_id = %s AND lower(user_id) = %s",
                (invitation["project_id"], invitation["actor_id"]),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        redeem_future = executor.submit(redeem)
        assert keyring.scope_loaded.wait(timeout=10)
        delete_future = executor.submit(delete_member)
        time.sleep(0.2)
        assert not delete_future.done()
        keyring.release.set()
        attempt_id = redeem_future.result(timeout=10)
        delete_future.result(timeout=10)

    with _connect(OWNER_URL) as owner, owner.cursor() as cursor:
        cursor.execute(
            """
            SELECT session_row.status
            FROM auth_invitation_redemption_attempts attempt
            JOIN runtime_sessions session_row ON session_row.id = attempt.session_id
            WHERE attempt.id = %s
            """,
            (attempt_id,),
        )
        assert cursor.fetchone()["status"] == "revoked"
