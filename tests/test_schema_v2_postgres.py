from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg

from geno_core.bootstrap import build_project_bootstrap
from geno_core.repositories.schema_v2_tenancy_repository import (
    PrivilegedSchemaV2TenancyRepository,
    SchemaV2TenancySeedConflictError,
)
from geno_core.schema_v2.tenancy_seed import translate_project_bootstrap_to_v2_seed


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/schema_v2_runner.py"
SCHEMA_ROOT = Path(os.getenv("SCHEMA_V2_ROOT", "/schema-v2"))
BEHAVIOR_TEST_ENABLED = os.getenv("SCHEMA_V2_BEHAVIOR_TEST") == "1"
LOCK_NAME = "geno:schema-v2:install"


@unittest.skipUnless(BEHAVIOR_TEST_ENABLED, "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2PostgresBehaviorTest(unittest.TestCase):
    def _run_runner(
        self,
        command: str,
        *,
        lock_timeout_seconds: float = 2.0,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                command,
                "--schema-root",
                str(SCHEMA_ROOT),
                "--app-version",
                os.getenv("GENO_APP_VERSION", "0.1.0"),
                "--app-commit",
                os.getenv("GENO_APP_COMMIT", "behavior-test"),
                "--lock-timeout-seconds",
                str(lock_timeout_seconds),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def _drop_bootstrap_metadata(self, connection: psycopg.Connection[object]) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP TABLE IF EXISTS auth_runtime_write_controls, "
                "runtime_session_reauth_queue, auth_preflight_rate_limits, "
                "auth_invitation_redemption_attempts, runtime_sessions, "
                "project_member_invitations, audit_events, "
                "runtime_project_access_grants, project_members, tenant_members, "
                "projects, industry_profiles, market_profiles, tenants CASCADE"
            )
            for signature in (
                "geno_v2_session_can_read_audit(uuid, uuid, text)",
                "geno_v2_session_can_read_project_member(uuid, uuid, text)",
                "geno_v2_session_can_read_tenant_member(uuid, text)",
                "geno_v2_session_can_read_profile(text, text)",
                "geno_v2_session_has_project_permission(uuid, uuid, text)",
                "geno_v2_session_has_tenant_permission(uuid, text)",
                "geno_v2_session_can_access_tenant(uuid)",
                "geno_v2_resolve_session_context()",
                "geno_v2_guard_runtime_session_update()",
                "geno_v2_validate_runtime_session_snapshot()",
                "geno_v2_validate_auth_redemption_lineage()",
                "geno_v2_jsonb_text_set(jsonb)",
                "geno_v2_reject_audit_event_mutation()",
                "geno_v2_sync_tenant_status_grants()",
                "geno_v2_sync_project_tenant_grants()",
                "geno_v2_sync_tenant_member_project_grants()",
                "geno_v2_authz_can_read_profile(text, text)",
                "geno_v2_authz_can_access_tenant(uuid)",
                "geno_v2_authz_has_project_permission(uuid, uuid, text)",
                "geno_v2_authz_has_tenant_permission(uuid, text)",
                "geno_v2_runtime_scope_contains(uuid)",
                "geno_v2_runtime_project_ids()",
                "geno_v2_runtime_project_id()",
                "geno_v2_runtime_tenant_id()",
                "geno_v2_runtime_actor_id()",
                "geno_v2_role_has_permission(text, text)",
                "geno_v2_permissions_for_role(text)",
            ):
                cursor.execute(f"DROP FUNCTION IF EXISTS {signature} CASCADE")
            cursor.execute("DROP TABLE IF EXISTS app_schema_metadata CASCADE")
            cursor.execute("DROP TABLE IF EXISTS schema_migration_ledger CASCADE")
            cursor.execute("DROP FUNCTION IF EXISTS geno_schema_v2_reject_ledger_mutation()")

    def _create_dirty_objects(self, connection: psycopg.Connection[object]) -> None:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE dirty_table (id integer PRIMARY KEY)")
            cursor.execute("CREATE VIEW dirty_view AS SELECT id FROM dirty_table")
            cursor.execute(
                "CREATE MATERIALIZED VIEW dirty_materialized_view AS "
                "SELECT id FROM dirty_table"
            )
            cursor.execute("CREATE SEQUENCE dirty_sequence")
            cursor.execute(
                "CREATE FUNCTION dirty_function() RETURNS integer "
                "LANGUAGE sql AS 'SELECT 1'"
            )
            cursor.execute("CREATE TYPE dirty_enum AS ENUM ('dirty')")
            cursor.execute('CREATE COLLATION dirty_collation FROM "C"')
            cursor.execute(
                "CREATE TEXT SEARCH CONFIGURATION dirty_ts_config "
                "(COPY = pg_catalog.simple)"
            )
            cursor.execute("CREATE EXTENSION postgres_fdw")
            cursor.execute("CREATE SERVER dirty_server FOREIGN DATA WRAPPER postgres_fdw")
            cursor.execute(
                "CREATE FOREIGN TABLE dirty_foreign_table (id integer) SERVER dirty_server"
            )

    def _drop_dirty_objects(self, connection: psycopg.Connection[object]) -> None:
        with connection.cursor() as cursor:
            cursor.execute("DROP FOREIGN TABLE IF EXISTS dirty_foreign_table")
            cursor.execute("DROP SERVER IF EXISTS dirty_server CASCADE")
            cursor.execute("DROP EXTENSION IF EXISTS postgres_fdw CASCADE")
            cursor.execute("DROP MATERIALIZED VIEW IF EXISTS dirty_materialized_view")
            cursor.execute("DROP VIEW IF EXISTS dirty_view")
            cursor.execute("DROP TABLE IF EXISTS dirty_table CASCADE")
            cursor.execute("DROP SEQUENCE IF EXISTS dirty_sequence")
            cursor.execute("DROP FUNCTION IF EXISTS dirty_function()")
            cursor.execute("DROP TYPE IF EXISTS dirty_enum")
            cursor.execute("DROP COLLATION IF EXISTS dirty_collation")
            cursor.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS dirty_ts_config")

    def test_advisory_lock_has_a_stable_timeout(self) -> None:
        with psycopg.connect(autocommit=True) as holder:
            with holder.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                    (LOCK_NAME,),
                )
            try:
                result = self._run_runner("verify", lock_timeout_seconds=0.2)
            finally:
                with holder.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                        (LOCK_NAME,),
                    )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(
            "timed out acquiring Schema v2 advisory lock after 0.200 seconds",
            result.stderr,
        )
        self.assertNotIn("Traceback", result.stderr)

    def test_dirty_public_namespace_fails_closed_but_required_extensions_are_allowed(self) -> None:
        with psycopg.connect(autocommit=True) as connection:
            self._drop_bootstrap_metadata(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER ROLE geno_v2_api_login "
                    "SET app.session_token_hash TO 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"
                )
                cursor.execute(
                    "ALTER ROLE geno_v2_api_login IN DATABASE geno_v2 "
                    "SET app.actor_id TO 'forged@example.test'"
                )

        extension_only_install = self._run_runner("install")
        self.assertEqual(
            extension_only_install.returncode,
            0,
            extension_only_install.stdout + extension_only_install.stderr,
        )
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT rolconfig FROM pg_roles WHERE rolname = 'geno_v2_api_login'"
                )
                self.assertIsNone(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT count(*) FROM pg_db_role_setting "
                    "WHERE setrole = ("
                    "SELECT oid FROM pg_roles WHERE rolname = 'geno_v2_api_login'"
                    ") AND setdatabase = ("
                    "SELECT oid FROM pg_database WHERE datname = 'geno_v2')"
                )
                self.assertEqual(cursor.fetchone()[0], 0)

        with psycopg.connect(autocommit=True) as connection:
            self._drop_bootstrap_metadata(connection)
            self._create_dirty_objects(connection)

        try:
            dirty_install = self._run_runner("install")
            self.assertEqual(dirty_install.returncode, 2, dirty_install.stdout + dirty_install.stderr)
            for expected in (
                "table:public.dirty_table",
                "view:public.dirty_view",
                "materialized_view:public.dirty_materialized_view",
                "sequence:public.dirty_sequence",
                "foreign_table:public.dirty_foreign_table",
                "dirty_function()",
                "enum_type:public.dirty_enum",
                "collation:public.dirty_collation",
                "text_search_configuration:public.dirty_ts_config",
                "extension:postgres_fdw",
            ):
                self.assertIn(expected, dirty_install.stderr)
            self.assertNotIn("Traceback", dirty_install.stderr)
        finally:
            with psycopg.connect(autocommit=True) as connection:
                self._drop_dirty_objects(connection)
            restored = self._run_runner("install")
            self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)

    def test_role_memberships_block_install_in_both_directions(self) -> None:
        probe_role = "geno_v2_membership_probe"
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP ROLE IF EXISTS {probe_role}")
                cursor.execute(f"CREATE ROLE {probe_role} NOLOGIN")

        membership_pairs = (
            (
                f"GRANT geno_v2_runtime TO {probe_role}",
                f"REVOKE geno_v2_runtime FROM {probe_role}",
            ),
            (
                f"GRANT {probe_role} TO geno_v2_authz_owner",
                f"REVOKE {probe_role} FROM geno_v2_authz_owner",
            ),
        )
        try:
            for grant_statement, revoke_statement in membership_pairs:
                with self.subTest(grant=grant_statement):
                    with psycopg.connect(autocommit=True) as connection:
                        self._drop_bootstrap_metadata(connection)
                        with connection.cursor() as cursor:
                            cursor.execute(grant_statement)

                    blocked = self._run_runner("install")
                    self.assertEqual(
                        blocked.returncode,
                        2,
                        blocked.stdout + blocked.stderr,
                    )
                    self.assertEqual(
                        blocked.stderr,
                        "schema-v2 error: database operation failed\n",
                    )

                    with psycopg.connect(autocommit=True) as connection:
                        with connection.cursor() as cursor:
                            cursor.execute(revoke_statement)
                    restored = self._run_runner("install")
                    self.assertEqual(
                        restored.returncode,
                        0,
                        restored.stdout + restored.stderr,
                    )
        finally:
            with psycopg.connect(autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(f"REVOKE geno_v2_runtime FROM {probe_role}")
                    cursor.execute(f"REVOKE {probe_role} FROM geno_v2_authz_owner")
                    cursor.execute(f"DROP ROLE IF EXISTS {probe_role}")


@unittest.skipUnless(BEHAVIOR_TEST_ENABLED, "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2TenancyPostgresBehaviorTest(unittest.TestCase):
    tenant_a: UUID
    tenant_b: UUID
    project_a1: UUID
    project_a2: UUID
    project_a3: UUID
    project_b1: UUID
    admin_a: str
    admin_b: str
    multi_actor: str
    actor_b: str
    admin_a_member_id: UUID
    audit_global_a: UUID
    audit_global_b: UUID
    audit_tenant_a: UUID
    audit_project_a1: UUID
    audit_project_a3: UUID
    audit_project_b1: UUID
    valid_session_id: UUID
    valid_session_hash: str
    expired_session_id: UUID
    expired_session_hash: str
    revoked_session_id: UUID
    revoked_session_hash: str
    future_session_id: UUID
    future_session_hash: str
    cross_tenant_session_id: UUID
    cross_tenant_session_hash: str
    viewer_actor: str
    viewer_session_id: UUID
    viewer_session_hash: str

    @classmethod
    def setUpClass(cls) -> None:
        unique = uuid4().hex
        market_code = f"AU-{unique}"
        industry_code = f"software-{unique}"
        cls.tenant_a = uuid4()
        cls.tenant_b = uuid4()
        cls.project_a1 = uuid4()
        cls.project_a2 = uuid4()
        cls.project_a3 = uuid4()
        cls.project_b1 = uuid4()
        cls.admin_a = f"admin-a-{unique}@example.test"
        cls.admin_b = f"admin-b-{unique}@example.test"
        cls.multi_actor = f"multi-{unique}@example.test"
        cls.actor_b = f"actor-b-{unique}@example.test"
        cls.viewer_actor = f"viewer-{unique}@example.test"
        cls.admin_a_member_id = uuid4()
        cls.audit_global_a = uuid4()
        cls.audit_global_b = uuid4()
        cls.audit_tenant_a = uuid4()
        cls.audit_project_a1 = uuid4()
        cls.audit_project_a3 = uuid4()
        cls.audit_project_b1 = uuid4()
        cls.valid_session_hash = hashlib.sha256(
            f"valid-session-{unique}".encode("utf-8")
        ).hexdigest()
        cls.expired_session_hash = hashlib.sha256(
            f"expired-session-{unique}".encode("utf-8")
        ).hexdigest()
        cls.revoked_session_hash = hashlib.sha256(
            f"revoked-session-{unique}".encode("utf-8")
        ).hexdigest()
        cls.future_session_hash = hashlib.sha256(
            f"future-session-{unique}".encode("utf-8")
        ).hexdigest()
        cls.cross_tenant_session_hash = hashlib.sha256(
            f"cross-tenant-session-{unique}".encode("utf-8")
        ).hexdigest()
        cls.viewer_session_hash = hashlib.sha256(
            f"viewer-session-{unique}".encode("utf-8")
        ).hexdigest()

        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO market_profiles (market_code, payload) VALUES (%s, %s)",
                    (market_code, psycopg.types.json.Jsonb({"region": "AU"})),
                )
                cursor.execute(
                    "INSERT INTO industry_profiles "
                    "(market_code, industry_code, payload) VALUES (%s, %s, %s)",
                    (
                        market_code,
                        industry_code,
                        psycopg.types.json.Jsonb({"industry": "software"}),
                    ),
                )
                cursor.execute(
                    "INSERT INTO tenants (id, name, slug) VALUES "
                    "(%s, 'Tenant A', %s), (%s, 'Tenant B', %s)",
                    (
                        cls.tenant_a,
                        f"tenant-a-{unique}",
                        cls.tenant_b,
                        f"tenant-b-{unique}",
                    ),
                )
                cursor.execute(
                    "INSERT INTO tenant_members "
                    "(id, tenant_id, user_id, role) VALUES "
                    "(%s, %s, %s, 'tenant_admin'), "
                    "(%s, %s, %s, 'tenant_admin')",
                    (
                        cls.admin_a_member_id,
                        cls.tenant_a,
                        cls.admin_a,
                        uuid4(),
                        cls.tenant_b,
                        cls.admin_b,
                    ),
                )
                for project_id, tenant_id, name, status in (
                    (cls.project_a1, cls.tenant_a, f"Project A1 {unique}", "active"),
                    (cls.project_a2, cls.tenant_a, f"Project A2 {unique}", "paused"),
                    (cls.project_a3, cls.tenant_a, f"Project A3 {unique}", "active"),
                    (cls.project_b1, cls.tenant_b, f"Project B1 {unique}", "active"),
                ):
                    cursor.execute(
                        "INSERT INTO projects "
                        "(id, tenant_id, name, market_code, industry_code, "
                        "target_brand, category, prompt_version, status) "
                        "VALUES (%s, %s, %s, %s, %s, 'Brand', 'Software', 'v1', %s)",
                        (
                            project_id,
                            tenant_id,
                            name,
                            market_code,
                            industry_code,
                            status,
                        ),
                    )
                for project_id, tenant_id, user_id, role in (
                    (cls.project_a1, cls.tenant_a, cls.admin_a, "analyst"),
                    (cls.project_a1, cls.tenant_a, cls.multi_actor, "project_owner"),
                    (cls.project_a2, cls.tenant_a, cls.multi_actor, "analyst"),
                    (cls.project_a1, cls.tenant_a, cls.viewer_actor, "client_viewer"),
                    (cls.project_b1, cls.tenant_b, cls.admin_b, "analyst"),
                    (cls.project_b1, cls.tenant_b, cls.actor_b, "project_owner"),
                ):
                    cursor.execute(
                        "INSERT INTO project_members "
                        "(tenant_id, project_id, user_id, role) VALUES (%s, %s, %s, %s)",
                        (tenant_id, project_id, user_id, role),
                    )
                for event_id, tenant_id, project_id, actor_id, target_id in (
                    (cls.audit_global_a, None, None, cls.admin_a, "global-a"),
                    (cls.audit_global_b, None, None, cls.admin_b, "global-b"),
                    (cls.audit_tenant_a, cls.tenant_a, None, cls.admin_a, "tenant-a"),
                    (cls.audit_project_a1, cls.tenant_a, cls.project_a1, cls.multi_actor, "a1"),
                    (cls.audit_project_a3, cls.tenant_a, cls.project_a3, cls.admin_a, "a3"),
                    (cls.audit_project_b1, cls.tenant_b, cls.project_b1, cls.actor_b, "b1"),
                ):
                    cursor.execute(
                        "INSERT INTO audit_events "
                        "(id, tenant_id, project_id, event_type, actor_type, actor_id, "
                        "target_type, target_id) "
                        "VALUES (%s, %s, %s, 'test.event', 'user', %s, 'test', %s)",
                        (event_id, tenant_id, project_id, actor_id, target_id),
                    )

        def insert_session_lineage(
            cursor: psycopg.Cursor[object],
            *,
            tenant_id: UUID,
            actor_id: str,
            project_ids: tuple[UUID, ...],
            canonical_role: str,
            tenant_roles: tuple[str, ...],
            session_hash: str,
            issued_at: datetime,
            expires_at: datetime,
            marker: str,
        ) -> UUID:
            sorted_project_ids = tuple(sorted(project_ids, key=str))
            requested_surface = "customer" if canonical_role == "client_viewer" else "admin"
            invitation_role = "client_viewer" if canonical_role == "client_viewer" else "analyst"
            project_scopes: list[dict[str, object]] = []
            aggregate_roles = set(tenant_roles)
            aggregate_permissions: set[str] = set()
            for project_id in sorted_project_ids:
                cursor.execute(
                    "SELECT role_name FROM ("
                    "SELECT role AS role_name FROM project_members "
                    "WHERE project_id = %s AND tenant_id = %s "
                    "AND user_id = %s AND status = 'active' UNION "
                    "SELECT canonical_role FROM runtime_project_access_grants "
                    "WHERE project_id = %s AND tenant_id = %s "
                    "AND actor_id = %s AND status = 'active'"
                    ") AS backed_roles ORDER BY role_name",
                    (
                        project_id,
                        tenant_id,
                        actor_id,
                        project_id,
                        tenant_id,
                        actor_id,
                    ),
                )
                project_roles = [row[0] for row in cursor.fetchall()]
                cursor.execute(
                    "SELECT DISTINCT permission FROM unnest(%s::text[]) AS role(role_name) "
                    "CROSS JOIN LATERAL unnest("
                    "geno_v2_permissions_for_role(role.role_name)) AS item(permission) "
                    "ORDER BY permission",
                    (project_roles,),
                )
                project_permissions = [row[0] for row in cursor.fetchall()]
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM project_members WHERE project_id = %s "
                    "AND tenant_id = %s AND user_id = %s AND status = 'active'), "
                    "EXISTS (SELECT 1 FROM runtime_project_access_grants "
                    "WHERE project_id = %s AND tenant_id = %s "
                    "AND actor_id = %s AND status = 'active')",
                    (
                        project_id,
                        tenant_id,
                        actor_id,
                        project_id,
                        tenant_id,
                        actor_id,
                    ),
                )
                has_direct_member, has_tenant_role = cursor.fetchone()
                scope_sources = []
                if has_direct_member:
                    scope_sources.append("direct_member")
                if has_tenant_role:
                    scope_sources.append("tenant_role")
                project_scopes.append(
                    {
                        "project_id": str(project_id),
                        "roles": project_roles,
                        "permissions": project_permissions,
                        "portal_capabilities": sorted(
                            {
                                "portal.customer.access"
                                if role == "client_viewer"
                                else "portal.admin.access"
                                for role in project_roles
                            }
                        ),
                        "scope_sources": scope_sources,
                    }
                )
                aggregate_roles.update(project_roles)
                aggregate_permissions.update(project_permissions)
            invitation_id = uuid4()
            history_attempt_id = uuid4()
            attempt_id = uuid4()
            session_id = uuid4()
            first_project_id = project_ids[0]
            current_time = datetime.now(UTC)
            invitation_created_at = min(issued_at, current_time) - timedelta(seconds=1)
            invitation_expires_at = max(
                current_time + timedelta(days=2),
                issued_at + timedelta(days=2),
            )

            def digest(value: str) -> str:
                return hashlib.sha256(value.encode("utf-8")).hexdigest()

            cursor.execute(
                "INSERT INTO project_member_invitations ("
                "id, tenant_id, project_id, email, role, status, invite_token_hash, "
                "audience, allowed_surfaces, policy_version, invited_by, "
                "accepted_by_attempt_id, expires_at, accepted_at, created_at) "
                "VALUES (%s, %s, %s, %s, %s, 'accepted', %s, "
                "%s, ARRAY[%s]::text[], 'auth_surface_policy_v1', 'behavior-test', "
                "%s, %s, %s, %s)",
                (
                    invitation_id,
                    tenant_id,
                    first_project_id,
                    actor_id,
                    invitation_role,
                    digest(f"invite-{marker}"),
                    requested_surface,
                    requested_surface,
                    attempt_id,
                    invitation_expires_at,
                    issued_at,
                    invitation_created_at,
                ),
            )
            cursor.execute(
                "INSERT INTO auth_invitation_redemption_attempts ("
                "id, tenant_id, project_id, invitation_id, requested_surface, "
                "idempotency_key_hash, request_hash, token_fingerprint, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'failed', %s)",
                (
                    history_attempt_id,
                    tenant_id,
                    first_project_id,
                    invitation_id,
                    requested_surface,
                    digest(f"history-idempotency-{marker}"),
                    digest(f"history-request-{marker}"),
                    digest(f"invite-{marker}"),
                    invitation_created_at + timedelta(milliseconds=500),
                ),
            )
            cursor.execute(
                "INSERT INTO auth_invitation_redemption_attempts ("
                "id, tenant_id, project_id, invitation_id, requested_surface, "
                "idempotency_key_hash, request_hash, token_fingerprint, created_at, "
                "session_id, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'succeeded')",
                (
                    attempt_id,
                    tenant_id,
                    first_project_id,
                    invitation_id,
                    requested_surface,
                    digest(f"idempotency-{marker}"),
                    digest(f"request-{marker}"),
                    digest(f"invite-{marker}"),
                    issued_at,
                    session_id,
                ),
            )
            cursor.execute(
                "INSERT INTO runtime_sessions ("
                "id, session_token_hash, actor_id, tenant_id, project_ids, roles, "
                "permissions, tenant_roles, project_scopes, redemption_attempt_id, "
                "issued_by, issued_at, expires_at, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "'behavior-test', %s, %s, %s)",
                (
                    session_id,
                    session_hash,
                    actor_id,
                    tenant_id,
                    psycopg.types.json.Jsonb([str(value) for value in sorted_project_ids]),
                    psycopg.types.json.Jsonb(sorted(aggregate_roles)),
                    psycopg.types.json.Jsonb(sorted(aggregate_permissions)),
                    psycopg.types.json.Jsonb(list(tenant_roles)),
                    psycopg.types.json.Jsonb(project_scopes),
                    attempt_id,
                    issued_at,
                    expires_at,
                    psycopg.types.json.Jsonb({"marker": marker}),
                ),
            )
            return session_id

        now = datetime.now(UTC)
        with psycopg.connect(autocommit=True) as connection:
            session_specs = (
                (
                    "valid",
                    cls.tenant_a,
                    cls.admin_a,
                    (cls.project_a1, cls.project_a2, cls.project_a3),
                    "tenant_admin",
                    ("tenant_admin",),
                    cls.valid_session_hash,
                    now,
                    now + timedelta(days=1),
                ),
                (
                    "expired",
                    cls.tenant_a,
                    cls.admin_a,
                    (cls.project_a1, cls.project_a2, cls.project_a3),
                    "tenant_admin",
                    ("tenant_admin",),
                    cls.expired_session_hash,
                    now - timedelta(days=2),
                    now - timedelta(days=1),
                ),
                (
                    "revoked",
                    cls.tenant_a,
                    cls.admin_a,
                    (cls.project_a1, cls.project_a2, cls.project_a3),
                    "tenant_admin",
                    ("tenant_admin",),
                    cls.revoked_session_hash,
                    now,
                    now + timedelta(days=1),
                ),
                (
                    "future",
                    cls.tenant_a,
                    cls.admin_a,
                    (cls.project_a1, cls.project_a2, cls.project_a3),
                    "tenant_admin",
                    ("tenant_admin",),
                    cls.future_session_hash,
                    now + timedelta(days=1),
                    now + timedelta(days=2),
                ),
                (
                    "cross-tenant",
                    cls.tenant_b,
                    cls.admin_b,
                    (cls.project_b1,),
                    "tenant_admin",
                    ("tenant_admin",),
                    cls.cross_tenant_session_hash,
                    now,
                    now + timedelta(days=1),
                ),
                (
                    "viewer",
                    cls.tenant_a,
                    cls.viewer_actor,
                    (cls.project_a1,),
                    "client_viewer",
                    (),
                    cls.viewer_session_hash,
                    now,
                    now + timedelta(days=1),
                ),
            )
            inserted_ids: dict[str, UUID] = {}
            for spec in session_specs:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        inserted_ids[spec[0]] = insert_session_lineage(
                            cursor,
                            tenant_id=spec[1],
                            actor_id=spec[2],
                            project_ids=spec[3],
                            canonical_role=spec[4],
                            tenant_roles=spec[5],
                            session_hash=spec[6],
                            issued_at=spec[7],
                            expires_at=spec[8],
                            marker=f"{unique}-{spec[0]}",
                        )
            cls.valid_session_id = inserted_ids["valid"]
            cls.expired_session_id = inserted_ids["expired"]
            cls.revoked_session_id = inserted_ids["revoked"]
            cls.future_session_id = inserted_ids["future"]
            cls.cross_tenant_session_id = inserted_ids["cross-tenant"]
            cls.viewer_session_id = inserted_ids["viewer"]
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE runtime_sessions SET status = 'revoked', revoked_at = %s, "
                    "revoked_by = 'behavior-test', revoke_reason = 'test-revocation', "
                    "updated_at = %s WHERE id = %s",
                    (now, now, cls.revoked_session_id),
                )

    def _set_forged_runtime_context(self, cursor: psycopg.Cursor[object]) -> None:
        cursor.execute("RESET ROLE")
        cursor.execute("RESET ALL")
        cursor.execute("SET ROLE geno_v2_api_login")
        cursor.execute("BEGIN")
        cursor.execute("SET LOCAL ROLE geno_v2_runtime")
        cursor.execute(
            "SELECT set_config('app.actor_id', %s, true), "
            "set_config('app.tenant_id', %s, true), "
            "set_config('app.project_id', %s, true), "
            "set_config('app.project_ids', %s, true), "
            "set_config('app.roles', %s, true)",
            (
                self.admin_a,
                str(self.tenant_a),
                str(self.project_a1),
                ",".join(str(value) for value in (self.project_a1, self.project_a2)),
                "super_admin,system,worker",
            ),
        )

    def _reset_role(self, cursor: psycopg.Cursor[object]) -> None:
        cursor.execute("ROLLBACK")
        cursor.execute("RESET ROLE")
        cursor.execute("RESET ALL")

    def _begin_runtime_transaction(self, cursor: psycopg.Cursor[object]) -> None:
        cursor.execute("BEGIN")
        cursor.execute("SET LOCAL ROLE geno_v2_runtime")

    def test_01_roles_rls_policies_and_privileges_are_exact(self) -> None:
        readable_tables = {
            "market_profiles",
            "industry_profiles",
            "tenants",
            "projects",
            "tenant_members",
            "project_members",
            "audit_events",
        }
        sensitive_tables = {
            "runtime_project_access_grants",
            "project_member_invitations",
            "runtime_sessions",
            "auth_invitation_redemption_attempts",
            "auth_preflight_rate_limits",
            "runtime_session_reauth_queue",
            "auth_runtime_write_controls",
        }
        expected_tables = readable_tables | sensitive_tables
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                    "rolreplication, rolbypassrls FROM pg_roles "
                    "WHERE rolname IN ("
                    "'geno_v2_api_login', 'geno_v2_runtime', 'geno_v2_authz_owner') "
                    "ORDER BY rolname"
                )
                role_rows = cursor.fetchall()
                self.assertEqual(
                    role_rows,
                    [
                        ("geno_v2_api_login", False, False, False, False, False, False),
                        ("geno_v2_authz_owner", False, False, False, False, False, True),
                        ("geno_v2_runtime", False, False, False, False, False, False),
                    ],
                )

                cursor.execute(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class JOIN pg_namespace ON pg_namespace.oid = relnamespace "
                    "WHERE nspname = 'public' AND relname = ANY(%s) ORDER BY relname",
                    (list(expected_tables),),
                )
                table_rows = cursor.fetchall()
                self.assertEqual({row[0] for row in table_rows}, expected_tables)
                self.assertTrue(all(row[1] and row[2] for row in table_rows))
                cursor.execute(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = ANY(%s) ORDER BY conname",
                    (
                        [
                            "auth_attempts_session_fkey",
                            "runtime_sessions_redemption_attempt_fkey",
                        ],
                    ),
                )
                self.assertEqual(
                    cursor.fetchall(),
                    [
                        (
                            "auth_attempts_session_fkey",
                            "FOREIGN KEY (session_id, tenant_id) REFERENCES "
                            "runtime_sessions(id, tenant_id) ON UPDATE RESTRICT "
                            "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
                        ),
                        (
                            "runtime_sessions_redemption_attempt_fkey",
                            "FOREIGN KEY (redemption_attempt_id, tenant_id) REFERENCES "
                            "auth_invitation_redemption_attempts(id, tenant_id) "
                            "ON UPDATE RESTRICT ON DELETE RESTRICT "
                            "DEFERRABLE INITIALLY DEFERRED",
                        ),
                    ],
                )

                cursor.execute(
                    "SELECT tablename, roles FROM pg_policies "
                    "WHERE schemaname = 'public' AND tablename = ANY(%s)",
                    (list(expected_tables),),
                )
                policy_rows = cursor.fetchall()
                self.assertEqual({row[0] for row in policy_rows}, readable_tables)
                self.assertTrue(all(row[1] == ["geno_v2_runtime"] for row in policy_rows))

                cursor.execute(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_namespace, "
                    "LATERAL aclexplode(coalesce(nspacl, acldefault('n', nspowner))) acl "
                    "WHERE nspname = 'public' AND acl.grantee = 0 "
                    "AND acl.privilege_type = 'CREATE')"
                )
                self.assertFalse(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_proc JOIN pg_namespace ON pg_namespace.oid = pronamespace, "
                    "LATERAL aclexplode(coalesce(proacl, acldefault('f', proowner))) acl "
                    "WHERE nspname = 'public' AND acl.grantee = 0 "
                    "AND acl.privilege_type = 'EXECUTE')"
                )
                self.assertFalse(cursor.fetchone()[0])

                for table_name in expected_tables:
                    with self.subTest(runtime_table_acl=table_name):
                        cursor.execute(
                            "SELECT "
                            "has_table_privilege('geno_v2_runtime', %s, 'SELECT'), "
                            "has_table_privilege('geno_v2_runtime', %s, 'INSERT'), "
                            "has_table_privilege('geno_v2_runtime', %s, 'UPDATE'), "
                            "has_table_privilege('geno_v2_runtime', %s, 'DELETE')",
                            tuple(f"public.{table_name}" for _ in range(4)),
                        )
                        self.assertEqual(
                            cursor.fetchone(),
                            (table_name in readable_tables, False, False, False),
                        )

                cursor.execute(
                    "SELECT has_schema_privilege('geno_v2_runtime', 'public', 'USAGE')"
                )
                self.assertTrue(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT proname, "
                    "has_function_privilege('geno_v2_runtime', pg_proc.oid, 'EXECUTE') "
                    "FROM pg_proc JOIN pg_namespace ON pg_namespace.oid = pronamespace "
                    "WHERE nspname = 'public' AND proname LIKE 'geno_v2_%' "
                    "ORDER BY proname"
                )
                function_acl_rows = cursor.fetchall()
                runtime_function_names = {
                    "geno_v2_resolve_session_context",
                    "geno_v2_session_can_access_tenant",
                    "geno_v2_session_can_read_audit",
                    "geno_v2_session_can_read_project_member",
                    "geno_v2_session_can_read_profile",
                    "geno_v2_session_can_read_tenant_member",
                    "geno_v2_session_has_project_permission",
                    "geno_v2_session_has_tenant_permission",
                }
                self.assertEqual(
                    {row[0] for row in function_acl_rows if row[1]},
                    runtime_function_names,
                )

                cursor.execute(
                    "SELECT proname, pg_get_userbyid(proowner), prosecdef, proconfig "
                    "FROM pg_proc JOIN pg_namespace ON pg_namespace.oid = pronamespace "
                    "WHERE nspname = 'public' AND proname LIKE 'geno_v2_%' "
                    "ORDER BY proname"
                )
                function_rows = cursor.fetchall()
                self.assertEqual(
                    {row[0] for row in function_rows},
                    {
                        "geno_v2_permissions_for_role",
                        "geno_v2_reject_audit_event_mutation",
                        "geno_v2_role_has_permission",
                        "geno_v2_sync_project_tenant_grants",
                        "geno_v2_sync_tenant_member_project_grants",
                        "geno_v2_sync_tenant_status_grants",
                        "geno_v2_jsonb_text_set",
                        "geno_v2_validate_auth_redemption_lineage",
                        "geno_v2_validate_runtime_session_snapshot",
                        "geno_v2_guard_runtime_session_update",
                        "geno_v2_resolve_session_context",
                        "geno_v2_session_can_access_tenant",
                        "geno_v2_session_has_tenant_permission",
                        "geno_v2_session_has_project_permission",
                        "geno_v2_session_can_read_profile",
                        "geno_v2_session_can_read_project_member",
                        "geno_v2_session_can_read_tenant_member",
                        "geno_v2_session_can_read_audit",
                    },
                )
                self.assertTrue(all(row[1] == "geno_v2_authz_owner" for row in function_rows))
                security_definer_functions = {row[0] for row in function_rows if row[2]}
                self.assertEqual(
                    security_definer_functions,
                    {
                        "geno_v2_sync_project_tenant_grants",
                        "geno_v2_sync_tenant_member_project_grants",
                        "geno_v2_sync_tenant_status_grants",
                        "geno_v2_validate_auth_redemption_lineage",
                        "geno_v2_validate_runtime_session_snapshot",
                        "geno_v2_resolve_session_context",
                        "geno_v2_session_can_access_tenant",
                        "geno_v2_session_has_tenant_permission",
                        "geno_v2_session_has_project_permission",
                        "geno_v2_session_can_read_profile",
                        "geno_v2_session_can_read_project_member",
                        "geno_v2_session_can_read_tenant_member",
                        "geno_v2_session_can_read_audit",
                    },
                )
                self.assertTrue(all(row[3] == ["search_path=pg_catalog"] for row in function_rows))

                cursor.execute(
                    "SELECT granted.rolname, member_role.rolname, "
                    "membership.admin_option, membership.inherit_option, "
                    "membership.set_option "
                    "FROM pg_auth_members AS membership "
                    "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
                    "JOIN pg_roles AS member_role ON member_role.oid = membership.member "
                    "WHERE granted.rolname IN ("
                    "'geno_v2_runtime', 'geno_v2_authz_owner', 'geno_v2_api_login') "
                    "OR member_role.rolname IN ("
                    "'geno_v2_runtime', 'geno_v2_authz_owner', 'geno_v2_api_login')"
                )
                self.assertEqual(
                    cursor.fetchall(),
                    [
                        (
                            "geno_v2_runtime",
                            "geno_v2_api_login",
                            False,
                            False,
                            True,
                        )
                    ],
                )
                cursor.execute(
                    "SELECT rolpassword IS NULL FROM pg_authid "
                    "WHERE rolname = 'geno_v2_api_login'"
                )
                self.assertTrue(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT rolconfig FROM pg_roles WHERE rolname = 'geno_v2_api_login'"
                )
                self.assertIsNone(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT count(*) FROM pg_db_role_setting "
                    "WHERE setrole = ("
                    "SELECT oid FROM pg_roles WHERE rolname = 'geno_v2_api_login'"
                    ")"
                )
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT has_table_privilege("
                    "'geno_v2_api_login', 'public.projects', 'SELECT')"
                )
                self.assertFalse(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT has_table_privilege("
                    "'geno_v2_authz_owner', 'public.project_member_invitations', 'SELECT'), "
                    "has_table_privilege("
                    "'geno_v2_authz_owner', "
                    "'public.auth_invitation_redemption_attempts', 'SELECT'), "
                    "has_table_privilege("
                    "'geno_v2_authz_owner', 'public.runtime_sessions', 'SELECT')"
                )
                self.assertEqual(cursor.fetchone(), (True, True, True))

                cursor.execute(
                    "SELECT privilege_type FROM pg_database, "
                    "LATERAL aclexplode(coalesce(datacl, acldefault('d', datdba))) acl "
                    "WHERE datname = current_database() AND acl.grantee = 0 "
                    "ORDER BY privilege_type"
                )
                self.assertEqual(cursor.fetchall(), [])
                cursor.execute(
                    "SELECT has_database_privilege("
                    "'geno_v2_api_login', current_database(), 'CONNECT'), "
                    "has_database_privilege("
                    "'geno_v2_api_login', current_database(), 'TEMPORARY')"
                )
                self.assertEqual(cursor.fetchone(), (True, False))
                cursor.execute(
                    "SELECT defaclobjtype, privilege_type "
                    "FROM pg_default_acl "
                    "JOIN pg_namespace ON pg_namespace.oid = defaclnamespace, "
                    "LATERAL aclexplode(defaclacl) acl "
                    "WHERE nspname = 'public' AND acl.grantee = 0"
                )
                self.assertEqual(cursor.fetchall(), [])

                probe_role = f"geno_v2_grant_probe_{uuid4().hex}"
                cursor.execute(f"CREATE ROLE {probe_role} NOLOGIN")
                try:
                    cursor.execute("SET ROLE geno_v2_api_login")
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        cursor.execute(f"GRANT geno_v2_runtime TO {probe_role}")
                    cursor.execute("RESET ROLE")
                    cursor.execute(
                        "SELECT "
                        "pg_has_role('geno_v2_api_login', "
                        "'geno_v2_authz_owner', 'SET'), "
                        "pg_has_role('geno_v2_api_login', "
                        "'geno_v2_authz_owner', 'USAGE')"
                    )
                    self.assertEqual(cursor.fetchone(), (False, False))
                finally:
                    cursor.execute("RESET ROLE")
                    cursor.execute(f"DROP ROLE IF EXISTS {probe_role}")

    def test_02_composite_foreign_keys_and_canonical_values_reject_bad_rows(self) -> None:
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                    cursor.execute(
                        "INSERT INTO project_members "
                        "(tenant_id, project_id, user_id, role) "
                        "VALUES (%s, %s, %s, 'analyst')",
                        (self.tenant_b, self.project_a1, f"cross-{uuid4()}@example.test"),
                    )
                with self.assertRaises(psycopg.errors.CheckViolation):
                    cursor.execute(
                        "INSERT INTO project_members "
                        "(tenant_id, project_id, user_id, role) "
                        "VALUES (%s, %s, %s, 'owner')",
                        (self.tenant_a, self.project_a1, f"alias-{uuid4()}@example.test"),
                    )
                with self.assertRaises(psycopg.errors.CheckViolation):
                    cursor.execute(
                        "INSERT INTO projects "
                        "(tenant_id, name, market_code, industry_code, target_brand, "
                        "category, prompt_version, status) "
                        "SELECT %s, 'Bad', market_code, industry_code, "
                        "'Brand', 'Category', 'v1', 'deleted' FROM projects WHERE id = %s",
                        (self.tenant_a, self.project_a1),
                    )

    def test_03_forged_gucs_cannot_unlock_any_runtime_table_or_function(self) -> None:
        readable_tables = (
            "market_profiles",
            "industry_profiles",
            "tenants",
            "projects",
            "tenant_members",
            "project_members",
            "audit_events",
        )
        sensitive_tables = (
            "runtime_project_access_grants",
            "project_member_invitations",
            "runtime_sessions",
            "auth_invitation_redemption_attempts",
            "auth_preflight_rate_limits",
            "runtime_session_reauth_queue",
            "auth_runtime_write_controls",
        )
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                self._set_forged_runtime_context(cursor)
                for table_name in readable_tables:
                    with self.subTest(table_name=table_name):
                        cursor.execute(f"SELECT count(*) FROM public.{table_name}")
                        self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute("SELECT * FROM geno_v2_resolve_session_context()")
                self.assertEqual(cursor.fetchall(), [])
                for table_name in sensitive_tables:
                    with self.subTest(sensitive_table_name=table_name):
                        cursor.execute("SAVEPOINT sensitive_table_check")
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            cursor.execute(f"SELECT * FROM public.{table_name} LIMIT 1")
                        cursor.execute("ROLLBACK TO SAVEPOINT sensitive_table_check")
                        cursor.execute("RELEASE SAVEPOINT sensitive_table_check")

                cursor.execute("SAVEPOINT internal_function_check")
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    cursor.execute(
                        "SELECT public.geno_v2_permissions_for_role('super_admin')"
                    )
                cursor.execute("ROLLBACK TO SAVEPOINT internal_function_check")
                cursor.execute("RELEASE SAVEPOINT internal_function_check")
                self._reset_role(cursor)

    def test_04_tenant_grants_sync_for_members_and_project_lifecycle(self) -> None:
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT project_id, canonical_role, permissions "
                    "FROM runtime_project_access_grants "
                    "WHERE source_id = %s ORDER BY project_id",
                    (self.admin_a_member_id,),
                )
                grants = cursor.fetchall()
                self.assertEqual(
                    {row[0] for row in grants},
                    {self.project_a1, self.project_a2, self.project_a3},
                )
                self.assertTrue(all(row[1] == "tenant_admin" for row in grants))
                self.assertTrue(all("audit.read" in row[2] for row in grants))

                cursor.execute(
                    "UPDATE tenant_members SET status = 'disabled' WHERE id = %s",
                    (self.admin_a_member_id,),
                )
                cursor.execute(
                    "SELECT count(*) FROM runtime_project_access_grants WHERE source_id = %s",
                    (self.admin_a_member_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

                cursor.execute(
                    "UPDATE tenant_members SET status = 'active' WHERE id = %s",
                    (self.admin_a_member_id,),
                )
                cursor.execute(
                    "SELECT count(*) FROM runtime_project_access_grants WHERE source_id = %s",
                    (self.admin_a_member_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 3)

                cursor.execute(
                    "UPDATE tenants SET status = 'disabled' WHERE id = %s",
                    (self.tenant_a,),
                )
                cursor.execute(
                    "SELECT count(*) FROM runtime_project_access_grants WHERE tenant_id = %s",
                    (self.tenant_a,),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

                cursor.execute(
                    "UPDATE tenant_members SET role = role WHERE id = %s",
                    (self.admin_a_member_id,),
                )
                cursor.execute(
                    "UPDATE projects SET status = 'paused' WHERE id = %s",
                    (self.project_a3,),
                )
                cursor.execute(
                    "SELECT count(*) FROM runtime_project_access_grants WHERE tenant_id = %s",
                    (self.tenant_a,),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

                cursor.execute(
                    "UPDATE tenants SET status = 'active' WHERE id = %s",
                    (self.tenant_a,),
                )
                cursor.execute(
                    "SELECT count(*) FROM runtime_project_access_grants WHERE source_id = %s",
                    (self.admin_a_member_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 3)

                cursor.execute(
                    "UPDATE projects SET status = 'archived' WHERE id = %s",
                    (self.project_a3,),
                )
                cursor.execute(
                    "SELECT count(*) FROM runtime_project_access_grants "
                    "WHERE source_id = %s AND project_id = %s",
                    (self.admin_a_member_id, self.project_a3),
                )
                self.assertEqual(cursor.fetchone()[0], 0)

                cursor.execute(
                    "UPDATE projects SET status = 'paused' WHERE id = %s",
                    (self.project_a3,),
                )
                cursor.execute(
                    "SELECT count(*) FROM runtime_project_access_grants "
                    "WHERE source_id = %s AND project_id = %s",
                    (self.admin_a_member_id, self.project_a3),
                )
                self.assertEqual(cursor.fetchone()[0], 1)

    def test_05_audit_supports_three_scopes_and_is_immutable(self) -> None:
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, tenant_id, project_id FROM audit_events "
                    "WHERE id = ANY(%s) ORDER BY id",
                    (
                        [
                            self.audit_global_a,
                            self.audit_tenant_a,
                            self.audit_project_a1,
                        ],
                    ),
                )
                rows = cursor.fetchall()
                self.assertEqual(
                    {(row[1], row[2]) for row in rows},
                    {
                        (None, None),
                        (self.tenant_a, None),
                        (self.tenant_a, self.project_a1),
                    },
                )

                with self.assertRaises(psycopg.errors.CheckViolation):
                    cursor.execute(
                        "INSERT INTO audit_events "
                        "(tenant_id, project_id, event_type, actor_type, actor_id, "
                        "target_type, target_id) "
                        "VALUES (NULL, %s, 'bad.scope', 'system', 'test', 'test', 'bad')",
                        (self.project_a1,),
                    )

                with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                    cursor.execute(
                        "INSERT INTO audit_events "
                        "(tenant_id, event_type, actor_type, actor_id, target_type, target_id) "
                        "VALUES (%s, 'bad.tenant', 'system', 'test', 'test', 'bad')",
                        (uuid4(),),
                    )

                for statement in (
                    "UPDATE audit_events SET reason = 'changed' WHERE id = %s",
                    "DELETE FROM audit_events WHERE id = %s",
                ):
                    with self.subTest(statement=statement):
                        with self.assertRaises(
                            psycopg.errors.ObjectNotInPrerequisiteState
                        ) as raised:
                            cursor.execute(statement, (self.audit_global_a,))
                        self.assertEqual(raised.exception.sqlstate, "55000")
                        self.assertIn("audit_events rows are immutable", str(raised.exception))

    def test_06_session_hash_is_the_only_read_authorization_context(self) -> None:
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET ROLE geno_v2_api_login")

                self._begin_runtime_transaction(cursor)
                cursor.execute(
                    "SELECT set_config('app.session_token_hash', %s, true), "
                    "set_config('app.actor_id', %s, true), "
                    "set_config('app.tenant_id', %s, true), "
                    "set_config('app.project_ids', %s, true), "
                    "set_config('app.roles', 'super_admin,system', true)",
                    (
                        self.valid_session_hash,
                        self.admin_b,
                        str(self.tenant_b),
                        str(self.project_b1),
                    ),
                )
                cursor.execute("SELECT * FROM geno_v2_resolve_session_context()")
                resolver_rows = cursor.fetchall()
                self.assertEqual(
                    tuple(column.name for column in cursor.description or ()),
                    (
                        "session_id",
                        "actor_id",
                        "tenant_id",
                        "project_ids",
                        "tenant_roles",
                        "project_scopes",
                    ),
                )
                self.assertEqual(len(resolver_rows), 1)
                self.assertEqual(resolver_rows[0][0], self.valid_session_id)
                self.assertEqual(resolver_rows[0][1], self.admin_a)
                self.assertEqual(resolver_rows[0][2], self.tenant_a)
                cursor.execute("SELECT id FROM projects ORDER BY id")
                self.assertEqual(
                    {row[0] for row in cursor.fetchall()},
                    {self.project_a1, self.project_a2, self.project_a3},
                )
                cursor.execute("SELECT id FROM tenants")
                self.assertEqual(cursor.fetchall(), [(self.tenant_a,)])
                cursor.execute("SELECT user_id, project_id FROM project_members")
                self.assertEqual(
                    set(cursor.fetchall()),
                    {
                        (self.admin_a, self.project_a1),
                        (self.multi_actor, self.project_a1),
                        (self.multi_actor, self.project_a2),
                        (self.viewer_actor, self.project_a1),
                    },
                )
                cursor.execute("COMMIT")

                self._begin_runtime_transaction(cursor)
                cursor.execute("SELECT count(*) FROM projects")
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute("COMMIT")

                for invalid_hash in (
                    "",
                    "not-a-sha256",
                    "f" * 64,
                    self.expired_session_hash,
                    self.revoked_session_hash,
                    self.future_session_hash,
                ):
                    with self.subTest(invalid_hash=invalid_hash):
                        self._begin_runtime_transaction(cursor)
                        cursor.execute(
                            "SELECT set_config('app.session_token_hash', %s, true)",
                            (invalid_hash,),
                        )
                        cursor.execute("SELECT * FROM geno_v2_resolve_session_context()")
                        self.assertEqual(cursor.fetchall(), [])
                        cursor.execute("SELECT count(*) FROM projects")
                        self.assertEqual(cursor.fetchone()[0], 0)
                        cursor.execute("COMMIT")

                self._begin_runtime_transaction(cursor)
                cursor.execute(
                    "SELECT set_config('app.session_token_hash', %s, true)",
                    (self.viewer_session_hash,),
                )
                cursor.execute("SELECT user_id, project_id FROM project_members")
                self.assertEqual(
                    cursor.fetchall(),
                    [(self.viewer_actor, self.project_a1)],
                )
                cursor.execute("COMMIT")

                self._begin_runtime_transaction(cursor)
                cursor.execute(
                    "SELECT set_config('app.session_token_hash', %s, true)",
                    (self.valid_session_hash,),
                )
                cursor.execute("SELECT count(*) FROM projects")
                self.assertEqual(cursor.fetchone()[0], 3)
                cursor.execute("ROLLBACK")
                self._begin_runtime_transaction(cursor)
                cursor.execute("SELECT count(*) FROM projects")
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute("COMMIT")

                self._begin_runtime_transaction(cursor)
                cursor.execute(
                    "SELECT set_config('app.session_token_hash', %s, true)",
                    (self.cross_tenant_session_hash,),
                )
                cursor.execute("SELECT id, tenant_id FROM projects")
                self.assertEqual(cursor.fetchall(), [(self.project_b1, self.tenant_b)])
                cursor.execute("COMMIT")

                cursor.execute("RESET ROLE")
                cursor.execute(
                    "UPDATE tenants SET status = 'disabled' WHERE id = %s",
                    (self.tenant_b,),
                )
                cursor.execute("SET ROLE geno_v2_api_login")
                self._begin_runtime_transaction(cursor)
                cursor.execute(
                    "SELECT set_config('app.session_token_hash', %s, true)",
                    (self.cross_tenant_session_hash,),
                )
                cursor.execute("SELECT * FROM geno_v2_resolve_session_context()")
                self.assertEqual(cursor.fetchall(), [])
                cursor.execute("COMMIT")
                cursor.execute("RESET ROLE")
                cursor.execute(
                    "UPDATE tenants SET status = 'active' WHERE id = %s",
                    (self.tenant_b,),
                )

    def test_07_session_snapshot_update_and_lineage_fail_closed(self) -> None:
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM auth_invitation_redemption_attempts AS attempt "
                    "JOIN project_member_invitations AS invitation "
                    "ON invitation.id = attempt.invitation_id "
                    "WHERE attempt.status = 'failed' AND invitation.status = 'accepted' "
                    "AND invitation.accepted_by_attempt_id <> attempt.id"
                )
                self.assertGreaterEqual(cursor.fetchone()[0], 6)
                cursor.execute(
                    "SELECT status FROM runtime_sessions WHERE id = %s",
                    (self.revoked_session_id,),
                )
                self.assertEqual(cursor.fetchone()[0], "revoked")
                negative_session_inserts = (
                    (
                        "missing-project",
                        "INSERT INTO runtime_sessions ("
                        "id, session_token_hash, actor_id, tenant_id, project_ids, roles, "
                        "permissions, tenant_roles, project_scopes, redemption_attempt_id, "
                        "issued_by, issued_at, expires_at, metadata) "
                        "SELECT %s, %s, actor_id, tenant_id, "
                        "jsonb_build_array(project_ids->0), roles, permissions, tenant_roles, "
                        "jsonb_build_array(project_scopes->0), %s, 'negative-test', "
                        "issued_at, expires_at, metadata FROM runtime_sessions WHERE id = %s",
                    ),
                    (
                        "duplicate-flat-role",
                        "INSERT INTO runtime_sessions ("
                        "id, session_token_hash, actor_id, tenant_id, project_ids, roles, "
                        "permissions, tenant_roles, project_scopes, redemption_attempt_id, "
                        "issued_by, issued_at, expires_at, metadata) "
                        "SELECT %s, %s, actor_id, tenant_id, project_ids, roles || roles, "
                        "permissions, tenant_roles, project_scopes, %s, 'negative-test', "
                        "issued_at, expires_at, metadata FROM runtime_sessions WHERE id = %s",
                    ),
                    (
                        "wrong-project-role",
                        "INSERT INTO runtime_sessions ("
                        "id, session_token_hash, actor_id, tenant_id, project_ids, roles, "
                        "permissions, tenant_roles, project_scopes, redemption_attempt_id, "
                        "issued_by, issued_at, expires_at, metadata) "
                        "SELECT %s, %s, actor_id, tenant_id, project_ids, roles, permissions, "
                        "tenant_roles, jsonb_set(project_scopes, '{0,roles}', "
                        "'[\"super_admin\"]'::jsonb), %s, 'negative-test', "
                        "issued_at, expires_at, metadata FROM runtime_sessions WHERE id = %s",
                    ),
                )
                for case_name, insert_statement in negative_session_inserts:
                    marker = uuid4().hex
                    invitation_id = uuid4()
                    attempt_id = uuid4()
                    session_id = uuid4()
                    cursor.execute("BEGIN")
                    cursor.execute(
                        "INSERT INTO project_member_invitations ("
                        "id, tenant_id, project_id, email, role, invite_token_hash, audience, "
                        "allowed_surfaces, invited_by, expires_at) "
                        "VALUES (%s, %s, %s, %s, 'analyst', %s, 'admin', "
                        "ARRAY['admin'], 'negative-test', %s)",
                        (
                            invitation_id,
                            self.tenant_a,
                            self.project_a1,
                            f"snapshot-{marker}@example.test",
                            hashlib.sha256(f"invite-{marker}".encode("utf-8")).hexdigest(),
                            datetime.now(UTC) + timedelta(days=1),
                        ),
                    )
                    cursor.execute(
                        "INSERT INTO auth_invitation_redemption_attempts ("
                        "id, tenant_id, project_id, invitation_id, requested_surface, "
                        "idempotency_key_hash, request_hash, token_fingerprint, "
                        "session_id, status) "
                        "VALUES (%s, %s, %s, %s, 'admin', %s, %s, %s, %s, 'succeeded')",
                        (
                            attempt_id,
                            self.tenant_a,
                            self.project_a1,
                            invitation_id,
                            hashlib.sha256(f"idem-{marker}".encode("utf-8")).hexdigest(),
                            hashlib.sha256(f"request-{marker}".encode("utf-8")).hexdigest(),
                            hashlib.sha256(f"invite-{marker}".encode("utf-8")).hexdigest(),
                            session_id,
                        ),
                    )
                    with self.subTest(case_name=case_name):
                        with self.assertRaises(psycopg.errors.CheckViolation):
                            cursor.execute(
                                insert_statement,
                                (
                                    session_id,
                                    hashlib.sha256(
                                        f"session-{marker}".encode("utf-8")
                                    ).hexdigest(),
                                    attempt_id,
                                    self.valid_session_id,
                                ),
                            )
                    cursor.execute("ROLLBACK")

                for update_statement, params in (
                    (
                        "UPDATE runtime_sessions SET actor_id = %s WHERE id = %s",
                        (self.admin_b, self.valid_session_id),
                    ),
                    (
                        "UPDATE runtime_sessions SET status = 'active', revoked_at = NULL, "
                        "revoked_by = NULL, revoke_reason = NULL WHERE id = %s",
                        (self.revoked_session_id,),
                    ),
                ):
                    with self.subTest(update_statement=update_statement):
                        with self.assertRaises(
                            psycopg.errors.ObjectNotInPrerequisiteState
                        ):
                            cursor.execute(update_statement, params)

        bad_invitation_id = uuid4()
        bad_attempt_id = uuid4()
        bad_session_id = uuid4()
        marker = uuid4().hex
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO project_member_invitations ("
                    "id, tenant_id, project_id, email, role, invite_token_hash, audience, "
                    "allowed_surfaces, invited_by, expires_at) "
                    "VALUES (%s, %s, %s, %s, 'analyst', %s, 'admin', "
                    "ARRAY['admin'], 'negative-test', %s)",
                    (
                        bad_invitation_id,
                        self.tenant_a,
                        self.project_a1,
                        f"lineage-{marker}@example.test",
                        hashlib.sha256(f"invite-{marker}".encode("utf-8")).hexdigest(),
                        datetime.now(UTC) + timedelta(days=1),
                    ),
                )
                cursor.execute(
                    "INSERT INTO auth_invitation_redemption_attempts ("
                    "id, tenant_id, project_id, invitation_id, requested_surface, "
                    "idempotency_key_hash, request_hash, token_fingerprint) "
                    "VALUES (%s, %s, %s, %s, 'admin', %s, %s, %s)",
                    (
                        bad_attempt_id,
                        self.tenant_a,
                        self.project_a1,
                        bad_invitation_id,
                        hashlib.sha256(f"idem-{marker}".encode("utf-8")).hexdigest(),
                        hashlib.sha256(f"request-{marker}".encode("utf-8")).hexdigest(),
                        hashlib.sha256(f"invite-{marker}".encode("utf-8")).hexdigest(),
                    ),
                )
                cursor.execute(
                    "INSERT INTO runtime_sessions ("
                    "id, session_token_hash, actor_id, tenant_id, project_ids, roles, "
                    "permissions, tenant_roles, project_scopes, redemption_attempt_id, "
                    "issued_by, issued_at, expires_at, metadata) "
                    "SELECT %s, %s, actor_id, tenant_id, project_ids, roles, permissions, "
                    "tenant_roles, project_scopes, %s, 'negative-lineage', issued_at, "
                    "expires_at, metadata FROM runtime_sessions WHERE id = %s",
                    (
                        bad_session_id,
                        hashlib.sha256(f"session-{marker}".encode("utf-8")).hexdigest(),
                        bad_attempt_id,
                        self.valid_session_id,
                    ),
                )
                with self.assertRaises(psycopg.IntegrityError):
                    connection.commit()
                connection.rollback()

    def test_08_auth_lineage_rejects_cross_scope_and_state_splicing(self) -> None:
        attack_cases = (
            {
                "name": "cross-tenant",
                "tenant_id": self.tenant_a,
                "project_id": self.project_a1,
                "email": self.admin_b,
                "role": "analyst",
                "surface": "admin",
                "session_source_id": self.cross_tenant_session_id,
                "error": "auth lineage session identity or policy mismatch",
            },
            {
                "name": "actor",
                "tenant_id": self.tenant_a,
                "project_id": self.project_a1,
                "email": self.multi_actor,
                "role": "analyst",
                "surface": "admin",
                "session_source_id": self.valid_session_id,
                "error": "auth lineage session identity or policy mismatch",
            },
            {
                "name": "project",
                "tenant_id": self.tenant_a,
                "project_id": self.project_a2,
                "email": self.viewer_actor,
                "role": "client_viewer",
                "surface": "customer",
                "session_source_id": self.viewer_session_id,
                "error": "auth lineage project or portal scope mismatch",
            },
            {
                "name": "surface",
                "tenant_id": self.tenant_a,
                "project_id": self.project_a1,
                "email": self.admin_a,
                "role": "analyst",
                "surface": "admin",
                "attempt_surface": "customer",
                "session_source_id": self.valid_session_id,
                "error": "auth lineage requested surface is not allowed",
            },
            {
                "name": "status",
                "tenant_id": self.tenant_a,
                "project_id": self.project_a1,
                "email": self.admin_a,
                "role": "analyst",
                "surface": "admin",
                "attempt_status": "preparing",
                "session_source_id": None,
                "error": "auth lineage accepted and succeeded state is not exact",
            },
            {
                "name": "token",
                "tenant_id": self.tenant_a,
                "project_id": self.project_a1,
                "email": self.admin_a,
                "role": "analyst",
                "surface": "admin",
                "wrong_token": True,
                "session_source_id": self.valid_session_id,
                "error": "auth lineage invitation token fingerprint mismatch",
            },
            {
                "name": "role",
                "tenant_id": self.tenant_a,
                "project_id": self.project_a1,
                "email": self.admin_a,
                "role": "reviewer",
                "surface": "admin",
                "session_source_id": self.valid_session_id,
                "error": "auth lineage project or portal scope mismatch",
            },
            {
                "name": "timeline",
                "tenant_id": self.tenant_a,
                "project_id": self.project_a1,
                "email": self.admin_a,
                "role": "analyst",
                "surface": "admin",
                "session_after_invitation_expiry": True,
                "session_source_id": self.valid_session_id,
                "error": "auth lineage issuance timeline is invalid",
            },
        )

        for attack in attack_cases:
            with self.subTest(attack=attack["name"]):
                marker = uuid4().hex
                invitation_id = uuid4()
                attempt_id = uuid4()
                session_id = uuid4()
                token_hash = hashlib.sha256(
                    f"lineage-token-{marker}".encode("utf-8")
                ).hexdigest()
                now = datetime.now(UTC)
                invitation_created_at = now - timedelta(seconds=2)
                attempt_created_at = now - timedelta(seconds=1)
                invitation_expires_at = now + timedelta(days=1)
                session_issued_at = now
                session_expires_at = now + timedelta(days=1)
                if attack.get("session_after_invitation_expiry"):
                    session_issued_at = now + timedelta(days=2)
                    session_expires_at = now + timedelta(days=3)
                attempt_status = attack.get("attempt_status", "succeeded")
                linked_session_id = session_id if attempt_status == "succeeded" else None
                session_source_id = attack["session_source_id"]
                audience = attack["surface"]
                attempt_surface = attack.get("attempt_surface", audience)
                token_fingerprint = (
                    hashlib.sha256(f"wrong-token-{marker}".encode("utf-8")).hexdigest()
                    if attack.get("wrong_token")
                    else token_hash
                )

                with psycopg.connect() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "INSERT INTO project_member_invitations ("
                            "id, tenant_id, project_id, email, role, status, "
                            "invite_token_hash, audience, allowed_surfaces, invited_by, "
                            "accepted_by_attempt_id, expires_at, accepted_at, created_at) "
                            "VALUES (%s, %s, %s, %s, %s, 'accepted', %s, %s, "
                            "ARRAY[%s]::text[], 'lineage-attack-test', %s, %s, %s, %s)",
                            (
                                invitation_id,
                                attack["tenant_id"],
                                attack["project_id"],
                                attack["email"],
                                attack["role"],
                                token_hash,
                                audience,
                                audience,
                                attempt_id,
                                invitation_expires_at,
                                now,
                                invitation_created_at,
                            ),
                        )
                        cursor.execute(
                            "INSERT INTO auth_invitation_redemption_attempts ("
                            "id, tenant_id, project_id, invitation_id, requested_surface, "
                            "idempotency_key_hash, request_hash, token_fingerprint, "
                            "session_id, status, created_at) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                            (
                                attempt_id,
                                attack["tenant_id"],
                                attack["project_id"],
                                invitation_id,
                                attempt_surface,
                                hashlib.sha256(
                                    f"lineage-idempotency-{marker}".encode("utf-8")
                                ).hexdigest(),
                                hashlib.sha256(
                                    f"lineage-request-{marker}".encode("utf-8")
                                ).hexdigest(),
                                token_fingerprint,
                                linked_session_id,
                                attempt_status,
                                attempt_created_at,
                            ),
                        )
                        if session_source_id is not None:
                            cursor.execute(
                                "INSERT INTO runtime_sessions ("
                                "id, session_token_hash, actor_id, tenant_id, project_ids, "
                                "roles, permissions, tenant_roles, project_scopes, "
                                "redemption_attempt_id, issued_by, issued_at, expires_at, "
                                "metadata) SELECT %s, %s, actor_id, tenant_id, project_ids, "
                                "roles, permissions, tenant_roles, project_scopes, %s, "
                                "'lineage-attack-test', %s, %s, metadata "
                                "FROM runtime_sessions WHERE id = %s",
                                (
                                    session_id,
                                    hashlib.sha256(
                                        f"lineage-session-{marker}".encode("utf-8")
                                    ).hexdigest(),
                                    attempt_id,
                                    session_issued_at,
                                    session_expires_at,
                                    session_source_id,
                                ),
                            )
                        with self.assertRaises(psycopg.errors.CheckViolation) as raised:
                            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                        self.assertIn(attack["error"], str(raised.exception))
                        connection.rollback()


@unittest.skipUnless(BEHAVIOR_TEST_ENABLED, "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2TenancySeedAdapterPostgresBehaviorTest(unittest.TestCase):
    def test_logical_rebuild_replays_and_conflicts_remain_atomic(self) -> None:
        unique = uuid4().hex

        def build(owner_user_id: str):
            return build_project_bootstrap(
                tenant_name=f"Seed Tenant {unique}",
                project_name=f"Seed Project {unique}",
                target_brand="Seed Brand",
                category="Seed Category",
                market_code=f"SEED-{unique}",
                market_name="Seed Market",
                locale="en-AU",
                timezone="Australia/Sydney",
                currency="AUD",
                primary_language="English",
                industry_code=f"seed_{unique}",
                industry_name="Seed Industry",
                competitors=("Seed Competitor",),
                owner_user_id=owner_user_id,
            )

        first_bootstrap = build("Owner@Example.TEST")
        replay_bootstrap = build("owner@example.test")
        self.assertNotEqual(first_bootstrap.members[0].id, replay_bootstrap.members[0].id)
        self.assertNotEqual(first_bootstrap.project.created_at, replay_bootstrap.project.created_at)

        first_seed = translate_project_bootstrap_to_v2_seed(first_bootstrap)
        replay_seed = translate_project_bootstrap_to_v2_seed(replay_bootstrap)
        self.assertEqual(first_seed, replay_seed)

        with psycopg.connect() as connection:
            PrivilegedSchemaV2TenancyRepository(connection).save(first_seed)
        created_at_query = (
            "SELECT "
            "(SELECT created_at FROM tenants WHERE id = %s), "
            "(SELECT created_at FROM projects WHERE id = %s), "
            "(SELECT created_at FROM project_members WHERE id = %s), "
            "(SELECT created_at FROM audit_events WHERE id = %s)"
        )
        identity_params = (
            first_seed.tenant.id,
            first_seed.project.id,
            first_seed.project_members[0].id,
            first_seed.audit_events[0].id,
        )
        with psycopg.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(created_at_query, identity_params)
                first_created_at = cursor.fetchone()

        with psycopg.connect() as connection:
            PrivilegedSchemaV2TenancyRepository(connection).save(replay_seed)
            with connection.cursor() as cursor:
                cursor.execute(created_at_query, identity_params)
                self.assertEqual(cursor.fetchone(), first_created_at)
                cursor.execute(
                    "SELECT user_id, role FROM project_members WHERE id = %s",
                    (first_seed.project_members[0].id,),
                )
                self.assertEqual(cursor.fetchone(), ("owner@example.test", "project_owner"))
                cursor.execute(
                    "SELECT actor_id FROM audit_events WHERE id = %s",
                    (first_seed.audit_events[0].id,),
                )
                self.assertEqual(cursor.fetchone(), ("owner@example.test",))

        conflicting_seed = replace(
            replay_seed,
            project=replace(replay_seed.project, status="active"),
        )
        with psycopg.connect() as connection:
            with self.assertRaises(SchemaV2TenancySeedConflictError):
                PrivilegedSchemaV2TenancyRepository(connection).save(conflicting_seed)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status FROM projects WHERE id = %s",
                    (first_seed.project.id,),
                )
                self.assertEqual(cursor.fetchone(), ("paused",))

        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                    cursor.execute(
                        "UPDATE audit_events SET reason = 'changed' WHERE id = %s",
                        (first_seed.audit_events[0].id,),
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
