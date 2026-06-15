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
from scripts.build_au_p0b_google_manual_backfill_fulfillment import (
    build_au_p0b_google_manual_backfill_fulfillment,
)
from scripts.build_au_p0b_google_manual_backfill_request_packet import (
    build_au_p0b_google_manual_backfill_request_packet,
)
from scripts.build_au_p0b_manual_backfill_template import build_manual_backfill_template
from scripts.verify_au_p0b_manual_backfill import verify_manual_backfill
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

    def _write_manual_fulfillment(self, temp_dir: str, p0b_google_path: Path) -> tuple[Path, dict[str, object]]:
        p0b_google = json.loads(p0b_google_path.read_text(encoding="utf-8"))
        request = build_au_p0b_google_manual_backfill_request_packet(
            p0b_google_execution_checklist_path=p0b_google_path,
            p0b_google_execution_checklist=p0b_google,
            output_path=Path(temp_dir) / "manual-request.json",
            generated_at="2026-06-13T00:00:00Z",
        )
        request_path = Path(temp_dir) / "manual-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        template_lines, _manifest = build_manual_backfill_template(generated_at="2026-06-13T00:00:00Z")
        manual_path = Path(temp_dir) / "manual-template.jsonl"
        manual_path.write_text(
            "".join(json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for line in template_lines),
            encoding="utf-8",
        )
        verification = verify_manual_backfill(manual_path, allow_template_placeholders=True)
        verification_path = Path(temp_dir) / "manual-verification.json"
        verification_path.write_text(json.dumps(verification), encoding="utf-8")
        fulfillment = build_au_p0b_google_manual_backfill_fulfillment(
            manual_backfill_request_path=request_path,
            manual_backfill_request=request,
            manual_backfill_verification_path=verification_path,
            manual_backfill_verification=verification,
            manual_jsonl_path=manual_path,
            output_path=Path(temp_dir) / "manual-fulfillment.json",
            generated_at="2026-06-13T00:00:00Z",
        )
        fulfillment_path = Path(temp_dir) / "manual-fulfillment.json"
        fulfillment_path.write_text(json.dumps(fulfillment), encoding="utf-8")
        return fulfillment_path, fulfillment

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
        self.assertGreater(handoff["summary"]["external_dependency_blocker_count"], 0)
        self.assertEqual(
            handoff["summary"]["external_dependency_blocker_count"],
            sum(1 for item in handoff["blocker_remediations"] if item["external_dependency"]),
        )
        self.assertGreaterEqual(handoff["summary"]["work_item_count"], 8)
        self.assertEqual(handoff["summary"]["dependency_group_count"], 5)
        self.assertEqual(handoff["summary"]["clearance_step_count"], 6)
        self.assertEqual(handoff["summary"]["clearance_ready_step_count"], 0)
        self.assertEqual(handoff["summary"]["clearance_blocked_step_count"], 6)
        self.assertEqual(handoff["summary"]["clearance_current_step_id"], "p0a_provider_credentials")
        self.assertEqual(handoff["summary"]["next_command"], "make verify-au-p0a-env-template")
        self.assertEqual(handoff["summary"]["runnable_now_work_item_count"], 0)
        self.assertEqual(handoff["next_dependency_item_id"], "p0a_environment")
        self.assertEqual(handoff["summary"]["p0a_required_secret_missing_count"], 3)
        self.assertEqual(
            sorted(handoff["summary"]["p0a_required_secret_missing"]),
            ["DATABASE_URL", "OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
        )
        self.assertEqual(handoff["summary"]["p0a_real_batch_phase_next_phase"], "preflight")
        self.assertEqual(handoff["summary"]["p0a_real_batch_total_planned_runs"], 2436)
        p0a_batches = next(group for group in handoff["dependency_groups"] if group["id"] == "p0a_real_batches")
        self.assertIn("make verify-au-p0a-real-batch-fulfillment", p0a_batches["verification_commands"])
        self.assertTrue(any(command.endswith("--require-fulfilled") for command in p0a_batches["verification_commands"]))
        self.assertIn(
            "docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json",
            p0a_batches["evidence_outputs"],
        )
        self.assertEqual(handoff["summary"]["p0b_google_required_input_missing_count"], 6)
        self.assertEqual(handoff["summary"]["p0b_google_manual_backfill_expected_record_count"], 120)
        self.assertEqual(handoff["summary"]["p0b_google_manual_backfill_record_count"], 0)
        self.assertFalse(handoff["summary"]["p0b_google_manual_backfill_fulfillment_available"])
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
        self.assertEqual(handoff["clearance_sequence"]["version"], "au_external_dependency_clearance_sequence_v1")
        self.assertEqual(
            handoff["clearance_sequence"]["step_ids"],
            [
                "p0a_provider_credentials",
                "p0a_real_batches",
                "p0b_google_environment",
                "p0b_google_manual_backfill",
                "p0b_google_phase_execution",
                "customer_report_handoff_gate",
            ],
        )
        self.assertEqual(handoff["clearance_sequence"]["current_step_id"], "p0a_provider_credentials")
        self.assertEqual(handoff["clearance_sequence"]["next_command"], handoff["summary"]["next_command"])
        self.assertEqual(handoff["clearance_sequence"]["steps"][0]["can_start"], True)
        self.assertEqual(handoff["clearance_sequence"]["steps"][0]["status"], "requires_external_input")
        self.assertIn("missing_required:DATABASE_URL", handoff["clearance_sequence"]["steps"][0]["blocked_by"])
        self.assertEqual(
            handoff["clearance_sequence"]["steps"][1]["status"],
            "blocked_waiting_on_prerequisite",
        )
        self.assertIn(
            "prerequisite_step_not_ready:p0a_provider_credentials",
            handoff["clearance_sequence"]["steps"][1]["blocked_by"],
        )
        self.assertEqual(handoff["clearance_sequence"]["steps"][-1]["id"], "customer_report_handoff_gate")
        self.assertIn(
            "scripts/verify_au_external_dependency_handoff.py",
            " ".join(handoff["clearance_sequence"]["steps"][-1]["verification_commands"]),
        )
        self.assertIn(
            "scripts/verify_au_launch_status.py",
            " ".join(handoff["clearance_sequence"]["steps"][-1]["verification_commands"]),
        )
        self.assertEqual(handoff["dependency_groups"][0]["target_env_file"], ".env.au-p0a")
        self.assertEqual(handoff["dependency_groups"][0]["next_command"], "make verify-au-p0a-env-template")
        self.assertFalse(handoff["dependency_groups"][0]["env_file_hygiene_exists"])
        self.assertIn("make au-p0a-env-bootstrap", handoff["dependency_groups"][0]["commands"])
        self.assertIn("make verify-au-p0a-credential-fulfillment", handoff["dependency_groups"][0]["verification_commands"])
        self.assertTrue(
            any("--require-fulfilled" in command for command in handoff["dependency_groups"][0]["verification_commands"])
        )
        self.assertIn(
            "docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json",
            handoff["dependency_groups"][0]["evidence_outputs"],
        )
        self.assertIn("make verify-au-p0a-credential-clearance", handoff["dependency_groups"][0]["verification_commands"])
        self.assertTrue(
            any("--require-cleared" in command for command in handoff["dependency_groups"][0]["verification_commands"])
        )
        self.assertIn(
            "docs/runtime_preflight/au-p0a-credential-clearance-latest.json",
            handoff["dependency_groups"][0]["evidence_outputs"],
        )
        self.assertIn(
            "make verify-au-p0a-credential-update-receipt",
            handoff["dependency_groups"][0]["verification_commands"],
        )
        self.assertTrue(
            any("--require-complete" in command for command in handoff["dependency_groups"][0]["verification_commands"])
        )
        self.assertIn(
            "docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json",
            handoff["dependency_groups"][0]["evidence_outputs"],
        )
        self.assertIn("missing_required:DATABASE_URL", handoff["dependency_groups"][0]["blocking_reasons"])
        self.assertTrue(handoff["dependency_groups"][2]["target_env_file"])
        self.assertEqual(handoff["dependency_groups"][2]["next_command"], "make verify-au-p0b-google-env-template")
        self.assertIn("make au-p0b-google-env-bootstrap", handoff["dependency_groups"][2]["commands"])
        self.assertIn(
            "make verify-au-p0b-google-environment-fulfillment",
            handoff["dependency_groups"][2]["verification_commands"],
        )
        self.assertTrue(
            any("--require-fulfilled" in command for command in handoff["dependency_groups"][2]["verification_commands"])
        )
        self.assertIn(
            "docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json",
            handoff["dependency_groups"][2]["evidence_outputs"],
        )
        self.assertIn(
            "missing_required:smoke_env:GOOGLE_PLAYWRIGHT_ENABLED",
            handoff["dependency_groups"][2]["blocking_reasons"],
        )
        self.assertIn(
            "make verify-au-p0b-google-manual-backfill-fulfillment",
            handoff["dependency_groups"][3]["verification_commands"],
        )
        self.assertTrue(
            any("--require-fulfilled" in command for command in handoff["dependency_groups"][3]["verification_commands"])
        )
        self.assertIn(
            "docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json",
            handoff["dependency_groups"][3]["evidence_outputs"],
        )
        self.assertIn(
            "make verify-au-p0b-google-phase-execution-fulfillment",
            handoff["dependency_groups"][4]["verification_commands"],
        )
        self.assertTrue(
            any("--require-fulfilled" in command for command in handoff["dependency_groups"][4]["verification_commands"])
        )
        self.assertIn(
            "docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json",
            handoff["dependency_groups"][4]["evidence_outputs"],
        )
        self.assertFalse(handoff["redaction_policy"]["raw_secret_values_allowed"])
        self.assertFalse(handoff["redaction_policy"]["raw_database_url_allowed"])
        self.assertFalse(handoff["redaction_policy"]["raw_selector_values_allowed"])
        self.assertFalse(handoff["redaction_policy"]["raw_manual_answer_values_allowed"])
        self.assertEqual(handoff["external_dependency_handoff_hash"], compute_external_dependency_handoff_hash(handoff))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("external_dependency_handoff_not_ready", hard_gate["errors"])

    def test_handoff_uses_manual_backfill_fulfillment_counts_when_available(self) -> None:
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path, p0a_env_path, p0a_exec_path, p0b_path = self._write_inputs(
                temp_dir
            )
            fulfillment_path, fulfillment = self._write_manual_fulfillment(temp_dir, p0b_path)
            handoff = build_au_external_dependency_handoff(
                launch_status_path=launch_status_path,
                remediation_plan_path=remediation_plan_path,
                p0a_environment_checklist_path=p0a_env_path,
                p0a_execution_checklist_path=p0a_exec_path,
                p0b_google_execution_checklist_path=p0b_path,
                p0b_google_manual_backfill_fulfillment_path=fulfillment_path,
                p0b_google_manual_backfill_fulfillment=fulfillment,
                output_path=Path(temp_dir) / "external-dependency-handoff.json",
                generated_at="2026-06-13T00:00:00Z",
            )
            verification = verify_au_external_dependency_handoff(handoff)

        manual_group = next(group for group in handoff["dependency_groups"] if group["id"] == "p0b_google_manual_backfill")
        self.assertEqual(verification["status"], "pass")
        self.assertFalse(handoff["external_dependency_handoff_ready"])
        self.assertTrue(handoff["summary"]["p0b_google_manual_backfill_fulfillment_available"])
        self.assertTrue(handoff["summary"]["p0b_google_manual_backfill_fulfillment_verified"])
        self.assertEqual(handoff["summary"]["p0b_google_manual_backfill_record_count"], 120)
        self.assertEqual(handoff["summary"]["p0b_google_manual_backfill_covered_prompt_city_count"], 60)
        self.assertEqual(
            handoff["summary"]["p0b_google_manual_backfill_fulfillment_missing_required_count"],
            fulfillment["summary"]["missing_required_count"],
        )
        self.assertEqual(
            handoff["summary"]["p0b_google_manual_backfill_fulfillment_hash"],
            fulfillment["p0b_google_manual_backfill_fulfillment_hash"],
        )
        self.assertEqual(manual_group["record_count"], 120)
        self.assertEqual(manual_group["covered_prompt_city_count"], 60)
        self.assertEqual(
            manual_group["manual_backfill_fulfillment_missing_required_count"],
            fulfillment["summary"]["missing_required_count"],
        )
        self.assertEqual(manual_group["manual_backfill_fulfilled"], fulfillment["manual_backfill_fulfilled"])

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
        tampered["summary"]["next_command"] = "make au-p0a-status"  # type: ignore[index]
        tampered["external_dependency_handoff_hash"] = compute_external_dependency_handoff_hash(tampered)
        verification = verify_au_external_dependency_handoff(tampered)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_p0b_google_phase_next_phase_mismatch", verification["errors"])
        self.assertIn("summary_next_command_mismatch", verification["errors"])

    def test_verifier_detects_dependency_group_execution_field_tampering(self) -> None:
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
        tampered["dependency_groups"][0]["next_command"] = "make au-p0a-status"  # type: ignore[index]
        tampered["dependency_groups"][2]["commands"] = []  # type: ignore[index]
        tampered["dependency_groups"][2]["blocking_reasons"] = []  # type: ignore[index]
        tampered["external_dependency_handoff_hash"] = compute_external_dependency_handoff_hash(tampered)
        verification = verify_au_external_dependency_handoff(tampered)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("dependency_group_next_command_mismatch:p0a_provider_credentials", verification["errors"])
        self.assertIn("dependency_group_commands_mismatch:p0b_google_environment", verification["errors"])
        self.assertIn("dependency_group_blocking_reasons_mismatch:p0b_google_environment", verification["errors"])

    def test_verifier_detects_clearance_sequence_tampering(self) -> None:
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
        tampered["clearance_sequence"]["steps"][1]["prerequisite_step_ids"] = []  # type: ignore[index]
        tampered["external_dependency_handoff_hash"] = compute_external_dependency_handoff_hash(tampered)
        verification = verify_au_external_dependency_handoff(tampered)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("clearance_step_prerequisites_mismatch:p0a_real_batches", verification["errors"])

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
