from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_phase_execution_request_packet import (
    PACKET_VERSION,
    build_au_p0b_google_phase_execution_request_packet,
    compute_p0b_google_phase_execution_request_packet_hash,
)
from scripts.verify_au_p0b_google_phase_execution_request_packet import (
    verify_au_p0b_google_phase_execution_request_packet,
)
from tests.test_au_p0b_google_environment_request_packet import AuP0bGoogleEnvironmentRequestPacketTest


class AuP0bGooglePhaseExecutionRequestPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuP0bGoogleEnvironmentRequestPacketTest()
        self._helper.setUp()

    def _write_execution_checklist(self, temp_dir: str, *, ready: bool) -> tuple[Path, dict[str, object]]:
        return self._helper._write_execution_checklist(temp_dir, ready=ready)

    def test_packet_records_blocked_google_phases_without_raw_payload_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0b_google_phase_execution_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                output_path=Path(temp_dir) / "phase-execution-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0b_google_phase_execution_request_packet(packet)
            hard_gate = verify_au_p0b_google_phase_execution_request_packet(
                packet,
                require_google_phases_ready=True,
            )

        self.assertEqual(packet["p0b_google_phase_execution_request_packet_version"], PACKET_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["phase_execution_request_packet_ready"])
        self.assertFalse(packet["google_spike_phase_handoff_ready"])
        self.assertFalse(packet["google_main_scoring_allowed"])
        self.assertEqual(packet["summary"]["phase_count"], 6)
        self.assertEqual(
            packet["summary"]["phase_order"],
            ["environment", "browser_smoke", "manual_backfill", "health_check", "full_spike", "main_scoring"],
        )
        self.assertEqual(packet["summary"]["ready_phase_count"], 0)
        self.assertEqual(packet["summary"]["blocked_phase_count"], 6)
        self.assertEqual(packet["summary"]["next_phase"], "environment")
        self.assertEqual(packet["summary"]["full_spike_planned_runs"], 240)
        self.assertEqual(packet["summary"]["manual_expected_record_count"], 120)
        self.assertEqual([phase["id"] for phase in packet["phase_requests"]], packet["summary"]["phase_order"])
        self.assertEqual(packet["phase_requests"][0]["planned_runs"], 0)
        self.assertEqual(packet["phase_requests"][1]["planned_runs"], 1)
        self.assertEqual(packet["phase_requests"][2]["planned_runs"], 120)
        self.assertEqual(packet["phase_requests"][3]["planned_runs"], 240)
        self.assertEqual(packet["phase_requests"][4]["planned_runs"], 240)
        self.assertEqual(packet["phase_requests"][5]["planned_runs"], 0)
        self.assertTrue(packet["phase_requests"][0]["can_start"])
        self.assertIn(
            "environment_handoff:smoke_env:GOOGLE_PLAYWRIGHT_ENABLED",
            packet["phase_requests"][0]["blocking_reasons"],
        )
        self.assertIn("make verify-au-p0b-google-playwright-env", packet["phase_commands"])
        self.assertTrue(any("verify_au_p0b_google_playwright_smoke.py" in command for command in packet["phase_commands"]))
        self.assertIn("make verify-au-p0b-google-manual-backfill", packet["phase_commands"])
        self.assertIn("make au-p0b-google-spike", packet["phase_commands"])
        self.assertIn("make au-p0b-google-package && make verify-au-p0b-google-package", packet["phase_commands"])
        self.assertEqual(packet["summary"]["next_command"], "make verify-au-p0b-google-playwright-env")
        self.assertEqual(packet["summary"]["post_update_verification_command"], "make au-p0b-google-playwright-env")
        self.assertFalse(packet["summary"]["raw_secret_values_allowed"])
        self.assertFalse(packet["summary"]["raw_answer_values_allowed"])
        self.assertFalse(packet["summary"]["raw_citation_values_allowed"])
        self.assertFalse(packet["summary"]["raw_asset_urls_allowed"])
        self.assertTrue(packet["summary"]["phase_entries_reference_command_ids_and_artifact_paths_only"])
        self.assertEqual(
            packet["runtime_endpoints"]["p0b_google_phase_execution_request"],
            "GET /v1/p0b-google-phase-execution-request/au",
        )
        self.assertIn("make verify-au-p0b-google-phase-execution-request", packet["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-google-phases-ready") for command in packet["hard_gate_commands"]))
        self.assertTrue(
            any(command.endswith("--require-google-main-scoring-ready") for command in packet["hard_gate_commands"])
        )
        self.assertEqual(
            packet["p0b_google_phase_execution_request_packet_hash"],
            compute_p0b_google_phase_execution_request_packet_hash(packet),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0b_google_phases_not_ready", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("#prompt", serialized)
        self.assertNotIn(".answer", serialized)
        self.assertNotIn("Manual Google AI Mode answer", serialized)

    def test_packet_passes_google_phase_ready_gate_when_all_phases_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=True)
            packet = build_au_p0b_google_phase_execution_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                output_path=Path(temp_dir) / "phase-execution-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            hard_gate = verify_au_p0b_google_phase_execution_request_packet(
                packet,
                require_google_phases_ready=True,
            )

        self.assertTrue(packet["google_spike_phase_handoff_ready"])
        self.assertTrue(packet["google_main_scoring_allowed"])
        self.assertEqual(packet["summary"]["ready_phase_count"], 6)
        self.assertEqual(packet["summary"]["blocked_phase_count"], 0)
        self.assertEqual(packet["summary"]["next_phase"], "complete")
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_detects_tampered_planned_runs_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0b_google_phase_execution_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                output_path=Path(temp_dir) / "phase-execution-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["phase_requests"][4]["planned_runs"] = 120
            packet["p0b_google_phase_execution_request_packet_hash"] = (
                compute_p0b_google_phase_execution_request_packet_hash(packet)
            )
            verification = verify_au_p0b_google_phase_execution_request_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("phase_planned_runs_mismatch:full_spike", verification["errors"])

    def test_cli_writes_google_phase_execution_request_packet_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, _checklist = self._write_execution_checklist(temp_dir, ready=False)
            output_path = Path(temp_dir) / "phase-execution-request.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_phase_execution_request_packet.py",
                    "--p0b-google-execution-checklist-path",
                    str(checklist_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            verify_result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0b_google_phase_execution_request_packet.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("au_p0b_google_phase_execution_request_packet_v1", result.stdout)
        self.assertIn("phase_execution_request_packet_ready", verify_result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["summary"]["full_spike_planned_runs"], 240)
        self.assertEqual(verify_au_p0b_google_phase_execution_request_packet(payload)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
