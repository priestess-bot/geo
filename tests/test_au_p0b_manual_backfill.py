from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_manual_backfill_template import (
    TEMPLATE_VERSION,
    build_manual_backfill_template,
    write_template,
)
from scripts.verify_au_p0b_manual_backfill import (
    compute_manual_backfill_verification_hash,
    verify_manual_backfill,
    verify_manual_backfill_verification_result,
)


class AuP0bManualBackfillTest(unittest.TestCase):
    def _filled_template(self) -> list[dict[str, object]]:
        lines, _manifest = build_manual_backfill_template(generated_at="2026-06-12T00:00:00Z")
        filled: list[dict[str, object]] = []
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
        return filled

    def test_build_manual_backfill_template_matches_google_spike_matrix(self) -> None:
        lines, manifest = build_manual_backfill_template(generated_at="2026-06-12T00:00:00Z")

        self.assertEqual(manifest["template_version"], TEMPLATE_VERSION)
        self.assertEqual(manifest["prompt_count"], 30)
        self.assertEqual(manifest["geo_cities"], ("Australia", "Sydney"))
        self.assertEqual(manifest["sample_size"], 2)
        self.assertEqual(manifest["expected_record_count"], 120)
        self.assertEqual(manifest["record_count"], 120)
        self.assertRegex(manifest["jsonl_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest["manifest_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(lines), 120)
        self.assertEqual(lines[0]["template_version"], TEMPLATE_VERSION)
        self.assertEqual(lines[0]["surface"], "google_ai_mode")
        self.assertEqual(lines[0]["answer_text"], "")

    def test_verify_template_allows_placeholders_but_strict_requires_answers(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "manual-template.jsonl"
            manifest_path = Path(temp_dir) / "manual-template-manifest.json"
            manifest = write_template(
                output_path=output_path,
                manifest_path=manifest_path,
                generated_at="2026-06-12T00:00:00Z",
            )

            relaxed = verify_manual_backfill(output_path, allow_template_placeholders=True)
            strict = verify_manual_backfill(output_path)

        self.assertEqual(manifest["record_count"], 120)
        self.assertEqual(manifest["jsonl_sha256"], relaxed["file_sha256"])
        self.assertEqual(relaxed["status"], "pass")
        self.assertEqual(relaxed["record_count"], 120)
        self.assertFalse(relaxed["summary"]["manual_backfill_ready"])
        self.assertTrue(relaxed["summary"]["template_placeholder_mode"])
        self.assertTrue(relaxed["summary"]["coverage_complete"])
        self.assertFalse(relaxed["summary"]["content_complete"])
        self.assertEqual(relaxed["summary"]["missing_answer_line_count"], 120)
        self.assertEqual(relaxed["summary"]["missing_citation_line_count"], 120)
        self.assertEqual(relaxed["summary"]["missing_asset_line_count"], 120)
        self.assertEqual(relaxed["summary"]["next_action"], "complete_manual_backfill_jsonl")
        self.assertEqual(strict["status"], "fail")
        self.assertIn("answer_text_missing:120", strict["errors"])
        self.assertIn("citation_urls_missing:120", strict["errors"])
        self.assertIn("evidence_asset_missing:120", strict["errors"])
        self.assertFalse(strict["summary"]["manual_backfill_ready"])
        self.assertFalse(strict["summary"]["template_placeholder_mode"])
        self.assertTrue(strict["summary"]["coverage_complete"])
        self.assertFalse(strict["summary"]["content_complete"])

    def test_verify_filled_manual_backfill_passes_strict_mode(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "manual-filled.jsonl"
            output_path.write_text(
                "".join(
                    json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                    for line in self._filled_template()
                ),
                encoding="utf-8",
            )

            result = verify_manual_backfill(output_path)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["record_count"], 120)
        self.assertEqual(result["covered_prompt_city_count"], 60)
        self.assertTrue(result["summary"]["manual_backfill_ready"])
        self.assertTrue(result["summary"]["coverage_complete"])
        self.assertTrue(result["summary"]["content_complete"])
        self.assertEqual(result["summary"]["missing_answer_line_count"], 0)
        self.assertEqual(result["summary"]["missing_citation_line_count"], 0)
        self.assertEqual(result["summary"]["missing_asset_line_count"], 0)
        self.assertEqual(result["summary"]["next_action"], "build_manual_backfill_fulfillment")
        self.assertRegex(result["file_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(result["verification_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(result["verification_hash"], compute_manual_backfill_verification_hash(result))
        self.assertEqual(verify_manual_backfill_verification_result(result)["status"], "pass")

    def test_verify_manual_backfill_fails_on_missing_record_and_answer(self) -> None:
        lines = self._filled_template()
        lines.pop()
        lines[0] = {**lines[0], "answer_text": ""}
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "manual-broken.jsonl"
            output_path.write_text(
                "".join(
                    json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                    for line in lines
                ),
                encoding="utf-8",
            )

            result = verify_manual_backfill(output_path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("record_count_invalid:119/120", result["errors"])
        self.assertIn("missing_prompt_city_samples:1", result["errors"])
        self.assertIn("answer_text_missing:1", result["errors"])
        self.assertFalse(result["summary"]["coverage_complete"])
        self.assertFalse(result["summary"]["content_complete"])
        self.assertEqual(result["summary"]["missing_prompt_city_sample_count"], 1)
        self.assertEqual(result["summary"]["missing_answer_line_count"], 1)
        self.assertEqual(result["summary"]["next_action"], "fix_google_manual_backfill_coverage")

    def test_verifier_detects_summary_tampering_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "manual-filled.jsonl"
            output_path.write_text(
                "".join(
                    json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                    for line in self._filled_template()
                ),
                encoding="utf-8",
            )
            result = verify_manual_backfill(output_path)
            result["summary"]["manual_backfill_ready"] = False
            result["summary"]["missing_answer_line_count"] = 1
            result["summary"]["raw_answer_values_allowed"] = True
            result["verification_hash"] = compute_manual_backfill_verification_hash(result)
            verification = verify_manual_backfill_verification_result(result)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_manual_backfill_ready_mismatch", verification["errors"])
        self.assertIn("summary_missing_answer_line_count_mismatch", verification["errors"])
        self.assertIn("summary_raw_answer_values_allowed_mismatch", verification["errors"])

    def test_cli_writes_template_and_verifies_placeholders(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "manual-template.jsonl"
            manifest_path = Path(temp_dir) / "manual-template-manifest.json"
            verification_path = Path(temp_dir) / "manual-template-verification.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_manual_backfill_template.py",
                    "--output-path",
                    str(output_path),
                    "--manifest-path",
                    str(manifest_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            verify_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0b_manual_backfill.py",
                    str(output_path),
                    "--output-path",
                    str(verification_path),
                    "--allow-template-placeholders",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            verification_payload = json.loads(verification_path.read_text(encoding="utf-8"))

        self.assertEqual(json.loads(build_result.stdout)["record_count"], 120)
        self.assertEqual(json.loads(verify_result.stdout)["status"], "pass")
        self.assertEqual(verification_payload, json.loads(verify_result.stdout))
        self.assertEqual(verify_manual_backfill_verification_result(verification_payload)["status"], "pass")

    def test_cli_can_write_blocked_verification_artifact_without_passing_strict_gate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "manual-template.jsonl"
            verification_path = Path(temp_dir) / "manual-template-verification.json"
            write_template(
                output_path=output_path,
                manifest_path=Path(temp_dir) / "manual-template-manifest.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            strict_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0b_manual_backfill.py",
                    str(output_path),
                    "--output-path",
                    str(verification_path),
                ],
                capture_output=True,
                text=True,
            )
            blocked_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0b_manual_backfill.py",
                    str(output_path),
                    "--output-path",
                    str(verification_path),
                    "--allow-blocked-output",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            verification_payload = json.loads(verification_path.read_text(encoding="utf-8"))

        self.assertEqual(strict_result.returncode, 2)
        self.assertEqual(json.loads(blocked_result.stdout)["status"], "fail")
        self.assertEqual(verification_payload["summary"]["missing_answer_line_count"], 120)
        self.assertEqual(verify_manual_backfill_verification_result(verification_payload)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
