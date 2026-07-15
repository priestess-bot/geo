from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "scripts/export_openapi_snapshot.py"
SNAPSHOT = ROOT / "contracts/openapi/geo-api.openapi.json"
MANIFEST = ROOT / "contracts/openapi/manifest.json"
REQUIRED_OPERATIONS = (
    ("/health", "get"),
    ("/v1/auth/invitations/preflight", "post"),
    ("/v1/auth/invitations/redeem", "post"),
    ("/v1/auth/me", "get"),
    ("/v1/projects/runtime", "get"),
)


def _run_export(snapshot: Path, manifest: Path, *, marker: str) -> None:
    environment = {
        **os.environ,
        "DATABASE_URL": f"postgresql://contract:{marker}@database.invalid/geo",
        "GEO_CONNECTOR_SECRET_MASTER_KEY": marker,
        "GEO_DEPLOYMENT_ENVIRONMENT": "production",
        "GEO_RUNTIME_JWT_SECRET": marker,
    }
    subprocess.run(
        [
            sys.executable,
            str(EXPORTER),
            "export",
            "--snapshot",
            str(snapshot),
            "--manifest",
            str(manifest),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


class OpenAPISnapshotContractTests(unittest.TestCase):
    def test_checked_in_openapi_snapshot_matches_runtime_and_manifest(self) -> None:
        result = subprocess.run(
            [sys.executable, str(EXPORTER), "verify"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("OpenAPI snapshot verified", result.stdout)

        snapshot_content = SNAPSHOT.read_bytes()
        document = json.loads(snapshot_content)
        manifest = json.loads(MANIFEST.read_bytes())
        self.assertEqual(
            manifest["artifact"]["sha256"],
            hashlib.sha256(snapshot_content).hexdigest(),
        )
        self.assertEqual(manifest["artifact"]["size_bytes"], len(snapshot_content))
        self.assertEqual(manifest["openapi"]["document_version"], document["openapi"])
        for path, method in REQUIRED_OPERATIONS:
            self.assertIn(method, document["paths"][path])

    def test_openapi_exports_are_byte_stable_and_environment_independent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openapi-snapshot-contract-") as temp:
            temp_path = Path(temp)
            first_dir = temp_path / "first"
            second_dir = temp_path / "second"
            first_snapshot = first_dir / "geo-api.openapi.json"
            second_snapshot = second_dir / "geo-api.openapi.json"
            first_manifest = first_dir / "manifest.json"
            second_manifest = second_dir / "manifest.json"
            first_marker = "OPENAPI_FIRST_SECRET_MARKER"
            second_marker = "OPENAPI_SECOND_SECRET_MARKER"

            _run_export(first_snapshot, first_manifest, marker=first_marker)
            _run_export(second_snapshot, second_manifest, marker=second_marker)

            self.assertEqual(first_snapshot.read_bytes(), second_snapshot.read_bytes())
            self.assertEqual(first_manifest.read_bytes(), second_manifest.read_bytes())
            combined = first_snapshot.read_bytes() + first_manifest.read_bytes()
            self.assertNotIn(first_marker.encode(), combined)
            self.assertNotIn(second_marker.encode(), combined)

    def test_stable_openapi_contract_targets_replace_legacy_build_wiring(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        requirements = (ROOT / "apps/api/requirements.txt").read_text(encoding="utf-8")
        self.assertIn("openapi-snapshots:", makefile)
        self.assertIn("openapi-contracts:", makefile)
        self.assertIn("scripts/export_stable_openapi.py export", makefile)
        self.assertIn("scripts/export_stable_openapi.py verify", makefile)
        self.assertIn("tests/test_stable_openapi_contracts.py", makefile)
        self.assertIn("openapi-contracts", makefile.split("\nci:", 1)[1].split("\n", 1)[0])
        self.assertIn("run: make openapi-contracts", workflow)
        self.assertIn("pydantic==2.12.4", requirements.splitlines())


if __name__ == "__main__":
    unittest.main()
