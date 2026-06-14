from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_phase_execution_clearance import (
    CLEARANCE_VERSION,
    build_au_p0b_google_phase_execution_clearance,
    compute_p0b_google_phase_execution_clearance_hash,
)
from scripts.build_au_p0b_google_phase_execution_fulfillment import (
    build_au_p0b_google_phase_execution_fulfillment,
)
from scripts.build_au_p0b_google_phase_execution_request_packet import (
    build_au_p0b_google_phase_execution_request_packet,
)
from scripts.run_au_external_dependency_clearance import run_au_external_dependency_clearance
from scripts.verify_au_p0b_google_phase_execution_clearance import (
    verify_au_p0b_google_phase_execution_clearance,
)
from tests.test_au_external_dependency_clearance import AuExternalDependencyClearanceTest
from tests.test_au_p0b_google_phase_execution_fulfillment import AuP0bGooglePhaseExecutionFulfillmentTest


class AuP0bGooglePhaseExecutionClearanceTest(unittest.TestCase):
    def _build_sources(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, Path, Path, Path, dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
        fulfillment_helper = AuP0bGooglePhaseExecutionFulfillmentTest()
        fulfillment_helper.setUp()
        checklist_path, checklist = fulfillment_helper._helper._write_execution_checklist(temp_dir, ready=ready)
        request = build_au_p0b_google_phase_execution_request_packet(
            p0b_google_execution_checklist_path=checklist_path,
            p0b_google_execution_checklist=checklist,
            output_path=Path(temp_dir) / "phase-execution-request.json",
            generated_at="2026-06-14T00:00:00Z",
        )
        request_path = Path(temp_dir) / "phase-execution-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        fulfillment_path = Path(temp_dir) / "phase-execution-fulfillment.json"
        fulfillment = build_au_p0b_google_phase_execution_fulfillment(
            phase_execution_request_path=request_path,
            p0b_google_execution_checklist_path=checklist_path,
            phase_execution_request=request,
            p0b_google_execution_checklist=checklist,
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
        return request_path, checklist_path, fulfillment_path, clearance_path, request, checklist, fulfillment, external_clearance

    def test_clearance_packet_records_blocked_phase_execution_without_raw_payload_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, fulfillment_path, clearance_path, request, checklist, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0b_google_phase_execution_clearance(
                phase_execution_request_path=request_path,
                p0b_google_execution_checklist_path=checklist_path,
                phase_execution_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                phase_execution_request=request,
                p0b_google_execution_checklist=checklist,
                phase_execution_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "phase-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            verification = verify_au_p0b_google_phase_execution_clearance(packet)
            hard_gate = verify_au_p0b_google_phase_execution_clearance(packet, require_cleared=True)

        self.assertEqual(packet["p0b_google_phase_execution_clearance_version"], CLEARANCE_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["phase_execution_clearance_packet_ready"])
        self.assertFalse(packet["phase_execution_fulfilled"])
        self.assertFalse(packet["phase_execution_clearance_ready"])
        self.assertFalse(packet["ready_for_next_clearance_step"])
        self.assertTrue(packet["blocked_by_prerequisite_step"])
        self.assertEqual(packet["clearance_step"]["id"], "p0b_google_phase_execution")
        self.assertEqual(packet["prerequisite_step"]["id"], "p0b_google_manual_backfill")
        self.assertEqual(packet["summary"]["phase_count"], 6)
        self.assertEqual(packet["summary"]["ready_phase_count"], 0)
        self.assertEqual(packet["summary"]["blocked_phase_count"], 6)
        self.assertEqual(packet["summary"]["next_phase"], "environment")
        self.assertEqual(packet["summary"]["missing_required_count"], 6)
        self.assertIn("phase:environment", packet["summary"]["missing_required"])
        self.assertEqual(packet["summary"]["next_action"], "clear_p0b_google_manual_backfill_first")
        self.assertEqual(packet["summary"]["next_command"], "make au-p0b-google-manual-backfill-clearance")
        self.assertIn("make verify-au-p0b-google-phase-execution-fulfillment", packet["post_update_validation_sequence"])
        self.assertTrue(any("--require-google-phases-ready" in command for command in packet["post_update_validation_sequence"]))
        self.assertTrue(
            any("--require-google-main-scoring-ready" in command for command in packet["post_update_validation_sequence"])
        )
        self.assertTrue(any("--require-fulfilled" in command for command in packet["post_update_validation_sequence"]))
        self.assertEqual(
            packet["runtime_endpoints"]["p0b_google_phase_execution_clearance"],
            "GET /v1/p0b-google-phase-execution-clearance/au",
        )
        self.assertIn("make verify-au-p0b-google-phase-execution-clearance", packet["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-cleared") for command in packet["hard_gate_commands"]))
        self.assertEqual(
            packet["p0b_google_phase_execution_clearance_hash"],
            compute_p0b_google_phase_execution_clearance_hash(packet),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0b_google_phase_execution_not_cleared", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)
        self.assertNotIn('"answer_text":', serialized)
        self.assertNotIn('"citation_urls":', serialized)
        self.assertNotIn('"provider_response":', serialized)

    def test_clearance_packet_passes_strict_gate_when_phase_execution_and_prerequisite_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, fulfillment_path, clearance_path, request, checklist, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=True)
            )
            for step in external_clearance["steps"]:
                if step["id"] in {
                    "p0a_provider_credentials",
                    "p0a_real_batches",
                    "p0b_google_environment",
                    "p0b_google_manual_backfill",
                    "p0b_google_phase_execution",
                }:
                    step["ready"] = True
                    step["can_start"] = True
                    step["status"] = "already_ready"
                    step["would_execute"] = False
                    step["blocked_by"] = []
            packet = build_au_p0b_google_phase_execution_clearance(
                phase_execution_request_path=request_path,
                p0b_google_execution_checklist_path=checklist_path,
                phase_execution_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                phase_execution_request=request,
                p0b_google_execution_checklist=checklist,
                phase_execution_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "phase-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            hard_gate = verify_au_p0b_google_phase_execution_clearance(packet, require_cleared=True)

        self.assertTrue(packet["phase_execution_fulfilled"])
        self.assertTrue(packet["ready_for_next_clearance_step"])
        self.assertTrue(packet["phase_execution_clearance_ready"])
        self.assertFalse(packet["blocked_by_prerequisite_step"])
        self.assertEqual(packet["summary"]["missing_required_count"], 0)
        self.assertEqual(packet["summary"]["ready_phase_count"], 6)
        self.assertEqual(packet["summary"]["blocked_phase_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_rejects_tampered_phase_count_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, fulfillment_path, clearance_path, request, checklist, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0b_google_phase_execution_clearance(
                phase_execution_request_path=request_path,
                p0b_google_execution_checklist_path=checklist_path,
                phase_execution_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                phase_execution_request=request,
                p0b_google_execution_checklist=checklist,
                phase_execution_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                generated_at="2026-06-14T00:00:00Z",
            )
            packet["summary"]["ready_phase_count"] = 6
            packet["p0b_google_phase_execution_clearance_hash"] = (
                compute_p0b_google_phase_execution_clearance_hash(packet)
            )
            verification = verify_au_p0b_google_phase_execution_clearance(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_ready_phase_count_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_clearance_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, fulfillment_path, clearance_path, _request, _checklist, _fulfillment, _external = (
                self._build_sources(temp_dir, ready=False)
            )
            output_path = Path(temp_dir) / "phase-clearance.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_phase_execution_clearance.py",
                    "--phase-execution-request-path",
                    str(request_path),
                    "--p0b-google-execution-checklist-path",
                    str(checklist_path),
                    "--phase-execution-fulfillment-path",
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
                    "scripts/verify_au_p0b_google_phase_execution_clearance.py",
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
