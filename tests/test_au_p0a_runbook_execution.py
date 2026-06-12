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
    def _write_env_file(self, temp_dir: str) -> Path:
        env_file = Path(temp_dir) / ".env.au-p0a"
        env_file.write_text(
            "\n".join(
                [
                    "PERPLEXITY_API_KEY=perplexity-secret",
                    "OPENAI_API_KEY=openai-secret",
                    "DATABASE_URL=postgresql://user:pass@example.test/db",
                    "OBJECT_STORE_ENDPOINT=http://localhost:9000",
                ]
            ),
            encoding="utf-8",
        )
        return env_file

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

    def test_dry_run_loads_env_file_without_leaking_secret_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_file = self._write_env_file(temp_dir)
            result = run_au_p0a_runbook(
                runbook_path=runbook_path,
                env={},
                env_file_path=env_file,
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["ready_to_execute"])
        self.assertEqual(result["environment"]["status"], "pass")
        self.assertEqual(result["environment"]["missing_required"], [])
        checks = {check["name"]: check for check in result["environment"]["required"]}
        self.assertEqual(checks["PERPLEXITY_API_KEY"]["source"], "env_file")
        self.assertEqual(len(checks["PERPLEXITY_API_KEY"]["sha256_prefix"]), 12)
        self.assertNotIn("perplexity-secret", json.dumps(result))
        self.assertNotIn("openai-secret", json.dumps(result))

    def test_process_environment_overrides_env_file_in_execution_plan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_file = self._write_env_file(temp_dir)
            result = run_au_p0a_runbook(
                runbook_path=runbook_path,
                env={
                    "PERPLEXITY_API_KEY": "process-perplexity",
                    "OPENAI_API_KEY": "process-openai",
                    "DATABASE_URL": "postgresql://process.example/db",
                },
                env_file_path=env_file,
                generated_at="2026-06-11T00:00:00Z",
            )

        checks = {check["name"]: check for check in result["environment"]["required"]}
        self.assertEqual(checks["PERPLEXITY_API_KEY"]["source"], "process")
        self.assertEqual(checks["OPENAI_API_KEY"]["source"], "process")
        self.assertEqual(checks["DATABASE_URL"]["source"], "process")

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
                    "--env-file",
                    str(Path(temp_dir) / "missing.env"),
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
