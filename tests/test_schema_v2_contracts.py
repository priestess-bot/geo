from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.schema_v2_runner import (
    ADVISORY_LOCK_NAME,
    EXPECTED_SCHEMA_GENERATION,
    SchemaV2Error,
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


class SchemaV2ManifestContractsTest(unittest.TestCase):
    def test_manifest_pins_the_ordered_bootstrap_and_its_baseline_hash(self) -> None:
        manifest = load_manifest(SCHEMA_ROOT)

        self.assertEqual(manifest.schema_generation, EXPECTED_SCHEMA_GENERATION)
        self.assertEqual(manifest.database_name, "geno_v2")
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
        self.assertIn("pg_advisory_lock(hashtextextended", runner)
        self.assertIn("pg_advisory_unlock(hashtextextended", runner)
        self.assertIn("connection.autocommit = True", runner)
        self.assertIn("with connection.transaction()", runner)
        self.assertIn("SET TRANSACTION READ ONLY", runner)
        self.assertIn("INSERT INTO schema_migration_ledger", runner)
        self.assertIn("SELECT current_database()", runner)
        self.assertIn("refusing to initialize Schema v2 in a non-empty public schema", runner)


@unittest.skipIf(yaml is None, "PyYAML is required for Compose contract checks")
class SchemaV2ComposeContractsTest(unittest.TestCase):
    def test_compose_isolated_database_and_installer_contract(self) -> None:
        result = subprocess.run(
            ["docker", "compose", "-f", "infra/docker-compose.schema-v2.yml", "config"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        config = yaml.safe_load(result.stdout)
        services = config["services"]
        database = services["postgres-v2"]
        installer = services["schema-v2-install"]
        verifier = services["schema-v2-verify"]

        self.assertEqual(database["environment"]["POSTGRES_DB"], "geno_v2")
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
        rendered = result.stdout
        self.assertNotIn("infra/db/migrations/up", rendered)
        self.assertNotIn("/docker-entrypoint-initdb.d", rendered)

    def test_makefile_exposes_contract_and_fresh_install_entrypoints(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertIn("schema-v2-contracts:", makefile)
        self.assertIn("schema-v2-fresh-install:", makefile)
        self.assertEqual(makefile.count("run --rm schema-v2-install"), 2)
        self.assertIn("run --rm schema-v2-verify", makefile)
        self.assertIn("down --remove-orphans -v", makefile)


if __name__ == "__main__":
    unittest.main()
