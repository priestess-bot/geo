from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_evidence_package import build_au_p0b_google_evidence_package
from scripts.build_au_p0b_google_execution_checklist import (
    CHECKLIST_VERSION,
    build_au_p0b_google_execution_checklist,
    compute_google_execution_checklist_hash,
)
from scripts.build_au_p0b_google_spike_status_report import build_au_p0b_google_spike_status_report
from scripts.verify_au_p0b_google_execution_checklist import verify_au_p0b_google_execution_checklist
from tests import test_au_p0b_google_spike_status_report as p0b_status_helpers


class AuP0bGoogleExecutionChecklistTest(unittest.TestCase):
    def setUp(self) -> None:
        self._status_helper = p0b_status_helpers.AuP0bGoogleSpikeStatusReportTest()

    def _write_runbook_and_execution(self, temp_dir: str) -> tuple[Path, Path, dict[str, object]]:
        return self._status_helper._write_runbook_and_execution(temp_dir)

    def _write_ready_artifacts(self, temp_dir: str, runbook_path: Path, runbook: dict[str, object]) -> None:
        artifacts = runbook["artifact_paths"]  # type: ignore[index]
        self._status_helper._write_playwright_env(
            runbook_path=runbook_path,
            env_path=Path(artifacts["playwright_env_json"]),
            temp_dir=temp_dir,
        )
        self._status_helper._write_smoke(Path(artifacts["playwright_smoke_json"]))
        self._status_helper._write_manual_backfill_verification(
            Path(artifacts["manual_backfill_verification_json"]),
            temp_dir,
        )
        self._status_helper._write_manifest(Path(artifacts["health_json"]), Path(artifacts["health_manifest"]), google_ready=True)
        self._status_helper._write_manifest(Path(artifacts["spike_json"]), Path(artifacts["spike_manifest"]), google_ready=True)

    def _write_status_and_package(
        self,
        temp_dir: str,
        *,
        google_ready: bool,
    ) -> tuple[Path, Path, Path, Path, Path, dict[str, object]]:
        runbook_path, execution_path, runbook = self._write_runbook_and_execution(temp_dir)
        if google_ready:
            self._write_ready_artifacts(temp_dir, runbook_path, runbook)
        status = build_au_p0b_google_spike_status_report(
            runbook_path=runbook_path,
            execution_path=execution_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        status_path = Path(temp_dir) / "status.json"
        status_path.write_text(json.dumps(status), encoding="utf-8")
        package = build_au_p0b_google_evidence_package(
            runbook_path=runbook_path,
            execution_path=execution_path,
            status_report_path=status_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        package_path = Path(temp_dir) / "package.json"
        package_path.write_text(json.dumps(package), encoding="utf-8")
        artifacts = runbook["artifact_paths"]  # type: ignore[index]
        return runbook_path, execution_path, Path(artifacts["playwright_env_json"]), status_path, package_path, runbook

    def test_checklist_records_current_google_blockers_without_raw_selector_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = self._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            checklist = build_au_p0b_google_execution_checklist(
                runbook_path=runbook_path,
                execution_path=execution_path,
                playwright_env_path=env_path,
                status_report_path=status_path,
                package_path=package_path,
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0b_google_execution_checklist(checklist)

        self.assertEqual(checklist["execution_checklist_version"], CHECKLIST_VERSION)
        self.assertEqual(checklist["status"], "fail")
        self.assertFalse(checklist["google_execution_checklist_ready"])
        self.assertFalse(checklist["google_main_scoring_allowed"])
        self.assertEqual(checklist["next_action"], "populate_google_playwright_smoke_environment")
        self.assertTrue(
            any(str(blocker).startswith("playwright_env:") for blocker in checklist["summary"]["remaining_blockers"])
        )
        self.assertIn("run_smoke", {command["id"] for command in checklist["execution_commands"]})
        self.assertEqual(
            checklist["google_execution_checklist_hash"],
            compute_google_execution_checklist_hash(checklist),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertNotIn("#prompt", json.dumps(checklist))
        self.assertNotIn(".answer", json.dumps(checklist))

    def test_checklist_passes_when_google_package_allows_main_scoring(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = self._write_status_and_package(
                temp_dir,
                google_ready=True,
            )
            checklist = build_au_p0b_google_execution_checklist(
                runbook_path=runbook_path,
                execution_path=execution_path,
                playwright_env_path=env_path,
                status_report_path=status_path,
                package_path=package_path,
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0b_google_execution_checklist(
                checklist,
                require_google_main_scoring_ready=True,
            )

        self.assertEqual(checklist["status"], "pass")
        self.assertTrue(checklist["google_execution_checklist_ready"])
        self.assertTrue(checklist["google_main_scoring_allowed"])
        self.assertEqual(checklist["next_action"], "allow_google_into_main_scoring_denominator")
        self.assertEqual(checklist["summary"]["remaining_blockers"], [])
        self.assertEqual(verification["status"], "pass")

    def test_verifier_detects_hash_and_summary_tampering(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = self._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            checklist = build_au_p0b_google_execution_checklist(
                runbook_path=runbook_path,
                execution_path=execution_path,
                playwright_env_path=env_path,
                status_report_path=status_path,
                package_path=package_path,
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-12T00:00:00Z",
            )
            checklist["summary"]["remaining_blocker_count"] = 0  # type: ignore[index]
            verification = verify_au_p0b_google_execution_checklist(checklist)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("google_execution_checklist_hash_mismatch", verification["errors"])
        self.assertIn("summary_remaining_blocker_count_mismatch", verification["errors"])

    def test_verifier_rejects_forbidden_secret_fields_anywhere(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = self._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            checklist = build_au_p0b_google_execution_checklist(
                runbook_path=runbook_path,
                execution_path=execution_path,
                playwright_env_path=env_path,
                status_report_path=status_path,
                package_path=package_path,
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-12T00:00:00Z",
            )
            checklist["selector_groups"][0]["raw_value"] = "#prompt"  # type: ignore[index]
            checklist["google_execution_checklist_hash"] = compute_google_execution_checklist_hash(checklist)
            verification = verify_au_p0b_google_execution_checklist(checklist)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("forbidden_secret_field:$.selector_groups[0].raw_value", verification["errors"])

    def test_cli_writes_and_verifies_checklist(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = self._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            output_path = Path(temp_dir) / "checklist.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_execution_checklist.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--execution-path",
                    str(execution_path),
                    "--playwright-env-path",
                    str(env_path),
                    "--status-report-path",
                    str(status_path),
                    "--package-path",
                    str(package_path),
                    "--env-file",
                    str(Path(temp_dir) / "missing.env"),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            verify_result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0b_google_execution_checklist.py", str(output_path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(build_result.stdout)
        verifier_payload = json.loads(verify_result.stdout)
        self.assertEqual(payload["google_execution_checklist_hash"], compute_google_execution_checklist_hash(payload))
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertEqual(verifier_payload["next_action"], "populate_google_playwright_smoke_environment")


if __name__ == "__main__":
    unittest.main()
