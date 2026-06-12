from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_serp_status_report import (
    build_au_p0b_google_serp_status_report,
    compute_google_serp_status_hash,
)
from scripts.verify_au_p0b_google_serp_status_report import verify_au_p0b_google_serp_status_report
from tests.test_au_p0b_google_serp_status_report import GoogleSerpStatusReportFixtureMixin


class AuP0bGoogleSerpStatusReportVerifierTest(GoogleSerpStatusReportFixtureMixin, unittest.TestCase):
    def _ready_report(self, temp_dir: str) -> dict[str, object]:
        root = Path(temp_dir)
        fixture_path = root / "fixture.json"
        fixture_manifest = root / "fixture-manifest.json"
        health_path = root / "health.json"
        health_manifest = root / "health-manifest.json"
        comparison_path = root / "comparison.json"
        comparison_manifest = root / "comparison-manifest.json"
        self._write_payload_and_manifest(payload_path=fixture_path, manifest_path=fixture_manifest)
        self._write_payload_and_manifest(
            payload_path=health_path,
            manifest_path=health_manifest,
            mode="google-serp-spike",
        )
        self._write_payload_and_manifest(
            payload_path=comparison_path,
            manifest_path=comparison_manifest,
            mode="google-serp-spike",
        )
        return build_au_p0b_google_serp_status_report(
            fixture_path=fixture_path,
            fixture_manifest_path=fixture_manifest,
            health_path=health_path,
            health_manifest_path=health_manifest,
            comparison_path=comparison_path,
            comparison_manifest_path=comparison_manifest,
            generated_at="2026-06-12T00:00:00Z",
        )

    def test_valid_ready_status_report_passes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._ready_report(temp_dir)
            result = verify_au_p0b_google_serp_status_report(report, require_comparison_evidence_ready=True)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertTrue(result["comparison_evidence_ready"])
        self.assertFalse(result["google_main_scoring_allowed"])
        self.assertEqual(result["remaining_blocker_count"], 0)

    def test_require_ready_fails_when_artifacts_are_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = build_au_p0b_google_serp_status_report(
                fixture_path=Path(temp_dir) / "fixture.json",
                fixture_manifest_path=Path(temp_dir) / "fixture-manifest.json",
                health_path=Path(temp_dir) / "health.json",
                health_manifest_path=Path(temp_dir) / "health-manifest.json",
                comparison_path=Path(temp_dir) / "comparison.json",
                comparison_manifest_path=Path(temp_dir) / "comparison-manifest.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            result = verify_au_p0b_google_serp_status_report(report, require_comparison_evidence_ready=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("comparison_evidence_not_ready", result["errors"])

    def test_hash_mismatch_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._ready_report(temp_dir)
            report["next_action"] = "tampered"
            result = verify_au_p0b_google_serp_status_report(report)

        self.assertEqual(result["status"], "fail")
        self.assertIn("status_report_hash_mismatch", result["errors"])

    def test_google_main_scoring_cannot_be_enabled_by_serp_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._ready_report(temp_dir)
            report["google_main_scoring_allowed"] = True
            report["status_report_hash"] = compute_google_serp_status_hash(report)
            result = verify_au_p0b_google_serp_status_report(report)

        self.assertEqual(result["status"], "fail")
        self.assertIn("google_main_scoring_must_remain_false", result["errors"])

    def test_cli_reads_status_report_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            report = self._ready_report(temp_dir)
            path.write_text(json.dumps(report), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0b_google_serp_status_report.py",
                    str(path),
                    "--require-comparison-evidence-ready",
                ],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["computed_status_report_hash"], compute_google_serp_status_hash(report))


if __name__ == "__main__":
    unittest.main()
