from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_spike_runbook import build_au_p0b_google_spike_runbook
from scripts.verify_au_p0b_google_spike_runbook import verify_au_p0b_google_spike_runbook


class AuP0bGoogleSpikeRunbookVerifierTest(unittest.TestCase):
    def _runbook(self) -> dict[str, object]:
        return build_au_p0b_google_spike_runbook(generated_at="2026-06-12T00:00:00Z")

    def test_valid_runbook_passes(self) -> None:
        result = verify_au_p0b_google_spike_runbook(self._runbook())

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertEqual(result["planned_runs"], 240)
        self.assertEqual(result["step_count"], 6)

    def test_hash_mismatch_fails(self) -> None:
        runbook = self._runbook()
        runbook["scope"]["planned_runs"] = 239  # type: ignore[index]
        result = verify_au_p0b_google_spike_runbook(runbook)

        self.assertEqual(result["status"], "fail")
        self.assertIn("runbook_payload_hash_mismatch", result["errors"])
        self.assertIn("planned_runs_invalid", result["errors"])

    def test_missing_google_gate_fails(self) -> None:
        runbook = self._runbook()
        steps = {step["id"]: step for step in runbook["steps"]}  # type: ignore[index]
        steps["google_spike_collect"]["command"].remove("--require-google-spike-gates")
        result = verify_au_p0b_google_spike_runbook(runbook)

        self.assertEqual(result["status"], "fail")
        self.assertIn("google_spike_gate_missing:--require-google-spike-gates", result["errors"])

    def test_cli_reads_runbook_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runbook.json"
            path.write_text(json.dumps(self._runbook()), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0b_google_spike_runbook.py", str(path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["hash_valid"])


if __name__ == "__main__":
    unittest.main()
