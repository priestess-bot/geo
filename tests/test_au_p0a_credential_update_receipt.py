from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_credential_clearance import build_au_p0a_credential_clearance
from scripts.build_au_p0a_credential_fulfillment import build_au_p0a_credential_fulfillment
from scripts.build_au_p0a_credential_request_packet import build_au_p0a_credential_request_packet
from scripts.build_au_p0a_credential_update_receipt import (
    RECEIPT_VERSION,
    build_au_p0a_credential_update_receipt,
    compute_p0a_credential_update_receipt_hash,
)
from scripts.build_au_p0a_env_report import build_au_p0a_env_report
from scripts.run_au_external_dependency_clearance import run_au_external_dependency_clearance
from scripts.verify_au_p0a_credential_update_receipt import verify_au_p0a_credential_update_receipt
from tests.test_au_external_dependency_clearance import AuExternalDependencyClearanceTest
from tests.test_au_p0a_credential_request_packet import AuP0aCredentialRequestPacketTest


class AuP0aCredentialUpdateReceiptTest(unittest.TestCase):
    def _build_sources(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, Path, Path, Path, dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
        request_helper = AuP0aCredentialRequestPacketTest()
        request_helper.setUp()
        checklist_path, checklist = request_helper._write_execution_checklist(temp_dir, ready=ready)
        request_path = Path(temp_dir) / "credential-request.json"
        request = build_au_p0a_credential_request_packet(
            p0a_execution_checklist_path=checklist_path,
            p0a_execution_checklist=checklist,
            output_path=request_path,
            generated_at="2026-06-15T00:00:00Z",
        )
        request_path.write_text(json.dumps(request), encoding="utf-8")

        env_file = Path(temp_dir) / ".env.au-p0a"
        if ready:
            env_file.write_text(
                "\n".join(
                    [
                        "PERPLEXITY_API_KEY=perplexity-secret",
                        "OPENAI_API_KEY=openai-secret",
                        "DATABASE_URL=postgresql://user:pass@example.test/db",
                    ]
                ),
                encoding="utf-8",
            )
            env_file.chmod(0o600)
        env_path = Path(temp_dir) / "env-report.json"
        env_report = build_au_p0a_env_report(
            runbook_path=Path(temp_dir) / "runbook.json",
            env_file_path=env_file,
            output_path=env_path,
            env={},
            generated_at="2026-06-15T00:00:00Z",
        )
        env_path.write_text(json.dumps(env_report), encoding="utf-8")

        fulfillment_path = Path(temp_dir) / "credential-fulfillment.json"
        fulfillment = build_au_p0a_credential_fulfillment(
            credential_request_path=request_path,
            env_report_path=env_path,
            credential_request=request,
            env_report=env_report,
            output_path=fulfillment_path,
            generated_at="2026-06-15T00:00:00Z",
        )
        fulfillment_path.write_text(json.dumps(fulfillment), encoding="utf-8")

        clearance_helper = AuExternalDependencyClearanceTest()
        clearance_helper.setUp()
        external_dir = Path(temp_dir) / "external"
        external_dir.mkdir()
        handoff_path = clearance_helper._write_handoff(str(external_dir))
        external_clearance_path = external_dir / "external-clearance.json"
        external_clearance = run_au_external_dependency_clearance(
            handoff_path=handoff_path,
            output_path=external_clearance_path,
            generated_at="2026-06-15T00:00:00Z",
        )
        external_clearance_path.write_text(json.dumps(external_clearance), encoding="utf-8")

        clearance_path = Path(temp_dir) / "credential-clearance.json"
        clearance = build_au_p0a_credential_clearance(
            credential_request_path=request_path,
            env_report_path=env_path,
            credential_fulfillment_path=fulfillment_path,
            external_dependency_clearance_path=external_clearance_path,
            credential_request=request,
            credential_fulfillment=fulfillment,
            external_dependency_clearance=external_clearance,
            output_path=clearance_path,
            generated_at="2026-06-15T00:00:00Z",
        )
        clearance_path.write_text(json.dumps(clearance), encoding="utf-8")
        return request_path, env_path, fulfillment_path, clearance_path, request, env_report, fulfillment, clearance

    def test_receipt_records_blocked_update_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, env_report, fulfillment, clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            receipt = build_au_p0a_credential_update_receipt(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_fulfillment_path=fulfillment_path,
                credential_clearance_path=clearance_path,
                credential_request=request,
                env_report=env_report,
                credential_fulfillment=fulfillment,
                credential_clearance=clearance,
                output_path=Path(temp_dir) / "receipt.json",
                generated_at="2026-06-15T00:00:00Z",
            )
            verification = verify_au_p0a_credential_update_receipt(receipt)
            hard_gate = verify_au_p0a_credential_update_receipt(receipt, require_complete=True)

        self.assertEqual(receipt["p0a_credential_update_receipt_version"], RECEIPT_VERSION)
        self.assertEqual(receipt["status"], "pass")
        self.assertTrue(receipt["credential_update_receipt_ready"])
        self.assertFalse(receipt["credential_update_receipt_complete"])
        self.assertTrue(receipt["summary"]["credential_update_receipt_ready"])
        self.assertEqual(receipt["summary"]["missing_required_count"], 3)
        self.assertTrue(receipt["summary"]["credential_update_action_plan_ready"])
        self.assertTrue(receipt["summary"]["credential_update_action_required"])
        self.assertEqual(receipt["summary"]["credential_update_action_item_count"], 3)
        self.assertEqual(receipt["summary"]["credential_update_action_owner_counts"]["provider_admin"], 2)
        self.assertEqual(receipt["summary"]["credential_update_action_owner_counts"]["runtime_database_admin"], 1)
        self.assertGreaterEqual(receipt["summary"]["credential_update_post_update_validation_command_count"], 1)
        self.assertEqual(receipt["summary"]["next_command"], "make au-p0a-env")
        self.assertEqual(receipt["credential_update_action_plan"]["version"], "au_p0a_credential_update_action_plan_v1")
        self.assertTrue(receipt["credential_update_action_plan"]["ready"])
        self.assertTrue(receipt["credential_update_action_plan"]["action_required"])
        self.assertEqual(receipt["credential_update_action_plan"]["action_item_count"], 3)
        self.assertEqual(
            [item["credential_name"] for item in receipt["credential_update_action_plan"]["action_items"]],
            ["DATABASE_URL", "OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
        )
        for item in receipt["credential_update_action_plan"]["action_items"]:
            self.assertIn("gitignored_env_file", item["allowed_update_surface_ids"])
            self.assertIn("process_environment", item["allowed_update_surface_ids"])
            self.assertFalse(item["raw_secret_values_allowed"])
            self.assertTrue(item["secret_redacted"])
            self.assertTrue(item["strict_gate_command"].endswith("--require-complete"))
        self.assertEqual(
            receipt["runtime_endpoints"]["p0a_credential_update_receipt"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertIn("make verify-au-p0a-credential-update-receipt", receipt["strict_gate_commands"])
        self.assertEqual(
            receipt["p0a_credential_update_receipt_hash"],
            compute_p0a_credential_update_receipt_hash(receipt),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0a_credential_update_receipt_not_complete", hard_gate["errors"])
        serialized = json.dumps(receipt)
        self.assertNotIn('"raw_value":', serialized)
        self.assertNotIn("openai-secret", serialized)

    def test_receipt_passes_strict_gate_when_credentials_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, env_report, fulfillment, clearance = (
                self._build_sources(temp_dir, ready=True)
            )
            receipt = build_au_p0a_credential_update_receipt(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_fulfillment_path=fulfillment_path,
                credential_clearance_path=clearance_path,
                credential_request=request,
                env_report=env_report,
                credential_fulfillment=fulfillment,
                credential_clearance=clearance,
                output_path=Path(temp_dir) / "receipt.json",
                generated_at="2026-06-15T00:00:00Z",
            )
            hard_gate = verify_au_p0a_credential_update_receipt(receipt, require_complete=True)

        self.assertTrue(receipt["credential_update_receipt_complete"])
        self.assertTrue(receipt["summary"]["credential_update_receipt_ready"])
        self.assertEqual(receipt["summary"]["missing_required_count"], 0)
        self.assertFalse(receipt["summary"]["credential_update_action_required"])
        self.assertEqual(receipt["summary"]["credential_update_action_item_count"], 0)
        self.assertEqual(receipt["credential_update_action_plan"]["action_items"], [])
        self.assertEqual(receipt["summary"]["next_command"], "make au-external-dependency-clearance")
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_rejects_tampered_summary_ready_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, env_report, fulfillment, clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            receipt = build_au_p0a_credential_update_receipt(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_fulfillment_path=fulfillment_path,
                credential_clearance_path=clearance_path,
                credential_request=request,
                env_report=env_report,
                credential_fulfillment=fulfillment,
                credential_clearance=clearance,
                output_path=Path(temp_dir) / "receipt.json",
                generated_at="2026-06-15T00:00:00Z",
            )
            receipt["summary"]["credential_update_receipt_ready"] = False
            receipt["p0a_credential_update_receipt_hash"] = compute_p0a_credential_update_receipt_hash(receipt)
            verification = verify_au_p0a_credential_update_receipt(receipt)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_credential_update_receipt_ready_mismatch", verification["errors"])

    def test_verifier_rejects_tampered_raw_value_policy_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, env_report, fulfillment, clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            receipt = build_au_p0a_credential_update_receipt(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_fulfillment_path=fulfillment_path,
                credential_clearance_path=clearance_path,
                credential_request=request,
                env_report=env_report,
                credential_fulfillment=fulfillment,
                credential_clearance=clearance,
                output_path=Path(temp_dir) / "receipt.json",
                generated_at="2026-06-15T00:00:00Z",
            )
            receipt["required_credential_records"][0]["raw_value_recorded"] = True
            receipt["p0a_credential_update_receipt_hash"] = compute_p0a_credential_update_receipt_hash(receipt)
            verification = verify_au_p0a_credential_update_receipt(receipt)

        self.assertEqual(verification["status"], "fail")
        self.assertIn(
            "credential_record_raw_value_policy_invalid:DATABASE_URL",
            verification["errors"],
        )

    def test_verifier_rejects_tampered_action_plan_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, env_report, fulfillment, clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            receipt = build_au_p0a_credential_update_receipt(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_fulfillment_path=fulfillment_path,
                credential_clearance_path=clearance_path,
                credential_request=request,
                env_report=env_report,
                credential_fulfillment=fulfillment,
                credential_clearance=clearance,
                output_path=Path(temp_dir) / "receipt.json",
                generated_at="2026-06-15T00:00:00Z",
            )
            receipt["credential_update_action_plan"]["action_items"][0]["strict_gate_command"] = "tampered"
            receipt["summary"]["credential_update_action_item_count"] = 99
            receipt["p0a_credential_update_receipt_hash"] = compute_p0a_credential_update_receipt_hash(receipt)
            verification = verify_au_p0a_credential_update_receipt(receipt)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_credential_update_action_item_count_mismatch", verification["errors"])
        self.assertIn("credential_update_action_item_strict_gate_invalid:DATABASE_URL", verification["errors"])

    def test_cli_writes_and_verifies_receipt_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, *_rest = self._build_sources(temp_dir, ready=False)
            output_path = Path(temp_dir) / "receipt.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_credential_update_receipt.py",
                    "--credential-request-path",
                    str(request_path),
                    "--env-report-path",
                    str(env_path),
                    "--credential-fulfillment-path",
                    str(fulfillment_path),
                    "--credential-clearance-path",
                    str(clearance_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-15T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            verify_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0a_credential_update_receipt.py",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(build_result.stdout)
            verification = json.loads(verify_result.stdout)
            output_exists = output_path.exists()

        self.assertTrue(output_exists)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(verification["status"], "pass")


if __name__ == "__main__":
    unittest.main()
