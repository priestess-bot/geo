from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_external_dependency_handoff import (
    HANDOFF_VERSION,
    build_au_external_dependency_handoff,
    compute_external_dependency_handoff_hash,
)
from scripts.verify_au_external_dependency_handoff import verify_au_external_dependency_handoff
from tests.test_au_handoff_dossier import AuHandoffDossierTest


class AuExternalDependencyHandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuHandoffDossierTest()
        self._helper.setUp()

    def _write_inputs(self, temp_dir: str) -> tuple[Path, Path, Path, Path, Path]:
        launch_status_path, remediation_plan_path = self._helper._write_launch_status_and_plan(temp_dir, ready=False)
        p0a_environment_path = self._helper._write_p0a_environment_checklist(temp_dir)
        p0a_execution_path = self._helper._write_p0a_execution_checklist(temp_dir)
        p0b_google_path = self._helper._write_p0b_google_execution_checklist(temp_dir)
        return launch_status_path, remediation_plan_path, p0a_environment_path, p0a_execution_path, p0b_google_path

    def test_handoff_records_external_dependency_boundary_without_raw_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path, p0a_env_path, p0a_exec_path, p0b_path = self._write_inputs(
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
            verification = verify_au_external_dependency_handoff(handoff)
            hard_gate = verify_au_external_dependency_handoff(handoff, require_ready=True)

        self.assertEqual(handoff["external_dependency_handoff_version"], HANDOFF_VERSION)
        self.assertEqual(handoff["status"], "pass")
        self.assertFalse(handoff["external_dependency_handoff_ready"])
        self.assertEqual(handoff["summary"]["handoff_posture"], "blocked_external_dependencies")
        self.assertTrue(handoff["summary"]["structural_ready"])
        self.assertTrue(handoff["summary"]["all_blockers_mapped"])
        self.assertEqual(handoff["summary"]["external_dependency_blocker_count"], 29)
        self.assertGreaterEqual(handoff["summary"]["work_item_count"], 8)
        self.assertEqual(handoff["summary"]["dependency_group_count"], 5)
        self.assertEqual(handoff["summary"]["runnable_now_work_item_count"], 0)
        self.assertEqual(handoff["next_dependency_item_id"], "p0a_environment")
        self.assertEqual(handoff["summary"]["p0a_required_secret_missing_count"], 3)
        self.assertEqual(
            sorted(handoff["summary"]["p0a_required_secret_missing"]),
            ["DATABASE_URL", "OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
        )
        self.assertEqual(handoff["summary"]["p0a_real_batch_phase_next_phase"], "preflight")
        self.assertEqual(handoff["summary"]["p0a_real_batch_total_planned_runs"], 2436)
        self.assertEqual(handoff["summary"]["p0b_google_required_input_missing_count"], 6)
        self.assertEqual(handoff["summary"]["p0b_google_manual_backfill_expected_record_count"], 120)
        self.assertEqual(handoff["summary"]["p0b_google_manual_backfill_record_count"], 0)
        self.assertEqual(handoff["summary"]["p0b_google_phase_next_phase"], "environment")
        self.assertEqual(handoff["summary"]["p0b_google_full_spike_planned_runs"], 240)
        self.assertEqual(
            [group["id"] for group in handoff["dependency_groups"]],
            [
                "p0a_provider_credentials",
                "p0a_real_batches",
                "p0b_google_environment",
                "p0b_google_manual_backfill",
                "p0b_google_phase_execution",
            ],
        )
        self.assertEqual(handoff["dependency_groups"][0]["target_env_file"], ".env.au-p0a")
        self.assertTrue(handoff["dependency_groups"][2]["target_env_file"])
        self.assertFalse(handoff["redaction_policy"]["raw_secret_values_allowed"])
        self.assertFalse(handoff["redaction_policy"]["raw_database_url_allowed"])
        self.assertFalse(handoff["redaction_policy"]["raw_selector_values_allowed"])
        self.assertFalse(handoff["redaction_policy"]["raw_manual_answer_values_allowed"])
        self.assertEqual(handoff["external_dependency_handoff_hash"], compute_external_dependency_handoff_hash(handoff))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("external_dependency_handoff_not_ready", hard_gate["errors"])

    def test_verifier_detects_summary_tampering(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path, p0a_env_path, p0a_exec_path, p0b_path = self._write_inputs(
                temp_dir
            )
            handoff = build_au_external_dependency_handoff(
                launch_status_path=launch_status_path,
                remediation_plan_path=remediation_plan_path,
                p0a_environment_checklist_path=p0a_env_path,
                p0a_execution_checklist_path=p0a_exec_path,
                p0b_google_execution_checklist_path=p0b_path,
                generated_at="2026-06-13T00:00:00Z",
            )
        tampered = copy.deepcopy(handoff)
        tampered["summary"]["p0b_google_phase_next_phase"] = "complete"  # type: ignore[index]
        tampered["external_dependency_handoff_hash"] = compute_external_dependency_handoff_hash(tampered)
        verification = verify_au_external_dependency_handoff(tampered)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_p0b_google_phase_next_phase_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_external_dependency_handoff(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path, p0a_env_path, p0a_exec_path, p0b_path = self._write_inputs(
                temp_dir
            )
            output_path = Path(temp_dir) / "external-dependency-handoff.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_external_dependency_handoff.py",
                    "--launch-status-path",
                    str(launch_status_path),
                    "--remediation-plan-path",
                    str(remediation_plan_path),
                    "--p0a-environment-checklist-path",
                    str(p0a_env_path),
                    "--p0a-execution-checklist-path",
                    str(p0a_exec_path),
                    "--p0b-google-execution-checklist-path",
                    str(p0b_path),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-13T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            verify_result = subprocess.run(
                [sys.executable, "scripts/verify_au_external_dependency_handoff.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            verification = json.loads(verify_result.stdout)

        self.assertIn("au_external_dependency_handoff_v1", build_result.stdout)
        self.assertEqual(payload["external_dependency_handoff_hash"], compute_external_dependency_handoff_hash(payload))
        self.assertEqual(verification["status"], "pass")


if __name__ == "__main__":
    unittest.main()
