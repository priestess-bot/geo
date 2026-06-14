from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_phase_execution_fulfillment import (
    FULFILLMENT_VERSION,
    build_au_p0b_google_phase_execution_fulfillment,
    compute_p0b_google_phase_execution_fulfillment_hash,
)
from scripts.build_au_p0b_google_phase_execution_request_packet import (
    build_au_p0b_google_phase_execution_request_packet,
)
from scripts.verify_au_p0b_google_phase_execution_fulfillment import (
    verify_au_p0b_google_phase_execution_fulfillment,
)
from tests.test_au_p0b_google_phase_execution_request_packet import (
    AuP0bGooglePhaseExecutionRequestPacketTest,
)


class AuP0bGooglePhaseExecutionFulfillmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuP0bGooglePhaseExecutionRequestPacketTest()
        self._helper.setUp()

    def _write_request_and_checklist(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
        checklist_path, checklist = self._helper._write_execution_checklist(temp_dir, ready=ready)
        request = build_au_p0b_google_phase_execution_request_packet(
            p0b_google_execution_checklist_path=checklist_path,
            p0b_google_execution_checklist=checklist,
            output_path=Path(temp_dir) / "phase-execution-request.json",
            generated_at="2026-06-12T00:00:00Z",
        )
        request_path = Path(temp_dir) / "phase-execution-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return request_path, checklist_path, request, checklist

    def test_fulfillment_records_blocked_phase_state_without_raw_payload_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, request, checklist = self._write_request_and_checklist(temp_dir, ready=False)
            fulfillment = build_au_p0b_google_phase_execution_fulfillment(
                phase_execution_request_path=request_path,
                p0b_google_execution_checklist_path=checklist_path,
                phase_execution_request=request,
                p0b_google_execution_checklist=checklist,
                output_path=Path(temp_dir) / "phase-fulfillment.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0b_google_phase_execution_fulfillment(fulfillment)
            hard_gate = verify_au_p0b_google_phase_execution_fulfillment(fulfillment, require_fulfilled=True)

        self.assertEqual(fulfillment["p0b_google_phase_execution_fulfillment_version"], FULFILLMENT_VERSION)
        self.assertEqual(fulfillment["status"], "pass")
        self.assertTrue(fulfillment["phase_execution_fulfillment_ready"])
        self.assertFalse(fulfillment["phase_execution_fulfilled"])
        self.assertFalse(fulfillment["google_spike_phase_handoff_ready"])
        self.assertFalse(fulfillment["google_main_scoring_allowed"])
        self.assertEqual(fulfillment["summary"]["phase_count"], 6)
        self.assertEqual(
            fulfillment["summary"]["phase_order"],
            ["environment", "browser_smoke", "manual_backfill", "health_check", "full_spike", "main_scoring"],
        )
        self.assertEqual(fulfillment["summary"]["ready_phase_count"], 0)
        self.assertEqual(fulfillment["summary"]["blocked_phase_count"], 6)
        self.assertEqual(fulfillment["summary"]["next_phase"], "environment")
        self.assertEqual(fulfillment["summary"]["missing_required_count"], 6)
        self.assertIn("phase:environment", fulfillment["summary"]["missing_required"])
        self.assertTrue(fulfillment["summary"]["source_checklist_hash_aligned"])
        self.assertEqual(fulfillment["phase_fulfillment_items"][0]["key"], "phase:environment")
        self.assertFalse(fulfillment["phase_fulfillment_items"][0]["fulfilled"])
        self.assertTrue(fulfillment["phase_fulfillment_items"][0]["request_can_start"])
        self.assertIn("phase_request_not_ready", fulfillment["phase_fulfillment_items"][0]["blocking_reasons"])
        self.assertEqual(
            fulfillment["runtime_endpoints"]["p0b_google_phase_execution_fulfillment"],
            "GET /v1/p0b-google-phase-execution-fulfillment/au",
        )
        self.assertIn("make verify-au-p0b-google-phase-execution-fulfillment", fulfillment["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-fulfilled") for command in fulfillment["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-google-phases-ready") for command in fulfillment["hard_gate_commands"]))
        self.assertTrue(
            any(command.endswith("--require-google-main-scoring-ready") for command in fulfillment["hard_gate_commands"])
        )
        self.assertEqual(
            fulfillment["p0b_google_phase_execution_fulfillment_hash"],
            compute_p0b_google_phase_execution_fulfillment_hash(fulfillment),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0b_google_phase_execution_not_fulfilled", hard_gate["errors"])
        serialized = json.dumps(fulfillment)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)
        self.assertNotIn("s3://manual-backfill", serialized)

    def test_fulfillment_passes_strict_gate_when_all_google_phases_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, request, checklist = self._write_request_and_checklist(temp_dir, ready=True)
            fulfillment = build_au_p0b_google_phase_execution_fulfillment(
                phase_execution_request_path=request_path,
                p0b_google_execution_checklist_path=checklist_path,
                phase_execution_request=request,
                p0b_google_execution_checklist=checklist,
                output_path=Path(temp_dir) / "phase-fulfillment.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            hard_gate = verify_au_p0b_google_phase_execution_fulfillment(fulfillment, require_fulfilled=True)

        self.assertTrue(fulfillment["phase_execution_fulfilled"])
        self.assertTrue(fulfillment["google_spike_phase_handoff_ready"])
        self.assertTrue(fulfillment["google_main_scoring_allowed"])
        self.assertEqual(fulfillment["summary"]["ready_phase_count"], 6)
        self.assertEqual(fulfillment["summary"]["blocked_phase_count"], 0)
        self.assertEqual(fulfillment["summary"]["next_phase"], "complete")
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_detects_stale_request_checklist_hash_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, request, checklist = self._write_request_and_checklist(temp_dir, ready=False)
            fulfillment = build_au_p0b_google_phase_execution_fulfillment(
                phase_execution_request_path=request_path,
                p0b_google_execution_checklist_path=checklist_path,
                phase_execution_request=request,
                p0b_google_execution_checklist=checklist,
                generated_at="2026-06-12T00:00:00Z",
            )
            fulfillment["source_p0b_google_phase_execution_request"]["source_google_execution_checklist_hash"] = (
                "stale-checklist-hash"
            )
            fulfillment["summary"]["source_checklist_hash_aligned"] = False
            fulfillment["phase_execution_fulfillment_ready"] = False
            fulfillment["status"] = "fail"
            fulfillment["p0b_google_phase_execution_fulfillment_hash"] = (
                compute_p0b_google_phase_execution_fulfillment_hash(fulfillment)
            )
            verification = verify_au_p0b_google_phase_execution_fulfillment(fulfillment)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("source_request_checklist_hash_not_aligned", verification["errors"])

    def test_cli_writes_phase_execution_fulfillment_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, _request, _checklist = self._write_request_and_checklist(temp_dir, ready=False)
            output_path = Path(temp_dir) / "phase-fulfillment.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_phase_execution_fulfillment.py",
                    "--phase-execution-request-path",
                    str(request_path),
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
                [sys.executable, "scripts/verify_au_p0b_google_phase_execution_fulfillment.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("au_p0b_google_phase_execution_fulfillment_v1", result.stdout)
        self.assertIn("phase_execution_fulfillment_ready", verify_result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["summary"]["full_spike_planned_runs"], 240)
        self.assertEqual(verify_au_p0b_google_phase_execution_fulfillment(payload)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
