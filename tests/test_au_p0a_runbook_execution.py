from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_runbook import build_au_p0a_runbook
from scripts.run_au_p0a_runbook import compute_execution_payload_hash, run_au_p0a_runbook


class AuP0aRunbookExecutionFixtureMixin:
    def _write_runbook(self, temp_dir: str, *, generated_at: str = "2026-06-11T00:00:00Z") -> Path:
        runbook = build_au_p0a_runbook(
            artifact_dir=str(Path(temp_dir) / "runtime"),
            generated_at=generated_at,
        )
        path = Path(temp_dir) / "runbook.json"
        path.write_text(json.dumps(runbook), encoding="utf-8")
        return path


class AuP0aRunbookExecutionTest(AuP0aRunbookExecutionFixtureMixin, unittest.TestCase):
    def test_dry_run_records_all_steps_without_executing_commands(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            result = run_au_p0a_runbook(
                runbook_path=runbook_path,
                env={},
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["ready_to_execute"])
        self.assertFalse(result["execute_requested"])
        self.assertEqual(result["planned_step_count"], 9)
        self.assertEqual(result["recorded_step_count"], 9)
        self.assertEqual(result["executed_command_count"], 0)
        self.assertEqual(result["execution_payload_hash"], compute_execution_payload_hash(result))
        steps = {step["id"]: step for step in result["steps"]}
        self.assertEqual(steps["prepare_environment"]["status"], "manual")
        self.assertEqual(steps["preflight_collect"]["status"], "dry_run")
        self.assertEqual(steps["preflight_collect"]["external_call_risk"], "provider_api_call")
        self.assertIn("PERPLEXITY_API_KEY", result["environment"]["missing_required"])

    def test_execute_requires_required_environment_before_running_commands(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            result = run_au_p0a_runbook(
                runbook_path=runbook_path,
                execute=True,
                env={},
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["ready_to_execute"])
        self.assertIn("environment:required_env_missing:PERPLEXITY_API_KEY", result["errors"])
        self.assertEqual(result["steps"], [])

    def test_dry_run_can_stop_after_named_step(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            result = run_au_p0a_runbook(
                runbook_path=runbook_path,
                stop_after_step="preflight_design_partner_gate",
                env={},
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["stopped_after_step"])
        self.assertEqual(result["recorded_step_count"], 5)
        self.assertEqual(result["steps"][-1]["id"], "preflight_design_partner_gate")

    def test_cli_writes_dry_run_execution_plan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            output_path = Path(temp_dir) / "execution.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_au_p0a_runbook.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            output_exists = output_path.exists()

        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["execution_payload_hash"], compute_execution_payload_hash(payload))
        self.assertTrue(output_exists)


if __name__ == "__main__":
    unittest.main()
