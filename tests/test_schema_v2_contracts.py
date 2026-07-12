from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.schema_v2_runner import (
    ADVISORY_LOCK_NAME,
    EXPECTED_DATABASE_NAME,
    EXPECTED_SCHEMA_GENERATION,
    SchemaV2Error,
    _acquire_advisory_lock,
    _unexpected_public_objects,
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


class SchemaV2ManifestContractsTest(unittest.TestCase):
    def test_manifest_pins_the_ordered_bootstrap_and_its_baseline_hash(self) -> None:
        manifest = load_manifest(SCHEMA_ROOT)

        self.assertEqual(manifest.schema_generation, EXPECTED_SCHEMA_GENERATION)
        self.assertEqual(manifest.database_name, EXPECTED_DATABASE_NAME)
        self.assertEqual(manifest.baseline_version, "2.0.0-b1")
        self.assertEqual(manifest.minimum_app_version, "0.1.0")
        self.assertEqual(
            [item.path for item in manifest.baseline_files],
            ["baseline/0000_extensions_roles.sql"],
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
                ("extension", "postgres_fdw"),
            ]
        )

        objects = _unexpected_public_objects(cursor)

        self.assertIn("pg_catalog.pg_class", cursor.statement)
        self.assertIn("pg_catalog.pg_proc", cursor.statement)
        self.assertIn("pg_catalog.pg_type", cursor.statement)
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

        self.assertEqual(database["environment"]["POSTGRES_DB"], "geno_v2")
        self.assertEqual(database["environment"]["POSTGRES_USER"], COMPOSE_USER)
        self.assertEqual(database["environment"]["POSTGRES_PASSWORD"], COMPOSE_PASSWORD)
        expected_url = (
            f"postgresql://{COMPOSE_USER}:{COMPOSE_PASSWORD}@postgres-v2:5432/geno_v2"
        )
        self.assertEqual(installer["environment"]["SCHEMA_V2_DATABASE_URL"], expected_url)
        self.assertEqual(verifier["environment"]["SCHEMA_V2_DATABASE_URL"], expected_url)
        self.assertEqual(
            behavior_test["environment"]["SCHEMA_V2_TEST_DATABASE_URL"], expected_url
        )
        self.assertNotIn("ports", database)
        self.assertTrue(
            any(volume["source"] == "schema_v2_postgres_data" for volume in database["volumes"])
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
        self.assertNotIn("infra/db/migrations/up", rendered)
        self.assertNotIn("/docker-entrypoint-initdb.d", rendered)
        self.assertNotIn("must_not_be_used", rendered)
        self.assertNotIn("geno_v2_local", rendered)

    def test_makefile_exposes_contract_and_fresh_install_entrypoints(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertIn("schema-v2-contracts:", makefile)
        self.assertIn("schema-v2-fresh-install:", makefile)
        self.assertEqual(makefile.count("run --rm schema-v2-install"), 2)
        self.assertEqual(makefile.count("run --rm schema-v2-verify"), 2)
        self.assertIn("run --rm schema-v2-behavior-test", makefile)
        self.assertIn("down --remove-orphans -v", makefile)


if __name__ == "__main__":
    unittest.main()
