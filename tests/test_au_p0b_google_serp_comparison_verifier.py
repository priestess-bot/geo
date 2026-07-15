from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.verify_au_p0b_google_serp_comparison import verify_au_p0b_google_serp_comparison


class AuP0bGoogleSerpComparisonVerifierTest(unittest.TestCase):
    def _run_worker_result(
        self,
        *args: str,
        unset_env: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for key in unset_env:
            env.pop(key, None)
        env["PYTHONPATH"] = "packages/geo_core:apps/api"
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

    def test_fixture_comparison_payload_passes_ready_gate(self) -> None:
        payload = self._run_worker("--mode", "google-serp-fixture")

        result = verify_au_p0b_google_serp_comparison(payload, require_comparison_ready=True)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertTrue(result["comparison_ready"])
        self.assertTrue(result["collector_health_ready"])
        self.assertTrue(result["full_spike_gates_absent"])
        self.assertEqual(result["planned_runs"], 120)
        self.assertEqual(result["main_google_spike_planned_runs"], 240)

    def test_health_failure_payload_is_auditable_but_not_ready(self) -> None:
        worker_result = self._run_worker_result(
            "--mode",
            "google-serp-spike",
            "--require-ready-collectors",
            "--health-check-only",
            unset_env=("SERP_API_KEY", "SERP_API_ENDPOINT"),
        )
        self.assertEqual(worker_result.returncode, 3)
        payload = json.loads(worker_result.stdout)

        result = verify_au_p0b_google_serp_comparison(payload)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertFalse(result["comparison_ready"])
        self.assertFalse(result["collector_health_ready"])
        self.assertEqual(result["collector_health_failure_reasons"], ["google.third_party_serp:not_configured"])

    def test_require_ready_fails_health_only_payload(self) -> None:
        worker_result = self._run_worker_result(
            "--mode",
            "google-serp-spike",
            "--require-ready-collectors",
            "--health-check-only",
            unset_env=("SERP_API_KEY", "SERP_API_ENDPOINT"),
        )
        payload = json.loads(worker_result.stdout)

        result = verify_au_p0b_google_serp_comparison(
            payload,
            require_comparison_ready=True,
            require_collector_health_ready=True,
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn("google_serp_comparison_not_ready", result["errors"])
        self.assertIn("collector_health_not_ready", result["errors"])

    def test_fails_if_full_google_spike_gate_is_present(self) -> None:
        payload = self._run_worker("--mode", "google-serp-fixture")
        payload["google_spike_gate"] = {"gate_status": "pass"}

        result = verify_au_p0b_google_serp_comparison(payload)

        self.assertEqual(result["status"], "fail")
        self.assertIn("preflight_payload_hash_mismatch", result["errors"])
        self.assertIn("full_google_spike_gate_present", result["errors"])

    def test_fails_if_planned_runs_are_mutated(self) -> None:
        payload = self._run_worker("--mode", "google-serp-fixture")
        payload["google_serp_comparison_plan"]["planned_runs"] = 121

        result = verify_au_p0b_google_serp_comparison(payload)

        self.assertEqual(result["status"], "fail")
        self.assertIn("preflight_payload_hash_mismatch", result["errors"])
        self.assertIn("comparison_plan_planned_runs_invalid", result["errors"])

    def test_cli_reads_file_and_reports_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "google-serp-fixture.json"
            payload = self._run_worker("--mode", "google-serp-fixture")
            payload["preflight_output_path"] = str(path)
            from scripts.verify_preflight_payload import compute_preflight_payload_hash

            payload["preflight_payload_hash"] = compute_preflight_payload_hash(payload)
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0b_google_serp_comparison.py",
                    str(path),
                    "--require-comparison-ready",
                ],
                capture_output=True,
                check=True,
                text=True,
            )

        verifier_payload = json.loads(result.stdout)
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertTrue(verifier_payload["comparison_ready"])
        self.assertTrue(verifier_payload["output_path_matches_file"])


if __name__ == "__main__":
    unittest.main()
