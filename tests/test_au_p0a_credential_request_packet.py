from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_credential_request_packet import (
    COMPLETION_CONTRACT_VERSION,
    COMPLETION_STRICT_GATE_COMMANDS,
    PACKET_VERSION,
    build_au_p0a_credential_request_packet,
    compute_p0a_credential_request_packet_hash,
)
from scripts.build_au_p0a_env_report import POST_UPDATE_VALIDATION_COMMANDS
from scripts.verify_au_p0a_credential_request_packet import verify_au_p0a_credential_request_packet
from tests.test_au_p0a_execution_checklist import AuP0aExecutionChecklistTest


class AuP0aCredentialRequestPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuP0aExecutionChecklistTest()

    def _write_execution_checklist(self, temp_dir: str, *, ready: bool) -> tuple[Path, dict[str, object]]:
        runbook_path, runbook = self._helper._write_runbook(temp_dir)
        environment_path = Path(temp_dir) / "environment.json"
        execution_path = Path(temp_dir) / "execution.json"
        readiness_path = Path(temp_dir) / "readiness.json"
        package_path = Path(temp_dir) / "package.json"
        status_path = Path(temp_dir) / "status.json"
        self._helper._write_env_report(environment_path, runbook_path, ready=ready)
        self._helper._write_runbook_execution(execution_path, runbook_path, ready=ready)
        self._helper._write_readiness(readiness_path, ready=ready)
        if ready:
            artifact_paths = runbook["artifact_paths"]  # type: ignore[index]
            self._helper._write_payload_and_manifest(
                Path(artifact_paths["preflight_json"]),  # type: ignore[index]
                Path(artifact_paths["preflight_manifest"]),  # type: ignore[index]
                planned_runs=6,
                record_count=6,
                prompt_limit=1,
                cities=["Sydney"],
            )
            self._helper._write_payload_and_manifest(
                Path(artifact_paths["small_batch_json"]),  # type: ignore[index]
                Path(artifact_paths["small_batch_manifest"]),  # type: ignore[index]
                planned_runs=30,
                record_count=30,
                prompt_limit=5,
                cities=["Sydney"],
            )
            self._helper._write_payload_and_manifest(
                Path(artifact_paths["full_batch_json"]),  # type: ignore[index]
                Path(artifact_paths["full_batch_manifest"]),  # type: ignore[index]
                planned_runs=2400,
                record_count=2400,
                prompt_limit=100,
                cities=["Australia", "Sydney", "Melbourne", "Brisbane"],
            )
        self._helper._write_package_and_status(
            runbook_path=runbook_path,
            environment_path=environment_path,
            execution_path=execution_path,
            readiness_path=readiness_path,
            package_path=package_path,
            status_path=status_path,
            ready=ready,
        )
        from scripts.build_au_p0a_execution_checklist import build_au_p0a_execution_checklist

        checklist = build_au_p0a_execution_checklist(
            runbook_path=runbook_path,
            environment_path=environment_path,
            runbook_execution_path=execution_path,
            readiness_path=readiness_path,
            package_path=package_path,
            status_path=status_path,
            env_file_path=Path(temp_dir) / "missing.env",
            output_path=Path(temp_dir) / "execution-checklist.json",
            generated_at="2026-06-12T00:00:00Z",
        )
        path = Path(temp_dir) / "execution-checklist.json"
        path.write_text(json.dumps(checklist), encoding="utf-8")
        return path, checklist

    def test_packet_records_missing_provider_credentials_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0a_credential_request_packet(
                p0a_execution_checklist_path=checklist_path,
                p0a_execution_checklist=checklist,
                output_path=Path(temp_dir) / "credential-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0a_credential_request_packet(packet)
            hard_gate = verify_au_p0a_credential_request_packet(packet, require_credentials_ready=True)

        self.assertEqual(packet["p0a_credential_request_packet_version"], PACKET_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["credential_request_packet_ready"])
        self.assertFalse(packet["credential_handoff_ready"])
        self.assertFalse(packet["ready_for_design_partner"])
        self.assertEqual(packet["summary"]["target_env_file"], str(Path(temp_dir) / "missing.env"))
        self.assertEqual(packet["summary"]["missing_required_count"], 3)
        self.assertEqual(
            sorted(packet["summary"]["missing_required"]),
            ["DATABASE_URL", "OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
        )
        self.assertEqual(packet["summary"]["credential_item_count"], 3)
        self.assertEqual(packet["summary"]["required_item_count"], 3)
        self.assertEqual(packet["summary"]["present_required_count"], 0)
        self.assertEqual(packet["summary"]["missing_required_by_owner"]["provider_admin"], ["OPENAI_API_KEY", "PERPLEXITY_API_KEY"])
        self.assertEqual(packet["summary"]["missing_required_by_owner"]["runtime_database_admin"], ["DATABASE_URL"])
        self.assertEqual(packet["summary"]["next_command"], "make verify-au-p0a-env-template")
        self.assertEqual(packet["summary"]["post_update_verification_command"], "make verify-au-p0a-env-bootstrap")
        self.assertTrue(packet["summary"]["credential_update_completion_contract_ready"])
        self.assertTrue(packet["summary"]["credential_update_receipt_required"])
        self.assertEqual(
            packet["summary"]["credential_update_receipt_endpoint"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertEqual(packet["summary"]["credential_update_receipt_strict_gate"], COMPLETION_STRICT_GATE_COMMANDS[-1])
        self.assertEqual(
            packet["summary"]["post_update_validation_command_count"],
            len(POST_UPDATE_VALIDATION_COMMANDS),
        )
        self.assertFalse(packet["summary"]["raw_secret_values_allowed"])
        self.assertTrue(packet["summary"]["forbidden_exact_secret_fields_redacted"])
        self.assertEqual(packet["post_update_validation_sequence"], list(POST_UPDATE_VALIDATION_COMMANDS))
        completion_contract = packet["credential_update_completion_contract"]
        self.assertEqual(completion_contract["version"], COMPLETION_CONTRACT_VERSION)
        self.assertTrue(completion_contract["ready"])
        self.assertEqual(completion_contract["target_env_file"], packet["summary"]["target_env_file"])
        self.assertEqual(completion_contract["required_missing_key_count"], 3)
        self.assertEqual(
            completion_contract["required_missing_keys"],
            ["DATABASE_URL", "OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
        )
        self.assertTrue(completion_contract["completion_receipt_required"])
        self.assertTrue(completion_contract["credential_update_receipt_complete_required"])
        self.assertEqual(
            completion_contract["post_update_validation_sequence"],
            list(POST_UPDATE_VALIDATION_COMMANDS),
        )
        self.assertEqual(completion_contract["strict_gate_commands"], list(COMPLETION_STRICT_GATE_COMMANDS))
        self.assertIn(
            "docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json",
            completion_contract["evidence_outputs"],
        )
        self.assertEqual(
            completion_contract["runtime_endpoints"]["p0a_credential_update_receipt"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertFalse(completion_contract["redaction_policy"]["raw_secret_values_allowed"])
        self.assertIn("make au-p0a-env-bootstrap", packet["setup_commands"])
        self.assertIn("make au-p0a-env", packet["verification_commands"])
        self.assertIn("docs/runtime_preflight/au-p0a-env-latest.json", packet["evidence_outputs"])
        self.assertEqual(packet["runtime_endpoints"]["p0a_credential_request"], "GET /v1/p0a-credential-request/au")
        self.assertEqual(
            packet["runtime_endpoints"]["p0a_credential_update_receipt"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertIn("make verify-au-p0a-credential-request", packet["hard_gate_commands"])
        self.assertTrue(any("--require-complete" in command for command in packet["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-ready-environment") for command in packet["hard_gate_commands"]))
        self.assertEqual(packet["p0a_credential_request_packet_hash"], compute_p0a_credential_request_packet_hash(packet))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0a_credentials_not_ready", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("perplexity-key", serialized)

    def test_packet_passes_credentials_ready_gate_when_all_required_values_are_present(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=True)
            packet = build_au_p0a_credential_request_packet(
                p0a_execution_checklist_path=checklist_path,
                p0a_execution_checklist=checklist,
                output_path=Path(temp_dir) / "credential-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            hard_gate = verify_au_p0a_credential_request_packet(packet, require_credentials_ready=True)

        self.assertTrue(packet["credential_handoff_ready"])
        self.assertEqual(packet["summary"]["missing_required_count"], 0)
        self.assertEqual(packet["summary"]["present_required_count"], 3)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_detects_tampered_completion_contract_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0a_credential_request_packet(
                p0a_execution_checklist_path=checklist_path,
                p0a_execution_checklist=checklist,
                output_path=Path(temp_dir) / "credential-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["credential_update_completion_contract"]["post_update_validation_sequence"] = []
            packet["credential_update_completion_contract"]["redaction_policy"]["raw_secret_values_allowed"] = True
            packet["summary"]["credential_update_receipt_required"] = False
            packet["p0a_credential_request_packet_hash"] = compute_p0a_credential_request_packet_hash(packet)
            verification = verify_au_p0a_credential_request_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("completion_contract_validation_sequence_mismatch", verification["errors"])
        self.assertIn("completion_contract_raw_secret_policy_invalid", verification["errors"])
        self.assertIn("summary_credential_update_receipt_required_missing", verification["errors"])

    def test_verifier_detects_tampered_missing_required_count_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0a_credential_request_packet(
                p0a_execution_checklist_path=checklist_path,
                p0a_execution_checklist=checklist,
                output_path=Path(temp_dir) / "credential-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["summary"]["missing_required_count"] = 0
            packet["p0a_credential_request_packet_hash"] = compute_p0a_credential_request_packet_hash(packet)
            verification = verify_au_p0a_credential_request_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_missing_required_count_mismatch", verification["errors"])

    def test_cli_writes_credential_request_packet_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, _checklist = self._write_execution_checklist(temp_dir, ready=False)
            output_path = Path(temp_dir) / "credential-request.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_credential_request_packet.py",
                    "--p0a-execution-checklist-path",
                    str(checklist_path),
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
            verify_result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0a_credential_request_packet.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("au_p0a_credential_request_packet_v1", result.stdout)
        self.assertIn("credential_request_packet_ready", verify_result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["summary"]["missing_required_count"], 3)
        self.assertEqual(verify_au_p0a_credential_request_packet(payload)["status"], "pass")
