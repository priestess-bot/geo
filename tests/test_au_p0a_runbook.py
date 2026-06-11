from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_runbook import RUNBOOK_VERSION, build_au_p0a_runbook, compute_runbook_payload_hash


class AuP0aRunbookTest(unittest.TestCase):
    def test_build_runbook_contains_preflight_small_and_full_gates(self) -> None:
        runbook = build_au_p0a_runbook(
            artifact_dir="docs/runtime_preflight",
            small_prompt_limit=5,
            full_prompt_limit=100,
            sample_size=3,
            generated_at="2026-06-11T00:00:00Z",
        )

        self.assertEqual(runbook["runbook_version"], RUNBOOK_VERSION)
        self.assertEqual(runbook["scope"]["small_batch"]["planned_runs"], 30)
        self.assertEqual(runbook["scope"]["full_batch"]["planned_runs"], 2400)
        self.assertEqual(runbook["required_env"], ("PERPLEXITY_API_KEY", "OPENAI_API_KEY", "DATABASE_URL"))
        steps = {step["id"]: step for step in runbook["steps"]}
        self.assertEqual(
            list(steps),
            [
                "prepare_environment",
                "preflight_collect",
                "preflight_verify_audit",
                "preflight_manifest_audit",
                "preflight_design_partner_gate",
                "small_batch_collect",
                "small_batch_manifest_gate",
                "full_batch_collect",
                "full_batch_manifest_gate",
            ],
        )
        self.assertIn("--require-design-partner-ready", steps["preflight_design_partner_gate"]["command"])
        self.assertIn("--persist", steps["small_batch_collect"]["command"])
        self.assertIn("--persist-analysis", steps["full_batch_collect"]["command"])
        self.assertEqual(steps["full_batch_collect"]["planned_runs"], 2400)
        self.assertEqual(runbook["runbook_payload_hash"], compute_runbook_payload_hash(runbook))

    def test_runbook_can_disable_persistence_for_dry_run_plans(self) -> None:
        runbook = build_au_p0a_runbook(
            persist=False,
            persist_analysis=False,
            generated_at="2026-06-11T00:00:00Z",
        )
        steps = {step["id"]: step for step in runbook["steps"]}
        self.assertNotIn("--persist", steps["small_batch_collect"]["command"])
        self.assertNotIn("--persist-analysis", steps["full_batch_collect"]["command"])

    def test_cli_writes_runbook_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "runbook.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_runbook.py",
                    "--output-path",
                    str(output_path),
                    "--artifact-dir",
                    "tmp/preflight",
                    "--small-prompt-limit",
                    "2",
                    "--full-prompt-limit",
                    "4",
                    "--cities",
                    "Sydney,Melbourne",
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            stdout_runbook = json.loads(result.stdout)
            written_runbook = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(stdout_runbook, written_runbook)
        self.assertEqual(written_runbook["scope"]["small_batch"]["planned_runs"], 12)
        self.assertEqual(written_runbook["scope"]["full_batch"]["planned_runs"], 48)
        self.assertEqual(written_runbook["artifact_paths"]["full_batch_json"], "tmp/preflight/au-p0a-full-batch.json")


if __name__ == "__main__":
    unittest.main()
