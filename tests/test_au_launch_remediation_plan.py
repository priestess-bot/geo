from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_launch_remediation_plan import (
    PLAN_VERSION,
    build_au_launch_remediation_plan,
    compute_remediation_plan_hash,
)
from scripts.verify_au_launch_remediation_plan import verify_au_launch_remediation_plan
from tests.test_au_launch_status import AuLaunchStatusTest


class AuLaunchRemediationPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self._launch_helper = AuLaunchStatusTest()
        self._launch_helper.setUp()

    def _write_launch_status(self, temp_dir: str, *, ready: bool = False) -> Path:
        p0a_status_path = self._launch_helper._write_p0a_status(temp_dir, ready=ready)
        p0c_package_path = self._launch_helper._write_p0c_package(temp_dir)
        runbook_path, execution_path, p0b_status_path, p0b_package_path = self._launch_helper._write_p0b_status_and_package(
            temp_dir,
            google_ready=ready,
        )
        from scripts.build_au_launch_status import build_au_launch_status

        launch_status = build_au_launch_status(
            p0a_status_path=p0a_status_path,
            p0b_google_status_path=p0b_status_path,
            p0b_google_package_path=p0b_package_path,
            p0b_google_runbook_path=runbook_path,
            p0b_google_execution_path=execution_path,
            p0c_report_package_path=p0c_package_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        launch_status_path = Path(temp_dir) / "launch-status.json"
        launch_status_path.write_text(json.dumps(launch_status), encoding="utf-8")
        return launch_status_path

    def test_plan_maps_every_current_launch_blocker_to_work_items(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path = self._write_launch_status(temp_dir, ready=False)
            launch_status = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan = build_au_launch_remediation_plan(
                launch_status=launch_status,
                launch_status_path=launch_status_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_launch_remediation_plan(plan, require_ready=True)

        blockers = launch_status["remaining_blockers"]
        self.assertEqual(plan["remediation_plan_version"], PLAN_VERSION)
        self.assertEqual(plan["status"], "pass")
        self.assertTrue(plan["remediation_plan_ready"])
        self.assertEqual(plan["summary"]["blocker_count"], len(blockers))
        self.assertEqual(plan["summary"]["covered_blocker_count"], len(blockers))
        self.assertEqual(plan["summary"]["unmapped_blocker_count"], 0)
        self.assertEqual(len(plan["blocker_remediations"]), len(blockers))
        self.assertEqual(plan["next_work_item_id"], "p0a_environment")
        self.assertIn("p0a_environment", [item["id"] for item in plan["work_items"]])
        self.assertIn("p0b_google_playwright_env", [item["id"] for item in plan["work_items"]])
        self.assertTrue(all(item["mapped"] for item in plan["blocker_remediations"]))
        self.assertEqual(plan["remediation_plan_hash"], compute_remediation_plan_hash(plan))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(verification["blocker_count"], len(blockers))

    def test_plan_for_ready_launch_status_has_no_work_items(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path = self._write_launch_status(temp_dir, ready=True)
            launch_status = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan = build_au_launch_remediation_plan(
                launch_status=launch_status,
                launch_status_path=launch_status_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_launch_remediation_plan(plan, require_ready=True)

        self.assertTrue(launch_status["ready_for_customer_report_handoff"])
        self.assertEqual(plan["next_work_item_id"], "none")
        self.assertEqual(plan["summary"]["blocker_count"], 0)
        self.assertEqual(plan["summary"]["work_item_count"], 0)
        self.assertEqual(plan["blocker_remediations"], [])
        self.assertEqual(verification["status"], "pass")

    def test_verifier_detects_hash_and_coverage_tampering(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path = self._write_launch_status(temp_dir, ready=False)
            launch_status = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan = build_au_launch_remediation_plan(
                launch_status=launch_status,
                launch_status_path=launch_status_path,
                generated_at="2026-06-12T00:00:00Z",
            )
            plan["blocker_remediations"] = plan["blocker_remediations"][:-1]
            verification = verify_au_launch_remediation_plan(plan)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("remediation_plan_hash_mismatch", verification["errors"])
        self.assertIn("blocker_remediation_coverage_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_remediation_plan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path = self._write_launch_status(temp_dir, ready=False)
            output_path = Path(temp_dir) / "remediation-plan.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_launch_remediation_plan.py",
                    "--launch-status-path",
                    str(launch_status_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            verify_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_launch_remediation_plan.py",
                    str(output_path),
                    "--require-ready",
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(build_result.returncode, 0, build_result.stderr)
        self.assertEqual(verify_result.returncode, 0, verify_result.stderr)
        payload = json.loads(build_result.stdout)
        verifier_payload = json.loads(verify_result.stdout)
        self.assertEqual(payload["remediation_plan_hash"], compute_remediation_plan_hash(payload))
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertEqual(payload["summary"]["unmapped_blocker_count"], 0)


if __name__ == "__main__":
    unittest.main()
