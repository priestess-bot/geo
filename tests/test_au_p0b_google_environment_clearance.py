from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_environment_clearance import (
    CLEARANCE_VERSION,
    build_au_p0b_google_environment_clearance,
    compute_p0b_google_environment_clearance_hash,
)
from scripts.build_au_p0b_google_environment_fulfillment import build_au_p0b_google_environment_fulfillment
from scripts.run_au_external_dependency_clearance import run_au_external_dependency_clearance
from scripts.verify_au_p0b_google_environment_clearance import verify_au_p0b_google_environment_clearance
from tests.test_au_external_dependency_clearance import AuExternalDependencyClearanceTest
from tests.test_au_p0b_google_environment_fulfillment import AuP0bGoogleEnvironmentFulfillmentTest


class AuP0bGoogleEnvironmentClearanceTest(unittest.TestCase):
    def _build_sources(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, Path, Path, Path, dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
        fulfillment_helper = AuP0bGoogleEnvironmentFulfillmentTest()
        fulfillment_helper.setUp()
        request_path, env_path, request, env_report = fulfillment_helper._write_request_and_env(temp_dir, ready=ready)
        fulfillment_path = Path(temp_dir) / "environment-fulfillment.json"
        fulfillment = build_au_p0b_google_environment_fulfillment(
            environment_request_path=request_path,
            playwright_env_report_path=env_path,
            environment_request=request,
            playwright_env_report=env_report,
            output_path=fulfillment_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        fulfillment_path.write_text(json.dumps(fulfillment), encoding="utf-8")
        clearance_helper = AuExternalDependencyClearanceTest()
        clearance_helper.setUp()
        handoff_path = clearance_helper._write_handoff(temp_dir)
        clearance_path = Path(temp_dir) / "external-clearance.json"
        external_clearance = run_au_external_dependency_clearance(
            handoff_path=handoff_path,
            output_path=clearance_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        clearance_path.write_text(json.dumps(external_clearance), encoding="utf-8")
        return request_path, env_path, fulfillment_path, clearance_path, request, env_report, fulfillment, external_clearance

    def test_clearance_packet_records_blocked_google_environment_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, env_report, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0b_google_environment_clearance(
                environment_request_path=request_path,
                playwright_env_report_path=env_path,
                environment_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                environment_request=request,
                playwright_env_report=env_report,
                environment_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "environment-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            verification = verify_au_p0b_google_environment_clearance(packet)
            hard_gate = verify_au_p0b_google_environment_clearance(packet, require_cleared=True)

        self.assertEqual(packet["p0b_google_environment_clearance_version"], CLEARANCE_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["environment_clearance_packet_ready"])
        self.assertFalse(packet["environment_fulfilled"])
        self.assertFalse(packet["environment_clearance_ready"])
        self.assertFalse(packet["ready_for_next_clearance_step"])
        self.assertTrue(packet["blocked_by_prerequisite_step"])
        self.assertEqual(packet["clearance_step"]["id"], "p0b_google_environment")
        self.assertEqual(packet["prerequisite_step"]["id"], "p0a_real_batches")
        self.assertEqual(packet["summary"]["missing_required_count"], 6)
        self.assertIn("environment:DATABASE_URL", packet["summary"]["missing_required"])
        self.assertIn("selector:google_aio_prompt_selector", packet["summary"]["missing_required"])
        self.assertTrue(packet["summary"]["database_url_reuse_available"])
        self.assertEqual(packet["summary"]["next_action"], "clear_p0a_real_batches_first")
        self.assertEqual(packet["summary"]["next_command"], "make au-p0a-real-batch-clearance")
        self.assertIn("make au-p0b-google-playwright-env", packet["post_update_validation_sequence"])
        self.assertIn("make verify-au-p0b-google-environment-fulfillment", packet["post_update_validation_sequence"])
        self.assertTrue(any("--require-fulfilled" in command for command in packet["post_update_validation_sequence"]))
        self.assertTrue(any("--require-ready-smoke" in command for command in packet["post_update_validation_sequence"]))
        self.assertEqual(
            packet["runtime_endpoints"]["p0b_google_environment_clearance"],
            "GET /v1/p0b-google-environment-clearance/au",
        )
        self.assertIn("make verify-au-p0b-google-environment-clearance", packet["hard_gate_commands"])
        self.assertTrue(any("--require-cleared" in command for command in packet["hard_gate_commands"]))
        self.assertEqual(
            packet["p0b_google_environment_clearance_hash"],
            compute_p0b_google_environment_clearance_hash(packet),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0b_google_environment_not_cleared", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn("postgresql://", serialized)
        self.assertNotIn("#prompt", serialized)
        self.assertNotIn(".answer", serialized)
        self.assertNotIn('"selector_value":', serialized)

    def test_clearance_packet_passes_strict_gate_when_environment_and_prerequisite_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, env_report, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=True)
            )
            for step in external_clearance["steps"]:
                if step["id"] in {"p0a_provider_credentials", "p0a_real_batches", "p0b_google_environment"}:
                    step["ready"] = True
                    step["can_start"] = True
                    step["status"] = "already_ready"
                    step["would_execute"] = False
                    step["blocked_by"] = []
            packet = build_au_p0b_google_environment_clearance(
                environment_request_path=request_path,
                playwright_env_report_path=env_path,
                environment_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                environment_request=request,
                playwright_env_report=env_report,
                environment_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "environment-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            hard_gate = verify_au_p0b_google_environment_clearance(packet, require_cleared=True)

        self.assertTrue(packet["environment_fulfilled"])
        self.assertTrue(packet["ready_for_next_clearance_step"])
        self.assertTrue(packet["environment_clearance_ready"])
        self.assertFalse(packet["blocked_by_prerequisite_step"])
        self.assertEqual(packet["summary"]["missing_required_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_rejects_tampered_missing_count_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, request, env_report, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0b_google_environment_clearance(
                environment_request_path=request_path,
                playwright_env_report_path=env_path,
                environment_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                environment_request=request,
                playwright_env_report=env_report,
                environment_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                generated_at="2026-06-14T00:00:00Z",
            )
            packet["summary"]["missing_required_count"] = 0
            packet["p0b_google_environment_clearance_hash"] = compute_p0b_google_environment_clearance_hash(packet)
            verification = verify_au_p0b_google_environment_clearance(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_missing_required_count_mismatch", verification["errors"])

    def test_path_verifier_detects_stale_environment_source_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, _request, _env_report, _fulfillment, _external = (
                self._build_sources(temp_dir, ready=False)
            )
            output_path = Path(temp_dir) / "environment-clearance.json"
            packet = build_au_p0b_google_environment_clearance(
                environment_request_path=request_path,
                playwright_env_report_path=env_path,
                environment_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                output_path=output_path,
                generated_at="2026-06-14T00:00:00Z",
            )
            output_path.write_text(json.dumps(packet), encoding="utf-8")
            stale_env_report = json.loads(env_path.read_text(encoding="utf-8"))
            stale_env_report["environment_report_hash"] = "0" * 64
            env_path.write_text(json.dumps(stale_env_report), encoding="utf-8")

            memory_verification = verify_au_p0b_google_environment_clearance(packet)
            path_verification = verify_au_p0b_google_environment_clearance(packet, path=output_path)
            explicit_verification = verify_au_p0b_google_environment_clearance(packet, verify_current_files=True)

        self.assertEqual(memory_verification["status"], "pass")
        self.assertFalse(memory_verification["current_file_check_enabled"])
        self.assertEqual(path_verification["status"], "fail")
        self.assertTrue(path_verification["current_file_check_enabled"])
        self.assertIn("source_playwright_env_report_current_hash_mismatch", path_verification["errors"])
        self.assertIn("source_playwright_env_report_file_sha256_mismatch", path_verification["errors"])
        self.assertEqual(explicit_verification["status"], "fail")
        self.assertTrue(explicit_verification["current_file_check_enabled"])

    def test_cli_writes_and_verifies_clearance_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, fulfillment_path, clearance_path, _request, _env_report, _fulfillment, _external = (
                self._build_sources(temp_dir, ready=False)
            )
            output_path = Path(temp_dir) / "environment-clearance.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_environment_clearance.py",
                    "--environment-request-path",
                    str(request_path),
                    "--playwright-env-report-path",
                    str(env_path),
                    "--environment-fulfillment-path",
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
                    "scripts/verify_au_p0b_google_environment_clearance.py",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(build_result.stdout)
            verification = json.loads(verify_result.stdout)
            self.assertTrue(output_path.exists())

        self.assertEqual(payload["status"], "pass")
        self.assertEqual(verification["status"], "pass")


if __name__ == "__main__":
    unittest.main()
