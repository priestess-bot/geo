from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_customer_handoff_readiness import build_au_customer_handoff_readiness
from scripts.build_au_delivery_progress import (
    PROGRESS_VERSION,
    build_au_delivery_progress,
    compute_delivery_progress_hash,
)
from scripts.build_au_external_dependency_handoff import build_au_external_dependency_handoff
from scripts.build_au_handoff_dossier import build_au_handoff_dossier
from scripts.build_au_next_work_item_packet import build_au_next_work_item_packet
from scripts.run_au_external_dependency_clearance import run_au_external_dependency_clearance
from scripts.verify_au_delivery_progress import verify_au_delivery_progress
from tests.test_au_handoff_dossier import AuHandoffDossierTest


class AuDeliveryProgressTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuHandoffDossierTest()
        self._helper.setUp()

    def _build_sources(self, temp_dir: str, *, ready: bool) -> dict[str, object]:
        launch_status_path, remediation_plan_path = self._helper._write_launch_status_and_plan(temp_dir, ready=ready)
        p0a_environment_path = self._helper._write_p0a_environment_checklist(temp_dir, ready=ready)
        p0a_execution_path = self._helper._write_p0a_execution_checklist(temp_dir, ready=ready)
        p0b_checklist_path = self._helper._write_p0b_google_execution_checklist(temp_dir, ready=ready)
        launch_status = json.loads(launch_status_path.read_text(encoding="utf-8"))
        remediation_plan = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
        handoff_path = Path(temp_dir) / "handoff.json"
        handoff = build_au_handoff_dossier(
            launch_status_path=launch_status_path,
            remediation_plan_path=remediation_plan_path,
            p0a_environment_checklist_path=p0a_environment_path,
            p0a_execution_checklist_path=p0a_execution_path,
            p0b_google_execution_checklist_path=p0b_checklist_path,
            output_path=handoff_path,
            markdown_output_path=Path(temp_dir) / "handoff.md",
            generated_at="2026-06-12T00:00:00Z",
        )
        handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
        readiness_path = Path(temp_dir) / "customer-readiness.json"
        readiness = build_au_customer_handoff_readiness(
            handoff_dossier_path=handoff_path,
            handoff_dossier=handoff,
            output_path=readiness_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
        dependency_handoff_path = Path(temp_dir) / "external-handoff.json"
        dependency_handoff = build_au_external_dependency_handoff(
            launch_status_path=launch_status_path,
            remediation_plan_path=remediation_plan_path,
            p0a_environment_checklist_path=p0a_environment_path,
            p0a_execution_checklist_path=p0a_execution_path,
            p0b_google_execution_checklist_path=p0b_checklist_path,
            launch_status=launch_status,
            remediation_plan=remediation_plan,
            output_path=dependency_handoff_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        dependency_handoff_path.write_text(json.dumps(dependency_handoff), encoding="utf-8")
        next_work_item_path = Path(temp_dir) / "next-work-item.json"
        next_work_item = build_au_next_work_item_packet(
            handoff_dossier_path=handoff_path,
            external_dependency_handoff_path=dependency_handoff_path,
            handoff_dossier=handoff,
            external_dependency_handoff=dependency_handoff,
            output_path=next_work_item_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        next_work_item_path.write_text(json.dumps(next_work_item), encoding="utf-8")
        clearance_path = Path(temp_dir) / "external-clearance.json"
        clearance = run_au_external_dependency_clearance(
            handoff_path=dependency_handoff_path,
            handoff=dependency_handoff,
            output_path=clearance_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        clearance_path.write_text(json.dumps(clearance), encoding="utf-8")
        return {
            "launch_status_path": launch_status_path,
            "handoff_path": handoff_path,
            "readiness_path": readiness_path,
            "next_work_item_path": next_work_item_path,
            "dependency_handoff_path": dependency_handoff_path,
            "clearance_path": clearance_path,
            "launch_status": launch_status,
            "handoff": handoff,
            "readiness": readiness,
            "next_work_item": next_work_item,
            "dependency_handoff": dependency_handoff,
            "clearance": clearance,
        }

    def test_progress_records_blocked_customer_handoff_with_machine_readable_percent(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            progress = build_au_delivery_progress(
                launch_status_path=sources["launch_status_path"],  # type: ignore[arg-type]
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                next_work_item_path=sources["next_work_item_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["dependency_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["clearance_path"],  # type: ignore[arg-type]
                launch_status=sources["launch_status"],  # type: ignore[arg-type]
                handoff_dossier=sources["handoff"],  # type: ignore[arg-type]
                customer_handoff_readiness=sources["readiness"],  # type: ignore[arg-type]
                next_work_item=sources["next_work_item"],  # type: ignore[arg-type]
                external_dependency_handoff=sources["dependency_handoff"],  # type: ignore[arg-type]
                external_dependency_clearance=sources["clearance"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "progress.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_delivery_progress(progress)
            hard_gate = verify_au_delivery_progress(progress, require_customer_ready=True)

        self.assertEqual(progress["delivery_progress_version"], PROGRESS_VERSION)
        self.assertEqual(progress["status"], "pass")
        self.assertTrue(progress["delivery_progress_ready"])
        self.assertFalse(progress["ready_for_customer_report_handoff"])
        self.assertEqual(progress["summary"]["engineering_progress_percent"], 46.2)
        self.assertEqual(progress["summary"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertEqual(progress["summary"]["structural_auditability_percent"], 100.0)
        self.assertEqual(progress["summary"]["ready_progress_gate_count"], 6)
        self.assertEqual(progress["summary"]["total_progress_gate_count"], 13)
        self.assertEqual(progress["summary"]["blocked_progress_gate_count"], 7)
        self.assertIn("p0a_credentials_fulfilled", progress["summary"]["blocked_progress_gate_ids"])
        self.assertIn("customer_report_handoff_ready", progress["summary"]["blocked_progress_gate_ids"])
        self.assertEqual(progress["summary"]["blocked_customer_gate_count"], 9)
        self.assertEqual(progress["summary"]["next_work_item_id"], "p0a_environment")
        self.assertEqual(progress["summary"]["current_clearance_step_id"], "p0a_provider_credentials")
        self.assertEqual(progress["summary"]["would_execute_step_count"], 1)
        self.assertEqual(progress["summary"]["next_command"], "make verify-au-p0a-env-template")
        self.assertEqual(progress["runtime_endpoints"]["delivery_progress"], "GET /v1/delivery-progress/au")
        self.assertIn("make au-delivery-progress", progress["hard_gate_commands"])
        self.assertIn("make verify-au-delivery-progress", progress["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-customer-ready") for command in progress["hard_gate_commands"]))
        self.assertTrue(progress["source_artifacts"]["next_work_item"]["hash"])
        self.assertEqual(progress["delivery_progress_hash"], compute_delivery_progress_hash(progress))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("customer_handoff_not_ready", hard_gate["errors"])

    def test_progress_reaches_customer_ready_when_all_customer_gates_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=True)
            progress = build_au_delivery_progress(
                launch_status_path=sources["launch_status_path"],  # type: ignore[arg-type]
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                next_work_item_path=sources["next_work_item_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["dependency_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["clearance_path"],  # type: ignore[arg-type]
                launch_status=sources["launch_status"],  # type: ignore[arg-type]
                handoff_dossier=sources["handoff"],  # type: ignore[arg-type]
                customer_handoff_readiness=sources["readiness"],  # type: ignore[arg-type]
                next_work_item=sources["next_work_item"],  # type: ignore[arg-type]
                external_dependency_handoff=sources["dependency_handoff"],  # type: ignore[arg-type]
                external_dependency_clearance=sources["clearance"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "progress.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            hard_gate = verify_au_delivery_progress(progress, require_customer_ready=True)

        self.assertTrue(progress["ready_for_customer_report_handoff"])
        self.assertEqual(progress["summary"]["customer_report_handoff_readiness_percent"], 100.0)
        self.assertEqual(progress["summary"]["blocked_customer_gate_count"], 0)
        self.assertEqual(progress["summary"]["engineering_progress_percent"], 100.0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_rejects_tampered_progress_percent_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            progress = build_au_delivery_progress(
                launch_status_path=sources["launch_status_path"],  # type: ignore[arg-type]
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                next_work_item_path=sources["next_work_item_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["dependency_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["clearance_path"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "progress.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            progress["summary"]["engineering_progress_percent"] = 99.0
            progress["delivery_progress_hash"] = compute_delivery_progress_hash(progress)
            verification = verify_au_delivery_progress(progress)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_engineering_progress_percent_mismatch", verification["errors"])

    def test_cli_writes_progress_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            output_path = Path(temp_dir) / "progress.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_delivery_progress.py",
                    "--launch-status-path",
                    str(sources["launch_status_path"]),
                    "--handoff-dossier-path",
                    str(sources["handoff_path"]),
                    "--customer-handoff-readiness-path",
                    str(sources["readiness_path"]),
                    "--next-work-item-path",
                    str(sources["next_work_item_path"]),
                    "--external-dependency-handoff-path",
                    str(sources["dependency_handoff_path"]),
                    "--external-dependency-clearance-path",
                    str(sources["clearance_path"]),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIn("au_delivery_progress_v1", result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(verify_au_delivery_progress(payload)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
