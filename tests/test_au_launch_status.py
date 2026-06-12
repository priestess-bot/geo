from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_launch_status import (
    LAUNCH_STATUS_VERSION,
    build_au_launch_status,
    compute_launch_status_hash,
)
from scripts.build_au_p0a_status_report import build_au_p0a_status_report
from scripts.build_au_p0b_google_evidence_package import build_au_p0b_google_evidence_package
from scripts.verify_au_launch_status import verify_au_launch_status
from tests.test_au_p0a_status_report import AuP0aStatusReportFixtureMixin
from tests.test_au_p0b_google_evidence_package import AuP0bGoogleEvidencePackageTest


class AuLaunchStatusTest(AuP0aStatusReportFixtureMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._p0b_helper = AuP0bGoogleEvidencePackageTest()
        self._p0b_helper.setUp()

    def _write_p0a_status(self, temp_dir: str, *, ready: bool) -> Path:
        output_path = Path(temp_dir) / "p0a-status.json"
        if ready:
            runbook_path, environment_path, readiness_path, execution_path, package_path = self._write_complete_package(
                temp_dir
            )
            report = build_au_p0a_status_report(
                runbook_path=runbook_path,
                environment_path=environment_path,
                readiness_path=readiness_path,
                runbook_execution_path=execution_path,
                package_path=package_path,
                env={
                    "PERPLEXITY_API_KEY": "perplexity-key",
                    "OPENAI_API_KEY": "openai-key",
                    "DATABASE_URL": "postgresql://user:pass@example.test/db",
                },
                generated_at="2026-06-12T00:00:00Z",
            )
        else:
            runbook_path, _ = self._write_runbook(temp_dir)
            environment_path = Path(temp_dir) / "p0a-environment.json"
            execution_path = Path(temp_dir) / "p0a-execution.json"
            self._write_env_report(environment_path, runbook_path, ready=False)
            self._write_runbook_execution(execution_path, runbook_path, ready=False)
            report = build_au_p0a_status_report(
                runbook_path=runbook_path,
                environment_path=environment_path,
                readiness_path=Path(temp_dir) / "missing-readiness.json",
                runbook_execution_path=execution_path,
                package_path=Path(temp_dir) / "missing-p0a-package.json",
                env={},
                generated_at="2026-06-12T00:00:00Z",
            )
        output_path.write_text(json.dumps(report), encoding="utf-8")
        return output_path

    def _write_p0b_status_and_package(self, temp_dir: str, *, google_ready: bool) -> tuple[Path, Path, Path, Path]:
        runbook_path, execution_path, status_path, _status = self._p0b_helper._write_status_report(
            temp_dir,
            google_ready=google_ready,
        )
        package = build_au_p0b_google_evidence_package(
            runbook_path=runbook_path,
            execution_path=execution_path,
            status_report_path=status_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        package_path = Path(temp_dir) / "p0b-package.json"
        package_path.write_text(json.dumps(package), encoding="utf-8")
        return runbook_path, execution_path, status_path, package_path

    def test_launch_status_records_p0a_blocker_before_design_partner_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            p0a_status_path = self._write_p0a_status(temp_dir, ready=False)
            runbook_path, execution_path, p0b_status_path, p0b_package_path = self._write_p0b_status_and_package(
                temp_dir,
                google_ready=False,
            )
            report = build_au_launch_status(
                p0a_status_path=p0a_status_path,
                p0b_google_status_path=p0b_status_path,
                p0b_google_package_path=p0b_package_path,
                p0b_google_runbook_path=runbook_path,
                p0b_google_execution_path=execution_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_launch_status(report)

        self.assertEqual(report["launch_status_version"], LAUNCH_STATUS_VERSION)
        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["ready_for_customer_report_handoff"])
        self.assertEqual(report["next_action"], "configure_required_environment")
        self.assertFalse(report["p0a_design_partner"]["ready_for_design_partner"])  # type: ignore[index]
        self.assertFalse(report["p0b_google"]["google_main_scoring_allowed"])  # type: ignore[index]
        self.assertEqual(report["p0c_customer_report"]["status"], "pass")  # type: ignore[index]
        self.assertIn("p0a:readiness:readiness_file_missing", report["remaining_blockers"])
        self.assertIn("p0b_google:playwright_env:file_missing", report["remaining_blockers"])
        self.assertEqual(report["launch_status_hash"], compute_launch_status_hash(report))
        self.assertEqual(verification["status"], "pass")
        self.assertFalse(verification["ready_for_customer_report_handoff"])

    def test_launch_status_moves_to_google_next_action_after_p0a_is_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            p0a_status_path = self._write_p0a_status(temp_dir, ready=True)
            runbook_path, execution_path, p0b_status_path, p0b_package_path = self._write_p0b_status_and_package(
                temp_dir,
                google_ready=False,
            )
            report = build_au_launch_status(
                p0a_status_path=p0a_status_path,
                p0b_google_status_path=p0b_status_path,
                p0b_google_package_path=p0b_package_path,
                p0b_google_runbook_path=runbook_path,
                p0b_google_execution_path=execution_path,
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(report["status"], "fail")
        self.assertTrue(report["p0a_design_partner"]["ready_for_design_partner"])  # type: ignore[index]
        self.assertFalse(report["p0b_google"]["google_main_scoring_allowed"])  # type: ignore[index]
        self.assertEqual(report["next_action"], "run_google_playwright_env_report")
        self.assertTrue(report["p0b_google"]["limited_coverage"])  # type: ignore[index]

    def test_launch_status_passes_when_p0a_p0b_and_p0c_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            p0a_status_path = self._write_p0a_status(temp_dir, ready=True)
            runbook_path, execution_path, p0b_status_path, p0b_package_path = self._write_p0b_status_and_package(
                temp_dir,
                google_ready=True,
            )
            report = build_au_launch_status(
                p0a_status_path=p0a_status_path,
                p0b_google_status_path=p0b_status_path,
                p0b_google_package_path=p0b_package_path,
                p0b_google_runbook_path=runbook_path,
                p0b_google_execution_path=execution_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_launch_status(report, require_ready=True)

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["ready_for_customer_report_handoff"])
        self.assertEqual(report["next_action"], "ready_for_customer_report_handoff")
        self.assertEqual(report["remaining_blockers"], [])
        self.assertEqual(report["p0c_customer_report"]["status"], "pass")  # type: ignore[index]
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(verification["ready_for_customer_report_handoff"])

    def test_verifier_detects_hash_mismatch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            p0a_status_path = self._write_p0a_status(temp_dir, ready=False)
            runbook_path, execution_path, p0b_status_path, p0b_package_path = self._write_p0b_status_and_package(
                temp_dir,
                google_ready=False,
            )
            report = build_au_launch_status(
                p0a_status_path=p0a_status_path,
                p0b_google_status_path=p0b_status_path,
                p0b_google_package_path=p0b_package_path,
                p0b_google_runbook_path=runbook_path,
                p0b_google_execution_path=execution_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            report["next_action"] = "tampered"
            verification = verify_au_launch_status(report)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("launch_status_hash_mismatch", verification["errors"])
        self.assertIn("next_action_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_launch_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            p0a_status_path = self._write_p0a_status(temp_dir, ready=False)
            runbook_path, execution_path, p0b_status_path, p0b_package_path = self._write_p0b_status_and_package(
                temp_dir,
                google_ready=False,
            )
            output_path = Path(temp_dir) / "launch.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_launch_status.py",
                    "--p0a-status-path",
                    str(p0a_status_path),
                    "--p0b-google-status-path",
                    str(p0b_status_path),
                    "--p0b-google-package-path",
                    str(p0b_package_path),
                    "--p0b-google-runbook-path",
                    str(runbook_path),
                    "--p0b-google-execution-path",
                    str(execution_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            verifier = subprocess.run(
                [sys.executable, "scripts/verify_au_launch_status.py", str(output_path)],
                capture_output=True,
                check=True,
                text=True,
            )
            hard_gate = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_launch_status.py",
                    str(output_path),
                    "--require-ready",
                ],
                capture_output=True,
                check=False,
                text=True,
            )

        payload = json.loads(result.stdout)
        verifier_payload = json.loads(verifier.stdout)
        self.assertEqual(payload["launch_status_hash"], compute_launch_status_hash(payload))
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertFalse(verifier_payload["ready_for_customer_report_handoff"])
        self.assertEqual(hard_gate.returncode, 2)


if __name__ == "__main__":
    unittest.main()
