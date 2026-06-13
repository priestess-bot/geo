from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_external_dependency_handoff import build_au_external_dependency_handoff
from scripts.run_au_external_dependency_clearance import (
    EXECUTION_VERSION,
    compute_clearance_execution_hash,
    run_au_external_dependency_clearance,
)
from scripts.verify_au_external_dependency_clearance import verify_au_external_dependency_clearance
from tests.test_au_external_dependency_handoff import AuExternalDependencyHandoffTest


class AuExternalDependencyClearanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuExternalDependencyHandoffTest()
        self._helper.setUp()

    def _write_handoff(self, temp_dir: str) -> Path:
        launch_status_path, remediation_plan_path, p0a_env_path, p0a_exec_path, p0b_path = self._helper._write_inputs(
            temp_dir
        )
        handoff = build_au_external_dependency_handoff(
            launch_status_path=launch_status_path,
            remediation_plan_path=remediation_plan_path,
            p0a_environment_checklist_path=p0a_env_path,
            p0a_execution_checklist_path=p0a_exec_path,
            p0b_google_execution_checklist_path=p0b_path,
            output_path=Path(temp_dir) / "external-dependency-handoff.json",
            generated_at="2026-06-13T00:00:00Z",
        )
        path = Path(temp_dir) / "external-dependency-handoff.json"
        path.write_text(json.dumps(handoff), encoding="utf-8")
        return path

    def test_dry_run_records_current_clearance_step_without_executing_commands(self) -> None:
        with TemporaryDirectory() as temp_dir:
            handoff_path = self._write_handoff(temp_dir)
            execution = run_au_external_dependency_clearance(
                handoff_path=handoff_path,
                output_path=Path(temp_dir) / "clearance.json",
                generated_at="2026-06-13T00:00:00Z",
            )
            verification = verify_au_external_dependency_clearance(execution)
            hard_gate = verify_au_external_dependency_clearance(execution, require_handoff_ready=True)

        self.assertEqual(execution["clearance_execution_version"], EXECUTION_VERSION)
        self.assertEqual(execution["status"], "pass")
        self.assertEqual(execution["mode"], "dry_run")
        self.assertTrue(execution["ready_to_execute"])
        self.assertFalse(execution["external_dependency_handoff_ready"])
        self.assertEqual(execution["clearance_sequence_version"], "au_external_dependency_clearance_sequence_v1")
        self.assertEqual(execution["planned_step_count"], 6)
        self.assertEqual(execution["recorded_step_count"], 6)
        self.assertEqual(execution["ready_step_count"], 0)
        self.assertEqual(execution["blocked_step_count"], 6)
        self.assertEqual(execution["would_execute_step_count"], 1)
        self.assertEqual(execution["current_step_id"], "p0a_provider_credentials")
        self.assertEqual(execution["next_command"], "make verify-au-p0a-env-template")
        self.assertEqual(execution["clearance_execution_hash"], compute_clearance_execution_hash(execution))
        steps = {step["id"]: step for step in execution["steps"]}
        self.assertEqual(steps["p0a_provider_credentials"]["status"], "dry_run_ready_to_start")
        self.assertTrue(steps["p0a_provider_credentials"]["would_execute"])
        self.assertIn("missing_required:DATABASE_URL", steps["p0a_provider_credentials"]["blocked_by"])
        self.assertEqual(steps["p0a_real_batches"]["status"], "blocked")
        self.assertIn("prerequisite_step_not_ready:p0a_provider_credentials", steps["p0a_real_batches"]["blocked_by"])
        self.assertIn("make verify-au-launch-status", execution["hard_gate_commands"])
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("external_dependency_handoff_not_ready", hard_gate["errors"])

    def test_stop_after_step_records_prefix_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            handoff_path = self._write_handoff(temp_dir)
            execution = run_au_external_dependency_clearance(
                handoff_path=handoff_path,
                stop_after_step="p0b_google_environment",
                generated_at="2026-06-13T00:00:00Z",
            )

        self.assertEqual(execution["status"], "pass")
        self.assertTrue(execution["stopped_after_step"])
        self.assertEqual(execution["recorded_step_count"], 3)
        self.assertEqual(execution["steps"][-1]["id"], "p0b_google_environment")

    def test_verifier_detects_clearance_execution_tampering(self) -> None:
        with TemporaryDirectory() as temp_dir:
            handoff_path = self._write_handoff(temp_dir)
            execution = run_au_external_dependency_clearance(
                handoff_path=handoff_path,
                generated_at="2026-06-13T00:00:00Z",
            )
        tampered = copy.deepcopy(execution)
        tampered["steps"][0]["would_execute"] = False
        tampered["clearance_execution_hash"] = compute_clearance_execution_hash(tampered)
        verification = verify_au_external_dependency_clearance(tampered)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("would_execute_step_count_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_clearance_dry_run(self) -> None:
        with TemporaryDirectory() as temp_dir:
            handoff_path = self._write_handoff(temp_dir)
            output_path = Path(temp_dir) / "clearance.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_au_external_dependency_clearance.py",
                    "--handoff-path",
                    str(handoff_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-13T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            verify_result = subprocess.run(
                [sys.executable, "scripts/verify_au_external_dependency_clearance.py", str(output_path)],
                capture_output=True,
                check=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            verification = json.loads(verify_result.stdout)

        self.assertIn("au_external_dependency_clearance_execution_v1", build_result.stdout)
        self.assertEqual(payload["clearance_execution_hash"], compute_clearance_execution_hash(payload))
        self.assertEqual(verification["status"], "pass")


if __name__ == "__main__":
    unittest.main()
