from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_retest_scheduler_plan import (
    build_au_retest_scheduler_plan,
    compute_retest_scheduler_plan_hash,
)
from scripts.verify_au_retest_scheduler_plan import verify_au_retest_scheduler_plan


class AuRetestSchedulerPlanTest(unittest.TestCase):
    def test_plan_freezes_au_retest_windows_and_collection_contract(self) -> None:
        plan = build_au_retest_scheduler_plan(generated_at="2026-06-12T00:00:00Z")
        verification = verify_au_retest_scheduler_plan(plan)

        self.assertEqual(verification["status"], "pass")
        self.assertEqual(plan["plan_version"], "au_retest_scheduler_plan_v1")
        self.assertTrue(plan["retest_scheduler_plan_ready"])
        self.assertEqual(plan["scope"]["prompt_version"], "au_dtc_ecommerce_v1")
        self.assertEqual(plan["scope"]["prompt_count"], 100)
        self.assertEqual(plan["scope"]["sample_size"], 3)
        self.assertEqual(plan["scope"]["offsets_days"], [0, 7, 14, 30])
        self.assertEqual(plan["scope"]["planned_runs_per_window"], 2400)
        self.assertEqual(plan["scope"]["total_planned_runs"], 9600)
        self.assertEqual(plan["timeline"][0]["id"], "baseline")
        self.assertEqual(plan["timeline"][-1]["id"], "t_plus_30")
        self.assertEqual(plan["timeline"][0]["commands"][0]["command"][1], "workers/collector_worker/run_collection_slice.py")
        self.assertIn("--require-no-collection-failures", plan["timeline"][0]["commands"][0]["command"])
        self.assertFalse(plan["current_boundary"]["real_external_runs_completed"])
        self.assertFalse(plan["current_boundary"]["temporal_scheduler_implemented"])
        self.assertEqual(plan["retest_scheduler_plan_hash"], compute_retest_scheduler_plan_hash(plan))

    def test_verifier_detects_scope_drift(self) -> None:
        plan = build_au_retest_scheduler_plan(generated_at="2026-06-12T00:00:00Z")
        plan["scope"]["sample_size"] = 2
        plan["retest_scheduler_plan_hash"] = compute_retest_scheduler_plan_hash(plan)

        verification = verify_au_retest_scheduler_plan(plan)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("scope_sample_size_invalid", verification["errors"])

    def test_verifier_detects_hash_tampering(self) -> None:
        plan = build_au_retest_scheduler_plan(generated_at="2026-06-12T00:00:00Z")
        plan["scope"]["total_planned_runs"] = 1

        verification = verify_au_retest_scheduler_plan(plan)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("retest_scheduler_plan_hash_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_plan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "retest-plan.json"
            build_result = subprocess.run(
                [
                    "python3",
                    "scripts/build_au_retest_scheduler_plan.py",
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            verify_result = subprocess.run(
                ["python3", "scripts/verify_au_retest_scheduler_plan.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        payload = json.loads(build_result.stdout)
        verifier = json.loads(verify_result.stdout)
        self.assertEqual(payload["scope"]["total_planned_runs"], 9600)
        self.assertEqual(verifier["status"], "pass")
        self.assertTrue(verifier["hash_valid"])


if __name__ == "__main__":
    unittest.main()
