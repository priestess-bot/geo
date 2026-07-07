from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_customer_handoff_package import (
    DEFAULT_MARKDOWN_OUTPUT_PATH,
    DEFAULT_OUTPUT_PATH,
    PACKAGE_VERSION,
    build_au_customer_handoff_package,
    compute_customer_handoff_package_hash,
)
from scripts.run_au_external_dependency_clearance import (
    P0A_COMPLETION_CONTRACT_VERSION,
    P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
    P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE,
    P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT,
)
from scripts.verify_au_customer_handoff_package import verify_au_customer_handoff_package


class AuCustomerHandoffPackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.skipTest(
            "Legacy AU runtime_preflight customer handoff package is archived; "
            "Production v1 gates cover the current GEO workflow."
        )

    def test_package_indexes_current_customer_handoff_sources_without_marking_ready(self) -> None:
        with TemporaryDirectory() as tmpdir:
            markdown_output_path = Path(tmpdir) / "not-written-yet.md"
            package = build_au_customer_handoff_package(
                generated_at="2026-06-15T00:00:00Z",
                markdown_output_path=markdown_output_path,
            )
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
        self.assertEqual(package["summary"]["source_artifact_count"], 17)
        self.assertEqual(package["summary"]["blocked_source_artifact_count"], 0)
        self.assertEqual(package["summary"]["engineering_progress_percent"], 46.2)
        self.assertEqual(package["summary"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertEqual(package["summary"]["structural_auditability_percent"], 100.0)
        self.assertEqual(package["summary"]["missing_required_count"], 9)
        self.assertEqual(package["summary"]["next_command"], "make au-p0a-env")
        clearance_verifier = package["verifiers"]["customer_handoff_clearance"]
        self.assertEqual(package["summary"]["current_clearance_request_artifact_id"], "p0a_credential_request")
        self.assertEqual(
            package["summary"]["current_clearance_request_artifact_hash"],
            clearance_verifier["current_clearance_request_artifact_hash"],
        )
        self.assertTrue(package["summary"]["current_clearance_completion_contract_ready"])
        self.assertEqual(
            package["summary"]["current_clearance_completion_contract_version"],
            P0A_COMPLETION_CONTRACT_VERSION,
        )
        self.assertTrue(package["summary"]["current_clearance_credential_update_receipt_required"])
        self.assertEqual(
            package["summary"]["current_clearance_credential_update_receipt_endpoint"],
            P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
        )
        self.assertEqual(
            package["summary"]["current_clearance_credential_update_receipt_strict_gate"],
            P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE,
        )
        self.assertEqual(
            package["summary"]["current_clearance_post_update_validation_command_count"],
            P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT,
        )
        self.assertEqual(
            package["summary"]["current_clearance_completion_contract_missing_required_count"],
            clearance_verifier["current_clearance_completion_contract_missing_required_count"],
        )
        self.assertFalse(package["summary"]["current_clearance_completion_contract_raw_secret_values_allowed"])
        self.assertIn("customer_handoff_clearance", package["source_artifacts"])
        self.assertIn("next_work_item", package["source_artifacts"])
        self.assertIn("p0a_credential_update_receipt", package["source_artifacts"])
        self.assertIn("p0c_report_package", package["source_artifacts"])
        self.assertIn("handoff_dossier_markdown", package["source_artifacts"])
        self.assertEqual(
            package["source_artifacts"]["customer_handoff_clearance"]["hash"],
            package["summary"]["customer_handoff_clearance_hash"],
        )
        self.assertEqual(
            package["source_artifacts"]["next_work_item"]["hash_field"],
            "next_work_item_packet_hash",
        )
        self.assertEqual(
            package["source_artifacts"]["next_work_item"]["hash"],
            package["summary"]["next_work_item_packet_hash"],
        )
        self.assertTrue(package["source_artifacts"]["next_work_item"]["hash_valid"])
        self.assertEqual(package["verifiers"]["next_work_item"]["status"], "pass")
        self.assertEqual(
            package["source_artifacts"]["p0c_report_package"]["hash"],
            package["summary"]["p0c_report_package_hash"],
        )
        self.assertEqual(
            package["source_artifacts"]["p0a_credential_update_receipt"]["hash_field"],
            "p0a_credential_update_receipt_hash",
        )
        self.assertEqual(
            package["source_artifacts"]["p0a_credential_update_receipt"]["hash"],
            package["summary"]["p0a_credential_update_receipt_hash"],
        )
        self.assertTrue(package["source_artifacts"]["p0a_credential_update_receipt"]["hash_valid"])
        self.assertEqual(package["verifiers"]["p0a_credential_update_receipt"]["status"], "pass")
        self.assertEqual(
            package["runtime_endpoints"]["customer_handoff_package"],
            "GET /v1/customer-handoff-package/au",
        )
        self.assertEqual(
            package["runtime_endpoints"]["p0a_credential_update_receipt"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertEqual(package["runtime_endpoints"]["next_work_item"], "GET /v1/next-work-item/au")
        self.assertIn("make au-next-work-item", package["post_update_validation_sequence"])
        self.assertIn("make verify-au-next-work-item", package["post_update_validation_sequence"])
        self.assertIn("make au-next-work-item", package["hard_gate_commands"])
        self.assertIn("make verify-au-next-work-item", package["hard_gate_commands"])
        self.assertIn("make au-p0a-credential-update-receipt", package["post_update_validation_sequence"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", package["post_update_validation_sequence"])
        self.assertIn("make au-p0a-credential-update-receipt", package["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", package["hard_gate_commands"])
        self.assertTrue(any("--require-complete" in command for command in package["hard_gate_commands"]))
        self.assertIn(P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE, package["hard_gate_commands"])
        self.assertTrue(any(step["id"] == "refresh_next_work_item" for step in package["operator_steps"]))
        self.assertTrue(
            any(step["id"] == "refresh_p0a_credential_update_receipt" for step in package["operator_steps"])
        )
        self.assertIn("make verify-au-customer-handoff-package", package["hard_gate_commands"])
        self.assertEqual(package["customer_handoff_package_markdown"]["artifact_type"], "markdown")
        self.assertEqual(package["customer_handoff_package_markdown"]["path"], str(markdown_output_path))
        self.assertFalse(package["customer_handoff_package_markdown"]["exists"])
        self.assertTrue(package["customer_handoff_package_markdown"]["file_sha256"])
        self.assertEqual(
            verification["customer_handoff_package_markdown_sha256"],
            package["customer_handoff_package_markdown"]["file_sha256"],
        )
        self.assertEqual(
            verification["customer_handoff_package_markdown_path"],
            str(markdown_output_path),
        )
        self.assertEqual(
            verification["current_clearance_request_artifact_hash"],
            package["summary"]["current_clearance_request_artifact_hash"],
        )
        self.assertEqual(
            verification["current_clearance_completion_contract_version"],
            P0A_COMPLETION_CONTRACT_VERSION,
        )
        self.assertFalse(verification["current_clearance_completion_contract_raw_secret_values_allowed"])
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

    def test_verifier_detects_markdown_manifest_tampering_even_when_hash_recomputed(self) -> None:
        package = build_au_customer_handoff_package(generated_at="2026-06-15T00:00:00Z")
        package["customer_handoff_package_markdown"]["file_sha256"] = "tampered"
        package["customer_handoff_package_markdown"]["hash"] = "tampered"
        package["customer_handoff_package_hash"] = compute_customer_handoff_package_hash(package)

        verification = verify_au_customer_handoff_package(package)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("customer_handoff_package_markdown_hash_mismatch", verification["errors"])
        self.assertIn("customer_handoff_package_markdown_file_sha256_mismatch", verification["errors"])

    def test_verifier_detects_next_work_item_summary_hash_tampering(self) -> None:
        package = build_au_customer_handoff_package(generated_at="2026-06-15T00:00:00Z")
        package["summary"]["next_work_item_packet_hash"] = "tampered"
        package["customer_handoff_package_hash"] = compute_customer_handoff_package_hash(package)

        verification = verify_au_customer_handoff_package(package)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_source_hash_mismatch:next_work_item", verification["errors"])

    def test_verifier_detects_current_clearance_contract_tampering(self) -> None:
        package = build_au_customer_handoff_package(generated_at="2026-06-15T00:00:00Z")
        package["summary"]["current_clearance_completion_contract_version"] = "tampered"
        package["customer_handoff_package_hash"] = compute_customer_handoff_package_hash(package)

        verification = verify_au_customer_handoff_package(package)

        self.assertEqual(verification["status"], "fail")
        self.assertIn(
            "summary_current_clearance_completion_contract_version_mismatch",
            verification["errors"],
        )
        self.assertIn(
            "summary_delivery_progress_current_clearance_completion_contract_version_mismatch",
            verification["errors"],
        )
        self.assertIn("summary_current_clearance_completion_contract_version_invalid", verification["errors"])

    def test_cli_writes_and_verifies_customer_handoff_package(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "customer-handoff-package.json"
            markdown_output_path = Path(tmpdir) / "customer-handoff-package.md"
            env = os.environ.copy()
            env["PYTHONPATH"] = "packages/geno_core:apps/api"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_customer_handoff_package.py",
                    "--output-path",
                    str(output_path),
                    "--markdown-output-path",
                    str(markdown_output_path),
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
            markdown_exists = markdown_output_path.is_file()
            markdown_text = markdown_output_path.read_text(encoding="utf-8") if markdown_exists else ""
            payload = json.loads(build_result.stdout)
            verifier_payload = json.loads(verify_result.stdout)

        self.assertEqual(build_result.returncode, 0, build_result.stderr)
        self.assertEqual(verify_result.returncode, 0, verify_result.stderr)
        self.assertTrue(markdown_exists)
        self.assertIn("AU Customer Handoff Package Manifest", markdown_text)
        self.assertIn("Current clearance request", markdown_text)
        self.assertIn("Current receipt strict gate", markdown_text)
        self.assertIn("Customer-Visible Artifacts", markdown_text)
        self.assertEqual(payload["output_path"], str(output_path))
        self.assertEqual(payload["customer_handoff_package_markdown"]["path"], str(markdown_output_path))
        self.assertTrue(payload["customer_handoff_package_markdown"]["exists"])
        self.assertEqual(payload["customer_handoff_package_hash"], compute_customer_handoff_package_hash(payload))
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertTrue(verifier_payload["customer_handoff_package_manifest_ready"])
        self.assertFalse(verifier_payload["customer_handoff_package_ready"])

    def test_default_output_path_is_runtime_preflight_customer_package(self) -> None:
        self.assertEqual(DEFAULT_OUTPUT_PATH, "docs/runtime_preflight/au-customer-handoff-package-latest.json")
        self.assertEqual(
            DEFAULT_MARKDOWN_OUTPUT_PATH,
            "docs/runtime_preflight/au-customer-handoff-package-latest.md",
        )

    def test_markdown_manifest_can_be_indexed_without_output_path(self) -> None:
        package = build_au_customer_handoff_package(
            generated_at="2026-06-15T00:00:00Z",
            markdown_output_path=None,
        )
        verification = verify_au_customer_handoff_package(package)

        self.assertEqual(package["customer_handoff_package_markdown"]["path"], "")
        self.assertFalse(package["customer_handoff_package_markdown"]["exists"])
        self.assertEqual(verification["status"], "fail")
        self.assertIn("customer_handoff_package_markdown_path_missing", verification["errors"])


if __name__ == "__main__":
    unittest.main()
