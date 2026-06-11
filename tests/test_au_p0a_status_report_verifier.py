from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_status_report import build_au_p0a_status_report, compute_status_report_hash
from scripts.verify_au_p0a_status_report import verify_au_p0a_status_report
from tests.test_au_p0a_status_report import AuP0aStatusReportFixtureMixin


class AuP0aStatusReportVerifierTest(AuP0aStatusReportFixtureMixin, unittest.TestCase):
    def _incomplete_report(self, temp_dir: str) -> dict[str, object]:
        runbook_path, _ = self._write_runbook(temp_dir)
        return build_au_p0a_status_report(
            runbook_path=runbook_path,
            readiness_path=Path(temp_dir) / "missing-readiness.json",
            package_path=Path(temp_dir) / "missing-package.json",
            env={},
            generated_at="2026-06-11T00:00:00Z",
        )

    def _complete_report(self, temp_dir: str) -> dict[str, object]:
        runbook_path, readiness_path, package_path = self._write_complete_package(temp_dir)
        return build_au_p0a_status_report(
            runbook_path=runbook_path,
            readiness_path=readiness_path,
            package_path=package_path,
            env={
                "PERPLEXITY_API_KEY": "perplexity-key",
                "OPENAI_API_KEY": "openai-key",
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
            },
            generated_at="2026-06-11T00:00:00Z",
        )

    def test_complete_status_report_passes_hard_gate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._complete_report(temp_dir)
            result = verify_au_p0a_status_report(report, require_design_partner_ready=True)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertTrue(result["ready_for_design_partner"])
        self.assertEqual(result["next_action"], "ready_for_design_partner_handoff")
        self.assertEqual(result["remaining_blocker_count"], 0)

    def test_hash_mismatch_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._complete_report(temp_dir)
            report["next_action"] = "tampered"
            result = verify_au_p0a_status_report(report)

        self.assertEqual(result["status"], "fail")
        self.assertIn("status_report_hash_mismatch", result["errors"])
        self.assertIn("next_action_mismatch", result["errors"])

    def test_completion_mismatch_fails_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._complete_report(temp_dir)
            report["completion"]["completion_percent"] = 50.0  # type: ignore[index]
            report["status_report_hash"] = compute_status_report_hash(report)
            result = verify_au_p0a_status_report(report)

        self.assertEqual(result["status"], "fail")
        self.assertIn("completion_mismatch:completion_percent", result["errors"])

    def test_require_design_partner_ready_fails_incomplete_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._incomplete_report(temp_dir)
            result = verify_au_p0a_status_report(report, require_design_partner_ready=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("design_partner_not_ready", result["errors"])
        self.assertEqual(result["next_action"], "configure_required_environment")

    def test_cli_reads_status_report_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            path.write_text(json.dumps(self._complete_report(temp_dir)), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0a_status_report.py", str(path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["hash_valid"])


if __name__ == "__main__":
    unittest.main()
