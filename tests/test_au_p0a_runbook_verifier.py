from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_runbook import build_au_p0a_runbook
from scripts.verify_au_p0a_runbook import verify_au_p0a_runbook


class AuP0aRunbookVerifierTest(unittest.TestCase):
    def _runbook(self) -> dict[str, object]:
        return build_au_p0a_runbook(generated_at="2026-06-11T00:00:00Z")

    def test_valid_runbook_passes(self) -> None:
        runbook = self._runbook()
        result = verify_au_p0a_runbook(runbook)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertEqual(result["small_batch_planned_runs"], 30)
        self.assertEqual(result["full_batch_planned_runs"], 2400)
        self.assertEqual(result["step_count"], 9)

    def test_hash_mismatch_fails(self) -> None:
        runbook = self._runbook()
        runbook["scope"]["small_batch"]["planned_runs"] = 31  # type: ignore[index]
        result = verify_au_p0a_runbook(runbook)
        self.assertEqual(result["status"], "fail")
        self.assertIn("runbook_payload_hash_mismatch", result["errors"])
        self.assertIn("small_batch_planned_runs_invalid", result["errors"])

    def test_missing_design_partner_gate_fails(self) -> None:
        runbook = self._runbook()
        steps = {step["id"]: step for step in runbook["steps"]}  # type: ignore[index]
        steps["full_batch_manifest_gate"]["command"].remove("--require-design-partner-ready")
        result = verify_au_p0a_runbook(runbook)
        self.assertEqual(result["status"], "fail")
        self.assertIn("design_partner_gate_missing:full_batch_manifest_gate", result["errors"])

    def test_step_order_change_fails(self) -> None:
        runbook = self._runbook()
        steps = list(runbook["steps"])  # type: ignore[index]
        steps[1], steps[2] = steps[2], steps[1]
        runbook["steps"] = steps
        result = verify_au_p0a_runbook(runbook)
        self.assertEqual(result["status"], "fail")
        self.assertIn("step_order_invalid", result["errors"])

    def test_cli_reads_runbook_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runbook.json"
            path.write_text(json.dumps(self._runbook()), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0a_runbook.py", str(path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["hash_valid"])


if __name__ == "__main__":
    unittest.main()
