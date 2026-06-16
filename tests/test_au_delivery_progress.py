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
from scripts.build_au_next_work_item_packet import REQUEST_PACKET_CONTEXTS, build_au_next_work_item_packet
from scripts.build_au_p0a_credential_clearance import build_au_p0a_credential_clearance
from scripts.build_au_p0a_credential_fulfillment import build_au_p0a_credential_fulfillment
from scripts.build_au_p0a_credential_request_packet import build_au_p0a_credential_request_packet
from scripts.build_au_p0a_credential_update_receipt import build_au_p0a_credential_update_receipt
from scripts.build_au_p0a_real_batch_clearance import build_au_p0a_real_batch_clearance
from scripts.build_au_p0a_real_batch_fulfillment import build_au_p0a_real_batch_fulfillment
from scripts.build_au_p0a_real_batch_request_packet import build_au_p0a_real_batch_request_packet
from scripts.build_au_p0b_google_environment_clearance import build_au_p0b_google_environment_clearance
from scripts.build_au_p0b_google_manual_backfill_clearance import build_au_p0b_google_manual_backfill_clearance
from scripts.build_au_p0b_google_phase_execution_clearance import build_au_p0b_google_phase_execution_clearance
from scripts.run_au_external_dependency_clearance import (
    P0A_COMPLETION_CONTRACT_VERSION,
    P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
    P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE,
    P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT,
    run_au_external_dependency_clearance,
)
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
        clearance_path = Path(temp_dir) / "external-clearance.json"
        clearance = run_au_external_dependency_clearance(
            handoff_path=dependency_handoff_path,
            handoff=dependency_handoff,
            output_path=clearance_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        clearance_path.write_text(json.dumps(clearance), encoding="utf-8")
        p0a_execution = json.loads(p0a_execution_path.read_text(encoding="utf-8"))
        env_report_path = Path(p0a_execution["paths"]["environment_report"])  # type: ignore[index]
        env_report = json.loads(env_report_path.read_text(encoding="utf-8"))
        credential_request_path = Path(temp_dir) / "credential-request.json"
        credential_request = build_au_p0a_credential_request_packet(
            p0a_execution_checklist_path=p0a_execution_path,
            p0a_execution_checklist=p0a_execution,
            output_path=credential_request_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        credential_request_path.write_text(json.dumps(credential_request), encoding="utf-8")
        next_work_item_path = Path(temp_dir) / "next-work-item.json"
        original_context = REQUEST_PACKET_CONTEXTS["p0a_environment"].copy()
        REQUEST_PACKET_CONTEXTS["p0a_environment"]["output_path"] = str(credential_request_path)
        try:
            next_work_item = build_au_next_work_item_packet(
                handoff_dossier_path=handoff_path,
                external_dependency_handoff_path=dependency_handoff_path,
                handoff_dossier=handoff,
                external_dependency_handoff=dependency_handoff,
                output_path=next_work_item_path,
                generated_at="2026-06-12T00:00:00Z",
            )
        finally:
            REQUEST_PACKET_CONTEXTS["p0a_environment"] = original_context
        next_work_item_path.write_text(json.dumps(next_work_item), encoding="utf-8")
        credential_fulfillment_path = Path(temp_dir) / "credential-fulfillment.json"
        credential_fulfillment = build_au_p0a_credential_fulfillment(
            credential_request_path=credential_request_path,
            env_report_path=env_report_path,
            credential_request=credential_request,
            env_report=env_report,
            output_path=credential_fulfillment_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        credential_fulfillment_path.write_text(json.dumps(credential_fulfillment), encoding="utf-8")
        credential_clearance_path = Path(temp_dir) / "credential-clearance.json"
        credential_clearance = build_au_p0a_credential_clearance(
            credential_request_path=credential_request_path,
            env_report_path=env_report_path,
            credential_fulfillment_path=credential_fulfillment_path,
            external_dependency_clearance_path=clearance_path,
            credential_request=credential_request,
            credential_fulfillment=credential_fulfillment,
            external_dependency_clearance=clearance,
            output_path=credential_clearance_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        credential_clearance_path.write_text(json.dumps(credential_clearance), encoding="utf-8")
        credential_update_receipt_path = Path(temp_dir) / "credential-update-receipt.json"
        credential_update_receipt = build_au_p0a_credential_update_receipt(
            credential_request_path=credential_request_path,
            env_report_path=env_report_path,
            credential_fulfillment_path=credential_fulfillment_path,
            credential_clearance_path=credential_clearance_path,
            credential_request=credential_request,
            env_report=env_report,
            credential_fulfillment=credential_fulfillment,
            credential_clearance=credential_clearance,
            output_path=credential_update_receipt_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        credential_update_receipt_path.write_text(json.dumps(credential_update_receipt), encoding="utf-8")
        real_batch_request_path = Path(temp_dir) / "real-batch-request.json"
        real_batch_request = build_au_p0a_real_batch_request_packet(
            p0a_execution_checklist_path=p0a_execution_path,
            p0a_execution_checklist=p0a_execution,
            output_path=real_batch_request_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        real_batch_request_path.write_text(json.dumps(real_batch_request), encoding="utf-8")
        real_batch_fulfillment_path = Path(temp_dir) / "real-batch-fulfillment.json"
        real_batch_fulfillment = build_au_p0a_real_batch_fulfillment(
            real_batch_request_path=real_batch_request_path,
            p0a_execution_checklist_path=p0a_execution_path,
            real_batch_request=real_batch_request,
            p0a_execution_checklist=p0a_execution,
            output_path=real_batch_fulfillment_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        real_batch_fulfillment_path.write_text(json.dumps(real_batch_fulfillment), encoding="utf-8")
        real_batch_clearance_path = Path(temp_dir) / "real-batch-clearance.json"
        real_batch_clearance = build_au_p0a_real_batch_clearance(
            real_batch_request_path=real_batch_request_path,
            p0a_execution_checklist_path=p0a_execution_path,
            real_batch_fulfillment_path=real_batch_fulfillment_path,
            external_dependency_clearance_path=clearance_path,
            real_batch_request=real_batch_request,
            p0a_execution_checklist=p0a_execution,
            real_batch_fulfillment=real_batch_fulfillment,
            external_dependency_clearance=clearance,
            output_path=real_batch_clearance_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        real_batch_clearance_path.write_text(json.dumps(real_batch_clearance), encoding="utf-8")
        p0b_environment_clearance_path = Path(temp_dir) / "p0b-environment-clearance.json"
        p0b_environment_clearance = build_au_p0b_google_environment_clearance(
            environment_request_path=Path(temp_dir) / "p0b-environment-request.json",
            playwright_env_report_path=Path(temp_dir) / "p0b-playwright-env.json",
            environment_fulfillment_path=Path(temp_dir) / "p0b-environment-fulfillment.json",
            external_dependency_clearance_path=clearance_path,
            playwright_env_file_path=Path(temp_dir) / "missing-google.env",
            external_dependency_clearance=clearance,
            output_path=p0b_environment_clearance_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        p0b_environment_clearance_path.write_text(json.dumps(p0b_environment_clearance), encoding="utf-8")
        p0b_manual_backfill_clearance_path = Path(temp_dir) / "p0b-manual-backfill-clearance.json"
        p0b_manual_backfill_clearance = build_au_p0b_google_manual_backfill_clearance(
            manual_backfill_request_path=Path(temp_dir) / "p0b-manual-backfill-request.json",
            manual_backfill_verification_path=Path(temp_dir) / "p0b-manual-backfill-verification.json",
            manual_backfill_fulfillment_path=Path(temp_dir) / "p0b-manual-backfill-fulfillment.json",
            external_dependency_clearance_path=clearance_path,
            manual_jsonl_path=Path(temp_dir) / "missing-manual-backfill.jsonl",
            external_dependency_clearance=clearance,
            output_path=p0b_manual_backfill_clearance_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        p0b_manual_backfill_clearance_path.write_text(json.dumps(p0b_manual_backfill_clearance), encoding="utf-8")
        p0b_phase_execution_clearance_path = Path(temp_dir) / "p0b-phase-execution-clearance.json"
        p0b_phase_execution_clearance = build_au_p0b_google_phase_execution_clearance(
            phase_execution_request_path=Path(temp_dir) / "p0b-phase-execution-request.json",
            p0b_google_execution_checklist_path=p0b_checklist_path,
            phase_execution_fulfillment_path=Path(temp_dir) / "p0b-phase-execution-fulfillment.json",
            external_dependency_clearance_path=clearance_path,
            external_dependency_clearance=clearance,
            output_path=p0b_phase_execution_clearance_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        p0b_phase_execution_clearance_path.write_text(json.dumps(p0b_phase_execution_clearance), encoding="utf-8")
        return {
            "launch_status_path": launch_status_path,
            "handoff_path": handoff_path,
            "readiness_path": readiness_path,
            "next_work_item_path": next_work_item_path,
            "dependency_handoff_path": dependency_handoff_path,
            "clearance_path": clearance_path,
            "credential_clearance_path": credential_clearance_path,
            "credential_update_receipt_path": credential_update_receipt_path,
            "real_batch_clearance_path": real_batch_clearance_path,
            "p0b_environment_clearance_path": p0b_environment_clearance_path,
            "p0b_manual_backfill_clearance_path": p0b_manual_backfill_clearance_path,
            "p0b_phase_execution_clearance_path": p0b_phase_execution_clearance_path,
            "launch_status": launch_status,
            "handoff": handoff,
            "readiness": readiness,
            "next_work_item": next_work_item,
            "dependency_handoff": dependency_handoff,
            "clearance": clearance,
            "credential_clearance": credential_clearance,
            "credential_update_receipt": credential_update_receipt,
            "real_batch_clearance": real_batch_clearance,
            "p0b_environment_clearance": p0b_environment_clearance,
            "p0b_manual_backfill_clearance": p0b_manual_backfill_clearance,
            "p0b_phase_execution_clearance": p0b_phase_execution_clearance,
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
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_update_receipt_path=sources["credential_update_receipt_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                launch_status=sources["launch_status"],  # type: ignore[arg-type]
                handoff_dossier=sources["handoff"],  # type: ignore[arg-type]
                customer_handoff_readiness=sources["readiness"],  # type: ignore[arg-type]
                next_work_item=sources["next_work_item"],  # type: ignore[arg-type]
                external_dependency_handoff=sources["dependency_handoff"],  # type: ignore[arg-type]
                external_dependency_clearance=sources["clearance"],  # type: ignore[arg-type]
                p0a_credential_clearance=sources["credential_clearance"],  # type: ignore[arg-type]
                p0a_credential_update_receipt=sources["credential_update_receipt"],  # type: ignore[arg-type]
                p0a_real_batch_clearance=sources["real_batch_clearance"],  # type: ignore[arg-type]
                p0b_google_environment_clearance=sources["p0b_environment_clearance"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance=sources["p0b_manual_backfill_clearance"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance=sources["p0b_phase_execution_clearance"],  # type: ignore[arg-type]
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
        self.assertEqual(progress["summary"]["current_clearance_request_artifact_id"], "p0a_credential_request")
        self.assertEqual(
            progress["summary"]["current_clearance_request_artifact_hash"],
            sources["clearance"]["current_step_request_context"]["artifact_hash"],
        )
        self.assertTrue(progress["summary"]["current_clearance_completion_contract_ready"])
        self.assertEqual(
            progress["summary"]["current_clearance_completion_contract_version"],
            P0A_COMPLETION_CONTRACT_VERSION,
        )
        self.assertTrue(progress["summary"]["current_clearance_credential_update_receipt_required"])
        self.assertEqual(
            progress["summary"]["current_clearance_credential_update_receipt_endpoint"],
            P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
        )
        self.assertEqual(
            progress["summary"]["current_clearance_credential_update_receipt_strict_gate"],
            P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE,
        )
        self.assertEqual(
            progress["summary"]["current_clearance_post_update_validation_command_count"],
            P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT,
        )
        self.assertEqual(
            progress["summary"]["current_clearance_completion_contract_missing_required_count"],
            len(sources["clearance"]["current_step_request_context"]["completion_contract_required_missing_keys"]),
        )
        self.assertFalse(progress["summary"]["current_clearance_completion_contract_raw_secret_values_allowed"])
        self.assertEqual(progress["summary"]["next_command"], "make verify-au-p0a-env-template")
        self.assertEqual(progress["summary"]["p0a_credential_missing_required_count"], 3)
        self.assertFalse(progress["summary"]["p0a_credential_clearance_ready"])
        self.assertFalse(progress["summary"]["p0a_credentials_fulfilled"])
        self.assertTrue(progress["summary"]["p0a_credential_update_receipt_ready"])
        self.assertFalse(progress["summary"]["p0a_credential_update_receipt_complete"])
        self.assertEqual(progress["summary"]["p0a_credential_update_receipt_missing_required_count"], 3)
        self.assertEqual(progress["summary"]["p0a_real_batch_missing_required_count"], 3)
        self.assertFalse(progress["summary"]["p0a_real_batch_clearance_ready"])
        self.assertFalse(progress["summary"]["p0a_real_batches_fulfilled"])
        self.assertTrue(progress["summary"]["p0a_real_batch_blocked_by_prerequisite"])
        self.assertTrue(progress["summary"]["p0a_real_batch_execution_plan_ready"])
        self.assertEqual(progress["summary"]["p0a_real_batch_total_planned_runs"], 2436)
        self.assertEqual(progress["summary"]["p0a_real_batch_ready_phase_count"], 0)
        self.assertEqual(progress["summary"]["p0a_real_batch_blocked_phase_count"], 3)
        self.assertEqual(progress["summary"]["p0a_real_batch_phase_command_count"], 8)
        self.assertEqual(progress["summary"]["p0a_real_batch_evidence_output_count"], 6)
        self.assertFalse(progress["summary"]["p0b_google_environment_clearance_ready"])
        self.assertFalse(progress["summary"]["p0b_google_environment_fulfilled"])
        self.assertGreaterEqual(progress["summary"]["p0b_google_environment_missing_required_count"], 1)
        self.assertFalse(progress["summary"]["p0b_google_manual_backfill_clearance_ready"])
        self.assertFalse(progress["summary"]["p0b_google_manual_backfill_fulfilled"])
        self.assertGreaterEqual(progress["summary"]["p0b_google_manual_backfill_missing_required_count"], 1)
        self.assertFalse(progress["summary"]["p0b_google_manual_backfill_ready"])
        self.assertFalse(progress["summary"]["p0b_google_manual_backfill_coverage_complete"])
        self.assertFalse(progress["summary"]["p0b_google_manual_backfill_content_complete"])
        self.assertFalse(progress["summary"]["p0b_google_manual_backfill_content_completion_handoff_ready"])
        self.assertGreaterEqual(progress["summary"]["p0b_google_manual_backfill_missing_answer_line_count"], 0)
        self.assertGreaterEqual(progress["summary"]["p0b_google_manual_backfill_missing_citation_line_count"], 0)
        self.assertGreaterEqual(progress["summary"]["p0b_google_manual_backfill_missing_asset_line_count"], 0)
        self.assertGreaterEqual(progress["summary"]["p0b_google_manual_backfill_missing_total_content_cell_count"], 0)
        self.assertGreaterEqual(
            progress["summary"]["p0b_google_manual_backfill_post_content_completion_validation_command_count"],
            0,
        )
        self.assertFalse(progress["summary"]["p0b_google_phase_execution_clearance_ready"])
        self.assertFalse(progress["summary"]["p0b_google_phase_execution_fulfilled"])
        self.assertGreaterEqual(progress["summary"]["p0b_google_phase_execution_missing_required_count"], 1)
        self.assertEqual(progress["runtime_endpoints"]["delivery_progress"], "GET /v1/delivery-progress/au")
        self.assertEqual(
            progress["runtime_endpoints"]["p0a_credential_clearance"],
            "GET /v1/p0a-credential-clearance/au",
        )
        self.assertEqual(
            progress["runtime_endpoints"]["p0a_credential_update_receipt"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertEqual(
            progress["runtime_endpoints"]["p0a_real_batch_clearance"],
            "GET /v1/p0a-real-batch-clearance/au",
        )
        self.assertEqual(
            progress["runtime_endpoints"]["p0b_google_environment_clearance"],
            "GET /v1/p0b-google-environment-clearance/au",
        )
        self.assertEqual(
            progress["runtime_endpoints"]["p0b_google_manual_backfill_clearance"],
            "GET /v1/p0b-google-manual-backfill-clearance/au",
        )
        self.assertEqual(
            progress["runtime_endpoints"]["p0b_google_phase_execution_clearance"],
            "GET /v1/p0b-google-phase-execution-clearance/au",
        )
        self.assertIn("make au-delivery-progress", progress["hard_gate_commands"])
        self.assertIn("make verify-au-delivery-progress", progress["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-clearance", progress["hard_gate_commands"])
        self.assertIn("make au-p0a-credential-update-receipt", progress["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", progress["hard_gate_commands"])
        self.assertIn(P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE, progress["hard_gate_commands"])
        self.assertTrue(any("--require-complete" in command for command in progress["hard_gate_commands"]))
        self.assertIn("make verify-au-p0a-real-batch-clearance", progress["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-environment-clearance", progress["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-manual-backfill-clearance", progress["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-phase-execution-clearance", progress["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-customer-ready") for command in progress["hard_gate_commands"]))
        self.assertTrue(progress["source_artifacts"]["next_work_item"]["hash"])
        self.assertEqual(
            progress["source_artifacts"]["p0a_credential_clearance"]["hash_field"],
            "p0a_credential_clearance_hash",
        )
        self.assertTrue(progress["source_artifacts"]["p0a_credential_clearance"]["hash_valid"])
        self.assertEqual(progress["verifiers"]["p0a_credential_clearance"]["status"], "pass")
        self.assertEqual(
            progress["source_artifacts"]["p0a_credential_update_receipt"]["hash_field"],
            "p0a_credential_update_receipt_hash",
        )
        self.assertTrue(progress["source_artifacts"]["p0a_credential_update_receipt"]["hash_valid"])
        self.assertEqual(progress["verifiers"]["p0a_credential_update_receipt"]["status"], "pass")
        self.assertEqual(
            progress["source_artifacts"]["p0a_real_batch_clearance"]["hash_field"],
            "p0a_real_batch_clearance_hash",
        )
        self.assertTrue(progress["source_artifacts"]["p0a_real_batch_clearance"]["hash_valid"])
        self.assertEqual(progress["verifiers"]["p0a_real_batch_clearance"]["status"], "pass")
        self.assertEqual(
            progress["source_artifacts"]["p0b_google_environment_clearance"]["hash_field"],
            "p0b_google_environment_clearance_hash",
        )
        self.assertTrue(progress["source_artifacts"]["p0b_google_environment_clearance"]["hash_valid"])
        self.assertEqual(progress["verifiers"]["p0b_google_environment_clearance"]["status"], "pass")
        self.assertEqual(
            progress["source_artifacts"]["p0b_google_manual_backfill_clearance"]["hash_field"],
            "p0b_google_manual_backfill_clearance_hash",
        )
        self.assertTrue(progress["source_artifacts"]["p0b_google_manual_backfill_clearance"]["hash_valid"])
        self.assertEqual(progress["verifiers"]["p0b_google_manual_backfill_clearance"]["status"], "pass")
        self.assertEqual(
            progress["source_artifacts"]["p0b_google_phase_execution_clearance"]["hash_field"],
            "p0b_google_phase_execution_clearance_hash",
        )
        self.assertTrue(progress["source_artifacts"]["p0b_google_phase_execution_clearance"]["hash_valid"])
        self.assertEqual(progress["verifiers"]["p0b_google_phase_execution_clearance"]["status"], "pass")
        self.assertEqual(progress["delivery_progress_hash"], compute_delivery_progress_hash(progress))
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(verification["current_clearance_completion_contract_ready"])
        self.assertEqual(
            verification["current_clearance_credential_update_receipt_endpoint"],
            P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
        )
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
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_update_receipt_path=sources["credential_update_receipt_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                launch_status=sources["launch_status"],  # type: ignore[arg-type]
                handoff_dossier=sources["handoff"],  # type: ignore[arg-type]
                customer_handoff_readiness=sources["readiness"],  # type: ignore[arg-type]
                next_work_item=sources["next_work_item"],  # type: ignore[arg-type]
                external_dependency_handoff=sources["dependency_handoff"],  # type: ignore[arg-type]
                external_dependency_clearance=sources["clearance"],  # type: ignore[arg-type]
                p0a_credential_clearance=sources["credential_clearance"],  # type: ignore[arg-type]
                p0a_credential_update_receipt=sources["credential_update_receipt"],  # type: ignore[arg-type]
                p0a_real_batch_clearance=sources["real_batch_clearance"],  # type: ignore[arg-type]
                p0b_google_environment_clearance=sources["p0b_environment_clearance"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance=sources["p0b_manual_backfill_clearance"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance=sources["p0b_phase_execution_clearance"],  # type: ignore[arg-type]
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
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_update_receipt_path=sources["credential_update_receipt_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "progress.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            progress["summary"]["engineering_progress_percent"] = 99.0
            progress["delivery_progress_hash"] = compute_delivery_progress_hash(progress)
            verification = verify_au_delivery_progress(progress)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_engineering_progress_percent_mismatch", verification["errors"])

    def test_verifier_rejects_tampered_manual_backfill_content_count_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            progress = build_au_delivery_progress(
                launch_status_path=sources["launch_status_path"],  # type: ignore[arg-type]
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                next_work_item_path=sources["next_work_item_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["dependency_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["clearance_path"],  # type: ignore[arg-type]
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_update_receipt_path=sources["credential_update_receipt_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "progress.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            progress["summary"]["p0b_google_manual_backfill_missing_asset_line_count"] = 999
            progress["delivery_progress_hash"] = compute_delivery_progress_hash(progress)
            verification = verify_au_delivery_progress(progress)

        self.assertEqual(verification["status"], "fail")
        self.assertIn(
            "summary_p0b_google_manual_backfill_missing_asset_line_count_mismatch",
            verification["errors"],
        )

    def test_verifier_rejects_tampered_real_batch_execution_plan_count_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            progress = build_au_delivery_progress(
                launch_status_path=sources["launch_status_path"],  # type: ignore[arg-type]
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                next_work_item_path=sources["next_work_item_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["dependency_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["clearance_path"],  # type: ignore[arg-type]
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_update_receipt_path=sources["credential_update_receipt_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "progress.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            progress["summary"]["p0a_real_batch_total_planned_runs"] = 2400
            progress["delivery_progress_hash"] = compute_delivery_progress_hash(progress)
            verification = verify_au_delivery_progress(progress)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_p0a_real_batch_total_planned_runs_mismatch", verification["errors"])

    def test_verifier_rejects_tampered_current_clearance_completion_contract_even_when_hash_is_recomputed(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            progress = build_au_delivery_progress(
                launch_status_path=sources["launch_status_path"],  # type: ignore[arg-type]
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                next_work_item_path=sources["next_work_item_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["dependency_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["clearance_path"],  # type: ignore[arg-type]
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_update_receipt_path=sources["credential_update_receipt_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "progress.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            progress["summary"]["current_clearance_credential_update_receipt_required"] = False
            progress["delivery_progress_hash"] = compute_delivery_progress_hash(progress)
            verification = verify_au_delivery_progress(progress)

        self.assertEqual(verification["status"], "fail")
        self.assertIn(
            "summary_current_clearance_credential_update_receipt_required_mismatch",
            verification["errors"],
        )
        self.assertIn(
            "summary_current_clearance_credential_update_receipt_not_required",
            verification["errors"],
        )

    def test_verifier_rejects_tampered_manual_backfill_handoff_count_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            progress = build_au_delivery_progress(
                launch_status_path=sources["launch_status_path"],  # type: ignore[arg-type]
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                next_work_item_path=sources["next_work_item_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["dependency_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["clearance_path"],  # type: ignore[arg-type]
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_update_receipt_path=sources["credential_update_receipt_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "progress.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            progress["summary"]["p0b_google_manual_backfill_missing_total_content_cell_count"] = 999
            progress["delivery_progress_hash"] = compute_delivery_progress_hash(progress)
            verification = verify_au_delivery_progress(progress)

        self.assertEqual(verification["status"], "fail")
        self.assertIn(
            "summary_p0b_google_manual_backfill_missing_total_content_cell_count_mismatch",
            verification["errors"],
        )

    def test_verifier_rejects_stale_next_work_item_source_artifact(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sources = self._build_sources(temp_dir, ready=False)
            progress = build_au_delivery_progress(
                launch_status_path=sources["launch_status_path"],  # type: ignore[arg-type]
                handoff_dossier_path=sources["handoff_path"],  # type: ignore[arg-type]
                customer_handoff_readiness_path=sources["readiness_path"],  # type: ignore[arg-type]
                next_work_item_path=sources["next_work_item_path"],  # type: ignore[arg-type]
                external_dependency_handoff_path=sources["dependency_handoff_path"],  # type: ignore[arg-type]
                external_dependency_clearance_path=sources["clearance_path"],  # type: ignore[arg-type]
                p0a_credential_clearance_path=sources["credential_clearance_path"],  # type: ignore[arg-type]
                p0a_credential_update_receipt_path=sources["credential_update_receipt_path"],  # type: ignore[arg-type]
                p0a_real_batch_clearance_path=sources["real_batch_clearance_path"],  # type: ignore[arg-type]
                p0b_google_environment_clearance_path=sources["p0b_environment_clearance_path"],  # type: ignore[arg-type]
                p0b_google_manual_backfill_clearance_path=sources["p0b_manual_backfill_clearance_path"],  # type: ignore[arg-type]
                p0b_google_phase_execution_clearance_path=sources["p0b_phase_execution_clearance_path"],  # type: ignore[arg-type]
                output_path=Path(temp_dir) / "progress.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            next_work_item_path = sources["next_work_item_path"]  # type: ignore[assignment]
            next_work_item = json.loads(Path(next_work_item_path).read_text(encoding="utf-8"))
            next_work_item["next_work_item_packet_hash"] = "refreshed-next-work-item-hash"
            Path(next_work_item_path).write_text(json.dumps(next_work_item), encoding="utf-8")
            progress["delivery_progress_hash"] = compute_delivery_progress_hash(progress)
            in_memory_verification = verify_au_delivery_progress(progress)
            verification = verify_au_delivery_progress(progress, verify_current_files=True)
            path_verification = verify_au_delivery_progress(progress, path=Path(temp_dir) / "progress.json")

        self.assertEqual(in_memory_verification["status"], "pass")
        self.assertFalse(in_memory_verification["current_file_check_enabled"])
        self.assertEqual(verification["status"], "fail")
        self.assertTrue(verification["current_file_check_enabled"])
        self.assertEqual(path_verification["status"], "fail")
        self.assertTrue(path_verification["current_file_check_enabled"])
        self.assertIn("source_artifact_current_hash_mismatch:next_work_item", verification["errors"])
        self.assertIn("summary_source_artifact_current_hash_mismatch:next_work_item", verification["errors"])
        self.assertIn("evidence_source_file_sha256_mismatch:next_work_item", verification["errors"])

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
                    "--p0a-credential-clearance-path",
                    str(sources["credential_clearance_path"]),
                    "--p0a-credential-update-receipt-path",
                    str(sources["credential_update_receipt_path"]),
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
