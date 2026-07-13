from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.schema_v2_runner import (
    ADVISORY_LOCK_NAME,
    EXPECTED_DATABASE_NAME,
    EXPECTED_SCHEMA_GENERATION,
    SchemaV2Error,
    _acquire_advisory_lock,
    _connect_deadline_seconds,
    _connect_with_retry,
    _nonnegative_finite_seconds,
    _unexpected_public_objects,
    _validate_pg_environment,
    compute_baseline_hash,
    ensure_app_compatible,
    load_manifest,
)

try:
    import yaml
except ImportError:  # pragma: no cover - the CI image provides PyYAML.
    yaml = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "infra/db/schema-v2"
COMPOSE_USER = "geno_v2_contract_installer"
COMPOSE_PASSWORD = "V2ContractToken_7qB8N5vR3mK9xT2wC6pL4sH1"


class _TryLockCursor:
    def __init__(self, results: list[bool]) -> None:
        self.results = list(results)
        self.statements: list[str] = []

    def execute(self, statement: str, _params: object) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[bool]:
        return (self.results.pop(0),)


class _CatalogCursor:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows
        self.statement = ""

    def execute(self, statement: str) -> None:
        self.statement = statement

    def fetchall(self) -> list[tuple[str, str]]:
        return self.rows


class _NeverConnectDriver:
    class OperationalError(Exception):
        pass

    @classmethod
    def connect(cls, *, connect_timeout: int) -> None:
        raise AssertionError("timeout validation must run before connect")


class _ConvergingConnectDriver:
    class OperationalError(Exception):
        pass

    def __init__(self, clock: list[float]) -> None:
        self.clock = clock
        self.connect_timeouts: list[int] = []
        self.result = object()

    def connect(self, *, connect_timeout: int) -> object:
        self.connect_timeouts.append(connect_timeout)
        if len(self.connect_timeouts) < 3:
            self.clock[0] += 2.0
            raise self.OperationalError("simulated black-hole timeout")
        return self.result


class SchemaV2ManifestContractsTest(unittest.TestCase):
    def test_manifest_pins_the_ordered_bootstrap_and_its_baseline_hash(self) -> None:
        manifest = load_manifest(SCHEMA_ROOT)

        self.assertEqual(manifest.schema_generation, EXPECTED_SCHEMA_GENERATION)
        self.assertEqual(manifest.database_name, EXPECTED_DATABASE_NAME)
        self.assertEqual(manifest.baseline_version, "2.0.0-b2")
        self.assertEqual(manifest.minimum_app_version, "0.1.0")
        self.assertEqual(
            [item.path for item in manifest.baseline_files],
            [
                "baseline/0000_extensions_roles.sql",
                "baseline/0010_tenancy_project_rls.sql",
                "baseline/0011_auth_session_context.sql",
                "baseline/0012_auth_state_guards.sql",
                "baseline/0013_auth_commands.sql",
                "baseline/0014_auth_login_provision.sql",
                "baseline/0020_collection_geo_scoring.sql",
                "baseline/0021_worker_login_provision.sql",
                "baseline/0030_knowledge_pipeline.sql",
            ],
        )
        self.assertEqual(manifest.migration_files, ())
        self.assertEqual(manifest.baseline_hash, compute_baseline_hash(manifest.baseline_files))

    def test_loader_fails_closed_when_a_listed_sql_file_drifts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            copied_root = Path(temp_dir) / "schema-v2"
            shutil.copytree(SCHEMA_ROOT, copied_root)
            bootstrap = copied_root / "baseline/0000_extensions_roles.sql"
            bootstrap.write_text(
                bootstrap.read_text(encoding="utf-8") + "\n-- drift\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SchemaV2Error, "checksum drift"):
                load_manifest(copied_root)

    def test_manifest_does_not_reference_the_schema_v1_chain(self) -> None:
        payload = json.loads((SCHEMA_ROOT / "manifest.json").read_text(encoding="utf-8"))
        paths = [entry["path"] for entry in payload["baseline_files"]]
        paths.extend(entry["path"] for entry in payload["migration_files"])

        self.assertTrue((ROOT / "infra/db/migrations/up/0001_init.sql").is_file())
        self.assertTrue((ROOT / "infra/db/migrations/up/0030_auth_session_scope_v2.sql").is_file())
        self.assertTrue(all(path.startswith(("baseline/", "migrations/")) for path in paths))
        self.assertTrue(all("infra/db/migrations" not in path for path in paths))

    def test_application_minimum_version_is_enforced(self) -> None:
        ensure_app_compatible(app_version="0.1.0", minimum_app_version="0.1.0")
        ensure_app_compatible(app_version="0.2.0", minimum_app_version="0.1.0")
        with self.assertRaisesRegex(SchemaV2Error, "older than required"):
            ensure_app_compatible(app_version="0.0.9", minimum_app_version="0.1.0")

    def test_database_name_cannot_be_overridden_in_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            copied_root = Path(temp_dir) / "schema-v2"
            shutil.copytree(SCHEMA_ROOT, copied_root)
            manifest_path = copied_root / "manifest.json"
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["database_name"] = "another_database"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(SchemaV2Error, "must remain fixed at 'geno_v2'"):
                load_manifest(copied_root)


class SchemaV2SqlContractsTest(unittest.TestCase):
    def test_bootstrap_creates_strict_metadata_and_checksum_ledger(self) -> None:
        sql = (SCHEMA_ROOT / "baseline/0000_extensions_roles.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", sql)
        self.assertIn("CREATE TABLE app_schema_metadata", sql)
        self.assertIn("schema_generation smallint PRIMARY KEY", sql)
        self.assertIn("CHECK (schema_generation = 2)", sql)
        self.assertIn("baseline_hash text NOT NULL", sql)
        self.assertIn("CREATE TABLE schema_migration_ledger", sql)
        self.assertIn("migration_id text PRIMARY KEY", sql)
        self.assertIn("checksum text NOT NULL", sql)
        self.assertIn("app_commit text NOT NULL", sql)
        self.assertIn("CREATE TRIGGER schema_migration_ledger_immutable", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON schema_migration_ledger", sql)

    def test_tenancy_baseline_is_clean_canonical_and_fail_closed(self) -> None:
        sql = (SCHEMA_ROOT / "baseline/0010_tenancy_project_rls.sql").read_text(
            encoding="utf-8"
        )

        for forbidden in (
            "uuid_generate_v4",
            "CREATE ROLE geno_v2_runtime LOGIN",
            "CREATE ROLE geno_v2_authz_owner LOGIN",
            "PASSWORD '",
            "CREATE ROLE geno_v2_api_login LOGIN",
            "ALTER ROLE geno_v2_api_login LOGIN",
            "CONCURRENTLY",
            "quarantine",
            "FROM public.runtime_sessions",
            "FROM public.project_member_invitations",
            "current_setting('app.",
            "CREATE POLICY",
            "GRANT SELECT ON market_profiles",
            "GRANT EXECUTE ON FUNCTION",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, sql)

        self.assertIn("DEFAULT gen_random_uuid()", sql)
        self.assertIn("NOLOGIN NOSUPERUSER", sql)
        self.assertIn("NOREPLICATION NOBYPASSRLS", sql)
        self.assertIn("NOREPLICATION BYPASSRLS", sql)
        self.assertIn("REVOKE CREATE ON SCHEMA public FROM PUBLIC", sql)
        self.assertIn("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC", sql)
        self.assertIn("FOREIGN KEY (project_id, tenant_id)", sql)
        self.assertIn("REFERENCES projects(id, tenant_id)", sql)
        self.assertIn("CHECK (role IN ('super_admin', 'tenant_admin'))", sql)
        self.assertIn("'project_owner', 'analyst', 'reviewer'", sql)
        self.assertIn("pg_catalog.pg_auth_members", sql)
        self.assertIn("unauthorized role membership", sql)
        self.assertIn("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY", sql)
        self.assertIn("CREATE TRIGGER tenant_members_sync_project_grants", sql)
        self.assertIn("CREATE TRIGGER projects_sync_tenant_grants", sql)
        self.assertIn("CREATE TRIGGER tenants_sync_status_grants", sql)
        self.assertIn("CREATE TRIGGER audit_events_immutable", sql)
        self.assertIn("FOREIGN KEY (tenant_id) REFERENCES tenants(id)", sql)

        readme = (SCHEMA_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("defines no runtime policies", readme)
        self.assertIn("session_token_hash", readme)
        self.assertIn("0013_auth_commands.sql", readme)
        self.assertIn("nine reviewed auth command entry", readme)

    def test_auth_context_accepts_only_session_hash_and_exposes_read_only_runtime(self) -> None:
        sql = (SCHEMA_ROOT / "baseline/0011_auth_session_context.sql").read_text(
            encoding="utf-8"
        )

        for table_name in (
            "project_member_invitations",
            "runtime_sessions",
            "auth_invitation_redemption_attempts",
            "auth_preflight_rate_limits",
            "runtime_session_reauth_queue",
            "auth_runtime_write_controls",
        ):
            with self.subTest(table_name=table_name):
                self.assertIn(f"CREATE TABLE {table_name}", sql)
                self.assertIn(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY", sql)

        for forbidden in (
            "current_setting('app.actor_id",
            "current_setting('app.tenant_id",
            "current_setting('app.project_id",
            "current_setting('app.project_ids",
            "current_setting('app.roles",
            "PASSWORD '",
            "GRANT INSERT",
            "GRANT UPDATE",
            "GRANT DELETE",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, sql)

        self.assertIn("CREATE ROLE geno_v2_api_login", sql)
        self.assertIn("NOLOGIN NOSUPERUSER", sql)
        self.assertIn("ALTER ROLE geno_v2_api_login PASSWORD NULL", sql)
        self.assertIn("ALTER ROLE geno_v2_api_login RESET ALL", sql)
        self.assertIn(
            "ALTER ROLE geno_v2_api_login IN DATABASE geno_v2 RESET ALL",
            sql,
        )
        self.assertIn("WITH ADMIN FALSE, INHERIT FALSE, SET TRUE", sql)
        self.assertIn("REVOKE CONNECT, TEMPORARY ON DATABASE geno_v2 FROM PUBLIC", sql)
        self.assertIn("GRANT CONNECT ON DATABASE geno_v2 TO geno_v2_api_login", sql)
        self.assertIn(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS",
            sql,
        )
        self.assertIn("current_setting('app.session_token_hash', true)", sql)
        self.assertIn("session_row.issued_at <= statement_timestamp()", sql)
        self.assertIn("DEFERRABLE INITIALLY DEFERRED", sql)
        self.assertEqual(sql.count("CREATE CONSTRAINT TRIGGER"), 3)
        self.assertIn("geno_v2_validate_auth_redemption_lineage", sql)
        self.assertIn(
            "attempt_row.token_fingerprint <> invitation_row.invite_token_hash",
            sql,
        )
        self.assertIn("scope.value->'roles' ? invitation_row.role", sql)
        self.assertIn("session_row.issued_at > invitation_row.expires_at", sql)
        self.assertIn("VALUES (true, false)", sql)
        self.assertIn("runtime session identity and scope snapshot are immutable", sql)
        self.assertIn(
            "GRANT SELECT ON project_member_invitations, "
            "auth_invitation_redemption_attempts",
            sql,
        )
        self.assertIn("runtime_sessions, project_members TO geno_v2_authz_owner", sql)
        self.assertIn("geno_v2_session_can_read_project_member", sql)
        self.assertIn(
            "USING (geno_v2_session_can_read_project_member("
            "project_id, tenant_id, user_id))",
            sql,
        )
        self.assertNotIn("GRANT SELECT ON runtime_sessions TO geno_v2_runtime", sql)
        self.assertNotIn(
            "GRANT SELECT ON runtime_project_access_grants TO geno_v2_runtime",
            sql,
        )

    def test_auth_state_guards_revoke_without_opening_runtime_commands(self) -> None:
        sql = (SCHEMA_ROOT / "baseline/0012_auth_state_guards.sql").read_text(
            encoding="utf-8"
        )

        for function_name in (
            "geno_v2_guard_project_member_invitation_state",
            "geno_v2_guard_auth_redemption_attempt_state",
            "geno_v2_guard_runtime_session_update",
            "geno_v2_guard_runtime_reauth_state",
            "geno_v2_guard_auth_write_control_state",
            "geno_v2_guard_auth_preflight_rate_limit_state",
            "geno_v2_require_auth_writes_enabled",
            "geno_v2_revoke_affected_sessions",
            "geno_v2_lock_runtime_session_authz_sources",
            "geno_v2_revoke_sessions_for_authz_change",
        ):
            with self.subTest(function_name=function_name):
                self.assertIn(f"FUNCTION {function_name}", sql)

        self.assertIn(
            "BEFORE INSERT OR UPDATE OR DELETE ON project_member_invitations", sql
        )
        self.assertIn(
            "BEFORE INSERT OR UPDATE OR DELETE ON auth_invitation_redemption_attempts",
            sql,
        )
        self.assertIn("BEFORE UPDATE OR DELETE ON runtime_sessions", sql)
        self.assertIn(
            "BEFORE INSERT OR UPDATE OR DELETE ON runtime_session_reauth_queue", sql
        )
        self.assertIn("BEFORE UPDATE OR DELETE ON auth_runtime_write_controls", sql)
        reauth_guard = sql.split(
            "CREATE FUNCTION geno_v2_guard_runtime_reauth_state()", 1
        )[1].split("$guard_reauth$;", 1)[0]
        session_guard = sql.split(
            "CREATE OR REPLACE FUNCTION geno_v2_guard_runtime_session_update()", 1
        )[1].split("$guard_session_update$;", 1)[0]
        self.assertIn("IF TG_OP = 'INSERT'", reauth_guard)
        self.assertIn("NEW.status <> 'pending'", reauth_guard)
        self.assertNotIn("runtime reauthentication must be inserted pending", session_guard)
        self.assertIn("FOR SHARE", sql)
        self.assertIn("auth_attempts_confirmation_requires_erasure", sql)
        self.assertIn("octet_length(delivery_ciphertext) BETWEEN 1 AND 16384", sql)
        self.assertIn("octet_length(delivery_nonce) = 12", sql)
        self.assertIn("delivery_expires_at > created_at", sql)
        self.assertIn("NEW.delivery_expires_at <= statement_timestamp()", sql)
        self.assertIn("auth_preflight_guard_state", sql)
        self.assertIn("ON CONFLICT (session_id) DO NOTHING", sql)
        self.assertIn("WHERE session_row.status = 'active'", sql)
        self.assertIn("GRANT UPDATE (status, revoked_at, revoked_by", sql)
        self.assertIn("GRANT INSERT ON runtime_session_reauth_queue", sql)
        self.assertIn("GRANT SELECT ON auth_runtime_write_controls", sql)
        self.assertNotIn("TO geno_v2_runtime", sql)
        self.assertNotIn("CREATE POLICY", sql)
        self.assertNotIn("LOGIN", sql.replace("NOLOGIN", ""))

    def test_auth_command_boundary_is_bounded_and_self_verifying(self) -> None:
        sql = (SCHEMA_ROOT / "baseline/0013_auth_commands.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("UNIQUE (invitation_id, idempotency_key_hash)", sql)
        self.assertNotIn(
            "UNIQUE (invitation_id, requested_surface, idempotency_key_hash)", sql
        )
        self.assertIn("delivery_expires_at <= updated_at + interval '1 hour'", sql)
        self.assertIn("expires_at <= issued_at + interval '30 days'", sql)
        self.assertIn("ADD COLUMN resolved_by_session_id uuid", sql)
        self.assertIn(
            "FOREIGN KEY (resolved_by_session_id, tenant_id, actor_id)", sql
        )
        self.assertIn("NEW.resolved_by_session_id IS NULL", sql)
        self.assertIn("auth-delivery-v1 + NUL + canonical attempt UUID", sql)
        public_signatures = (
            "geno_v2_preflight_auth_invitation(uuid, text, text, text)",
            "geno_v2_create_project_member_invitation(\n    uuid, uuid, text, text, text, timestamptz\n)",
            "geno_v2_revoke_project_member_invitation(uuid, text)",
            "geno_v2_expire_project_member_invitation(uuid)",
            "geno_v2_redeem_auth_invitation(\n    uuid, uuid, uuid, text, text, text, text, timestamptz,\n    bytea, text, bytea, timestamptz\n)",
            "geno_v2_confirm_current_auth_delivery()",
            "geno_v2_erase_current_auth_delivery_secret()",
            "geno_v2_logout_current_session()",
            "geno_v2_resolve_current_reauth_queue()",
        )
        normalized_sql = " ".join(sql.split())
        for signature in public_signatures:
            with self.subTest(signature=signature):
                normalized_signature = " ".join(signature.split())
                self.assertIn(
                    f"GRANT EXECUTE ON FUNCTION {normalized_signature}", normalized_sql
                )
                self.assertIn(
                    f"REVOKE ALL ON FUNCTION {normalized_signature} FROM PUBLIC",
                    normalized_sql,
                )
        self.assertEqual(sql.count("TO geno_v2_runtime;"), 9)
        self.assertIn("invitation_limit constant integer := 20", sql)
        self.assertIn("source_limit constant integer := 100", sql)
        self.assertIn("window_seconds constant integer := 600", sql)
        self.assertIn("attempt_row.replay_count >= 3", sql)
        self.assertIn("public.digest(", sql)
        self.assertNotRegex(sql, r"(?<!public\.)digest\(")
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION public.digest(bytea, text) "
            "TO geno_v2_authz_owner",
            sql,
        )
        self.assertIn("'member.manage'", sql)
        self.assertIn("UUID-ordered NO KEY UPDATE lock", sql)
        self.assertIn("CREATE OR REPLACE FUNCTION geno_v2_require_auth_writes_enabled", sql)
        self.assertIn("CREATE FUNCTION geno_v2_lock_auth_write_control()", sql)
        self.assertIn("VOLATILE", sql)
        self.assertIn("FOR SHARE", sql)
        self.assertIn(
            "REVOKE ALL ON FUNCTION geno_v2_lock_auth_write_control() FROM PUBLIC",
            sql,
        )
        self.assertIn(
            "GRANT UPDATE (writes_enabled) ON auth_runtime_write_controls", sql
        )
        self.assertIn("DO $auth_command_catalog_assert$", sql)
        self.assertIn("procedure.proowner = authz_owner_oid", sql)
        self.assertIn("procedure.prosecdef", sql)
        self.assertIn("'search_path=pg_catalog' = ANY(procedure.proconfig)", sql)
        self.assertIn("role_row.rolpassword IS NOT NULL", sql)
        self.assertIn("WHERE control.singleton AND NOT control.writes_enabled", sql)
        self.assertTrue(sql.rstrip().endswith("WHERE singleton;"))
        self.assertNotIn("LOGIN", sql.replace("NOLOGIN", ""))
        self.assertNotIn("PASSWORD", sql)
        self.assertNotIn("CREATE POLICY", sql)

    def test_auth_login_provision_contract_is_sealed_and_fail_closed(self) -> None:
        sql = (SCHEMA_ROOT / "baseline/0014_auth_login_provision.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("CREATE TABLE auth_login_provision_attempts", sql)
        self.assertIn("attempt_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE", sql)
        self.assertIn("CHECK (login_kind IN ('api', 'worker'))", sql)
        self.assertIn("ON auth_login_provision_attempts (login_kind)", sql)
        self.assertIn("WHERE status = 'preparing'", sql)
        self.assertIn("CREATE TABLE auth_login_provision_receipts", sql)
        self.assertIn("auth_login_successful_credential_version_idx", sql)
        self.assertIn(
            "ON auth_login_provision_receipts (login_kind, credential_version)", sql
        )
        self.assertIn("auth_login_attempts_guard_state", sql)
        self.assertIn("auth_login_receipts_reject_mutation", sql)
        self.assertIn("DEFERRABLE INITIALLY DEFERRED", sql)
        self.assertIn("geno_v2_auth_login_startup_ready", sql)
        self.assertIn("ORDER BY attempt.attempt_sequence DESC", sql)
        self.assertIn("attempt.status = 'succeeded'", sql)
        self.assertIn("attempt.operation IN ('provision', 'rotate')", sql)
        self.assertIn("WHERE attempt.login_kind = 'api'", sql)
        self.assertIn("session_user = 'geno_v2_api_login'", sql)
        self.assertIn("current_setting('role', true) = 'geno_v2_runtime'", sql)
        self.assertIn("DO $auth_login_provision_catalog_assert$", sql)
        self.assertIn("has_schema_privilege(api_login_oid, 'public', 'USAGE')", sql)
        self.assertIn("has_function_privilege(api_login_oid", sql)
        self.assertIn("NOLOGIN NOSUPERUSER", sql)
        self.assertIn("NOBYPASSRLS PASSWORD NULL", sql)
        self.assertNotIn("ALTER ROLE geno_v2_api_login LOGIN", sql)
        self.assertNotIn("PASSWORD '", sql)
        self.assertNotIn("CREATE POLICY", sql)
        self.assertTrue(sql.rstrip().endswith("$auth_login_provision_catalog_assert$;"))

    def test_runner_uses_a_session_lock_and_transactional_ledger(self) -> None:
        runner = (ROOT / "scripts/schema_v2_runner.py").read_text(encoding="utf-8")

        self.assertEqual(ADVISORY_LOCK_NAME, "geno:schema-v2:install")
        self.assertIn("pg_try_advisory_lock(hashtextextended", runner)
        self.assertIn("pg_advisory_unlock(hashtextextended", runner)
        self.assertIn("connection.autocommit = True", runner)
        self.assertIn("with connection.transaction()", runner)
        self.assertIn("SET TRANSACTION READ ONLY", runner)
        self.assertIn("INSERT INTO schema_migration_ledger", runner)
        self.assertIn("SELECT current_database()", runner)
        self.assertIn("refusing to initialize Schema v2 with unexpected public objects", runner)

    def test_catalog_discovery_reports_all_supported_public_object_kinds(self) -> None:
        cursor = _CatalogCursor(
            [
                ("table", "public.dirty_table"),
                ("view", "public.dirty_view"),
                ("materialized_view", "public.dirty_materialized_view"),
                ("sequence", "public.dirty_sequence"),
                ("foreign_table", "public.dirty_foreign_table"),
                ("function", "dirty_function()"),
                ("enum_type", "public.dirty_enum"),
                ("collation", "public.dirty_collation"),
                ("operator", "public.dirty_operator"),
                ("text_search_configuration", "public.dirty_ts_config"),
                ("extension", "postgres_fdw"),
            ]
        )

        objects = _unexpected_public_objects(cursor)

        self.assertIn("pg_catalog.pg_class", cursor.statement)
        self.assertIn("pg_catalog.pg_proc", cursor.statement)
        self.assertIn("pg_catalog.pg_type", cursor.statement)
        self.assertIn("pg_catalog.pg_collation", cursor.statement)
        self.assertIn("pg_catalog.pg_operator", cursor.statement)
        self.assertIn("pg_catalog.pg_ts_config", cursor.statement)
        self.assertIn("pg_catalog.pg_ts_dict", cursor.statement)
        self.assertIn("pg_catalog.pg_ts_parser", cursor.statement)
        self.assertIn("pg_catalog.pg_ts_template", cursor.statement)
        self.assertIn("pg_catalog.pg_extension", cursor.statement)
        self.assertIn("dependency.deptype = 'e'", cursor.statement)
        self.assertEqual(objects[0], "table:public.dirty_table")
        self.assertEqual(objects[-1], "extension:postgres_fdw")

    def test_try_lock_polls_until_acquired_and_times_out_stably(self) -> None:
        cursor = _TryLockCursor([False, True])
        clock = [0.0]
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds

        _acquire_advisory_lock(
            cursor,
            timeout_seconds=1.0,
            poll_interval_seconds=0.1,
            monotonic=lambda: clock[0],
            sleep=sleep,
        )
        self.assertEqual(len(cursor.statements), 2)
        self.assertEqual(sleeps, [0.1])

        timeout_cursor = _TryLockCursor([False])
        with self.assertRaisesRegex(
            SchemaV2Error,
            "timed out acquiring Schema v2 advisory lock after 0.000 seconds",
        ):
            _acquire_advisory_lock(timeout_cursor, timeout_seconds=0.0)

    def test_connect_and_lock_timeouts_reject_non_finite_or_negative_values(self) -> None:
        for invalid in (float("nan"), float("inf"), float("-inf"), -0.1):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(SchemaV2Error, "finite and non-negative"):
                    _acquire_advisory_lock(
                        _TryLockCursor([True]),
                        timeout_seconds=invalid,
                    )
        for invalid_connect_timeout in (
            float("nan"),
            float("inf"),
            float("-inf"),
            -0.1,
            0.0,
            1.999,
        ):
            with self.subTest(invalid_connect_timeout=invalid_connect_timeout):
                with self.assertRaisesRegex(SchemaV2Error, "finite and at least 2 seconds"):
                    _connect_with_retry(
                        timeout_seconds=invalid_connect_timeout,
                        driver=_NeverConnectDriver,
                    )

        with self.assertRaisesRegex(SchemaV2Error, "finite and positive"):
            _acquire_advisory_lock(
                _TryLockCursor([True]),
                timeout_seconds=1.0,
                poll_interval_seconds=float("inf"),
            )
        for raw in ("nan", "inf", "-inf", "-0.1", "not-a-number"):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(
                    argparse.ArgumentTypeError,
                    "finite non-negative number",
                ):
                    _nonnegative_finite_seconds(raw)
        for raw in ("nan", "inf", "-inf", "-0.1", "0", "1.999", "not-a-number"):
            with self.subTest(connect_raw=raw):
                with self.assertRaisesRegex(
                    argparse.ArgumentTypeError,
                    "finite and at least 2 seconds",
                ):
                    _connect_deadline_seconds(raw)

        # Lock timeout zero remains a valid single non-blocking attempt.
        self.assertEqual(_nonnegative_finite_seconds("0"), 0.0)

    def test_each_libpq_connect_attempt_uses_the_rounded_remaining_deadline(self) -> None:
        clock = [0.0]
        driver = _ConvergingConnectDriver(clock)

        result = _connect_with_retry(
            timeout_seconds=8.0,
            driver=driver,
            retry_interval_seconds=0.5,
            monotonic=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        )

        self.assertIs(result, driver.result)
        self.assertEqual(driver.connect_timeouts, [8, 6, 3])
        self.assertTrue(all(timeout >= 2 for timeout in driver.connect_timeouts))

        minimum_clock = [0.0]
        minimum_driver = _ConvergingConnectDriver(minimum_clock)
        with self.assertRaises(_ConvergingConnectDriver.OperationalError):
            _connect_with_retry(
                timeout_seconds=2.0,
                driver=minimum_driver,
                monotonic=lambda: minimum_clock[0],
                sleep=lambda seconds: minimum_clock.__setitem__(
                    0, minimum_clock[0] + seconds
                ),
            )
        self.assertEqual(minimum_driver.connect_timeouts, [2])

    def test_structured_pg_environment_is_required_and_database_is_fixed(self) -> None:
        environment = {
            "PGHOST": "postgres-v2",
            "PGPORT": "5432",
            "PGDATABASE": "geno_v2",
            "PGUSER": "runner",
            "PGPASSWORD": "marker-password",
        }
        _validate_pg_environment(environment)

        for key in environment:
            with self.subTest(missing=key):
                invalid = {**environment, key: ""}
                with self.assertRaisesRegex(SchemaV2Error, key):
                    _validate_pg_environment(invalid)
        with self.assertRaisesRegex(SchemaV2Error, "PGDATABASE must remain fixed"):
            _validate_pg_environment({**environment, "PGDATABASE": "geno"})

    def test_connection_failure_stderr_is_stable_and_contains_no_connection_markers(self) -> None:
        password_marker = "PASSWORD_MARKER_must_never_appear"
        user_marker = "DSN_MARKER_must_never_appear"
        deprecated_dsn_marker = "postgresql://DEPRECATED_DSN_MARKER_must_never_appear"
        environment = {
            **os.environ,
            "PGHOST": "127.0.0.1",
            "PGPORT": "1",
            "PGDATABASE": "geno_v2",
            "PGUSER": user_marker,
            "PGPASSWORD": password_marker,
            "SCHEMA_V2_DATABASE_URL": deprecated_dsn_marker,
        }
        result = subprocess.run(
            [
                sys.executable,
                "scripts/schema_v2_runner.py",
                "verify",
                "--schema-root",
                "infra/db/schema-v2",
                "--connect-timeout-seconds",
                "2",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "schema-v2 error: database connection failed\n")
        self.assertNotIn(password_marker, result.stderr)
        self.assertNotIn(user_marker, result.stderr)
        self.assertNotIn(deprecated_dsn_marker, result.stderr)
        self.assertNotIn("postgresql://", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_timeout_environment_values_fail_without_a_traceback(self) -> None:
        base_environment = {
            **os.environ,
            "PGHOST": "127.0.0.1",
            "PGPORT": "1",
            "PGDATABASE": "geno_v2",
            "PGUSER": "timeout-test",
            "PGPASSWORD": "timeout-test-marker",
        }
        invalid_by_variable = {
            "SCHEMA_V2_CONNECT_TIMEOUT_SECONDS": (
                "nan",
                "inf",
                "-inf",
                "-0.1",
                "0",
                "1.999",
                "not-a-number",
            ),
            "SCHEMA_V2_LOCK_TIMEOUT_SECONDS": (
                "nan",
                "inf",
                "-inf",
                "-0.1",
                "not-a-number",
            ),
        }
        for variable, invalid_values in invalid_by_variable.items():
            for invalid in invalid_values:
                with self.subTest(variable=variable, invalid=invalid):
                    result = subprocess.run(
                        [
                            sys.executable,
                            "scripts/schema_v2_runner.py",
                            "verify",
                            "--schema-root",
                            "infra/db/schema-v2",
                        ],
                        cwd=ROOT,
                        env={**base_environment, variable: invalid},
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, 2)
                    expected_error = (
                        "must be finite and at least 2 seconds"
                        if variable == "SCHEMA_V2_CONNECT_TIMEOUT_SECONDS"
                        else "must be a finite non-negative number"
                    )
                    self.assertIn(expected_error, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)


@unittest.skipIf(yaml is None, "PyYAML is required for Compose contract checks")
class SchemaV2ComposeContractsTest(unittest.TestCase):
    def _compose_config(self) -> tuple[dict[str, object], str]:
        environment = {
            **os.environ,
            "SCHEMA_V2_POSTGRES_USER": COMPOSE_USER,
            "SCHEMA_V2_POSTGRES_PASSWORD": COMPOSE_PASSWORD,
            # The fixed database contract must ignore this attempted override.
            "SCHEMA_V2_POSTGRES_DB": "must_not_be_used",
        }
        result = subprocess.run(
            ["docker", "compose", "-f", "infra/docker-compose.schema-v2.yml", "config"],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        return yaml.safe_load(result.stdout), result.stdout

    def test_compose_isolated_database_and_installer_contract(self) -> None:
        config, rendered = self._compose_config()
        services = config["services"]
        database = services["postgres-v2"]
        installer = services["schema-v2-install"]
        verifier = services["schema-v2-verify"]
        behavior_test = services["schema-v2-behavior-test"]
        session_uow_behavior_test = services["schema-v2-session-uow-behavior-test"]
        collection_scoring_behavior_test = services[
            "schema-v2-collection-scoring-behavior-test"
        ]
        knowledge_behavior_test = services["schema-v2-knowledge-behavior-test"]
        auth_commands_behavior_test = services[
            "schema-v2-auth-commands-behavior-test"
        ]
        anonymous_auth_uow_behavior_test = services[
            "schema-v2-anonymous-auth-uow-behavior-test"
        ]
        login_provision_behavior_test = services[
            "schema-v2-login-provision-behavior-test"
        ]
        worker_login_provision_behavior_test = services[
            "schema-v2-worker-login-provision-behavior-test"
        ]

        self.assertEqual(database["environment"]["POSTGRES_DB"], "geno_v2")
        self.assertEqual(database["environment"]["POSTGRES_USER"], COMPOSE_USER)
        self.assertEqual(database["environment"]["POSTGRES_PASSWORD"], COMPOSE_PASSWORD)
        self.assertEqual(
            database["command"],
            ["postgres", "-c", "log_statement=all", "-c", "log_min_error_statement=error"],
        )
        expected_pg_environment = {
            "PGHOST": "postgres-v2",
            "PGPORT": "5432",
            "PGDATABASE": "geno_v2",
            "PGUSER": COMPOSE_USER,
            "PGPASSWORD": COMPOSE_PASSWORD,
        }
        for service in (
            installer,
            verifier,
            behavior_test,
            session_uow_behavior_test,
            collection_scoring_behavior_test,
            knowledge_behavior_test,
            auth_commands_behavior_test,
            anonymous_auth_uow_behavior_test,
            login_provision_behavior_test,
            worker_login_provision_behavior_test,
        ):
            for key, expected_value in expected_pg_environment.items():
                self.assertEqual(service["environment"][key], expected_value)
            self.assertNotIn("SCHEMA_V2_DATABASE_URL", service["environment"])
        self.assertNotIn("ports", database)
        self.assertTrue(
            any(volume["source"] == "schema_v2_postgres_data" for volume in database["volumes"])
        )
        self.assertEqual(
            collection_scoring_behavior_test["command"],
            ["python", "/app/tests/test_schema_v2_collection_scoring_postgres.py"],
        )
        self.assertEqual(
            collection_scoring_behavior_test["environment"]["SCHEMA_V2_BEHAVIOR_TEST"],
            "1",
        )
        self.assertTrue(
            any(
                volume["target"]
                == "/app/tests/test_schema_v2_collection_scoring_postgres.py"
                and volume["read_only"]
                for volume in collection_scoring_behavior_test["volumes"]
            )
        )
        self.assertEqual(
            knowledge_behavior_test["command"],
            ["python", "/app/tests/test_schema_v2_knowledge_postgres.py"],
        )
        self.assertEqual(
            knowledge_behavior_test["environment"]["SCHEMA_V2_BEHAVIOR_TEST"],
            "1",
        )
        self.assertTrue(
            any(
                volume["target"] == "/app/tests/test_schema_v2_knowledge_postgres.py"
                and volume["read_only"]
                for volume in knowledge_behavior_test["volumes"]
            )
        )
        self.assertIn("scripts/schema_v2_runner.py", installer["command"])
        self.assertIn("install", installer["command"])
        self.assertIn("verify", verifier["command"])
        self.assertEqual(
            installer["depends_on"]["postgres-v2"]["condition"],
            "service_healthy",
        )
        self.assertTrue(
            any(volume["target"] == "/schema-v2" and volume["read_only"] for volume in installer["volumes"])
        )
        self.assertEqual(
            session_uow_behavior_test["command"],
            ["python", "/app/tests/test_schema_v2_session_uow_postgres.py"],
        )
        self.assertEqual(session_uow_behavior_test["environment"]["SCHEMA_V2_BEHAVIOR_TEST"], "1")
        self.assertTrue(
            any(
                volume["target"] == "/app/tests/test_schema_v2_session_uow_postgres.py"
                and volume["read_only"]
                for volume in session_uow_behavior_test["volumes"]
            )
        )
        self.assertEqual(
            auth_commands_behavior_test["command"],
            ["python", "/app/tests/test_schema_v2_auth_commands_postgres.py"],
        )
        self.assertEqual(
            auth_commands_behavior_test["environment"]["SCHEMA_V2_BEHAVIOR_TEST"],
            "1",
        )
        self.assertTrue(
            any(
                volume["target"]
                == "/app/tests/test_schema_v2_auth_commands_postgres.py"
                and volume["read_only"]
                for volume in auth_commands_behavior_test["volumes"]
            )
        )
        self.assertEqual(
            anonymous_auth_uow_behavior_test["command"],
            ["python", "/app/tests/test_schema_v2_anonymous_auth_uow_postgres.py"],
        )
        self.assertEqual(
            anonymous_auth_uow_behavior_test["environment"][
                "SCHEMA_V2_BEHAVIOR_TEST"
            ],
            "1",
        )
        self.assertTrue(
            any(
                volume["target"]
                == "/app/tests/test_schema_v2_anonymous_auth_uow_postgres.py"
                and volume["read_only"]
                for volume in anonymous_auth_uow_behavior_test["volumes"]
            )
        )
        self.assertEqual(
            login_provision_behavior_test["command"],
            ["python", "/app/tests/test_schema_v2_login_provision_postgres.py"],
        )
        self.assertEqual(
            login_provision_behavior_test["environment"]["SCHEMA_V2_BEHAVIOR_TEST"],
            "1",
        )
        self.assertNotIn("infra/db/migrations/up", rendered)
        self.assertNotIn("/docker-entrypoint-initdb.d", rendered)
        self.assertNotIn("must_not_be_used", rendered)
        self.assertNotIn("geno_v2_local", rendered)
        self.assertNotIn("postgresql://", rendered)

    def test_makefile_exposes_contract_and_fresh_install_entrypoints(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("schema-v2-contracts:", makefile)
        self.assertIn("schema-v2-fresh-install:", makefile)
        self.assertIn(
            "schema-v2-gate: schema-v2-contracts schema-v2-config schema-v2-fresh-install",
            makefile,
        )
        self.assertEqual(makefile.count("run --rm schema-v2-install"), 5)
        self.assertEqual(makefile.count("run --rm schema-v2-verify"), 5)
        self.assertIn("run --rm schema-v2-behavior-test", makefile)
        self.assertIn("run --rm schema-v2-session-uow-behavior-test", makefile)
        self.assertIn("run --rm schema-v2-collection-scoring-behavior-test", makefile)
        self.assertIn("run --rm schema-v2-knowledge-behavior-test", makefile)
        self.assertIn("run --rm schema-v2-auth-commands-behavior-test", makefile)
        self.assertIn("schema-v2-anonymous-auth-uow-gate:", makefile)
        self.assertIn(
            "run --rm schema-v2-anonymous-auth-uow-behavior-test", makefile
        )
        self.assertIn("geno-schema-v2-anonymous-auth-pg", makefile)
        self.assertIn("schema-v2-login-provision-gate:", makefile)
        self.assertIn("run --rm schema-v2-login-provision-behavior-test", makefile)
        self.assertIn("geno-schema-v2-login-provision-pg", makefile)
        self.assertIn("schema-v2-worker-login-provision-gate:", makefile)
        self.assertIn(
            "run --rm schema-v2-worker-login-provision-behavior-test",
            makefile,
        )
        self.assertIn("geno-schema-v2-worker-login-provision-pg", makefile)
        self.assertIn("SCRAM-SHA-256$$", makefile)
        self.assertIn("appeared in PostgreSQL logs", makefile)
        self.assertIn("down --remove-orphans -v", makefile)
        ci_local = makefile.split("\nci-local:", 1)[1].split("\n", 1)[0]
        self.assertIn("schema-v2-gate", ci_local)
        ordinary_test = makefile.split("\ntest:\n", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("schema-v2-fresh-install", ordinary_test)
        self.assertIn("run: make db-smoke", workflow)
        self.assertIn("run: make schema-v2-config", workflow)
        self.assertIn("run: make schema-v2-fresh-install", workflow)


if __name__ == "__main__":
    unittest.main()
