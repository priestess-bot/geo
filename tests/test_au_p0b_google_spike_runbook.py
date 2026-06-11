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
        steps = {step["id"]: step for step in runbook["steps"]}
        self.assertEqual(
            list(steps),
            [
                "prepare_environment",
                "google_spike_health_check",
                "google_spike_health_manifest",
                "google_spike_collect",
                "google_spike_manifest",
                "google_spike_decision_handoff",
            ],
        )
        self.assertIn("--health-check-only", steps["google_spike_health_check"]["command"])
        self.assertIn("--require-google-spike-gates", steps["google_spike_collect"]["command"])
        self.assertIn("--persist", steps["google_spike_collect"]["command"])
        self.assertEqual(steps["google_spike_collect"]["planned_runs"], 240)
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


if __name__ == "__main__":
    unittest.main()
