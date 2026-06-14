from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_real_batch_request_packet import (
    PACKET_VERSION,
    build_au_p0a_real_batch_request_packet,
    compute_p0a_real_batch_request_packet_hash,
)
from scripts.verify_au_p0a_real_batch_request_packet import verify_au_p0a_real_batch_request_packet
from tests.test_au_p0a_credential_request_packet import AuP0aCredentialRequestPacketTest


class AuP0aRealBatchRequestPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuP0aCredentialRequestPacketTest()
        self._helper.setUp()

    def _write_execution_checklist(self, temp_dir: str, *, ready: bool) -> tuple[Path, dict[str, object]]:
        return self._helper._write_execution_checklist(temp_dir, ready=ready)

    def test_packet_records_blocked_real_batch_phases_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0a_real_batch_request_packet(
                p0a_execution_checklist_path=checklist_path,
                p0a_execution_checklist=checklist,
                output_path=Path(temp_dir) / "real-batch-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0a_real_batch_request_packet(packet)
            hard_gate = verify_au_p0a_real_batch_request_packet(packet, require_real_batches_ready=True)

        self.assertEqual(packet["p0a_real_batch_request_packet_version"], PACKET_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["real_batch_request_packet_ready"])
        self.assertFalse(packet["real_batch_phase_handoff_ready"])
        self.assertFalse(packet["ready_for_design_partner"])
        self.assertEqual(packet["summary"]["phase_count"], 3)
        self.assertEqual(packet["summary"]["phase_order"], ["preflight", "small_batch", "full_batch"])
        self.assertEqual(packet["summary"]["ready_phase_count"], 0)
        self.assertEqual(packet["summary"]["blocked_phase_count"], 3)
        self.assertEqual(packet["summary"]["next_phase"], "preflight")
        self.assertEqual(packet["summary"]["total_planned_runs"], 2436)
        self.assertEqual([phase["id"] for phase in packet["phase_requests"]], ["preflight", "small_batch", "full_batch"])
        self.assertEqual(packet["phase_requests"][0]["planned_runs"], 6)
        self.assertEqual(packet["phase_requests"][1]["planned_runs"], 30)
        self.assertEqual(packet["phase_requests"][2]["planned_runs"], 2400)
        self.assertFalse(packet["phase_requests"][0]["can_start"])
        self.assertIn("credential_handoff_missing_required:OPENAI_API_KEY", packet["phase_requests"][0]["blocking_reasons"])
        self.assertIn("make api-preflight", packet["phase_commands"])
        self.assertTrue(any("run_collection_slice.py --mode api --prompt-limit 5" in command for command in packet["phase_commands"]))
        self.assertTrue(any("run_collection_slice.py --mode api --prompt-limit 100" in command for command in packet["phase_commands"]))
        small_batch_json_path = next(
            artifact["path"]
            for phase in packet["phase_requests"]
            for artifact in phase["artifacts"]
            if artifact["key"] == "small_batch_json"
        )
        full_batch_json_path = next(
            artifact["path"]
            for phase in packet["phase_requests"]
            for artifact in phase["artifacts"]
            if artifact["key"] == "full_batch_json"
        )
        self.assertIn(small_batch_json_path, packet["evidence_outputs"])
        self.assertIn(full_batch_json_path, packet["evidence_outputs"])
        self.assertEqual(packet["summary"]["next_command"], "make api-preflight")
        self.assertEqual(packet["summary"]["post_update_verification_command"], "make api-preflight")
        self.assertFalse(packet["summary"]["raw_secret_values_allowed"])
        self.assertTrue(packet["summary"]["phase_entries_reference_command_ids_and_artifact_paths_only"])
        self.assertEqual(packet["runtime_endpoints"]["p0a_real_batch_request"], "GET /v1/p0a-real-batch-request/au")
        self.assertIn("make verify-au-p0a-real-batch-request", packet["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-real-batches-ready") for command in packet["hard_gate_commands"]))
        self.assertEqual(packet["p0a_real_batch_request_packet_hash"], compute_p0a_real_batch_request_packet_hash(packet))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0a_real_batches_not_ready", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("perplexity-key", serialized)

    def test_packet_passes_real_batch_ready_gate_when_all_phases_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=True)
            packet = build_au_p0a_real_batch_request_packet(
                p0a_execution_checklist_path=checklist_path,
                p0a_execution_checklist=checklist,
                output_path=Path(temp_dir) / "real-batch-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            hard_gate = verify_au_p0a_real_batch_request_packet(packet, require_real_batches_ready=True)

        self.assertTrue(packet["real_batch_phase_handoff_ready"])
        self.assertTrue(packet["ready_for_design_partner"])
        self.assertEqual(packet["summary"]["ready_phase_count"], 3)
        self.assertEqual(packet["summary"]["blocked_phase_count"], 0)
        self.assertEqual(packet["summary"]["next_phase"], "complete")
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_detects_tampered_total_runs_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0a_real_batch_request_packet(
                p0a_execution_checklist_path=checklist_path,
                p0a_execution_checklist=checklist,
                output_path=Path(temp_dir) / "real-batch-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["summary"]["total_planned_runs"] = 6
            packet["p0a_real_batch_request_packet_hash"] = compute_p0a_real_batch_request_packet_hash(packet)
            verification = verify_au_p0a_real_batch_request_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_total_planned_runs_mismatch", verification["errors"])

    def test_cli_writes_real_batch_request_packet_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, _checklist = self._write_execution_checklist(temp_dir, ready=False)
            output_path = Path(temp_dir) / "real-batch-request.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_real_batch_request_packet.py",
                    "--p0a-execution-checklist-path",
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
                [sys.executable, "scripts/verify_au_p0a_real_batch_request_packet.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("au_p0a_real_batch_request_packet_v1", result.stdout)
        self.assertIn("real_batch_request_packet_ready", verify_result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["summary"]["total_planned_runs"], 2436)
        self.assertEqual(verify_au_p0a_real_batch_request_packet(payload)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
