from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from uuid import UUID, uuid4

import psycopg


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
                "DROP TABLE IF EXISTS audit_events, runtime_project_access_grants, "
                "project_members, tenant_members, projects, industry_profiles, "
                "market_profiles, tenants CASCADE"
            )
            for signature in (
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

        extension_only_install = self._run_runner("install")
        self.assertEqual(
            extension_only_install.returncode,
            0,
            extension_only_install.stdout + extension_only_install.stderr,
        )

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
        cls.admin_a_member_id = uuid4()
        cls.audit_global_a = uuid4()
        cls.audit_global_b = uuid4()
        cls.audit_tenant_a = uuid4()
        cls.audit_project_a1 = uuid4()
        cls.audit_project_a3 = uuid4()
        cls.audit_project_b1 = uuid4()

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
                    (cls.project_a1, cls.tenant_a, cls.multi_actor, "project_owner"),
                    (cls.project_a2, cls.tenant_a, cls.multi_actor, "analyst"),
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

    def _set_forged_runtime_context(self, cursor: psycopg.Cursor[object]) -> None:
        cursor.execute("RESET ROLE")
        cursor.execute("RESET ALL")
        cursor.execute(
            "SELECT set_config('app.actor_id', %s, false), "
            "set_config('app.tenant_id', %s, false), "
            "set_config('app.project_id', %s, false), "
            "set_config('app.project_ids', %s, false), "
            "set_config('app.roles', %s, false)",
            (
                self.admin_a,
                str(self.tenant_a),
                str(self.project_a1),
                ",".join(str(value) for value in (self.project_a1, self.project_a2)),
                "super_admin,system,worker",
            ),
        )
        cursor.execute("SET ROLE geno_v2_runtime")

    def _reset_role(self, cursor: psycopg.Cursor[object]) -> None:
        cursor.execute("RESET ROLE")
        cursor.execute("RESET ALL")

    def test_01_roles_rls_policies_and_privileges_are_exact(self) -> None:
        expected_tables = {
            "market_profiles",
            "industry_profiles",
            "tenants",
            "projects",
            "tenant_members",
            "project_members",
            "runtime_project_access_grants",
            "audit_events",
        }
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                    "rolreplication, rolbypassrls FROM pg_roles "
                    "WHERE rolname IN ('geno_v2_runtime', 'geno_v2_authz_owner') "
                    "ORDER BY rolname"
                )
                role_rows = cursor.fetchall()
                self.assertEqual(
                    role_rows,
                    [
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
                    "SELECT tablename FROM pg_policies "
                    "WHERE schemaname = 'public' AND tablename = ANY(%s)",
                    (list(expected_tables),),
                )
                self.assertEqual(cursor.fetchall(), [])

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
                        self.assertEqual(cursor.fetchone(), (False, False, False, False))

                cursor.execute(
                    "SELECT has_schema_privilege('geno_v2_runtime', 'public', 'USAGE')"
                )
                self.assertFalse(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT proname, "
                    "has_function_privilege('geno_v2_runtime', pg_proc.oid, 'EXECUTE') "
                    "FROM pg_proc JOIN pg_namespace ON pg_namespace.oid = pronamespace "
                    "WHERE nspname = 'public' AND proname LIKE 'geno_v2_%' "
                    "ORDER BY proname"
                )
                function_acl_rows = cursor.fetchall()
                self.assertEqual(len(function_acl_rows), 6)
                self.assertTrue(all(not row[1] for row in function_acl_rows))

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
                    },
                )
                self.assertTrue(all(row[3] == ["search_path=pg_catalog"] for row in function_rows))

                cursor.execute(
                    "SELECT count(*) FROM pg_auth_members WHERE roleid IN ("
                    "SELECT oid FROM pg_roles WHERE rolname IN "
                    "('geno_v2_runtime', 'geno_v2_authz_owner')) OR member IN ("
                    "SELECT oid FROM pg_roles WHERE rolname IN "
                    "('geno_v2_runtime', 'geno_v2_authz_owner'))"
                )
                self.assertEqual(cursor.fetchone()[0], 0)

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
        expected_tables = (
            "market_profiles",
            "industry_profiles",
            "tenants",
            "projects",
            "tenant_members",
            "project_members",
            "runtime_project_access_grants",
            "audit_events",
        )
        with psycopg.connect(autocommit=True) as connection:
            with connection.cursor() as cursor:
                self._set_forged_runtime_context(cursor)
                for table_name in expected_tables:
                    with self.subTest(table_name=table_name):
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            cursor.execute(f"SELECT * FROM public.{table_name} LIMIT 1")

                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    cursor.execute(
                        "SELECT public.geno_v2_permissions_for_role('super_admin')"
                    )
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
