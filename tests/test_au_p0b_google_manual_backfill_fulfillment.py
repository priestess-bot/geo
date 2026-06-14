from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_manual_backfill_fulfillment import (
    FULFILLMENT_VERSION,
    build_au_p0b_google_manual_backfill_fulfillment,
    compute_p0b_google_manual_backfill_fulfillment_hash,
)
from scripts.build_au_p0b_google_manual_backfill_request_packet import (
    build_au_p0b_google_manual_backfill_request_packet,
)
from scripts.build_au_p0b_manual_backfill_template import build_manual_backfill_template
from scripts.verify_au_p0b_google_manual_backfill_fulfillment import (
    verify_au_p0b_google_manual_backfill_fulfillment,
)
from tests.test_au_p0b_google_execution_checklist import AuP0bGoogleExecutionChecklistTest


class AuP0bGoogleManualBackfillFulfillmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuP0bGoogleExecutionChecklistTest()
        self._helper.setUp()

    def _write_request(self, temp_dir: str, *, ready: bool) -> tuple[Path, dict[str, object]]:
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
        checklist_path = Path(temp_dir) / "google-checklist.json"
        checklist_path.write_text(json.dumps(checklist), encoding="utf-8")
        request = build_au_p0b_google_manual_backfill_request_packet(
            p0b_google_execution_checklist_path=checklist_path,
            p0b_google_execution_checklist=checklist,
            output_path=Path(temp_dir) / "manual-backfill-request.json",
            generated_at="2026-06-12T00:00:00Z",
        )
        request_path = Path(temp_dir) / "manual-backfill-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return request_path, request

    def _filled_jsonl(self, temp_dir: str) -> Path:
        lines, _manifest = build_manual_backfill_template(generated_at="2026-06-12T00:00:00Z")
        output_path = Path(temp_dir) / "manual-filled.jsonl"
        filled = []
        for index, line in enumerate(lines, start=1):
            filled.append(
                {
                    **line,
                    "answer_text": f"Manual Google AI Mode answer {index} mentioning ExampleBrand.",
                    "citation_urls": [f"https://examplebrand.example/manual/{index}"],
                    "screenshot_url": f"s3://manual-google-ai-mode/{index}.png",
                    "html_snapshot_url": f"s3://manual-google-ai-mode/{index}.html",
                    "submitted_by": "analyst@example.com",
                }
            )
        output_path.write_text(
            "".join(json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for line in filled),
            encoding="utf-8",
        )
        return output_path

    def test_fulfillment_records_missing_manual_verification_without_raw_content_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, request = self._write_request(temp_dir, ready=False)
            fulfillment = build_au_p0b_google_manual_backfill_fulfillment(
                manual_backfill_request_path=request_path,
                manual_backfill_request=request,
                manual_backfill_verification_path=Path(temp_dir) / "missing-verification.json",
                manual_jsonl_path=Path(temp_dir) / "missing-manual.jsonl",
                output_path=Path(temp_dir) / "manual-fulfillment.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0b_google_manual_backfill_fulfillment(fulfillment)
            hard_gate = verify_au_p0b_google_manual_backfill_fulfillment(fulfillment, require_fulfilled=True)

        self.assertEqual(fulfillment["p0b_google_manual_backfill_fulfillment_version"], FULFILLMENT_VERSION)
        self.assertEqual(fulfillment["status"], "pass")
        self.assertTrue(fulfillment["manual_backfill_fulfillment_ready"])
        self.assertFalse(fulfillment["manual_backfill_fulfilled"])
        self.assertFalse(fulfillment["google_main_scoring_allowed"])
        self.assertEqual(fulfillment["summary"]["expected_record_count"], 120)
        self.assertEqual(fulfillment["summary"]["record_count"], 0)
        self.assertEqual(fulfillment["summary"]["covered_prompt_city_count"], 0)
        self.assertIn("manual_backfill_file_missing", fulfillment["summary"]["verification_errors"])
        self.assertIn("verification:status", fulfillment["summary"]["missing_required"])
        self.assertIn("count:record_count", fulfillment["summary"]["missing_required"])
        self.assertEqual(
            fulfillment["runtime_endpoints"]["p0b_google_manual_backfill_fulfillment"],
            "GET /v1/p0b-google-manual-backfill-fulfillment/au",
        )
        self.assertIn("make verify-au-p0b-google-manual-backfill-fulfillment", fulfillment["hard_gate_commands"])
        self.assertTrue(any("--require-fulfilled" in command for command in fulfillment["hard_gate_commands"]))
        self.assertEqual(
            fulfillment["p0b_google_manual_backfill_fulfillment_hash"],
            compute_p0b_google_manual_backfill_fulfillment_hash(fulfillment),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0b_google_manual_backfill_not_fulfilled", hard_gate["errors"])
        serialized = json.dumps(fulfillment)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)
        self.assertNotIn("s3://manual-google-ai-mode", serialized)

    def test_strict_gate_passes_when_manual_verification_is_fulfilled(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, request = self._write_request(temp_dir, ready=True)
            verification_path = Path(str(request["summary"]["verification_path"]))  # type: ignore[index]
            verification_payload = json.loads(verification_path.read_text(encoding="utf-8"))
            fulfillment = build_au_p0b_google_manual_backfill_fulfillment(
                manual_backfill_request_path=request_path,
                manual_backfill_request=request,
                manual_backfill_verification_path=verification_path,
                manual_backfill_verification=verification_payload,
                manual_jsonl_path=Path(str(verification_payload["path"])),
                output_path=Path(temp_dir) / "manual-fulfillment.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            hard_gate = verify_au_p0b_google_manual_backfill_fulfillment(fulfillment, require_fulfilled=True)

        self.assertTrue(fulfillment["manual_backfill_fulfilled"])
        self.assertTrue(fulfillment["google_main_scoring_allowed"])
        self.assertEqual(fulfillment["summary"]["record_count"], 120)
        self.assertEqual(fulfillment["summary"]["covered_prompt_city_count"], 60)
        self.assertEqual(fulfillment["summary"]["missing_required_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_detects_tampered_record_count_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, request = self._write_request(temp_dir, ready=False)
            fulfillment = build_au_p0b_google_manual_backfill_fulfillment(
                manual_backfill_request_path=request_path,
                manual_backfill_request=request,
                manual_backfill_verification_path=Path(temp_dir) / "missing-verification.json",
                manual_jsonl_path=Path(temp_dir) / "missing-manual.jsonl",
                output_path=Path(temp_dir) / "manual-fulfillment.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            fulfillment["summary"]["record_count"] = 120
            fulfillment["p0b_google_manual_backfill_fulfillment_hash"] = (
                compute_p0b_google_manual_backfill_fulfillment_hash(fulfillment)
            )
            verification = verify_au_p0b_google_manual_backfill_fulfillment(fulfillment)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_record_count_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_manual_backfill_fulfillment_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, _request = self._write_request(temp_dir, ready=False)
            output_path = Path(temp_dir) / "manual-fulfillment.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_manual_backfill_fulfillment.py",
                    "--manual-backfill-request-path",
                    str(request_path),
                    "--manual-backfill-verification-path",
                    str(Path(temp_dir) / "missing-verification.json"),
                    "--manual-jsonl-path",
                    str(Path(temp_dir) / "missing-manual.jsonl"),
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
                [sys.executable, "scripts/verify_au_p0b_google_manual_backfill_fulfillment.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("au_p0b_google_manual_backfill_fulfillment_v1", result.stdout)
        self.assertIn("manual_backfill_fulfillment_ready", verify_result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(verify_au_p0b_google_manual_backfill_fulfillment(payload)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
