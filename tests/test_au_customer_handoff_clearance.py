from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_customer_handoff_clearance import (
    CLEARANCE_VERSION,
    build_au_customer_handoff_clearance,
    compute_customer_handoff_clearance_hash,
)
from scripts.build_au_customer_handoff_readiness import build_au_customer_handoff_readiness
from scripts.build_au_delivery_progress import build_au_delivery_progress
from scripts.build_au_external_dependency_handoff import build_au_external_dependency_handoff
from scripts.build_au_handoff_dossier import build_au_handoff_dossier
from scripts.build_au_next_work_item_packet import build_au_next_work_item_packet
from scripts.build_au_p0a_credential_clearance import build_au_p0a_credential_clearance
from scripts.build_au_p0a_credential_fulfillment import build_au_p0a_credential_fulfillment
from scripts.build_au_p0a_credential_request_packet import build_au_p0a_credential_request_packet
from scripts.build_au_p0a_real_batch_clearance import build_au_p0a_real_batch_clearance
from scripts.build_au_p0a_real_batch_fulfillment import build_au_p0a_real_batch_fulfillment
from scripts.build_au_p0a_real_batch_request_packet import build_au_p0a_real_batch_request_packet
from scripts.build_au_p0b_google_environment_clearance import build_au_p0b_google_environment_clearance
from scripts.build_au_p0b_google_manual_backfill_clearance import build_au_p0b_google_manual_backfill_clearance
from scripts.build_au_p0b_google_phase_execution_clearance import build_au_p0b_google_phase_execution_clearance
from scripts.run_au_external_dependency_clearance import run_au_external_dependency_clearance
from scripts.verify_au_customer_handoff_clearance import verify_au_customer_handoff_clearance
from tests.test_au_handoff_dossier import AuHandoffDossierTest


class AuCustomerHandoffClearanceTest(unittest.TestCase):
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
            generated_at="2026-06-14T00:00:00Z",
        )
        handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
        readiness_path = Path(temp_dir) / "customer-readiness.json"
        readiness = build_au_customer_handoff_readiness(
            handoff_dossier_path=handoff_path,
            handoff_dossier=handoff,
            output_path=readiness_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
        external_handoff_path = Path(temp_dir) / "external-handoff.json"
        external_handoff = build_au_external_dependency_handoff(
            launch_status_path=launch_status_path,
            remediation_plan_path=remediation_plan_path,
            p0a_environment_checklist_path=p0a_environment_path,
            p0a_execution_checklist_path=p0a_execution_path,
            p0b_google_execution_checklist_path=p0b_checklist_path,
            launch_status=launch_status,
            remediation_plan=remediation_plan,
            output_path=external_handoff_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        external_handoff_path.write_text(json.dumps(external_handoff), encoding="utf-8")
        next_work_item_path = Path(temp_dir) / "next-work-item.json"
        next_work_item = build_au_next_work_item_packet(
            handoff_dossier_path=handoff_path,
            external_dependency_handoff_path=external_handoff_path,
            handoff_dossier=handoff,
            external_dependency_handoff=external_handoff,
            output_path=next_work_item_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        next_work_item_path.write_text(json.dumps(next_work_item), encoding="utf-8")
        external_clearance_path = Path(temp_dir) / "external-clearance.json"
        external_clearance = run_au_external_dependency_clearance(
            handoff_path=external_handoff_path,
            handoff=external_handoff,
            output_path=external_clearance_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        external_clearance_path.write_text(json.dumps(external_clearance), encoding="utf-8")
        p0a_execution = json.loads(p0a_execution_path.read_text(encoding="utf-8"))
        env_report_path = Path(p0a_execution["paths"]["environment_report"])  # type: ignore[index]
        env_report = json.loads(env_report_path.read_text(encoding="utf-8"))
        credential_request_path = Path(temp_dir) / "credential-request.json"
        credential_request = build_au_p0a_credential_request_packet(
            p0a_execution_checklist_path=p0a_execution_path,
            p0a_execution_checklist=p0a_execution,
            output_path=credential_request_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        credential_request_path.write_text(json.dumps(credential_request), encoding="utf-8")
        credential_fulfillment_path = Path(temp_dir) / "credential-fulfillment.json"
        credential_fulfillment = build_au_p0a_credential_fulfillment(
            credential_request_path=credential_request_path,
            env_report_path=env_report_path,
            credential_request=credential_request,
            env_report=env_report,
            output_path=credential_fulfillment_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        credential_fulfillment_path.write_text(json.dumps(credential_fulfillment), encoding="utf-8")
        credential_clearance_path = Path(temp_dir) / "credential-clearance.json"
        credential_clearance = build_au_p0a_credential_clearance(
            credential_request_path=credential_request_path,
            env_report_path=env_report_path,
            credential_fulfillment_path=credential_fulfillment_path,
            external_dependency_clearance_path=external_clearance_path,
            credential_request=credential_request,
            credential_fulfillment=credential_fulfillment,
            external_dependency_clearance=external_clearance,
            output_path=credential_clearance_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        credential_clearance_path.write_text(json.dumps(credential_clearance), encoding="utf-8")
        real_batch_request_path = Path(temp_dir) / "real-batch-request.json"
        real_batch_request = build_au_p0a_real_batch_request_packet(
            p0a_execution_checklist_path=p0a_execution_path,
            p0a_execution_checklist=p0a_execution,
            output_path=real_batch_request_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        real_batch_request_path.write_text(json.dumps(real_batch_request), encoding="utf-8")
        real_batch_fulfillment_path = Path(temp_dir) / "real-batch-fulfillment.json"
        real_batch_fulfillment = build_au_p0a_real_batch_fulfillment(
            real_batch_request_path=real_batch_request_path,
            p0a_execution_checklist_path=p0a_execution_path,
            real_batch_request=real_batch_request,
            p0a_execution_checklist=p0a_execution,
            output_path=real_batch_fulfillment_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        real_batch_fulfillment_path.write_text(json.dumps(real_batch_fulfillment), encoding="utf-8")
        real_batch_clearance_path = Path(temp_dir) / "real-batch-clearance.json"
        real_batch_clearance = build_au_p0a_real_batch_clearance(
            real_batch_request_path=real_batch_request_path,
            p0a_execution_checklist_path=p0a_execution_path,
            real_batch_fulfillment_path=real_batch_fulfillment_path,
            external_dependency_clearance_path=external_clearance_path,
            real_batch_request=real_batch_request,
            p0a_execution_checklist=p0a_execution,
            real_batch_fulfillment=real_batch_fulfillment,
            external_dependency_clearance=external_clearance,
            output_path=real_batch_clearance_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        real_batch_clearance_path.write_text(json.dumps(real_batch_clearance), encoding="utf-8")
        p0b_environment_clearance_path = Path(temp_dir) / "p0b-environment-clearance.json"
        p0b_environment_clearance = build_au_p0b_google_environment_clearance(
            environment_request_path=Path(temp_dir) / "p0b-environment-request.json",
            playwright_env_report_path=Path(temp_dir) / "p0b-playwright-env.json",
            environment_fulfillment_path=Path(temp_dir) / "p0b-environment-fulfillment.json",
            external_dependency_clearance_path=external_clearance_path,
            playwright_env_file_path=Path(temp_dir) / "missing-google.env",
            external_dependency_clearance=external_clearance,
            output_path=p0b_environment_clearance_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        p0b_environment_clearance_path.write_text(json.dumps(p0b_environment_clearance), encoding="utf-8")
        p0b_manual_backfill_clearance_path = Path(temp_dir) / "p0b-manual-backfill-clearance.json"
        p0b_manual_backfill_clearance = build_au_p0b_google_manual_backfill_clearance(
            manual_backfill_request_path=Path(temp_dir) / "p0b-manual-backfill-request.json",
            manual_backfill_verification_path=Path(temp_dir) / "p0b-manual-backfill-verification.json",
            manual_backfill_fulfillment_path=Path(temp_dir) / "p0b-manual-backfill-fulfillment.json",
            external_dependency_clearance_path=external_clearance_path,
            manual_jsonl_path=Path(temp_dir) / "missing-manual-backfill.jsonl",
            external_dependency_clearance=external_clearance,
            output_path=p0b_manual_backfill_clearance_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        p0b_manual_backfill_clearance_path.write_text(json.dumps(p0b_manual_backfill_clearance), encoding="utf-8")
        p0b_phase_execution_clearance_path = Path(temp_dir) / "p0b-phase-execution-clearance.json"
        p0b_phase_execution_clearance = build_au_p0b_google_phase_execution_clearance(
            phase_execution_request_path=Path(temp_dir) / "p0b-phase-execution-request.json",
            p0b_google_execution_checklist_path=p0b_checklist_path,
            phase_execution_fulfillment_path=Path(temp_dir) / "p0b-phase-execution-fulfillment.json",
            external_dependency_clearance_path=external_clearance_path,
            external_dependency_clearance=external_clearance,
            output_path=p0b_phase_execution_clearance_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        p0b_phase_execution_clearance_path.write_text(json.dumps(p0b_phase_execution_clearance), encoding="utf-8")
        delivery_progress_path = Path(temp_dir) / "delivery-progress.json"
        delivery_progress = build_au_delivery_progress(
            launch_status_path=launch_status_path,
            handoff_dossier_path=handoff_path,
            customer_handoff_readiness_path=readiness_path,
            next_work_item_path=next_work_item_path,
            external_dependency_handoff_path=external_handoff_path,
            external_dependency_clearance_path=external_clearance_path,
            p0a_credential_clearance_path=credential_clearance_path,
            p0a_real_batch_clearance_path=real_batch_clearance_path,
            p0b_google_environment_clearance_path=p0b_environment_clearance_path,
            p0b_google_manual_backfill_clearance_path=p0b_manual_backfill_clearance_path,
            p0b_google_phase_execution_clearance_path=p0b_phase_execution_clearance_path,
            launch_status=launch_status,
            handoff_dossier=handoff,
            customer_handoff_readiness=readiness,
            next_work_item=next_work_item,
            external_dependency_handoff=external_handoff,
            external_dependency_clearance=external_clearance,
            p0a_credential_clearance=credential_clearance,
            p0a_real_batch_clearance=real_batch_clearance,
            p0b_google_environment_clearance=p0b_environment_clearance,
            p0b_google_manual_backfill_clearance=p0b_manual_backfill_clearance,
            p0b_google_phase_execution_clearance=p0b_phase_execution_clearance,
            output_path=delivery_progress_path,
            generated_at="2026-06-14T00:00:00Z",
        )
        delivery_progress_path.write_text(json.dumps(delivery_progress), encoding="utf-8")
        return {
            "handoff_path": handoff_path,
            "readiness_path": readiness_path,
            "delivery_progress_path": delivery_progress_path,
            "external_handoff_path": external_handoff_path,
            "external_clearance_path": external_clearance_path,
            "credential_clearance_path": credential_clearance_path,
            "real_batch_clearance_path": real_batch_clearance_path,
            "p0b_environment_clearance_path": p0b_environment_clearance_path,
            "p0b_manual_backfill_clearance_path": p0b_manual_backfill_clearance_path,
            "p0b_phase_execution_clearance_path": p0b_phase_execution_clearance_path,
            "handoff": handoff,
            "readiness": readiness,
            "delivery_progress": delivery_progress,
            "external_handoff": external_handoff,
            "external_clearance": external_clearance,
            "credential_clearance": credential_clearance,
            "real_batch_clearance": real_batch_clearance,
            "p0b_environment_clearance": p0b_environment_clearance,
            "p0b_manual_backfill_clearance": p0b_manual_backfill_clearance,
            "p0b_phase_execution_clearance": p0b_phase_execution_clearance,
        }

    def test_clearance_packet_records_blocked_customer_handoff_without_raw_payload_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            packet = build_au_customer_handoff_clearance(
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                delivery_progress_path=sources["delivery_progress_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["external_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["external_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                handoff_dossier=sources["handoff"],  # type: ignore[arg-type]
                customer_handoff_readiness=sources["readiness"],  # type: ignore[arg-type]
                delivery_progress=sources["delivery_progress"],  # type: ignore[arg-type]
                external_dependency_handoff=sources["external_handoff"],  # type: ignore[arg-type]
                external_dependency_clearance=sources["external_clearance"],  # type: ignore[arg-type]
                p0a_credential_clearance=sources["credential_clearance"],  # type: ignore[arg-type]
                p0a_real_batch_clearance=sources["real_batch_clearance"],  # type: ignore[arg-type]
                p0b_google_environment_clearance=sources["p0b_environment_clearance"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance=sources["p0b_manual_backfill_clearance"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance=sources["p0b_phase_execution_clearance"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "customer-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            verification = verify_au_customer_handoff_clearance(packet)
            hard_gate = verify_au_customer_handoff_clearance(packet, require_cleared=True)

        self.assertEqual(packet["customer_handoff_clearance_version"], CLEARANCE_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["customer_handoff_clearance_packet_ready"])
        self.assertFalse(packet["customer_handoff_ready"])
        self.assertFalse(packet["customer_handoff_clearance_ready"])
        self.assertFalse(packet["ready_for_report_export_handoff"])
        self.assertTrue(packet["blocked_by_prerequisite_step"])
        self.assertEqual(packet["clearance_step"]["id"], "customer_report_handoff_gate")
        self.assertEqual(packet["summary"]["required_count"], 10)
        self.assertEqual(packet["summary"]["fulfilled_required_count"], 1)
        self.assertEqual(packet["summary"]["missing_required_count"], 9)
        self.assertEqual(packet["summary"]["engineering_progress_percent"], 46.2)
        self.assertEqual(packet["summary"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertFalse(packet["summary"]["p0a_credential_clearance_ready"])
        self.assertFalse(packet["summary"]["p0a_credentials_fulfilled"])
        self.assertEqual(packet["summary"]["p0a_credential_missing_required_count"], 3)
        self.assertFalse(packet["summary"]["p0a_real_batch_clearance_ready"])
        self.assertFalse(packet["summary"]["p0a_real_batches_fulfilled"])
        self.assertTrue(packet["summary"]["p0a_real_batch_blocked_by_prerequisite"])
        self.assertEqual(packet["summary"]["p0a_real_batch_missing_required_count"], 3)
        self.assertFalse(packet["summary"]["p0b_google_environment_clearance_ready"])
        self.assertFalse(packet["summary"]["p0b_google_environment_fulfilled"])
        self.assertGreaterEqual(packet["summary"]["p0b_google_environment_missing_required_count"], 1)
        self.assertFalse(packet["summary"]["p0b_google_manual_backfill_clearance_ready"])
        self.assertFalse(packet["summary"]["p0b_google_manual_backfill_fulfilled"])
        self.assertGreaterEqual(packet["summary"]["p0b_google_manual_backfill_missing_required_count"], 1)
        self.assertFalse(packet["summary"]["p0b_google_phase_execution_clearance_ready"])
        self.assertFalse(packet["summary"]["p0b_google_phase_execution_fulfilled"])
        self.assertGreaterEqual(packet["summary"]["p0b_google_phase_execution_missing_required_count"], 1)
        self.assertEqual(packet["summary"]["next_action"], "clear_customer_handoff_prerequisites_first")
        self.assertEqual(packet["summary"]["next_command"], "make verify-au-p0a-env-template")
        self.assertIn("customer_gate:customer_report_handoff_gate", packet["summary"]["missing_required"])
        self.assertIn("make verify-au-customer-handoff-clearance", packet["post_update_validation_sequence"])
        self.assertTrue(any("--require-cleared" in command for command in packet["post_update_validation_sequence"]))
        self.assertTrue(any("--require-customer-ready" in command for command in packet["post_update_validation_sequence"]))
        self.assertEqual(
            packet["runtime_endpoints"]["customer_handoff_clearance"],
            "GET /v1/customer-handoff-clearance/au",
        )
        self.assertEqual(
            packet["runtime_endpoints"]["p0a_credential_clearance"],
            "GET /v1/p0a-credential-clearance/au",
        )
        self.assertEqual(
            packet["runtime_endpoints"]["p0a_real_batch_clearance"],
            "GET /v1/p0a-real-batch-clearance/au",
        )
        self.assertEqual(
            packet["runtime_endpoints"]["p0b_google_environment_clearance"],
            "GET /v1/p0b-google-environment-clearance/au",
        )
        self.assertEqual(
            packet["runtime_endpoints"]["p0b_google_manual_backfill_clearance"],
            "GET /v1/p0b-google-manual-backfill-clearance/au",
        )
        self.assertEqual(
            packet["runtime_endpoints"]["p0b_google_phase_execution_clearance"],
            "GET /v1/p0b-google-phase-execution-clearance/au",
        )
        self.assertIn("make verify-au-customer-handoff-clearance", packet["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-clearance", packet["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-real-batch-clearance", packet["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-environment-clearance", packet["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-manual-backfill-clearance", packet["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-phase-execution-clearance", packet["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-cleared") for command in packet["hard_gate_commands"]))
        self.assertEqual(
            packet["source_artifacts"]["p0a_credential_clearance"]["hash_field"],
            "p0a_credential_clearance_hash",
        )
        self.assertTrue(packet["source_artifacts"]["p0a_credential_clearance"]["hash_valid"])
        self.assertEqual(packet["verifiers"]["p0a_credential_clearance"]["status"], "pass")
        self.assertEqual(
            packet["source_artifacts"]["p0a_real_batch_clearance"]["hash_field"],
            "p0a_real_batch_clearance_hash",
        )
        self.assertTrue(packet["source_artifacts"]["p0a_real_batch_clearance"]["hash_valid"])
        self.assertEqual(packet["verifiers"]["p0a_real_batch_clearance"]["status"], "pass")
        self.assertEqual(
            packet["source_artifacts"]["p0b_google_environment_clearance"]["hash_field"],
            "p0b_google_environment_clearance_hash",
        )
        self.assertTrue(packet["source_artifacts"]["p0b_google_environment_clearance"]["hash_valid"])
        self.assertEqual(packet["verifiers"]["p0b_google_environment_clearance"]["status"], "pass")
        self.assertEqual(
            packet["source_artifacts"]["p0b_google_manual_backfill_clearance"]["hash_field"],
            "p0b_google_manual_backfill_clearance_hash",
        )
        self.assertTrue(packet["source_artifacts"]["p0b_google_manual_backfill_clearance"]["hash_valid"])
        self.assertEqual(packet["verifiers"]["p0b_google_manual_backfill_clearance"]["status"], "pass")
        self.assertEqual(
            packet["source_artifacts"]["p0b_google_phase_execution_clearance"]["hash_field"],
            "p0b_google_phase_execution_clearance_hash",
        )
        self.assertTrue(packet["source_artifacts"]["p0b_google_phase_execution_clearance"]["hash_valid"])
        self.assertEqual(packet["verifiers"]["p0b_google_phase_execution_clearance"]["status"], "pass")
        self.assertEqual(packet["customer_handoff_clearance_hash"], compute_customer_handoff_clearance_hash(packet))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("customer_handoff_not_cleared", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn('"answer_text":', serialized)
        self.assertNotIn('"citation_urls":', serialized)
        self.assertNotIn('"provider_response":', serialized)

    def test_clearance_packet_passes_strict_gate_when_customer_handoff_is_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=True)
            packet = build_au_customer_handoff_clearance(
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                delivery_progress_path=sources["delivery_progress_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["external_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["external_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                handoff_dossier=sources["handoff"],  # type: ignore[arg-type]
                customer_handoff_readiness=sources["readiness"],  # type: ignore[arg-type]
                delivery_progress=sources["delivery_progress"],  # type: ignore[arg-type]
                external_dependency_handoff=sources["external_handoff"],  # type: ignore[arg-type]
                external_dependency_clearance=sources["external_clearance"],  # type: ignore[arg-type]
                p0a_credential_clearance=sources["credential_clearance"],  # type: ignore[arg-type]
                p0a_real_batch_clearance=sources["real_batch_clearance"],  # type: ignore[arg-type]
                p0b_google_environment_clearance=sources["p0b_environment_clearance"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance=sources["p0b_manual_backfill_clearance"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance=sources["p0b_phase_execution_clearance"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "customer-clearance.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            hard_gate = verify_au_customer_handoff_clearance(packet, require_cleared=True)

        self.assertTrue(packet["customer_handoff_ready"])
        self.assertTrue(packet["customer_handoff_clearance_ready"])
        self.assertTrue(packet["ready_for_report_export_handoff"])
        self.assertFalse(packet["blocked_by_prerequisite_step"])
        self.assertEqual(packet["summary"]["missing_required_count"], 0)
        self.assertEqual(packet["summary"]["fulfilled_required_count"], 10)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_rejects_tampered_customer_gate_count_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            packet = build_au_customer_handoff_clearance(
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                delivery_progress_path=sources["delivery_progress_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["external_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["external_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                handoff_dossier=sources["handoff"],  # type: ignore[arg-type]
                customer_handoff_readiness=sources["readiness"],  # type: ignore[arg-type]
                delivery_progress=sources["delivery_progress"],  # type: ignore[arg-type]
                external_dependency_handoff=sources["external_handoff"],  # type: ignore[arg-type]
                external_dependency_clearance=sources["external_clearance"],  # type: ignore[arg-type]
                p0a_credential_clearance=sources["credential_clearance"],  # type: ignore[arg-type]
                p0a_real_batch_clearance=sources["real_batch_clearance"],  # type: ignore[arg-type]
                p0b_google_environment_clearance=sources["p0b_environment_clearance"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance=sources["p0b_manual_backfill_clearance"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance=sources["p0b_phase_execution_clearance"],  # type: ignore[arg-type]
                generated_at="2026-06-14T00:00:00Z",
            )
            packet["summary"]["fulfilled_required_count"] = 10
            packet["customer_handoff_clearance_hash"] = compute_customer_handoff_clearance_hash(packet)
            verification = verify_au_customer_handoff_clearance(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_fulfilled_required_count_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_clearance_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            output_path = Path(temp_dir) / "customer-clearance.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_customer_handoff_clearance.py",
                    "--handoff-dossier-path",
                    str(sources["handoff_path"]),
                    "--customer-handoff-readiness-path",
                    str(sources["readiness_path"]),
                    "--delivery-progress-path",
                    str(sources["delivery_progress_path"]),
                    "--external-dependency-handoff-path",
                    str(sources["external_handoff_path"]),
                    "--external-dependency-clearance-path",
                    str(sources["external_clearance_path"]),
                    "--p0a-credential-clearance-path",
                    str(sources["credential_clearance_path"]),
                    "--p0a-real-batch-clearance-path",
                    str(sources["real_batch_clearance_path"]),
                    "--p0b-google-environment-clearance-path",
                    str(sources["p0b_environment_clearance_path"]),
                    "--p0b-google-manual-backfill-clearance-path",
                    str(sources["p0b_manual_backfill_clearance_path"]),
                    "--p0b-google-phase-execution-clearance-path",
                    str(sources["p0b_phase_execution_clearance_path"]),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-14T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            verify_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_customer_handoff_clearance.py",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(build_result.stdout)
            verification = json.loads(verify_result.stdout)
            output_exists = output_path.exists()

        self.assertTrue(output_exists)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(verification["status"], "pass")


if __name__ == "__main__":
    unittest.main()
