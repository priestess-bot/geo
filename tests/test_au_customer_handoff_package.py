from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_customer_handoff_package import (
    DEFAULT_OUTPUT_PATH,
    PACKAGE_VERSION,
    build_au_customer_handoff_package,
    compute_customer_handoff_package_hash,
)
from scripts.verify_au_customer_handoff_package import verify_au_customer_handoff_package


class AuCustomerHandoffPackageTest(unittest.TestCase):
    def test_package_indexes_current_customer_handoff_sources_without_marking_ready(self) -> None:
        package = build_au_customer_handoff_package(generated_at="2026-06-15T00:00:00Z")
        verification = verify_au_customer_handoff_package(package)

        self.assertEqual(package["customer_handoff_package_version"], PACKAGE_VERSION)
        self.assertEqual(package["status"], "pass")
        self.assertTrue(package["customer_handoff_package_manifest_ready"])
        self.assertFalse(package["customer_handoff_package_ready"])
        self.assertFalse(package["ready_for_report_export_handoff"])
        self.assertFalse(package["ready_for_customer_delivery"])
        self.assertEqual(package["next_action"], "clear_customer_handoff_prerequisites_first")
        self.assertEqual(package["customer_handoff_package_hash"], compute_customer_handoff_package_hash(package))
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(verification["hash_valid"])
        self.assertEqual(package["summary"]["source_artifact_count"], 15)
        self.assertEqual(package["summary"]["blocked_source_artifact_count"], 0)
        self.assertEqual(package["summary"]["engineering_progress_percent"], 46.2)
        self.assertEqual(package["summary"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertEqual(package["summary"]["structural_auditability_percent"], 100.0)
        self.assertEqual(package["summary"]["missing_required_count"], 9)
        self.assertEqual(package["summary"]["next_command"], "make au-p0a-env")
        self.assertIn("customer_handoff_clearance", package["source_artifacts"])
        self.assertIn("p0c_report_package", package["source_artifacts"])
        self.assertIn("handoff_dossier_markdown", package["source_artifacts"])
        self.assertEqual(
            package["source_artifacts"]["customer_handoff_clearance"]["hash"],
            package["summary"]["customer_handoff_clearance_hash"],
        )
        self.assertEqual(
            package["source_artifacts"]["p0c_report_package"]["hash"],
            package["summary"]["p0c_report_package_hash"],
        )
        self.assertEqual(
            package["runtime_endpoints"]["customer_handoff_package"],
            "GET /v1/customer-handoff-package/au",
        )
        self.assertIn("make verify-au-customer-handoff-package", package["hard_gate_commands"])
        self.assertFalse(package["redaction_policy"]["source_payloads_embedded"])
        self.assertTrue(package["redaction_policy"]["hash_path_status_only"])

    def test_require_ready_fails_until_customer_handoff_clearance_is_ready(self) -> None:
        package = build_au_customer_handoff_package(generated_at="2026-06-15T00:00:00Z")

        verification = verify_au_customer_handoff_package(package, require_ready=True)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("customer_handoff_package_not_ready", verification["errors"])
        self.assertTrue(verification["customer_handoff_package_manifest_ready"])
        self.assertFalse(verification["customer_handoff_package_ready"])

    def test_verifier_detects_hash_and_summary_tampering(self) -> None:
        package = build_au_customer_handoff_package(generated_at="2026-06-15T00:00:00Z")
        package["summary"]["source_artifact_count"] = 1
        package["source_artifacts"]["delivery_progress"]["hash"] = "tampered"

        verification = verify_au_customer_handoff_package(package)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("customer_handoff_package_hash_mismatch", verification["errors"])
        self.assertIn("source_verifier_hash_mismatch:delivery_progress", verification["errors"])
        self.assertIn("summary_source_artifact_count_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_customer_handoff_package(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "customer-handoff-package.json"
            env = os.environ.copy()
            env["PYTHONPATH"] = "packages/geno_core:apps/api"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_customer_handoff_package.py",
                    "--output-path",
                    str(output_path),
                ],
                check=False,
                text=True,
                capture_output=True,
                env=env,
            )
            verify_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_customer_handoff_package.py",
                    str(output_path),
                ],
                check=False,
                text=True,
                capture_output=True,
                env=env,
            )

        self.assertEqual(build_result.returncode, 0, build_result.stderr)
        self.assertEqual(verify_result.returncode, 0, verify_result.stderr)
        payload = json.loads(build_result.stdout)
        verifier_payload = json.loads(verify_result.stdout)
        self.assertEqual(payload["output_path"], str(output_path))
        self.assertEqual(payload["customer_handoff_package_hash"], compute_customer_handoff_package_hash(payload))
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertTrue(verifier_payload["customer_handoff_package_manifest_ready"])
        self.assertFalse(verifier_payload["customer_handoff_package_ready"])

    def test_default_output_path_is_runtime_preflight_customer_package(self) -> None:
        self.assertEqual(DEFAULT_OUTPUT_PATH, "docs/runtime_preflight/au-customer-handoff-package-latest.json")


if __name__ == "__main__":
    unittest.main()
