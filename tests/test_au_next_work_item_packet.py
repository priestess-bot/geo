from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_external_dependency_handoff import build_au_external_dependency_handoff
from scripts.build_au_handoff_dossier import build_au_handoff_dossier
from scripts.build_au_next_work_item_packet import (
    PACKET_VERSION,
    REQUEST_PACKET_CONTEXTS,
    build_au_next_work_item_packet,
    compute_next_work_item_packet_hash,
)
from scripts.verify_au_next_work_item_packet import verify_au_next_work_item_packet
from scripts.verify_au_next_work_item_packet import (
    P0A_COMPLETION_CONTRACT_VERSION,
    P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
    P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE,
    P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT,
)
from tests.test_au_handoff_dossier import AuHandoffDossierTest


class AuNextWorkItemPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self.skipTest(
            "Legacy AU runtime_preflight next-work-item packet is archived; "
            "Production v1 gates cover the current GEO workflow."
        )
        self._helper = AuHandoffDossierTest()
        self._helper.setUp()

    def _build_handoff_dossier(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, dict[str, object], Path, dict[str, object]]:
        launch_status_path, remediation_plan_path = self._helper._write_launch_status_and_plan(temp_dir, ready=ready)
        checklist_path = self._helper._write_p0a_environment_checklist(temp_dir, ready=ready)
        p0a_execution_checklist_path = self._helper._write_p0a_execution_checklist(temp_dir, ready=ready)
        p0b_checklist_path = self._helper._write_p0b_google_execution_checklist(temp_dir, ready=ready)
        external_handoff_path = Path(temp_dir) / "external-dependency-handoff.json"
        external_handoff = build_au_external_dependency_handoff(
            launch_status_path=launch_status_path,
            remediation_plan_path=remediation_plan_path,
            p0a_environment_checklist_path=checklist_path,
            p0a_execution_checklist_path=p0a_execution_checklist_path,
            p0b_google_execution_checklist_path=p0b_checklist_path,
            output_path=external_handoff_path,
            generated_at="2026-06-12T00:00:00Z",
        )
        external_handoff_path.write_text(json.dumps(external_handoff), encoding="utf-8")
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
        return dossier_path, dossier, external_handoff_path, external_handoff

    def test_packet_records_current_p0a_environment_work_item(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier, external_handoff_path, external_handoff = self._build_handoff_dossier(
                temp_dir,
                ready=False,
            )
            packet = build_au_next_work_item_packet(
                handoff_dossier_path=dossier_path,
                external_dependency_handoff_path=external_handoff_path,
                handoff_dossier=dossier,
                external_dependency_handoff=external_handoff,
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
        self.assertEqual(packet["summary"]["work_item_command_count"], len(packet["execution_context"]["work_item_commands"]))
        self.assertEqual(
            packet["summary"]["work_item_verification_command_count"],
            len(packet["execution_context"]["work_item_verification_commands"]),
        )
        self.assertEqual(
            packet["summary"]["work_item_evidence_output_count"],
            len(packet["execution_context"]["work_item_evidence_outputs"]),
        )
        self.assertEqual(packet["summary"]["group_command_count"], len(packet["execution_context"]["group_commands"]))
        self.assertEqual(
            packet["summary"]["group_verification_command_count"],
            len(packet["execution_context"]["group_verification_commands"]),
        )
        self.assertEqual(
            packet["summary"]["group_evidence_output_count"],
            len(packet["execution_context"]["group_evidence_outputs"]),
        )
        self.assertGreater(packet["summary"]["group_verification_command_count"], 0)
        self.assertEqual(packet["summary"]["blocked_customer_gate_count"], 9)
        self.assertEqual(packet["summary"]["linked_dependency_group_id"], "p0a_provider_credentials")
        self.assertNotEqual(packet["summary"]["linked_dependency_group_status"], "missing")
        self.assertTrue(packet["summary"]["linked_dependency_group_next_command"])
        self.assertGreater(packet["summary"]["linked_dependency_group_blocking_reason_count"], 0)
        self.assertEqual(packet["summary"]["linked_request_packet_id"], "p0a_credential_request")
        self.assertEqual(packet["summary"]["linked_request_artifact_type"], "request_packet")
        self.assertTrue(packet["summary"]["linked_request_packet_exists"] in {True, False})
        self.assertTrue(packet["summary"]["linked_request_completion_contract_ready"])
        self.assertEqual(
            packet["summary"]["linked_request_completion_contract_version"],
            P0A_COMPLETION_CONTRACT_VERSION,
        )
        self.assertTrue(packet["summary"]["linked_request_credential_update_receipt_required"])
        self.assertEqual(
            packet["summary"]["linked_request_credential_update_receipt_endpoint"],
            P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
        )
        self.assertEqual(
            packet["summary"]["linked_request_credential_update_receipt_strict_gate"],
            P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE,
        )
        self.assertEqual(
            packet["summary"]["linked_request_post_update_validation_command_count"],
            P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT,
        )
        self.assertEqual(packet["summary"]["linked_request_completion_contract_missing_required_count"], 2)
        self.assertFalse(packet["summary"]["linked_request_completion_contract_raw_secret_values_allowed"])
        self.assertEqual(packet["execution_context"]["linked_request_packet"]["artifact_type"], "request_packet")
        self.assertEqual(packet["summary"]["recommended_sequence_count"], len(packet["execution_context"]["recommended_sequence"]))
        self.assertEqual(packet["execution_context"]["execution_context_version"], "au_next_work_item_execution_context_v1")
        self.assertEqual(packet["execution_context"]["linked_dependency_group"]["id"], "p0a_provider_credentials")
        self.assertEqual(packet["execution_context"]["linked_dependency_group"]["source"], "external_dependency_handoff")
        self.assertEqual(packet["execution_context"]["linked_dependency_group"]["status"], "requires_external_input")
        self.assertEqual(
            packet["execution_context"]["linked_dependency_group"]["next_command"],
            "make verify-au-p0a-env-template",
        )
        self.assertFalse(packet["execution_context"]["linked_dependency_group"]["env_file_hygiene_exists"])
        self.assertTrue(packet["execution_context"]["linked_dependency_group"]["env_file_hygiene_ready"])
        self.assertIn("make au-p0a-credential-fulfillment", packet["execution_context"]["group_verification_commands"])
        self.assertIn("make verify-au-p0a-credential-fulfillment", packet["execution_context"]["group_verification_commands"])
        self.assertIn(
            "docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json",
            packet["execution_context"]["group_evidence_outputs"],
        )
        self.assertIn("make au-p0a-credential-clearance", packet["execution_context"]["group_verification_commands"])
        self.assertIn("make verify-au-p0a-credential-clearance", packet["execution_context"]["group_verification_commands"])
        self.assertIn(
            "docs/runtime_preflight/au-p0a-credential-clearance-latest.json",
            packet["execution_context"]["group_evidence_outputs"],
        )
        self.assertIn(
            "make au-p0a-credential-update-receipt",
            packet["execution_context"]["group_verification_commands"],
        )
        self.assertIn(
            "make verify-au-p0a-credential-update-receipt",
            packet["execution_context"]["group_verification_commands"],
        )
        self.assertIn(
            "docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json",
            packet["execution_context"]["group_evidence_outputs"],
        )
        self.assertGreater(packet["execution_context"]["linked_dependency_group"]["blocking_reason_count"], 0)
        self.assertEqual(
            packet["execution_context"]["linked_dependency_group"]["source_path"],
            packet["source_external_dependency_handoff"]["path"],
        )
        self.assertEqual(packet["execution_context"]["linked_request_packet"]["request_packet_id"], "p0a_credential_request")
        self.assertEqual(
            packet["execution_context"]["linked_request_packet"]["runtime_endpoint"],
            "GET /v1/p0a-credential-request/au",
        )
        self.assertTrue(
            packet["execution_context"]["linked_request_packet"]["credential_update_completion_contract_ready"]
        )
        self.assertEqual(
            packet["execution_context"]["linked_request_packet"]["credential_update_completion_contract_version"],
            P0A_COMPLETION_CONTRACT_VERSION,
        )
        self.assertTrue(packet["execution_context"]["linked_request_packet"]["credential_update_receipt_required"])
        self.assertTrue(
            packet["execution_context"]["linked_request_packet"]["credential_update_receipt_complete_required"]
        )
        self.assertEqual(
            packet["execution_context"]["linked_request_packet"]["credential_update_receipt_endpoint"],
            P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
        )
        self.assertEqual(
            packet["execution_context"]["linked_request_packet"]["credential_update_receipt_strict_gate"],
            P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE,
        )
        self.assertEqual(
            packet["execution_context"]["linked_request_packet"]["post_update_validation_command_count"],
            P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT,
        )
        self.assertEqual(
            packet["execution_context"]["linked_request_packet"]["completion_contract_required_missing_keys"],
            ["OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
        )
        self.assertFalse(
            packet["execution_context"]["linked_request_packet"]["completion_contract_raw_secret_values_allowed"]
        )
        self.assertIn("make au-p0a-credential-request", packet["execution_context"]["recommended_sequence"])
        self.assertIn("make verify-au-p0a-credential-request", packet["execution_context"]["recommended_sequence"])
        self.assertIn("make au-p0a-credential-fulfillment", packet["execution_context"]["recommended_sequence"])
        self.assertIn("make verify-au-p0a-credential-fulfillment", packet["execution_context"]["recommended_sequence"])
        self.assertIn("make au-p0a-credential-clearance", packet["execution_context"]["recommended_sequence"])
        self.assertIn("make verify-au-p0a-credential-clearance", packet["execution_context"]["recommended_sequence"])
        self.assertIn("make au-p0a-credential-update-receipt", packet["execution_context"]["recommended_sequence"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", packet["execution_context"]["recommended_sequence"])
        self.assertTrue(
            any(command.endswith("--require-fulfilled") for command in packet["execution_context"]["recommended_sequence"])
        )
        self.assertTrue(
            any(command.endswith("--require-cleared") for command in packet["execution_context"]["recommended_sequence"])
        )
        self.assertTrue(
            any(command.endswith("--require-complete") for command in packet["execution_context"]["recommended_sequence"])
        )
        self.assertTrue(
            any(command.endswith("--require-credentials-ready") for command in packet["execution_context"]["recommended_sequence"])
        )
        self.assertEqual(packet["summary"]["recommended_sequence_count"], 26)
        self.assertEqual(packet["commands"][0], "make verify-au-p0a-env-template")
        self.assertIn("make au-p0a-env-bootstrap", packet["commands"])
        self.assertIn("make verify-au-p0a-env-bootstrap", packet["commands"])
        self.assertIn("make verify-au-p0a-status", packet["verification_commands"])
        self.assertIn("make verify-au-p0a-credential-fulfillment", packet["verification_commands"])
        self.assertIn("make verify-au-p0a-credential-clearance", packet["verification_commands"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", packet["verification_commands"])
        self.assertIn("docs/runtime_preflight/au-p0a-env-bootstrap-latest.json", packet["evidence_outputs"])
        self.assertIn("docs/runtime_preflight/au-p0a-env-latest.json", packet["evidence_outputs"])
        self.assertIn("docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json", packet["evidence_outputs"])
        self.assertIn("docs/runtime_preflight/au-p0a-credential-clearance-latest.json", packet["evidence_outputs"])
        self.assertIn("docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json", packet["evidence_outputs"])
        self.assertEqual(packet["runtime_endpoints"]["next_work_item"], "GET /v1/next-work-item/au")
        self.assertEqual(packet["runtime_endpoints"]["customer_handoff_readiness"], "GET /v1/customer-handoff-readiness/au")
        self.assertIn("make au-next-work-item", packet["hard_gate_commands"])
        self.assertIn("make verify-au-next-work-item", packet["hard_gate_commands"])
        self.assertIn("make au-p0a-credential-request", packet["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-request", packet["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-fulfillment", packet["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-clearance", packet["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", packet["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-customer-ready") for command in packet["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-credentials-ready") for command in packet["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-fulfilled") for command in packet["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-cleared") for command in packet["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-complete") for command in packet["hard_gate_commands"]))
        self.assertEqual(packet["next_work_item_packet_hash"], compute_next_work_item_packet_hash(packet))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("customer_handoff_not_ready", hard_gate["errors"])

    def test_downstream_next_work_item_contexts_are_fulfillment_aware(self) -> None:
        expected_contexts = {
            "p0a_small_batch": (
                "p0a_real_batch_fulfillment",
                "docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json",
                "GET /v1/p0a-real-batch-fulfillment/au",
                "make verify-au-p0a-real-batch-fulfillment",
                "scripts/verify_au_p0a_real_batch_fulfillment.py",
            ),
            "p0a_full_batch": (
                "p0a_real_batch_fulfillment",
                "docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json",
                "GET /v1/p0a-real-batch-fulfillment/au",
                "make verify-au-p0a-real-batch-fulfillment",
                "scripts/verify_au_p0a_real_batch_fulfillment.py",
            ),
            "p0b_google_playwright_env": (
                "p0b_google_environment_fulfillment",
                "docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json",
                "GET /v1/p0b-google-environment-fulfillment/au",
                "make verify-au-p0b-google-environment-fulfillment",
                "scripts/verify_au_p0b_google_environment_fulfillment.py",
            ),
            "p0b_google_manual_backfill": (
                "p0b_google_manual_backfill_fulfillment",
                "docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json",
                "GET /v1/p0b-google-manual-backfill-fulfillment/au",
                "make verify-au-p0b-google-manual-backfill-fulfillment",
                "scripts/verify_au_p0b_google_manual_backfill_fulfillment.py",
            ),
            "p0b_google_playwright_smoke": (
                "p0b_google_phase_execution_fulfillment",
                "docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json",
                "GET /v1/p0b-google-phase-execution-fulfillment/au",
                "make verify-au-p0b-google-phase-execution-fulfillment",
                "scripts/verify_au_p0b_google_phase_execution_fulfillment.py",
            ),
            "p0b_google_spike_health": (
                "p0b_google_phase_execution_fulfillment",
                "docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json",
                "GET /v1/p0b-google-phase-execution-fulfillment/au",
                "make verify-au-p0b-google-phase-execution-fulfillment",
                "scripts/verify_au_p0b_google_phase_execution_fulfillment.py",
            ),
            "p0b_google_full_spike": (
                "p0b_google_phase_execution_fulfillment",
                "docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json",
                "GET /v1/p0b-google-phase-execution-fulfillment/au",
                "make verify-au-p0b-google-phase-execution-fulfillment",
                "scripts/verify_au_p0b_google_phase_execution_fulfillment.py",
            ),
        }
        forbidden_request_only_ids = {
            "p0a_real_batch_request",
            "p0b_google_environment_request",
            "p0b_google_manual_backfill_request",
            "p0b_google_phase_execution_request",
        }

        for work_item_id, (
            request_packet_id,
            output_path,
            runtime_endpoint,
            verify_command,
            strict_script,
        ) in expected_contexts.items():
            with self.subTest(work_item_id=work_item_id):
                context = REQUEST_PACKET_CONTEXTS[work_item_id]
                self.assertEqual(context["artifact_type"], "fulfillment_artifact")
                self.assertEqual(context["request_packet_id"], request_packet_id)
                self.assertEqual(context["output_path"], output_path)
                self.assertEqual(context["runtime_endpoint"], runtime_endpoint)
                self.assertEqual(context["verify_command"], verify_command)
                self.assertIn(strict_script, context["strict_gate_command"])
                self.assertIn("--require-fulfilled", context["strict_gate_command"])
                self.assertNotIn(context["request_packet_id"], forbidden_request_only_ids)

    def test_packet_records_none_work_item_after_customer_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier, external_handoff_path, external_handoff = self._build_handoff_dossier(
                temp_dir,
                ready=True,
            )
            packet = build_au_next_work_item_packet(
                handoff_dossier_path=dossier_path,
                external_dependency_handoff_path=external_handoff_path,
                handoff_dossier=dossier,
                external_dependency_handoff=external_handoff,
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
            dossier_path, dossier, external_handoff_path, external_handoff = self._build_handoff_dossier(
                temp_dir,
                ready=False,
            )
            packet = build_au_next_work_item_packet(
                handoff_dossier_path=dossier_path,
                external_dependency_handoff_path=external_handoff_path,
                handoff_dossier=dossier,
                external_dependency_handoff=external_handoff,
                output_path=Path(temp_dir) / "next-work-item.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["summary"]["command_count"] = 999
            packet["next_work_item_packet_hash"] = compute_next_work_item_packet_hash(packet)
            verification = verify_au_next_work_item_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_command_count_mismatch", verification["errors"])

    def test_verifier_rejects_tampered_linked_request_context(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier, external_handoff_path, external_handoff = self._build_handoff_dossier(
                temp_dir,
                ready=False,
            )
            packet = build_au_next_work_item_packet(
                handoff_dossier_path=dossier_path,
                external_dependency_handoff_path=external_handoff_path,
                handoff_dossier=dossier,
                external_dependency_handoff=external_handoff,
                output_path=Path(temp_dir) / "next-work-item.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["execution_context"]["linked_request_packet"]["request_packet_id"] = "wrong_packet"
            packet["execution_context"]["linked_dependency_group"]["status"] = ""
            packet["execution_context"]["recommended_sequence"] = []
            packet["summary"]["recommended_sequence_count"] = 0
            packet["execution_context"]["recommended_sequence_count"] = 0
            packet["execution_context"]["combined_verification_commands"] = []
            packet["next_work_item_packet_hash"] = compute_next_work_item_packet_hash(packet)
            verification = verify_au_next_work_item_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("linked_request_packet_request_packet_id_mismatch", verification["errors"])
        self.assertIn("execution_context_dependency_group_status_missing", verification["errors"])
        self.assertIn("recommended_sequence_missing:make au-p0a-credential-request", verification["errors"])
        self.assertIn("execution_context_combined_verification_commands_mismatch", verification["errors"])

    def test_verifier_rejects_tampered_p0a_completion_contract_context(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier, external_handoff_path, external_handoff = self._build_handoff_dossier(
                temp_dir,
                ready=False,
            )
            packet = build_au_next_work_item_packet(
                handoff_dossier_path=dossier_path,
                external_dependency_handoff_path=external_handoff_path,
                handoff_dossier=dossier,
                external_dependency_handoff=external_handoff,
                output_path=Path(temp_dir) / "next-work-item.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["execution_context"]["linked_request_packet"]["credential_update_receipt_required"] = False
            packet["execution_context"]["linked_request_packet"]["credential_update_receipt_strict_gate"] = (
                "python3 forged-receipt-gate.py --require-complete"
            )
            packet["summary"]["linked_request_credential_update_receipt_required"] = False
            packet["summary"]["linked_request_credential_update_receipt_strict_gate"] = (
                "python3 forged-receipt-gate.py --require-complete"
            )
            packet["next_work_item_packet_hash"] = compute_next_work_item_packet_hash(packet)
            verification = verify_au_next_work_item_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("linked_request_packet_credential_update_receipt_required_mismatch", verification["errors"])
        self.assertIn("linked_request_packet_credential_update_receipt_strict_gate_mismatch", verification["errors"])
        self.assertIn("recommended_sequence_missing:p0a_credential_update_receipt_strict_gate", verification["errors"])
        self.assertIn("hard_gate_missing:p0a_credential_update_receipt_strict_gate", verification["errors"])

    def test_verifier_rejects_stale_linked_request_artifact_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, dossier, external_handoff_path, external_handoff = self._build_handoff_dossier(
                temp_dir,
                ready=False,
            )
            linked_path = Path(temp_dir) / "linked-request.json"
            linked_payload = {
                "p0a_credential_request_packet_hash": "current-request-hash",
                "status": "pass",
                "summary": {
                    "credential_update_completion_contract_ready": True,
                    "credential_update_receipt_required": True,
                    "credential_update_receipt_endpoint": P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
                    "credential_update_receipt_strict_gate": P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE,
                    "post_update_validation_command_count": P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT,
                },
                "credential_update_completion_contract": {
                    "version": P0A_COMPLETION_CONTRACT_VERSION,
                    "required_missing_key_count": 2,
                    "required_missing_keys": ["OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
                    "credential_update_receipt_ready_required": True,
                    "credential_update_receipt_complete_required": True,
                    "post_update_validation_command_count": P0A_POST_UPDATE_VALIDATION_COMMAND_COUNT,
                    "strict_gate_commands": [
                        "make verify-au-p0a-credential-update-receipt",
                        P0A_CREDENTIAL_UPDATE_RECEIPT_STRICT_GATE,
                    ],
                    "runtime_endpoints": {
                        "p0a_credential_update_receipt": P0A_CREDENTIAL_UPDATE_RECEIPT_ENDPOINT,
                    },
                    "redaction_policy": {
                        "raw_secret_values_allowed": False,
                        "raw_database_url_allowed": False,
                        "raw_provider_response_allowed": False,
                    },
                },
            }
            linked_path.write_text(json.dumps(linked_payload), encoding="utf-8")
            original_context = REQUEST_PACKET_CONTEXTS["p0a_environment"].copy()
            REQUEST_PACKET_CONTEXTS["p0a_environment"]["output_path"] = str(linked_path)
            try:
                packet = build_au_next_work_item_packet(
                    handoff_dossier_path=dossier_path,
                    external_dependency_handoff_path=external_handoff_path,
                    handoff_dossier=dossier,
                    external_dependency_handoff=external_handoff,
                    output_path=Path(temp_dir) / "next-work-item.json",
                    generated_at="2026-06-12T00:00:00Z",
                )
                linked_payload["p0a_credential_request_packet_hash"] = "refreshed-request-hash"
                linked_path.write_text(json.dumps(linked_payload), encoding="utf-8")
                packet["next_work_item_packet_hash"] = compute_next_work_item_packet_hash(packet)
                in_memory_verification = verify_au_next_work_item_packet(packet)
                verification = verify_au_next_work_item_packet(packet, verify_current_files=True)
                path_verification = verify_au_next_work_item_packet(packet, path=Path(temp_dir) / "next-work-item.json")
            finally:
                REQUEST_PACKET_CONTEXTS["p0a_environment"] = original_context

        self.assertEqual(in_memory_verification["status"], "pass")
        self.assertFalse(in_memory_verification["current_file_check_enabled"])
        self.assertEqual(verification["status"], "fail")
        self.assertTrue(verification["current_file_check_enabled"])
        self.assertEqual(path_verification["status"], "fail")
        self.assertTrue(path_verification["current_file_check_enabled"])
        self.assertIn("linked_request_packet_current_hash_mismatch", verification["errors"])
        self.assertIn("summary_linked_request_packet_current_hash_mismatch", verification["errors"])
        self.assertIn("linked_request_packet_file_sha256_mismatch", verification["errors"])

    def test_cli_writes_next_work_item_packet_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            dossier_path, _, external_handoff_path, _ = self._build_handoff_dossier(temp_dir, ready=False)
            output_path = Path(temp_dir) / "next-work-item.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_next_work_item_packet.py",
                    "--handoff-dossier-path",
                    str(dossier_path),
                    "--external-dependency-handoff-path",
                    str(external_handoff_path),
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
