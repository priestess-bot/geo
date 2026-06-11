from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.run_au_p0b_google_spike_runbook import compute_google_spike_execution_hash, run_au_p0b_google_spike_runbook
from scripts.verify_au_p0b_google_spike_runbook_execution import verify_au_p0b_google_spike_runbook_execution
from tests.test_au_p0b_google_spike_runbook_execution import AuP0bGoogleSpikeRunbookExecutionFixtureMixin


class AuP0bGoogleSpikeRunbookExecutionVerifierTest(AuP0bGoogleSpikeRunbookExecutionFixtureMixin, unittest.TestCase):
    def _execution(self, temp_dir: str) -> dict[str, object]:
        runbook_path = self._write_runbook(temp_dir)
        return run_au_p0b_google_spike_runbook(
            runbook_path=runbook_path,
            env={},
            generated_at="2026-06-12T00:00:00Z",
        )

    def test_valid_dry_run_execution_passes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            execution = self._execution(temp_dir)
            result = verify_au_p0b_google_spike_runbook_execution(execution)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertFalse(result["ready_to_execute"])
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["executed_command_count"], 0)

    def test_hash_mismatch_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            execution = self._execution(temp_dir)
            execution["mode"] = "execute"
            result = verify_au_p0b_google_spike_runbook_execution(execution)

        self.assertEqual(result["status"], "fail")
        self.assertIn("execution_payload_hash_mismatch", result["errors"])
        self.assertIn("execute_requested_mismatch", result["errors"])

    def test_require_ready_to_execute_fails_without_required_env(self) -> None:
        with TemporaryDirectory() as temp_dir:
            execution = self._execution(temp_dir)
            result = verify_au_p0b_google_spike_runbook_execution(execution, require_ready_to_execute=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("not_ready_to_execute", result["errors"])

    def test_recomputed_hash_still_catches_recorded_step_mismatch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            execution = self._execution(temp_dir)
            execution["recorded_step_count"] = 5
            execution["execution_payload_hash"] = compute_google_spike_execution_hash(execution)
            result = verify_au_p0b_google_spike_runbook_execution(execution)

        self.assertEqual(result["status"], "fail")
        self.assertIn("recorded_step_count_mismatch", result["errors"])

    def test_cli_reads_execution_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "execution.json"
            path.write_text(json.dumps(self._execution(temp_dir)), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0b_google_spike_runbook_execution.py", str(path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["hash_valid"])


if __name__ == "__main__":
    unittest.main()
