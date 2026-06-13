from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_handoff_dossier import build_au_handoff_dossier
from scripts.build_au_next_work_item_packet import (
    PACKET_VERSION,
    build_au_next_work_item_packet,
    compute_next_work_item_packet_hash,
)
from scripts.verify_au_next_work_item_packet import verify_au_next_work_item_packet
from tests.test_au_handoff_dossier import AuHandoffDossierTest


class AuNextWorkItemPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuHandoffDossierTest()
        self._helper.setUp()

    def _build_handoff_dossier(self, temp_dir: str, *, ready: bool) -> tuple[Path, dict[str, object]]:
        launch_status_path, remediation_plan_path = self._helper._write_launch_status_and_plan(temp_dir, ready=ready)
        checklist_path = self._helper._write_p0a_environment_checklist(temp_dir, ready=ready)
        p0a_execution_checklist_path = self._helper._write_p0a_execution_checklist(temp_dir, ready=ready)
        p0b_checklist_path = self._helper._write_p0b_google_execution_checklist(temp_dir, ready=ready)
        dossier_path = Path(temp_dir) / "dossier.json"
        dossier = build_au_handoff_dossier(
            launch_status_path=launch_status_path,
            remediation_plan_path=remediation_plan_path,
            p0a_environment_checklist_path=checklist_path,
            p0a_execution_checklist_path=p0a_execution_checklist_path,
            p0b_google_execution_checklist_path=p0b_checklist_path,
            output_path=dossier_path,
            markdown_output_path=Path(temp_dir) / "dossier.md",
            generated_at="2026-06-12T00:00:00Z",
        )
        dossier_path.write_text(json.dumps(dossier), encoding="utf-8")
        return dossier_path, dossier

    def test_packet_records_current_p0a_environment_work_item(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier = self._build_handoff_dossier(temp_dir, ready=False)
            packet = build_au_next_work_item_packet(
                handoff_dossier_path=dossier_path,
                handoff_dossier=dossier,
                output_path=Path(temp_dir) / "next-work-item.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_next_work_item_packet(packet)
            hard_gate = verify_au_next_work_item_packet(packet, require_customer_ready=True)

        self.assertEqual(packet["next_work_item_packet_version"], PACKET_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["next_work_item_packet_ready"])
        self.assertFalse(packet["ready_for_customer_report_handoff"])
        self.assertEqual(packet["summary"]["next_work_item_id"], "p0a_environment")
        self.assertEqual(packet["summary"]["stage"], "P0a")
        self.assertEqual(packet["summary"]["dependency_class"], "provider_keys_and_database")
        self.assertTrue(packet["summary"]["external_dependency"])
        self.assertEqual(packet["summary"]["blocker_count"], packet["next_work_item"]["blocker_count"])
        self.assertGreater(packet["summary"]["blocker_count"], 0)
        self.assertGreater(packet["summary"]["remaining_blocker_count"], 0)
        self.assertEqual(
            packet["summary"]["remaining_blocker_count"],
            packet["handoff_dossier_verifier"]["remaining_blocker_count"],
        )
        self.assertEqual(
            packet["summary"]["external_dependency_blocker_count"],
            dossier["summary"]["external_dependency_blocker_count"],
        )
        self.assertEqual(packet["summary"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertEqual(packet["summary"]["structural_auditability_percent"], 100.0)
        self.assertTrue(packet["summary"]["runnable_now"])
        self.assertEqual(packet["summary"]["command_count"], len(packet["commands"]))
        self.assertEqual(packet["summary"]["verification_command_count"], len(packet["verification_commands"]))
        self.assertEqual(packet["summary"]["evidence_output_count"], len(packet["evidence_outputs"]))
        self.assertEqual(packet["summary"]["blocked_customer_gate_count"], 9)
        self.assertEqual(packet["commands"][0], "make verify-au-p0a-env-template")
        self.assertIn("make au-p0a-env-bootstrap", packet["commands"])
        self.assertIn("make verify-au-p0a-env-bootstrap", packet["commands"])
        self.assertIn("make verify-au-p0a-status", packet["verification_commands"])
        self.assertIn("docs/runtime_preflight/au-p0a-env-bootstrap-latest.json", packet["evidence_outputs"])
        self.assertIn("docs/runtime_preflight/au-p0a-env-latest.json", packet["evidence_outputs"])
        self.assertEqual(packet["runtime_endpoints"]["next_work_item"], "GET /v1/next-work-item/au")
        self.assertEqual(packet["runtime_endpoints"]["customer_handoff_readiness"], "GET /v1/customer-handoff-readiness/au")
        self.assertIn("make au-next-work-item", packet["hard_gate_commands"])
        self.assertIn("make verify-au-next-work-item", packet["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-customer-ready") for command in packet["hard_gate_commands"]))
        self.assertEqual(packet["next_work_item_packet_hash"], compute_next_work_item_packet_hash(packet))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("customer_handoff_not_ready", hard_gate["errors"])

    def test_packet_records_none_work_item_after_customer_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier = self._build_handoff_dossier(temp_dir, ready=True)
            packet = build_au_next_work_item_packet(
                handoff_dossier_path=dossier_path,
                handoff_dossier=dossier,
                output_path=Path(temp_dir) / "next-work-item.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            hard_gate = verify_au_next_work_item_packet(packet, require_customer_ready=True)

        self.assertTrue(packet["ready_for_customer_report_handoff"])
        self.assertEqual(packet["summary"]["next_work_item_id"], "none")
        self.assertEqual(packet["summary"]["remaining_blocker_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_rejects_tampered_command_count_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier = self._build_handoff_dossier(temp_dir, ready=False)
            packet = build_au_next_work_item_packet(
                handoff_dossier_path=dossier_path,
                handoff_dossier=dossier,
                output_path=Path(temp_dir) / "next-work-item.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["summary"]["command_count"] = 999
            packet["next_work_item_packet_hash"] = compute_next_work_item_packet_hash(packet)
            verification = verify_au_next_work_item_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_command_count_mismatch", verification["errors"])

    def test_cli_writes_next_work_item_packet_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, _ = self._build_handoff_dossier(temp_dir, ready=False)
            output_path = Path(temp_dir) / "next-work-item.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_next_work_item_packet.py",
                    "--handoff-dossier-path",
                    str(dossier_path),
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

        self.assertIn("au_next_work_item_packet_v1", result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["summary"]["next_work_item_id"], "p0a_environment")
        self.assertEqual(verify_au_next_work_item_packet(payload)["status"], "pass")
