from __future__ import annotations

import json
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_environment_request_packet import (
    PACKET_VERSION,
    build_au_p0b_google_environment_request_packet,
    compute_p0b_google_environment_request_packet_hash,
)
from scripts.verify_au_p0b_google_environment_request_packet import (
    verify_au_p0b_google_environment_request_packet,
)
from tests.test_au_p0b_google_execution_checklist import AuP0bGoogleExecutionChecklistTest
from scripts.build_au_p0a_env_report import compute_env_report_hash


def _find_forbidden_exact_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"value", "raw_value", "database_url"}:
                findings.append(child_path)
            findings.extend(_find_forbidden_exact_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_exact_fields(child, path=f"{path}[{index}]"))
    return findings


class AuP0bGoogleEnvironmentRequestPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self._helper = AuP0bGoogleExecutionChecklistTest()
        self._helper.setUp()

    def _write_execution_checklist(self, temp_dir: str, *, ready: bool) -> tuple[Path, dict[str, object]]:
        runbook_path, execution_path, env_path, status_path, package_path, _runbook = self._helper._write_status_and_package(
            temp_dir,
            google_ready=ready,
        )
        from scripts.build_au_p0b_google_execution_checklist import build_au_p0b_google_execution_checklist

        checklist = build_au_p0b_google_execution_checklist(
            runbook_path=runbook_path,
            execution_path=execution_path,
            playwright_env_path=env_path,
            status_report_path=status_path,
            package_path=package_path,
            env_file_path=Path(temp_dir) / "missing-google.env",
            output_path=Path(temp_dir) / "google-checklist.json",
            generated_at="2026-06-12T00:00:00Z",
        )
        path = Path(temp_dir) / "google-checklist.json"
        path.write_text(json.dumps(checklist), encoding="utf-8")
        return path, checklist

    def _write_p0a_env_report_with_database(self, temp_dir: str) -> tuple[Path, dict[str, object]]:
        report: dict[str, object] = {
            "environment_report_version": "au_p0a_environment_report_v1",
            "generated_at": "2026-06-12T00:00:00Z",
            "status": "fail",
            "ready_for_real_batch": False,
            "next_action": "populate_required_environment",
            "runbook_path": "runbook.json",
            "runbook": {"status": "pass"},
            "env_file": {
                "exists": True,
                "errors": [],
                "hygiene": {
                    "exists": True,
                    "hygiene_ready": True,
                    "hygiene_required": True,
                    "errors": [],
                    "warnings": [],
                    "secret_redacted": True,
                },
            },
            "required": [
                {
                    "name": "PERPLEXITY_API_KEY",
                    "present": False,
                    "source": "missing",
                    "value_length": 0,
                    "sha256_prefix": "",
                    "secret_redacted": True,
                },
                {
                    "name": "OPENAI_API_KEY",
                    "present": False,
                    "source": "missing",
                    "value_length": 0,
                    "sha256_prefix": "",
                    "secret_redacted": True,
                },
                {
                    "name": "DATABASE_URL",
                    "present": True,
                    "source": "env_file",
                    "value_length": 66,
                    "sha256_prefix": "237b9d13d4e5",
                    "secret_redacted": True,
                },
            ],
            "recommended": [],
            "missing_required": ["OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
            "missing_recommended": [],
            "warnings": [],
            "errors": [
                "required_env_missing:PERPLEXITY_API_KEY",
                "required_env_missing:OPENAI_API_KEY",
            ],
            "secrets_redacted": True,
        }
        report["environment_report_hash"] = compute_env_report_hash(report)
        path = Path(temp_dir) / "p0a-env.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path, report

    def test_packet_records_missing_google_environment_without_raw_selector_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0b_google_environment_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                p0a_env_report_path=Path(temp_dir) / "missing-p0a-env.json",
                output_path=Path(temp_dir) / "environment-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0b_google_environment_request_packet(packet)
            hard_gate = verify_au_p0b_google_environment_request_packet(packet, require_environment_ready=True)

        self.assertEqual(packet["p0b_google_environment_request_packet_version"], PACKET_VERSION)
        self.assertEqual(packet["status"], "pass")
        self.assertTrue(packet["google_environment_request_packet_ready"])
        self.assertFalse(packet["environment_handoff_ready"])
        self.assertFalse(packet["google_main_scoring_allowed"])
        self.assertEqual(packet["summary"]["target_env_file"], str(Path(temp_dir) / "missing-google.env"))
        self.assertEqual(packet["summary"]["missing_required_count"], 5)
        self.assertEqual(
            sorted(packet["summary"]["missing_required"]),
            [
                "full_run_env:DATABASE_URL",
                "full_run_env:MANUAL_BACKFILL_PATH",
                "selector_group:google_aio_answer_selector",
                "selector_group:google_aio_prompt_selector",
                "smoke_env:GOOGLE_PLAYWRIGHT_ENABLED",
            ],
        )
        self.assertEqual(packet["summary"]["environment_item_count"], 3)
        self.assertEqual(packet["summary"]["cross_stage_reuse_hint_count"], 0)
        self.assertFalse(packet["summary"]["database_url_reuse_available"])
        self.assertEqual(packet["summary"]["selector_item_count"], 2)
        self.assertEqual(packet["summary"]["file_item_count"], 3)
        self.assertEqual(packet["summary"]["dependency_item_count"], 1)
        self.assertEqual(
            packet["summary"]["missing_required_by_owner"]["browser_automation_operator"],
            [
                "selector_group:google_aio_answer_selector",
                "selector_group:google_aio_prompt_selector",
                "smoke_env:GOOGLE_PLAYWRIGHT_ENABLED",
            ],
        )
        self.assertEqual(
            packet["summary"]["missing_required_by_owner"]["google_manual_backfill_operator"],
            ["full_run_env:MANUAL_BACKFILL_PATH"],
        )
        self.assertEqual(
            packet["summary"]["missing_required_by_owner"]["runtime_database_admin"],
            ["full_run_env:DATABASE_URL"],
        )
        self.assertEqual(packet["summary"]["next_command"], "make verify-au-p0b-google-env-template")
        self.assertEqual(packet["summary"]["post_update_verification_command"], "make au-p0b-google-playwright-env")
        self.assertFalse(packet["summary"]["raw_secret_values_allowed"])
        self.assertTrue(packet["summary"]["forbidden_exact_secret_fields_redacted"])
        self.assertIn("make au-p0b-google-env-bootstrap", packet["setup_commands"])
        self.assertIn("make verify-au-p0b-google-playwright-env", packet["verification_commands"])
        self.assertIn("docs/runtime_preflight/au-p0b-google-playwright-env-latest.json", packet["evidence_outputs"])
        self.assertEqual(
            packet["runtime_endpoints"]["p0b_google_environment_request"],
            "GET /v1/p0b-google-environment-request/au",
        )
        self.assertIn("make verify-au-p0b-google-environment-request", packet["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-ready-smoke") for command in packet["hard_gate_commands"]))
        self.assertEqual(
            packet["p0b_google_environment_request_packet_hash"],
            compute_p0b_google_environment_request_packet_hash(packet),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0b_google_environment_not_ready", hard_gate["errors"])
        serialized = json.dumps(packet)
        self.assertNotIn("#prompt", serialized)
        self.assertNotIn(".answer", serialized)
        self.assertNotIn("postgres://", serialized)
        self.assertEqual(_find_forbidden_exact_fields(packet), [])

    def test_packet_passes_environment_ready_gate_when_google_inputs_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=True)
            packet = build_au_p0b_google_environment_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                p0a_env_report_path=Path(temp_dir) / "missing-p0a-env.json",
                output_path=Path(temp_dir) / "environment-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            hard_gate = verify_au_p0b_google_environment_request_packet(packet, require_environment_ready=True)

        self.assertTrue(packet["environment_handoff_ready"])
        self.assertTrue(packet["google_main_scoring_allowed"])
        self.assertEqual(packet["summary"]["missing_required_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_detects_tampered_missing_required_count_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            packet = build_au_p0b_google_environment_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                p0a_env_report_path=Path(temp_dir) / "missing-p0a-env.json",
                output_path=Path(temp_dir) / "environment-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            packet["summary"]["missing_required_count"] = 0
            packet["p0b_google_environment_request_packet_hash"] = compute_p0b_google_environment_request_packet_hash(
                packet
            )
            verification = verify_au_p0b_google_environment_request_packet(packet)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_missing_required_count_mismatch", verification["errors"])

    def test_cli_writes_google_environment_request_packet_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, _checklist = self._write_execution_checklist(temp_dir, ready=False)
            output_path = Path(temp_dir) / "environment-request.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_environment_request_packet.py",
                    "--p0b-google-execution-checklist-path",
                    str(checklist_path),
                    "--p0a-env-report-path",
                    str(Path(temp_dir) / "missing-p0a-env.json"),
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
                [sys.executable, "scripts/verify_au_p0b_google_environment_request_packet.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("au_p0b_google_environment_request_packet_v1", result.stdout)
        self.assertIn("google_environment_request_packet_ready", verify_result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["summary"]["missing_required_count"], 5)
        self.assertEqual(payload["summary"]["cross_stage_reuse_hint_count"], 0)
        self.assertEqual(verify_au_p0b_google_environment_request_packet(payload)["status"], "pass")

    def test_packet_records_redacted_database_reuse_hint_from_p0a_env_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            p0a_env_path, p0a_env_report = self._write_p0a_env_report_with_database(temp_dir)
            packet = build_au_p0b_google_environment_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                p0a_env_report_path=p0a_env_path,
                p0a_env_report=p0a_env_report,
                output_path=Path(temp_dir) / "environment-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0b_google_environment_request_packet(packet)

        self.assertEqual(verification["status"], "pass")
        self.assertEqual(packet["summary"]["cross_stage_reuse_hint_count"], 1)
        self.assertTrue(packet["summary"]["database_url_reuse_available"])
        self.assertEqual(packet["source_p0a_env_report"]["environment_report_hash"], p0a_env_report["environment_report_hash"])
        self.assertEqual(packet["p0a_env_report_verifier"]["status"], "pass")
        self.assertTrue(packet["p0a_env_report_verifier"]["hash_valid"])
        hint = packet["cross_stage_reuse_hints"][0]
        self.assertEqual(hint["id"], "reuse_p0a_database_url_for_p0b_google")
        self.assertEqual(hint["source_key"], "DATABASE_URL")
        self.assertEqual(hint["target_missing_id"], "full_run_env:DATABASE_URL")
        self.assertEqual(hint["target_env_file"], str(Path(temp_dir) / "missing-google.env"))
        self.assertFalse(hint["copy_raw_value_required"])
        self.assertTrue(hint["secret_redacted"])
        self.assertEqual(hint["value_length"], 66)
        self.assertEqual(hint["sha256_prefix"], "237b9d13d4e5")
        self.assertIn("make verify-au-p0b-google-environment-request", hint["post_update_checks"])
        serialized = json.dumps(packet)
        self.assertNotIn("postgres://", serialized)
        self.assertEqual(_find_forbidden_exact_fields(packet), [])

    def test_verifier_detects_tampered_cross_stage_reuse_hint_even_when_hash_is_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            checklist_path, checklist = self._write_execution_checklist(temp_dir, ready=False)
            p0a_env_path, p0a_env_report = self._write_p0a_env_report_with_database(temp_dir)
            packet = build_au_p0b_google_environment_request_packet(
                p0b_google_execution_checklist_path=checklist_path,
                p0b_google_execution_checklist=checklist,
                p0a_env_report_path=p0a_env_path,
                p0a_env_report=p0a_env_report,
                output_path=Path(temp_dir) / "environment-request.json",
                generated_at="2026-06-12T00:00:00Z",
            )
            tampered = deepcopy(packet)
            tampered["cross_stage_reuse_hints"][0]["source_hash_valid"] = False
            tampered["summary"]["cross_stage_reuse_hint_count"] = 0
            tampered["p0b_google_environment_request_packet_hash"] = compute_p0b_google_environment_request_packet_hash(
                tampered
            )
            verification = verify_au_p0b_google_environment_request_packet(tampered)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_cross_stage_reuse_hint_count_mismatch", verification["errors"])
        self.assertIn("cross_stage_reuse_hint_hash_valid_mismatch", verification["errors"])


if __name__ == "__main__":
    unittest.main()
