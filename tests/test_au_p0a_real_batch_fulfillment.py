from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_real_batch_fulfillment import (
    FULFILLMENT_VERSION,
    build_au_p0a_real_batch_fulfillment,
    compute_p0a_real_batch_fulfillment_hash,
)
from scripts.build_au_p0a_real_batch_request_packet import build_au_p0a_real_batch_request_packet
from scripts.verify_au_p0a_real_batch_fulfillment import verify_au_p0a_real_batch_fulfillment
from tests.test_au_p0a_real_batch_request_packet import AuP0aRealBatchRequestPacketTest


class AuP0aRealBatchFulfillmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuP0aRealBatchRequestPacketTest()
        self._helper.setUp()

    def _write_request_and_checklist(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
        checklist_path, checklist = self._helper._write_execution_checklist(temp_dir, ready=ready)
        request = build_au_p0a_real_batch_request_packet(
            p0a_execution_checklist_path=checklist_path,
            p0a_execution_checklist=checklist,
            output_path=Path(temp_dir) / "real-batch-request.json",
            generated_at="2026-06-14T00:00:00Z",
        )
        request_path = Path(temp_dir) / "real-batch-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return request_path, checklist_path, request, checklist

    def test_fulfillment_records_blocked_real_batch_state_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, request, checklist = self._write_request_and_checklist(temp_dir, ready=False)
            fulfillment = build_au_p0a_real_batch_fulfillment(
                real_batch_request_path=request_path,
                p0a_execution_checklist_path=checklist_path,
                real_batch_request=request,
                p0a_execution_checklist=checklist,
                output_path=Path(temp_dir) / "real-batch-fulfillment.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            verification = verify_au_p0a_real_batch_fulfillment(fulfillment)
            hard_gate = verify_au_p0a_real_batch_fulfillment(fulfillment, require_fulfilled=True)

        self.assertEqual(fulfillment["p0a_real_batch_fulfillment_version"], FULFILLMENT_VERSION)
        self.assertEqual(fulfillment["status"], "pass")
        self.assertTrue(fulfillment["real_batch_fulfillment_ready"])
        self.assertFalse(fulfillment["real_batches_fulfilled"])
        self.assertFalse(fulfillment["real_batch_phase_handoff_ready"])
        self.assertFalse(fulfillment["ready_for_design_partner"])
        self.assertEqual(fulfillment["summary"]["phase_order"], ["preflight", "small_batch", "full_batch"])
        self.assertEqual(fulfillment["summary"]["next_phase"], "preflight")
        self.assertEqual(fulfillment["summary"]["total_planned_runs"], 2436)
        self.assertTrue(fulfillment["summary"]["real_batch_execution_plan_ready"])
        self.assertEqual(fulfillment["summary"]["missing_required_count"], 3)
        self.assertEqual(fulfillment["summary"]["command_count"], 8)
        self.assertEqual(fulfillment["summary"]["evidence_output_count"], 6)
        self.assertTrue(fulfillment["summary"]["source_checklist_hash_aligned"])
        self.assertTrue(verification["real_batch_execution_plan_ready"])
        self.assertEqual(verification["total_planned_runs"], 2436)
        self.assertEqual(verification["command_count"], 8)
        self.assertEqual(verification["evidence_output_count"], 6)
        self.assertEqual(fulfillment["real_batch_fulfillment_items"][0]["key"], "phase:preflight")
        self.assertIn("real_batch_request_phase_not_ready", fulfillment["real_batch_fulfillment_items"][0]["blocking_reasons"])
        self.assertEqual(
            fulfillment["runtime_endpoints"]["p0a_real_batch_fulfillment"],
            "GET /v1/p0a-real-batch-fulfillment/au",
        )
        self.assertIn("make verify-au-p0a-real-batch-fulfillment", fulfillment["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-fulfilled") for command in fulfillment["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-real-batches-ready") for command in fulfillment["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-design-partner-ready") for command in fulfillment["hard_gate_commands"]))
        self.assertEqual(
            fulfillment["p0a_real_batch_fulfillment_hash"],
            compute_p0a_real_batch_fulfillment_hash(fulfillment),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0a_real_batches_not_fulfilled", hard_gate["errors"])
        serialized = json.dumps(fulfillment)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("perplexity-key", serialized)

    def test_fulfillment_passes_strict_gate_when_all_real_batches_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, request, checklist = self._write_request_and_checklist(temp_dir, ready=True)
            fulfillment = build_au_p0a_real_batch_fulfillment(
                real_batch_request_path=request_path,
                p0a_execution_checklist_path=checklist_path,
                real_batch_request=request,
                p0a_execution_checklist=checklist,
                output_path=Path(temp_dir) / "real-batch-fulfillment.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            hard_gate = verify_au_p0a_real_batch_fulfillment(fulfillment, require_fulfilled=True)

        self.assertTrue(fulfillment["real_batches_fulfilled"])
        self.assertTrue(fulfillment["real_batch_phase_handoff_ready"])
        self.assertTrue(fulfillment["ready_for_design_partner"])
        self.assertEqual(fulfillment["summary"]["ready_phase_count"], 3)
        self.assertEqual(fulfillment["summary"]["blocked_phase_count"], 0)
        self.assertEqual(fulfillment["summary"]["next_phase"], "complete")
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_detects_stale_request_checklist_hash_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, request, checklist = self._write_request_and_checklist(temp_dir, ready=False)
            fulfillment = build_au_p0a_real_batch_fulfillment(
                real_batch_request_path=request_path,
                p0a_execution_checklist_path=checklist_path,
                real_batch_request=request,
                p0a_execution_checklist=checklist,
                generated_at="2026-06-14T00:00:00Z",
            )
            fulfillment["source_p0a_real_batch_request"]["source_p0a_execution_checklist_hash"] = "stale-checklist-hash"
            fulfillment["summary"]["source_checklist_hash_aligned"] = False
            fulfillment["real_batch_fulfillment_ready"] = False
            fulfillment["status"] = "fail"
            fulfillment["p0a_real_batch_fulfillment_hash"] = compute_p0a_real_batch_fulfillment_hash(fulfillment)
            verification = verify_au_p0a_real_batch_fulfillment(fulfillment)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("source_request_checklist_hash_not_aligned", verification["errors"])

    def test_cli_writes_real_batch_fulfillment_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, checklist_path, _request, _checklist = self._write_request_and_checklist(temp_dir, ready=False)
            output_path = Path(temp_dir) / "real-batch-fulfillment.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_real_batch_fulfillment.py",
                    "--real-batch-request-path",
                    str(request_path),
                    "--p0a-execution-checklist-path",
                    str(checklist_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-14T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            verify_result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0a_real_batch_fulfillment.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("au_p0a_real_batch_fulfillment_v1", result.stdout)
        self.assertIn("real_batch_fulfillment_ready", verify_result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["summary"]["total_planned_runs"], 2436)
        self.assertEqual(verify_au_p0a_real_batch_fulfillment(payload)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
