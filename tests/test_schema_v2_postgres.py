from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/schema_v2_runner.py"
SCHEMA_ROOT = Path(os.getenv("SCHEMA_V2_ROOT", "/schema-v2"))
DATABASE_URL = os.getenv("SCHEMA_V2_TEST_DATABASE_URL", "")
LOCK_NAME = "geno:schema-v2:install"


@unittest.skipUnless(DATABASE_URL, "SCHEMA_V2_TEST_DATABASE_URL is required")
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
                "--database-url",
                DATABASE_URL,
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

    def test_advisory_lock_has_a_stable_timeout(self) -> None:
        with psycopg.connect(DATABASE_URL, autocommit=True) as holder:
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
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            self._drop_bootstrap_metadata(connection)

        extension_only_install = self._run_runner("install")
        self.assertEqual(
            extension_only_install.returncode,
            0,
            extension_only_install.stdout + extension_only_install.stderr,
        )

        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
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
                "extension:postgres_fdw",
            ):
                self.assertIn(expected, dirty_install.stderr)
            self.assertNotIn("Traceback", dirty_install.stderr)
        finally:
            with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
                self._drop_dirty_objects(connection)
            restored = self._run_runner("install")
            self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
