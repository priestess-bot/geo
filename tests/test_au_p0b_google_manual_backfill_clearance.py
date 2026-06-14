from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_manual_backfill_clearance import (
    CLEARANCE_VERSION,
    build_au_p0b_google_manual_backfill_clearance,
    compute_p0b_google_manual_backfill_clearance_hash,
)
from scripts.build_au_p0b_google_manual_backfill_fulfillment import (
    build_au_p0b_google_manual_backfill_fulfillment,
)
from scripts.run_au_external_dependency_clearance import run_au_external_dependency_clearance
from scripts.verify_au_p0b_google_manual_backfill_clearance import (
    verify_au_p0b_google_manual_backfill_clearance,
)
from tests.test_au_external_dependency_clearance import AuExternalDependencyClearanceTest
from tests.test_au_p0b_google_manual_backfill_fulfillment import AuP0bGoogleManualBackfillFulfillmentTest


class AuP0bGoogleManualBackfillClearanceTest(unittest.TestCase):
    def _build_sources(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, Path, Path, Path, dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
        fulfillment_helper = AuP0bGoogleManualBackfillFulfillmentTest()
        fulfillment_helper.setUp()
        request_path, request = fulfillment_helper._write_request(temp_dir, ready=ready)
        if ready:
            verification_path = Path(str(request["summary"]["verification_path"]))  # type: ignore[index]
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            manual_jsonl_path = Path(str(verification["path"]))
        else:
            verification_path = Path(temp_dir) / "missing-verification.json"
            manual_jsonl_path = Path(temp_dir) / "missing-manual.jsonl"
            from scripts.verify_au_p0b_manual_backfill import verify_manual_backfill

            verification = verify_manual_backfill(manual_jsonl_path)
            verification_path.write_text(json.dumps(verification), encoding="utf-8")
        fulfillment_path = Path(temp_dir) / "manual-fulfillment.json"
        fulfillment = build_au_p0b_google_manual_backfill_fulfillment(
            manual_backfill_request_path=request_path,
            manual_backfill_request=request,
            manual_backfill_verification_path=verification_path,
            manual_backfill_verification=verification,
            manual_jsonl_path=manual_jsonl_path,
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
        return request_path, verification_path, fulfillment_path, clearance_path, request, verification, fulfillment, external_clearance

    def test_clearance_packet_records_blocked_manual_backfill_without_content_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, verification_path, fulfillment_path, clearance_path, request, verification, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0b_google_manual_backfill_clearance(
                manual_backfill_request_path=request_path,
                manual_backfill_verification_path=verification_path,
                manual_backfill_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                manual_jsonl_path=Path(temp_dir) / "missing-manual.jsonl",
                manual_backfill_request=request,
                manual_backfill_verification=verification,
                manual_backfill_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "manual-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            verification_result = verify_au_p0b_google_manual_backfill_clearance(packet)
            hard_gate = verify_au_p0b_google_manual_backfill_clearance(packet, require_cleared=True)

        self.assertEqual(packet["p0b_google_manual_backfill_clearance_version"], CLEARANCE_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["manual_backfill_clearance_packet_ready"])
        self.assertFalse(packet["manual_backfill_fulfilled"])
        self.assertFalse(packet["manual_backfill_clearance_ready"])
        self.assertFalse(packet["ready_for_next_clearance_step"])
        self.assertTrue(packet["blocked_by_prerequisite_step"])
        self.assertEqual(packet["clearance_step"]["id"], "p0b_google_manual_backfill")
        self.assertEqual(packet["prerequisite_step"]["id"], "p0b_google_environment")
        self.assertEqual(packet["summary"]["expected_record_count"], 120)
        self.assertEqual(packet["summary"]["record_count"], 0)
        self.assertEqual(packet["summary"]["covered_prompt_city_count"], 0)
        self.assertIn("verification:status", packet["summary"]["missing_required"])
        self.assertIn("count:record_count", packet["summary"]["missing_required"])
        self.assertIn("manual_backfill_file_missing", packet["summary"]["verification_errors"])
        self.assertEqual(packet["summary"]["next_action"], "clear_p0b_google_environment_first")
        self.assertEqual(packet["summary"]["next_command"], "make au-p0b-google-environment-clearance")
        self.assertIn("make verify-au-p0b-google-manual-backfill", packet["post_update_validation_sequence"])
        self.assertTrue(any("--require-manual-backfill-ready" in command for command in packet["post_update_validation_sequence"]))
        self.assertTrue(any("--require-fulfilled" in command for command in packet["post_update_validation_sequence"]))
        self.assertEqual(
            packet["runtime_endpoints"]["p0b_google_manual_backfill_clearance"],
            "GET /v1/p0b-google-manual-backfill-clearance/au",
        )
        self.assertIn("make verify-au-p0b-google-manual-backfill-clearance", packet["hard_gate_commands"])
        self.assertTrue(any("--require-cleared" in command for command in packet["hard_gate_commands"]))
        self.assertEqual(
            packet["p0b_google_manual_backfill_clearance_hash"],
            compute_p0b_google_manual_backfill_clearance_hash(packet),
        )
        self.assertEqual(verification_result["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0b_google_manual_backfill_not_cleared", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)
        self.assertNotIn("s3://manual-google-ai-mode", serialized)
        self.assertNotIn('"answer_text":', serialized)
        self.assertNotIn('"citation_urls":', serialized)
        self.assertNotIn('"screenshot_url":', serialized)

    def test_clearance_packet_passes_strict_gate_when_manual_backfill_and_prerequisite_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, verification_path, fulfillment_path, clearance_path, request, verification, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=True)
            )
            for step in external_clearance["steps"]:
                if step["id"] in {
                    "p0a_provider_credentials",
                    "p0a_real_batches",
                    "p0b_google_environment",
                    "p0b_google_manual_backfill",
                }:
                    step["ready"] = True
                    step["can_start"] = True
                    step["status"] = "already_ready"
                    step["would_execute"] = False
                    step["blocked_by"] = []
            packet = build_au_p0b_google_manual_backfill_clearance(
                manual_backfill_request_path=request_path,
                manual_backfill_verification_path=verification_path,
                manual_backfill_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                manual_jsonl_path=Path(str(verification["path"])),
                manual_backfill_request=request,
                manual_backfill_verification=verification,
                manual_backfill_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                output_path=Path(temp_dir) / "manual-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            hard_gate = verify_au_p0b_google_manual_backfill_clearance(packet, require_cleared=True)

        self.assertTrue(packet["manual_backfill_fulfilled"])
        self.assertTrue(packet["ready_for_next_clearance_step"])
        self.assertTrue(packet["manual_backfill_clearance_ready"])
        self.assertFalse(packet["blocked_by_prerequisite_step"])
        self.assertEqual(packet["summary"]["missing_required_count"], 0)
        self.assertEqual(packet["summary"]["record_count"], 120)
        self.assertEqual(packet["summary"]["covered_prompt_city_count"], 60)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_rejects_tampered_record_count_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, verification_path, fulfillment_path, clearance_path, request, verification, fulfillment, external_clearance = (
                self._build_sources(temp_dir, ready=False)
            )
            packet = build_au_p0b_google_manual_backfill_clearance(
                manual_backfill_request_path=request_path,
                manual_backfill_verification_path=verification_path,
                manual_backfill_fulfillment_path=fulfillment_path,
                external_dependency_clearance_path=clearance_path,
                manual_backfill_request=request,
                manual_backfill_verification=verification,
                manual_backfill_fulfillment=fulfillment,
                external_dependency_clearance=external_clearance,
                generated_at="2026-06-14T00:00:00Z",
            )
            packet["summary"]["record_count"] = 120
            packet["p0b_google_manual_backfill_clearance_hash"] = compute_p0b_google_manual_backfill_clearance_hash(packet)
            verification_result = verify_au_p0b_google_manual_backfill_clearance(packet)

        self.assertEqual(verification_result["status"], "fail")
        self.assertIn("summary_record_count_mismatch", verification_result["errors"])

    def test_cli_writes_and_verifies_clearance_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, verification_path, fulfillment_path, clearance_path, _request, _verification, _fulfillment, _external = (
                self._build_sources(temp_dir, ready=False)
            )
            output_path = Path(temp_dir) / "manual-clearance.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_manual_backfill_clearance.py",
                    "--manual-backfill-request-path",
                    str(request_path),
                    "--manual-backfill-verification-path",
                    str(verification_path),
                    "--manual-backfill-fulfillment-path",
                    str(fulfillment_path),
                    "--external-dependency-clearance-path",
                    str(clearance_path),
                    "--manual-jsonl-path",
                    str(Path(temp_dir) / "missing-manual.jsonl"),
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
                    "scripts/verify_au_p0b_google_manual_backfill_clearance.py",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(build_result.stdout)
            verification_result = json.loads(verify_result.stdout)
            self.assertTrue(output_path.exists())

        self.assertEqual(payload["status"], "pass")
        self.assertEqual(verification_result["status"], "pass")


if __name__ == "__main__":
    unittest.main()
