from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.run_au_p0a_runbook import compute_execution_payload_hash, run_au_p0a_runbook
from scripts.verify_au_p0a_runbook_execution import verify_au_p0a_runbook_execution
from tests.test_au_p0a_runbook_execution import AuP0aRunbookExecutionFixtureMixin


class AuP0aRunbookExecutionVerifierTest(AuP0aRunbookExecutionFixtureMixin, unittest.TestCase):
    def _write_env_file(self, temp_dir: str) -> Path:
        env_file = Path(temp_dir) / ".env.au-p0a"
        env_file.write_text(
            "\n".join(
                [
                    "PERPLEXITY_API_KEY=perplexity-secret",
                    "OPENAI_API_KEY=openai-secret",
                    "DATABASE_URL=postgresql://user:pass@example.test/db",
                ]
            ),
            encoding="utf-8",
        )
        env_file.chmod(0o600)
        return env_file

    def _execution(self, temp_dir: str) -> dict[str, object]:
        runbook_path = self._write_runbook(temp_dir)
        return run_au_p0a_runbook(
            runbook_path=runbook_path,
            env={},
            generated_at="2026-06-11T00:00:00Z",
        )

    def test_valid_dry_run_execution_passes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            execution = self._execution(temp_dir)
            result = verify_au_p0a_runbook_execution(execution)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertFalse(result["ready_to_execute"])
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["executed_command_count"], 0)

    def test_ready_env_file_execution_passes_require_ready_to_execute(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            execution = run_au_p0a_runbook(
                runbook_path=runbook_path,
                env={},
                env_file_path=self._write_env_file(temp_dir),
                generated_at="2026-06-11T00:00:00Z",
            )
            result = verify_au_p0a_runbook_execution(execution, require_ready_to_execute=True)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertTrue(result["ready_to_execute"])
        self.assertNotIn("perplexity-secret", json.dumps(execution))

    def test_hash_mismatch_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            execution = self._execution(temp_dir)
            execution["mode"] = "execute"
            result = verify_au_p0a_runbook_execution(execution)

        self.assertEqual(result["status"], "fail")
        self.assertIn("execution_payload_hash_mismatch", result["errors"])
        self.assertIn("execute_requested_mismatch", result["errors"])

    def test_recorded_step_count_mismatch_fails_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            execution = self._execution(temp_dir)
            execution["recorded_step_count"] = 8
            execution["execution_payload_hash"] = compute_execution_payload_hash(execution)
            result = verify_au_p0a_runbook_execution(execution)

        self.assertEqual(result["status"], "fail")
        self.assertIn("recorded_step_count_mismatch", result["errors"])

    def test_require_ready_to_execute_fails_without_required_env(self) -> None:
        with TemporaryDirectory() as temp_dir:
            execution = self._execution(temp_dir)
            result = verify_au_p0a_runbook_execution(execution, require_ready_to_execute=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("not_ready_to_execute", result["errors"])

    def test_forbidden_secret_field_fails_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            execution = self._execution(temp_dir)
            execution["environment"]["required"][0]["raw_value"] = "secret"  # type: ignore[index]
            execution["execution_payload_hash"] = compute_execution_payload_hash(execution)  # type: ignore[arg-type]
            result = verify_au_p0a_runbook_execution(execution)

        self.assertEqual(result["status"], "fail")
        self.assertIn("forbidden_secret_field:$.environment.required[0].raw_value", result["errors"])

    def test_cli_reads_execution_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "execution.json"
            path.write_text(json.dumps(self._execution(temp_dir)), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0a_runbook_execution.py", str(path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["hash_valid"])


if __name__ == "__main__":
    unittest.main()
