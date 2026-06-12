from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_spike_runbook import build_au_p0b_google_spike_runbook
from scripts.run_au_p0b_google_spike_runbook import (
    compute_google_spike_execution_hash,
    run_au_p0b_google_spike_runbook,
)


class AuP0bGoogleSpikeRunbookExecutionFixtureMixin:
    def _write_runbook(self, temp_dir: str) -> Path:
        path = Path(temp_dir) / "runbook.json"
        runbook = build_au_p0b_google_spike_runbook(
            artifact_dir=str(Path(temp_dir) / "runtime"),
            runbook_path=str(path),
            generated_at="2026-06-12T00:00:00Z",
        )
        path.write_text(json.dumps(runbook), encoding="utf-8")
        return path


class AuP0bGoogleSpikeRunbookExecutionTest(AuP0bGoogleSpikeRunbookExecutionFixtureMixin, unittest.TestCase):
    def test_dry_run_records_all_steps_without_executing_google(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            result = run_au_p0b_google_spike_runbook(
                runbook_path=runbook_path,
                env={},
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["ready_to_execute"])
        self.assertFalse(result["execute_requested"])
        self.assertEqual(result["planned_step_count"], 10)
        self.assertEqual(result["recorded_step_count"], 10)
        self.assertEqual(result["executed_command_count"], 0)
        self.assertEqual(result["execution_payload_hash"], compute_google_spike_execution_hash(result))
        steps = {step["id"]: step for step in result["steps"]}
        self.assertEqual(steps["prepare_environment"]["status"], "manual")
        self.assertEqual(steps["google_playwright_env"]["status"], "dry_run")
        self.assertEqual(steps["google_playwright_env"]["external_call_risk"], "local_environment_readiness_report")
        self.assertEqual(steps["google_playwright_env_verify"]["status"], "dry_run")
        self.assertEqual(
            steps["google_playwright_env_verify"]["external_call_risk"],
            "local_environment_readiness_verifier",
        )
        self.assertEqual(steps["google_playwright_smoke"]["status"], "dry_run")
        self.assertEqual(steps["google_playwright_smoke"]["planned_runs"], 1)
        self.assertEqual(steps["google_playwright_smoke"]["external_call_risk"], "google_browser_smoke_capture")
        self.assertEqual(steps["google_playwright_smoke_verify"]["status"], "dry_run")
        self.assertEqual(steps["google_spike_collect"]["status"], "dry_run")
        self.assertEqual(steps["google_spike_collect"]["external_call_risk"], "google_browser_or_manual_capture")
        self.assertIn("GOOGLE_PLAYWRIGHT_ENABLED", result["environment"]["missing_required"])

    def test_execute_requires_required_environment(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            result = run_au_p0b_google_spike_runbook(
                runbook_path=runbook_path,
                execute=True,
                env={},
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["ready_to_execute"])
        self.assertIn("environment:required_env_missing:GOOGLE_PLAYWRIGHT_ENABLED", result["errors"])
        self.assertEqual(result["steps"], [])

    def test_cli_writes_dry_run_execution_plan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            output_path = Path(temp_dir) / "execution.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_au_p0b_google_spike_runbook.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            output_exists = output_path.exists()

        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["execution_payload_hash"], compute_google_spike_execution_hash(payload))
        self.assertTrue(output_exists)


if __name__ == "__main__":
    unittest.main()
