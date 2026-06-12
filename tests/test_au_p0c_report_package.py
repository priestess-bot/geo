from __future__ import annotations

import json
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from scripts.build_au_p0c_report_package import (
    PACKAGE_VERSION,
    build_au_p0c_report_package,
    compute_p0c_report_package_hash,
)
from scripts.verify_au_p0c_report_package import verify_au_p0c_report_package


class AuP0cReportPackageTest(unittest.TestCase):
    def test_report_package_builds_customer_handoff_contract(self) -> None:
        package = build_au_p0c_report_package(generated_at="2026-06-12T00:00:00Z", prompt_limit=2)
        verification = verify_au_p0c_report_package(package, require_ready=True)

        self.assertEqual(package["package_version"], PACKAGE_VERSION)
        self.assertEqual(package["status"], "pass")
        self.assertTrue(package["p0c_report_contract_ready"])
        self.assertEqual(package["next_action"], "ready_for_p0c_customer_report_handoff")
        self.assertEqual(package["remaining_blockers"], [])
        self.assertEqual(package["package_payload_hash"], compute_p0c_report_package_hash(package))
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(verification["hash_valid"])
        self.assertTrue(verification["p0c_report_contract_ready"])
        self.assertEqual(package["report_export"]["market_code"], "AU")
        self.assertEqual(package["report_export"]["api_browser_fidelity_status"], "sampled")
        self.assertEqual(package["report_export"]["google_coverage"], "limited_coverage_appendix_only")
        self.assertGreater(package["context"]["excluded_fidelity_sample_record_count"], 0)
        self.assertEqual(package["summary"]["failed_artifacts"], [])
        self.assertIn("white_label_pdf", package["summary"]["ready_artifacts"])
        self.assertEqual(package["artifacts"]["method_disclosure_contract"]["checks"]["api_browser_fidelity_sampled"], True)
        self.assertEqual(package["artifacts"]["audit_summary_contract"]["checks"]["visibility_score_audit_present"], True)
        self.assertEqual(package["artifacts"]["traceability_contract"]["checks"]["graph_has_source_nodes"], True)

    def test_verifier_detects_hash_and_summary_tampering(self) -> None:
        package = build_au_p0c_report_package(generated_at="2026-06-12T00:00:00Z", prompt_limit=1)
        package["summary"]["failed_artifacts"] = ["markdown"]

        verification = verify_au_p0c_report_package(package)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("package_payload_hash_mismatch", verification["errors"])
        self.assertIn("summary_failed_artifacts_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_report_package(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "p0c-report-package.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0c_report_package.py",
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                    "--prompt-limit",
                    "1",
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            verify_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0c_report_package.py",
                    str(output_path),
                    "--require-ready",
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(build_result.returncode, 0, build_result.stderr)
        self.assertEqual(verify_result.returncode, 0, verify_result.stderr)
        payload = json.loads(build_result.stdout)
        verifier_payload = json.loads(verify_result.stdout)
        self.assertEqual(payload["package_payload_hash"], compute_p0c_report_package_hash(payload))
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertTrue(verifier_payload["p0c_report_contract_ready"])


if __name__ == "__main__":
    unittest.main()
