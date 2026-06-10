from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest


class WorkerCliTest(unittest.TestCase):
    def _run_worker_result(
        self,
        *args: str,
        unset_env: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for key in unset_env:
            env.pop(key, None)
        env["PYTHONPATH"] = "packages/geno_core:apps/api"
        return subprocess.run(
            [sys.executable, "workers/collector_worker/run_collection_slice.py", *args],
            capture_output=True,
            text=True,
            env=env,
        )

    def _run_worker(self, *args: str) -> dict[str, object]:
        result = self._run_worker_result(*args)
        result.check_returncode()
        return json.loads(result.stdout)

    def test_fixture_worker_slice_succeeds(self) -> None:
        payload = self._run_worker("--mode", "fixture", "--prompt-limit", "1")
        self.assertEqual(payload["record_count"], 4)
        self.assertEqual(payload["success_count"], 4)
        self.assertEqual(payload["failure_count"], 0)
        gate = payload["p0a_readiness_gate"]
        self.assertEqual(gate["gate_status"], "fail")
        self.assertIn("below_required_sample_size=4", gate["failure_reasons"])
        self.assertEqual(payload["persistence"], {"enabled": False})

    def test_fixture_worker_k3_slice_passes_p0a_readiness_gate(self) -> None:
        payload = self._run_worker("--mode", "fixture", "--prompt-limit", "1", "--sample-size", "3")
        self.assertEqual(payload["record_count"], 12)
        gate = payload["p0a_readiness_gate"]
        self.assertEqual(gate["gate_status"], "pass")
        self.assertEqual(set(gate["observed_platforms"]), {"chatgpt", "perplexity"})
        self.assertEqual(gate["required_sample_size"], 3)
        self.assertEqual(gate["observed_sample_sizes"], [3])
        self.assertEqual(gate["failure_reasons"], [])

    def test_api_worker_slice_without_keys_is_audited_failure(self) -> None:
        payload = self._run_worker("--mode", "api", "--prompt-limit", "1", "--cities", "Australia")
        self.assertEqual(payload["record_count"], 2)
        self.assertEqual(payload["success_count"], 0)
        self.assertEqual(payload["failure_count"], 2)
        gate = payload["p0a_readiness_gate"]
        self.assertEqual(gate["gate_status"], "fail")
        self.assertIn("collection_failures=2", gate["failure_reasons"])
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
        readiness_gate = payload["google_spike_readiness_gate"]
        self.assertEqual(readiness_gate["gate_status"], "fail")
        self.assertIn("insufficient_collection_paths=1/2", readiness_gate["failure_reasons"])

    def test_persist_without_database_url_fails_loudly(self) -> None:
        result = self._run_worker_result(
            "--mode",
            "fixture",
            "--prompt-limit",
            "1",
            "--persist",
            unset_env=("DATABASE_URL",),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("DATABASE_URL", result.stderr)

    def test_persist_analysis_requires_persist(self) -> None:
        result = self._run_worker_result(
            "--mode",
            "fixture",
            "--prompt-limit",
            "1",
            "--persist-analysis",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--persist-analysis requires --persist", result.stderr)


if __name__ == "__main__":
    unittest.main()
