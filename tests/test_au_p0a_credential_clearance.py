from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_credential_clearance import (
    CLEARANCE_VERSION,
    build_au_p0a_credential_clearance,
    compute_p0a_credential_clearance_hash,
)
from scripts.build_au_p0a_credential_fulfillment import build_au_p0a_credential_fulfillment
from scripts.build_au_p0a_credential_request_packet import build_au_p0a_credential_request_packet
from scripts.build_au_p0a_env_report import build_au_p0a_env_report
from scripts.run_au_external_dependency_clearance import run_au_external_dependency_clearance
from scripts.verify_au_p0a_credential_clearance import verify_au_p0a_credential_clearance
from tests.test_au_external_dependency_clearance import AuExternalDependencyClearanceTest
from tests.test_au_p0a_credential_request_packet import AuP0aCredentialRequestPacketTest


class AuP0aCredentialClearanceTest(unittest.TestCase):
    def _build_sources(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, Path, Path, Path, dict[str, object], dict[str, object], dict[str, object]]:
        request_helper = AuP0aCredentialRequestPacketTest()
        request_helper.setUp()
        checklist_path, checklist = request_helper._write_execution_checklist(temp_dir, ready=ready)
        request_path = Path(temp_dir) / "credential-request.json"
        request = build_au_p0a_credential_request_packet(
            p0a_execution_checklist_path=checklist_path,
            p0a_execution_checklist=checklist,
            output_path=request_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        request_path.write_text(json.dumps(request), encoding="utf-8")
        env_path = Path(temp_dir) / "env-report.json"
        env_report = build_au_p0a_env_report(
            runbook_path=Path(temp_dir) / "runbook.json",
            env_file_path=Path(temp_dir) / "missing.env",
            output_path=env_path,
            env={
                "PERPLEXITY_API_KEY": "perplexity-key",
                "OPENAI_API_KEY": "openai-key",
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
            }
            if ready
            else {},
            generated_at="2026-06-14T00:00:00Z",
        )
        env_path.write_text(json.dumps(env_report), encoding="utf-8")
        fulfillment_path = Path(temp_dir) / "credential-fulfillment.json"
        fulfillment = build_au_p0a_credential_fulfillment(
            credential_request_path=request_path,
            env_report_path=env_path,
            credential_request=request,
            env_report=env_report,
            output_path=fulfillment_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        fulfillment_path.write_text(json.dumps(fulfillment), encoding="utf-8")

        clearance_helper = AuExternalDependencyClearanceTest()
        clearance_helper.setUp()
        external_dir = Path(temp_dir) / "external"
        external_dir.mkdir()
        handoff_path = clearance_helper._write_handoff(str(external_dir))
        clearance_path = external_dir / "external-clearance.json"
        external_clearance = run_au_external_dependency_clearance(
            handoff_path=handoff_path,
            output_path=clearance_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        clearance_path.write_text(json.dumps(external_clearance), encoding="utf-8")
        return request_path, env_path, fulfillment_path, clearance_path, request, fulfillment, external_clearance

    def test_clearance_packet_records_current_missing_credentials_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0a_credential_clearance(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                credential_request=request,
                credential_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "credential-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            verification = verify_au_p0a_credential_clearance(packet)
            hard_gate = verify_au_p0a_credential_clearance(packet, require_cleared=True)

        self.assertEqual(packet["p0a_credential_clearance_version"], CLEARANCE_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["credential_clearance_packet_ready"])
        self.assertFalse(packet["credential_clearance_ready"])
        self.assertFalse(packet["credentials_fulfilled"])
        self.assertTrue(packet["summary"]["target_env_file"].endswith("missing.env"))
        self.assertEqual(packet["summary"]["missing_required_count"], 3)
        self.assertEqual(
            packet["summary"]["missing_required"],
            ["DATABASE_URL", "OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
        )
        self.assertEqual(packet["summary"]["provider_missing_required"], ["OPENAI_API_KEY", "PERPLEXITY_API_KEY"])
        self.assertEqual(packet["summary"]["runtime_database_missing_required"], ["DATABASE_URL"])
        self.assertEqual(packet["summary"]["current_clearance_step_id"], "p0a_provider_credentials")
        self.assertEqual(packet["summary"]["next_action"], "populate_required_p0a_credentials")
        self.assertEqual(packet["summary"]["next_command"], "make au-p0a-env")
        self.assertIn("make verify-au-p0a-env-template", [step["command"] for step in packet["operator_steps"]])
        self.assertIn("make au-p0a-env", packet["post_update_validation_sequence"])
        self.assertTrue(any("--require-fulfilled" in command for command in packet["post_update_validation_sequence"]))
        self.assertEqual(
            packet["runtime_endpoints"]["p0a_credential_clearance"],
            "GET /v1/p0a-credential-clearance/au",
        )
        self.assertIn("make verify-au-p0a-credential-clearance", packet["hard_gate_commands"])
        self.assertTrue(any("--require-cleared" in command for command in packet["hard_gate_commands"]))
        self.assertEqual(
            packet["p0a_credential_clearance_hash"],
            compute_p0a_credential_clearance_hash(packet),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0a_credentials_not_cleared", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn('"raw_value":', serialized)
        self.assertNotIn("perplexity-key", serialized)

    def test_clearance_packet_passes_strict_gate_when_credentials_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=True)
            )
            packet = build_au_p0a_credential_clearance(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                credential_request=request,
                credential_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "credential-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            hard_gate = verify_au_p0a_credential_clearance(packet, require_cleared=True)

        self.assertTrue(packet["credentials_fulfilled"])
        self.assertTrue(packet["credential_clearance_ready"])
        self.assertEqual(packet["summary"]["missing_required_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_rejects_tampered_missing_count_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0a_credential_clearance(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                credential_request=request,
                credential_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "credential-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            packet["summary"]["missing_required_count"] = 0
            packet["p0a_credential_clearance_hash"] = compute_p0a_credential_clearance_hash(packet)
            verification = verify_au_p0a_credential_clearance(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_missing_required_count_mismatch", verification["errors"])

    def test_path_verifier_detects_stale_fulfillment_source_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            output_path = Path(temp_dir) / "credential-clearance.json"
            packet = build_au_p0a_credential_clearance(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                output_path=output_path,
                generated_at="2026-06-14T00:00:00Z",
            )
            output_path.write_text(json.dumps(packet), encoding="utf-8")
            memory_verification = verify_au_p0a_credential_clearance(packet)

            refreshed_env = build_au_p0a_env_report(
                runbook_path=Path(temp_dir) / "runbook.json",
                env_file_path=Path(temp_dir) / "missing.env",
                output_path=env_path,
                env={
                    "PERPLEXITY_API_KEY": "perplexity-key",
                    "OPENAI_API_KEY": "openai-key",
                    "DATABASE_URL": "postgresql://user:pass@example.test/db",
                },
                generated_at="2026-06-14T00:01:00Z",
            )
            env_path.write_text(json.dumps(refreshed_env), encoding="utf-8")
            refreshed_fulfillment = build_au_p0a_credential_fulfillment(
                credential_request_path=request_path,
                env_report_path=env_path,
                output_path=fulfillment_path,
                generated_at="2026-06-14T00:01:00Z",
            )
            fulfillment_path.write_text(json.dumps(refreshed_fulfillment), encoding="utf-8")
            path_verification = verify_au_p0a_credential_clearance(packet, path=output_path)
            explicit_verification = verify_au_p0a_credential_clearance(packet, verify_current_files=True)

        self.assertEqual(memory_verification["status"], "pass")
        self.assertFalse(memory_verification["current_file_check_enabled"])
        self.assertEqual(path_verification["status"], "fail")
        self.assertTrue(path_verification["current_file_check_enabled"])
        self.assertIn("source_fulfillment_current_hash_mismatch", path_verification["errors"])
        self.assertIn("source_fulfillment_file_sha256_mismatch", path_verification["errors"])
        self.assertEqual(explicit_verification["status"], "fail")
        self.assertTrue(explicit_verification["current_file_check_enabled"])
        self.assertIn("source_fulfillment_current_hash_mismatch", explicit_verification["errors"])

    def test_cli_writes_and_verifies_clearance_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, _request, _fulfillment, _external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            output_path = Path(temp_dir) / "credential-clearance.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_credential_clearance.py",
                    "--credential-request-path",
                    str(request_path),
                    "--env-report-path",
                    str(env_path),
                    "--credential-fulfillment-path",
                    str(fulfillment_path),
                    "--external-dependency-clearance-path",
                    str(clearance_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-14T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            verify_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0a_credential_clearance.py",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            output_exists = output_path.exists()
            payload = json.loads(build_result.stdout)
            verification = json.loads(verify_result.stdout)

        self.assertTrue(output_exists)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(verification["status"], "pass")


if __name__ == "__main__":
    unittest.main()
