from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_real_batch_clearance import (
    CLEARANCE_VERSION,
    build_au_p0a_real_batch_clearance,
    compute_p0a_real_batch_clearance_hash,
)
from scripts.build_au_p0a_real_batch_fulfillment import build_au_p0a_real_batch_fulfillment
from scripts.build_au_p0a_real_batch_request_packet import build_au_p0a_real_batch_request_packet
from scripts.run_au_external_dependency_clearance import run_au_external_dependency_clearance
from scripts.verify_au_p0a_real_batch_clearance import verify_au_p0a_real_batch_clearance
from tests.test_au_external_dependency_clearance import AuExternalDependencyClearanceTest
from tests.test_au_p0a_real_batch_request_packet import AuP0aRealBatchRequestPacketTest


class AuP0aRealBatchClearanceTest(unittest.TestCase):
    def _build_sources(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, Path, Path, Path, dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
        request_helper = AuP0aRealBatchRequestPacketTest()
        request_helper.setUp()
        checklist_path, checklist = request_helper._write_execution_checklist(temp_dir, ready=ready)
        request_path = Path(temp_dir) / "real-batch-request.json"
        request = build_au_p0a_real_batch_request_packet(
            p0a_execution_checklist_path=checklist_path,
            p0a_execution_checklist=checklist,
            output_path=request_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        request_path.write_text(json.dumps(request), encoding="utf-8")
        fulfillment_path = Path(temp_dir) / "real-batch-fulfillment.json"
        fulfillment = build_au_p0a_real_batch_fulfillment(
            real_batch_request_path=request_path,
            p0a_execution_checklist_path=checklist_path,
            real_batch_request=request,
            p0a_execution_checklist=checklist,
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

    def test_clearance_packet_records_blocked_real_batch_state_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, fulfillment_path, clearance_path, request, checklist, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0a_real_batch_clearance(
                real_batch_request_path=request_path,
                p0a_execution_checklist_path=checklist_path,
                real_batch_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                real_batch_request=request,
                p0a_execution_checklist=checklist,
                real_batch_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "real-batch-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            verification = verify_au_p0a_real_batch_clearance(packet)
            hard_gate = verify_au_p0a_real_batch_clearance(packet, require_cleared=True)

        self.assertEqual(packet["p0a_real_batch_clearance_version"], CLEARANCE_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["real_batch_clearance_packet_ready"])
        self.assertFalse(packet["real_batches_fulfilled"])
        self.assertFalse(packet["real_batch_clearance_ready"])
        self.assertFalse(packet["ready_for_next_clearance_step"])
        self.assertTrue(packet["blocked_by_prerequisite_step"])
        self.assertEqual(packet["summary"]["phase_order"], ["preflight", "small_batch", "full_batch"])
        self.assertEqual(packet["summary"]["missing_required_count"], 3)
        self.assertEqual(packet["summary"]["total_planned_runs"], 2436)
        self.assertTrue(packet["summary"]["real_batch_execution_plan_ready"])
        self.assertEqual(packet["summary"]["ready_phase_count"], 0)
        self.assertEqual(packet["summary"]["blocked_phase_count"], 3)
        self.assertEqual(packet["summary"]["phase_command_count"], 8)
        self.assertEqual(packet["summary"]["evidence_output_count"], 6)
        self.assertEqual(packet["summary"]["next_phase"], "preflight")
        self.assertEqual(packet["summary"]["next_action"], "clear_p0a_provider_credentials_first")
        self.assertEqual(packet["summary"]["next_command"], "make au-p0a-credential-clearance")
        self.assertEqual(packet["clearance_step"]["id"], "p0a_real_batches")
        self.assertEqual(packet["prerequisite_step"]["id"], "p0a_provider_credentials")
        self.assertIn("phase:preflight", packet["summary"]["missing_required"])
        self.assertIn("make au-p0a-credential-clearance", packet["post_update_validation_sequence"])
        self.assertIn("make verify-au-p0a-real-batch-fulfillment", packet["post_update_validation_sequence"])
        self.assertTrue(any("--require-fulfilled" in command for command in packet["post_update_validation_sequence"]))
        self.assertEqual(
            packet["runtime_endpoints"]["p0a_real_batch_clearance"],
            "GET /v1/p0a-real-batch-clearance/au",
        )
        self.assertIn("make verify-au-p0a-real-batch-clearance", packet["hard_gate_commands"])
        self.assertTrue(any("--require-cleared" in command for command in packet["hard_gate_commands"]))
        self.assertEqual(
            packet["p0a_real_batch_clearance_hash"],
            compute_p0a_real_batch_clearance_hash(packet),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(verification["real_batch_execution_plan_ready"])
        self.assertEqual(verification["total_planned_runs"], 2436)
        self.assertEqual(verification["phase_command_count"], 8)
        self.assertEqual(verification["evidence_output_count"], 6)
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0a_real_batches_not_cleared", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("perplexity-key", serialized)

    def test_clearance_packet_passes_strict_gate_when_batches_and_prerequisites_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, fulfillment_path, clearance_path, request, checklist, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=True)
            )
            external_clearance["steps"][0]["ready"] = True
            external_clearance["steps"][0]["status"] = "already_ready"
            external_clearance["steps"][0]["would_execute"] = False
            external_clearance["steps"][0]["blocked_by"] = []
            external_clearance["steps"][1]["ready"] = True
            external_clearance["steps"][1]["can_start"] = True
            external_clearance["steps"][1]["status"] = "already_ready"
            external_clearance["steps"][1]["would_execute"] = False
            external_clearance["steps"][1]["blocked_by"] = []
            packet = build_au_p0a_real_batch_clearance(
                real_batch_request_path=request_path,
                p0a_execution_checklist_path=checklist_path,
                real_batch_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                real_batch_request=request,
                p0a_execution_checklist=checklist,
                real_batch_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "real-batch-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            hard_gate = verify_au_p0a_real_batch_clearance(packet, require_cleared=True)

        self.assertTrue(packet["real_batches_fulfilled"])
        self.assertTrue(packet["ready_for_next_clearance_step"])
        self.assertTrue(packet["real_batch_clearance_ready"])
        self.assertFalse(packet["blocked_by_prerequisite_step"])
        self.assertEqual(packet["summary"]["missing_required_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_rejects_tampered_phase_count_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, fulfillment_path, clearance_path, request, checklist, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0a_real_batch_clearance(
                real_batch_request_path=request_path,
                p0a_execution_checklist_path=checklist_path,
                real_batch_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                real_batch_request=request,
                p0a_execution_checklist=checklist,
                real_batch_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                generated_at="2026-06-14T00:00:00Z",
            )
            packet["summary"]["phase_count"] = 2
            packet["p0a_real_batch_clearance_hash"] = compute_p0a_real_batch_clearance_hash(packet)
            verification = verify_au_p0a_real_batch_clearance(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_phase_count_mismatch", verification["errors"])

    def test_verifier_rejects_tampered_execution_plan_count_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, fulfillment_path, clearance_path, request, checklist, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0a_real_batch_clearance(
                real_batch_request_path=request_path,
                p0a_execution_checklist_path=checklist_path,
                real_batch_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                real_batch_request=request,
                p0a_execution_checklist=checklist,
                real_batch_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                generated_at="2026-06-14T00:00:00Z",
            )
            packet["summary"]["total_planned_runs"] = 2400
            packet["p0a_real_batch_clearance_hash"] = compute_p0a_real_batch_clearance_hash(packet)
            verification = verify_au_p0a_real_batch_clearance(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_total_planned_runs_mismatch", verification["errors"])

    def test_path_verifier_detects_stale_real_batch_source_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, fulfillment_path, clearance_path, _request, _checklist, _fulfillment, _external = (
                self._build_sources(temp_dir, ready=False)
            )
            output_path = Path(temp_dir) / "real-batch-clearance.json"
            packet = build_au_p0a_real_batch_clearance(
                real_batch_request_path=request_path,
                p0a_execution_checklist_path=checklist_path,
                real_batch_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                output_path=output_path,
                generated_at="2026-06-14T00:00:00Z",
            )
            output_path.write_text(json.dumps(packet), encoding="utf-8")
            stale_fulfillment = json.loads(fulfillment_path.read_text(encoding="utf-8"))
            stale_fulfillment["p0a_real_batch_fulfillment_hash"] = "0" * 64
            fulfillment_path.write_text(json.dumps(stale_fulfillment), encoding="utf-8")

            memory_verification = verify_au_p0a_real_batch_clearance(packet)
            path_verification = verify_au_p0a_real_batch_clearance(packet, path=output_path)
            explicit_verification = verify_au_p0a_real_batch_clearance(packet, verify_current_files=True)

        self.assertEqual(memory_verification["status"], "pass")
        self.assertFalse(memory_verification["current_file_check_enabled"])
        self.assertEqual(path_verification["status"], "fail")
        self.assertTrue(path_verification["current_file_check_enabled"])
        self.assertIn("source_fulfillment_current_hash_mismatch", path_verification["errors"])
        self.assertIn("source_fulfillment_file_sha256_mismatch", path_verification["errors"])
        self.assertEqual(explicit_verification["status"], "fail")
        self.assertTrue(explicit_verification["current_file_check_enabled"])

    def test_cli_writes_and_verifies_clearance_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, fulfillment_path, clearance_path, _request, _checklist, _fulfillment, _external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            output_path = Path(temp_dir) / "real-batch-clearance.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_real_batch_clearance.py",
                    "--real-batch-request-path",
                    str(request_path),
                    "--p0a-execution-checklist-path",
                    str(checklist_path),
                    "--real-batch-fulfillment-path",
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
                    "scripts/verify_au_p0a_real_batch_clearance.py",
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
