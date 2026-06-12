from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_evidence_package import (
    PACKAGE_VERSION,
    build_au_p0b_google_evidence_package,
    compute_google_evidence_package_hash,
)
from scripts.build_au_p0b_google_spike_status_report import build_au_p0b_google_spike_status_report
from scripts.verify_au_p0b_google_evidence_package import verify_au_p0b_google_evidence_package
from tests.test_au_p0b_google_spike_status_report import AuP0bGoogleSpikeStatusReportTest


class AuP0bGoogleEvidencePackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._status_helper = AuP0bGoogleSpikeStatusReportTest()

    def _write_playwright_env(self, *, runbook_path: Path, env_path: Path, temp_dir: str) -> None:
        self._status_helper._write_playwright_env(
            runbook_path=runbook_path,
            env_path=env_path,
            temp_dir=temp_dir,
        )

    def _write_smoke(self, smoke_path: Path) -> None:
        self._status_helper._write_smoke(smoke_path)

    def _write_manual_backfill_verification(self, path: Path, temp_dir: str) -> None:
        self._status_helper._write_manual_backfill_verification(path, temp_dir)

    def _write_manifest(self, payload_path: Path, manifest_path: Path, *, google_ready: bool) -> None:
        self._status_helper._write_manifest(payload_path, manifest_path, google_ready=google_ready)

    def _write_runbook_and_execution(self, temp_dir: str) -> tuple[Path, Path, dict[str, object]]:
        return self._status_helper._write_runbook_and_execution(temp_dir)

    def _write_status_report(
        self,
        temp_dir: str,
        *,
        google_ready: bool,
    ) -> tuple[Path, Path, Path, dict[str, object]]:
        runbook_path, execution_path, runbook = self._write_runbook_and_execution(temp_dir)
        if google_ready:
            artifacts = runbook["artifact_paths"]  # type: ignore[index]
            self._write_playwright_env(
                runbook_path=runbook_path,
                env_path=Path(artifacts["playwright_env_json"]),
                temp_dir=temp_dir,
            )
            self._write_smoke(Path(artifacts["playwright_smoke_json"]))
            self._write_manual_backfill_verification(Path(artifacts["manual_backfill_verification_json"]), temp_dir)
            self._write_manifest(Path(artifacts["health_json"]), Path(artifacts["health_manifest"]), google_ready=True)
            self._write_manifest(Path(artifacts["spike_json"]), Path(artifacts["spike_manifest"]), google_ready=True)

        status_report = build_au_p0b_google_spike_status_report(
            runbook_path=runbook_path,
            execution_path=execution_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        status_path = Path(temp_dir) / "status.json"
        status_path.write_text(json.dumps(status_report), encoding="utf-8")
        return runbook_path, execution_path, status_path, status_report

    def test_package_records_status_blockers_before_real_spike_exists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, status_path, _status_report = self._write_status_report(
                temp_dir,
                google_ready=False,
            )
            package = build_au_p0b_google_evidence_package(
                runbook_path=runbook_path,
                execution_path=execution_path,
                status_report_path=status_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0b_google_evidence_package(package)

        self.assertEqual(package["package_version"], PACKAGE_VERSION)
        self.assertEqual(package["status"], "fail")
        self.assertFalse(package["google_main_scoring_allowed"])
        self.assertTrue(package["limited_coverage"])
        self.assertEqual(package["next_action"], "run_google_playwright_env_report")
        self.assertIn("playwright_env", package["summary"]["missing_artifacts"])
        self.assertIn("playwright_env:file_missing", package["remaining_blockers"])
        self.assertTrue(package["artifacts"]["status_report"]["hash_valid"])  # type: ignore[index]
        self.assertEqual(package["package_payload_hash"], compute_google_evidence_package_hash(package))
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(verification["hash_valid"])

    def test_package_passes_when_status_report_allows_google_main_scoring(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, status_path, _status_report = self._write_status_report(
                temp_dir,
                google_ready=True,
            )
            package = build_au_p0b_google_evidence_package(
                runbook_path=runbook_path,
                execution_path=execution_path,
                status_report_path=status_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0b_google_evidence_package(
                package,
                require_google_main_scoring_allowed=True,
            )

        self.assertEqual(package["status"], "pass")
        self.assertTrue(package["google_main_scoring_allowed"])
        self.assertFalse(package["limited_coverage"])
        self.assertEqual(package["remaining_blockers"], [])
        self.assertEqual(package["summary"]["missing_artifacts"], [])
        self.assertEqual(package["summary"]["failed_artifacts"], [])
        self.assertIn("spike", package["summary"]["ready_artifacts"])
        self.assertIn("manual_backfill", package["summary"]["ready_artifacts"])
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(verification["google_main_scoring_allowed"])

    def test_verifier_detects_summary_mismatch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, status_path, _status_report = self._write_status_report(
                temp_dir,
                google_ready=False,
            )
            package = build_au_p0b_google_evidence_package(
                runbook_path=runbook_path,
                execution_path=execution_path,
                status_report_path=status_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            package["summary"]["failed_artifacts"] = []  # type: ignore[index]
            package["package_payload_hash"] = compute_google_evidence_package_hash(package)
            verification = verify_au_p0b_google_evidence_package(package)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_failed_artifacts_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_package(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, status_path, _status_report = self._write_status_report(
                temp_dir,
                google_ready=False,
            )
            output_path = Path(temp_dir) / "package.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_evidence_package.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--execution-path",
                    str(execution_path),
                    "--status-report-path",
                    str(status_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                capture_output=True,
                text=True,
            )
            output_exists = output_path.exists()
            verifier = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0b_google_evidence_package.py",
                    str(output_path),
                ],
                capture_output=True,
                check=True,
                text=True,
            )

        self.assertEqual(result.returncode, 2)
        stdout_payload = json.loads(result.stdout)
        verifier_payload = json.loads(verifier.stdout)
        self.assertTrue(output_exists)
        self.assertEqual(stdout_payload["package_payload_hash"], compute_google_evidence_package_hash(stdout_payload))
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertFalse(verifier_payload["google_main_scoring_allowed"])


if __name__ == "__main__":
    unittest.main()
