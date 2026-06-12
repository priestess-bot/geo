from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_spike_runbook import (
    RUNBOOK_VERSION,
    build_au_p0b_google_spike_runbook,
    compute_google_spike_runbook_hash,
)


class AuP0bGoogleSpikeRunbookTest(unittest.TestCase):
    def test_build_runbook_contains_health_collect_and_manifest_gates(self) -> None:
        runbook = build_au_p0b_google_spike_runbook(generated_at="2026-06-12T00:00:00Z")

        self.assertEqual(runbook["runbook_version"], RUNBOOK_VERSION)
        self.assertEqual(runbook["scope"]["planned_runs"], 240)
        self.assertEqual(runbook["scope"]["surfaces"], ("google_aio", "google_ai_mode"))
        self.assertEqual(runbook["scope"]["collection_paths"], ("browser", "manual"))
        self.assertEqual(runbook["required_env"], ("GOOGLE_PLAYWRIGHT_ENABLED", "MANUAL_BACKFILL_PATH", "DATABASE_URL"))
        self.assertIn("GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR", runbook["recommended_env"])
        self.assertIn("GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR", runbook["recommended_env"])
        self.assertIn("GOOGLE_AIO_PLAYWRIGHT_START_URL", runbook["recommended_env"])
        self.assertIn("SERP_API_KEY", runbook["recommended_env"])
        self.assertIn("SERP_API_ENDPOINT", runbook["recommended_env"])
        steps = {step["id"]: step for step in runbook["steps"]}
        self.assertEqual(
            list(steps),
            [
                "prepare_environment",
                "google_playwright_env",
                "google_playwright_env_verify",
                "google_playwright_smoke",
                "google_playwright_smoke_verify",
                "google_manual_backfill_verify",
                "google_spike_health_check",
                "google_spike_health_manifest",
                "google_spike_collect",
                "google_spike_manifest",
                "google_spike_decision_handoff",
            ],
        )
        self.assertIn("--health-check-only", steps["google_spike_health_check"]["command"])
        self.assertIn("scripts/build_au_p0b_google_playwright_env_report.py", steps["google_playwright_env"]["command"])
        self.assertIn("--runbook-path", steps["google_playwright_env"]["command"])
        self.assertIn("docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json", steps["google_playwright_env"]["command"])
        self.assertIn("scripts/verify_au_p0b_google_playwright_env_report.py", steps["google_playwright_env_verify"]["command"])
        self.assertIn("--require-ready-smoke", steps["google_playwright_env_verify"]["command"])
        self.assertIn("scripts/run_au_p0b_google_playwright_smoke.py", steps["google_playwright_smoke"]["command"])
        self.assertIn("scripts/verify_au_p0b_google_playwright_smoke.py", steps["google_playwright_smoke_verify"]["command"])
        self.assertIn("--require-success", steps["google_playwright_smoke_verify"]["command"])
        self.assertIn("scripts/verify_au_p0b_manual_backfill.py", steps["google_manual_backfill_verify"]["command"])
        self.assertIn("--output-path", steps["google_manual_backfill_verify"]["command"])
        self.assertIn("--require-google-spike-gates", steps["google_spike_collect"]["command"])
        self.assertIn("--persist", steps["google_spike_collect"]["command"])
        self.assertTrue(
            any(
                "verify-au-p0b-google-manual-backfill" in note
                for note in steps["prepare_environment"]["notes"]
            )
        )
        self.assertTrue(
            any("au-p0b-google-playwright-smoke" in note for note in steps["prepare_environment"]["notes"])
        )
        self.assertEqual(steps["google_playwright_env"]["output_paths"][0], "docs/runtime_preflight/au-p0b-google-playwright-env-latest.json")
        self.assertEqual(steps["google_playwright_smoke"]["planned_runs"], 1)
        self.assertEqual(steps["google_manual_backfill_verify"]["planned_runs"], 120)
        self.assertEqual(steps["google_spike_collect"]["planned_runs"], 240)
        self.assertEqual(
            runbook["artifact_paths"]["playwright_env_json"],
            "docs/runtime_preflight/au-p0b-google-playwright-env-latest.json",
        )
        self.assertEqual(
            runbook["artifact_paths"]["playwright_smoke_json"],
            "docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json",
        )
        self.assertEqual(
            runbook["artifact_paths"]["manual_backfill_verification_json"],
            "docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json",
        )
        self.assertEqual(runbook["runbook_payload_hash"], compute_google_spike_runbook_hash(runbook))

    def test_runbook_can_disable_persistence(self) -> None:
        runbook = build_au_p0b_google_spike_runbook(persist=False, generated_at="2026-06-12T00:00:00Z")
        steps = {step["id"]: step for step in runbook["steps"]}
        self.assertNotIn("--persist", steps["google_spike_collect"]["command"])

    def test_cli_writes_runbook_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "runbook.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_spike_runbook.py",
                    "--output-path",
                    str(output_path),
                    "--artifact-dir",
                    "tmp/google",
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            stdout_runbook = json.loads(result.stdout)
            written_runbook = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(stdout_runbook, written_runbook)
        self.assertEqual(written_runbook["artifact_paths"]["spike_json"], "tmp/google/au-p0b-google-spike-latest.json")
        steps = {step["id"]: step for step in written_runbook["steps"]}
        self.assertIn(str(output_path), steps["google_playwright_env"]["command"])


if __name__ == "__main__":
    unittest.main()
