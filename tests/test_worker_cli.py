from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest


class WorkerCliTest(unittest.TestCase):
    def _run_worker(self, *args: str) -> dict[str, object]:
        env = os.environ.copy()
        env["PYTHONPATH"] = "packages/geno_core:apps/api"
        result = subprocess.run(
            [sys.executable, "workers/collector_worker/run_collection_slice.py", *args],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return json.loads(result.stdout)

    def test_fixture_worker_slice_succeeds(self) -> None:
        payload = self._run_worker("--mode", "fixture", "--prompt-limit", "1")
        self.assertEqual(payload["record_count"], 4)
        self.assertEqual(payload["success_count"], 4)
        self.assertEqual(payload["failure_count"], 0)

    def test_api_worker_slice_without_keys_is_audited_failure(self) -> None:
        payload = self._run_worker("--mode", "api", "--prompt-limit", "1", "--cities", "Australia")
        self.assertEqual(payload["record_count"], 2)
        self.assertEqual(payload["success_count"], 0)
        self.assertEqual(payload["failure_count"], 2)
        failure_events = payload["failure_events"]
        self.assertIsInstance(failure_events, list)
        self.assertEqual(failure_events[0]["audit_events"][0]["event_type"], "answer_run_failed")

    def test_google_fixture_worker_slice_returns_gate(self) -> None:
        payload = self._run_worker("--mode", "google-fixture")
        self.assertEqual(payload["record_count"], 240)
        self.assertEqual(payload["success_count"], 240)
        gate = payload["google_spike_gate"]
        self.assertEqual(gate["gate_status"], "pass")
        self.assertFalse(gate["limited_coverage"])


if __name__ == "__main__":
    unittest.main()
