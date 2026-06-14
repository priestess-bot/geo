from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_manual_backfill_request_packet import (
    PACKET_VERSION,
    build_au_p0b_google_manual_backfill_request_packet,
    compute_p0b_google_manual_backfill_request_packet_hash,
)
from scripts.verify_au_p0b_google_manual_backfill_request_packet import (
    verify_au_p0b_google_manual_backfill_request_packet,
)
from tests.test_au_p0b_google_execution_checklist import AuP0bGoogleExecutionChecklistTest


class AuP0bGoogleManualBackfillRequestPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuP0bGoogleExecutionChecklistTest()
        self._helper.setUp()

    def _write_execution_checklist(self, temp_dir: str, *, ready: bool) -> tuple[Path, dict[str, object]]:
        runbook_path, execution_path, env_path, status_path, package_path, _runbook = self._helper._write_status_and_package(
            temp_dir,
            google_ready=ready,
        )
        from scripts.build_au_p0b_google_execution_checklist import build_au_p0b_google_execution_checklist

        checklist = build_au_p0b_google_execution_checklist(
            runbook_path=runbook_path,
            execution_path=execution_path,
            playwright_env_path=env_path,
            status_report_path=status_path,
            package_path=package_path,
            env_file_path=Path(temp_dir) / "missing-google.env",
            output_path=Path(temp_dir) / "google-checklist.json",
            generated_at="2026-06-12T00:00:00Z",
        )
        path = Path(temp_dir) / "google-checklist.json"
        path.write_text(json.dumps(checklist), encoding="utf-8")
        return path, checklist

    def test_packet_records_missing_manual_backfill_without_raw_content_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0b_google_manual_backfill_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                output_path=Path(temp_dir) / "manual-backfill-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0b_google_manual_backfill_request_packet(packet)
            hard_gate = verify_au_p0b_google_manual_backfill_request_packet(
                packet,
                require_manual_backfill_ready=True,
            )

        self.assertEqual(packet["p0b_google_manual_backfill_request_packet_version"], PACKET_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["manual_backfill_request_packet_ready"])
        self.assertFalse(packet["manual_backfill_handoff_ready"])
        self.assertFalse(packet["google_main_scoring_allowed"])
        self.assertEqual(packet["summary"]["expected_record_count"], 120)
        self.assertEqual(packet["summary"]["record_count"], 0)
        self.assertEqual(packet["summary"]["expected_prompt_city_count"], 60)
        self.assertEqual(packet["summary"]["covered_prompt_city_count"], 0)
        self.assertEqual(packet["summary"]["expected_sample_size"], 2)
        self.assertEqual(packet["summary"]["prompt_count"], 30)
        self.assertEqual(packet["summary"]["geo_cities"], ["Australia", "Sydney"])
        self.assertEqual(packet["summary"]["missing_reasons"], ["manual_backfill:file_missing"])
        self.assertEqual(packet["summary"]["next_command"], "make au-p0b-google-manual-template")
        self.assertEqual(
            packet["summary"]["post_update_verification_command"],
            "make verify-au-p0b-google-manual-backfill",
        )
        self.assertTrue(packet["summary"]["content_redacted"])
        self.assertFalse(packet["summary"]["raw_answer_values_allowed"])
        self.assertFalse(packet["summary"]["raw_citation_values_allowed"])
        self.assertFalse(packet["summary"]["raw_asset_urls_allowed"])
        self.assertEqual(
            packet["manual_backfill_request"]["template_path"],
            "docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl",
        )
        self.assertIn("answer_text", packet["required_fields"])
        self.assertIn("citation_urls", packet["required_fields"])
        self.assertIn("screenshot_url or html_snapshot_url", packet["required_fields"])
        self.assertIn("fill_answer_text_for_each_record", packet["operator_requirements"])
        self.assertIn("make au-p0b-google-manual-template", packet["setup_commands"])
        self.assertIn("make verify-au-p0b-google-manual-backfill", packet["verification_commands"])
        self.assertIn(packet["summary"]["verification_path"], packet["evidence_outputs"])
        self.assertEqual(
            packet["runtime_endpoints"]["p0b_google_manual_backfill_request"],
            "GET /v1/p0b-google-manual-backfill-request/au",
        )
        self.assertIn("make verify-au-p0b-google-manual-backfill-request", packet["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-manual-backfill-ready") for command in packet["hard_gate_commands"]))
        self.assertEqual(
            packet["p0b_google_manual_backfill_request_packet_hash"],
            compute_p0b_google_manual_backfill_request_packet_hash(packet),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0b_google_manual_backfill_not_ready", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)
        self.assertNotIn("s3://manual-backfill", serialized)

    def test_packet_passes_manual_backfill_ready_gate_when_google_inputs_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=True)
            packet = build_au_p0b_google_manual_backfill_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                output_path=Path(temp_dir) / "manual-backfill-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            hard_gate = verify_au_p0b_google_manual_backfill_request_packet(
                packet,
                require_manual_backfill_ready=True,
            )

        self.assertTrue(packet["manual_backfill_handoff_ready"])
        self.assertTrue(packet["google_main_scoring_allowed"])
        self.assertEqual(packet["summary"]["record_count"], 120)
        self.assertEqual(packet["summary"]["covered_prompt_city_count"], 60)
        self.assertEqual(packet["summary"]["missing_reason_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_detects_tampered_record_count_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0b_google_manual_backfill_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                output_path=Path(temp_dir) / "manual-backfill-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["summary"]["record_count"] = 120
            packet["p0b_google_manual_backfill_request_packet_hash"] = (
                compute_p0b_google_manual_backfill_request_packet_hash(packet)
            )
            verification = verify_au_p0b_google_manual_backfill_request_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_record_count_mismatch", verification["errors"])

    def test_verifier_rejects_raw_manual_payload_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0b_google_manual_backfill_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                output_path=Path(temp_dir) / "manual-backfill-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["manual_backfill_request"]["answer_text"] = "raw answer should not be in request packet"
            packet["p0b_google_manual_backfill_request_packet_hash"] = (
                compute_p0b_google_manual_backfill_request_packet_hash(packet)
            )
            verification = verify_au_p0b_google_manual_backfill_request_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn(
            "forbidden_manual_payload_field:$.manual_backfill_request.answer_text",
            verification["errors"],
        )

    def test_cli_writes_google_manual_backfill_request_packet_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, _checklist = self._write_execution_checklist(temp_dir, ready=False)
            output_path = Path(temp_dir) / "manual-backfill-request.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_manual_backfill_request_packet.py",
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
                [sys.executable, "scripts/verify_au_p0b_google_manual_backfill_request_packet.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("au_p0b_google_manual_backfill_request_packet_v1", result.stdout)
        self.assertIn("manual_backfill_request_packet_ready", verify_result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["summary"]["missing_reason_count"], 1)
        self.assertEqual(verify_au_p0b_google_manual_backfill_request_packet(payload)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
