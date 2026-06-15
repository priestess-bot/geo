from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_credential_fulfillment import (
    FULFILLMENT_VERSION,
    build_au_p0a_credential_fulfillment,
    compute_p0a_credential_fulfillment_hash,
)
from scripts.verify_au_p0a_credential_fulfillment import verify_au_p0a_credential_fulfillment
from tests.test_au_p0a_credential_request_packet import AuP0aCredentialRequestPacketTest
from scripts.build_au_p0a_env_report import build_au_p0a_env_report


class AuP0aCredentialFulfillmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._request_helper = AuP0aCredentialRequestPacketTest()
        self._request_helper.setUp()

    def _write_request_and_env(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
        checklist_path, checklist = self._request_helper._write_execution_checklist(temp_dir, ready=ready)
        from scripts.build_au_p0a_credential_request_packet import build_au_p0a_credential_request_packet

        request = build_au_p0a_credential_request_packet(
            p0a_execution_checklist_path=checklist_path,
            p0a_execution_checklist=checklist,
            output_path=Path(temp_dir) / "credential-request.json",
            generated_at="2026-06-14T00:00:00Z",
        )
        request_path = Path(temp_dir) / "credential-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        runbook_path = Path(temp_dir) / "runbook.json"
        env_report = build_au_p0a_env_report(
            runbook_path=runbook_path,
            env_file_path=Path(temp_dir) / "missing.env",
            output_path=Path(temp_dir) / "env-report.json",
            env={
                "PERPLEXITY_API_KEY": "perplexity-key",
                "OPENAI_API_KEY": "openai-key",
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
            }
            if ready
            else {},
            generated_at="2026-06-14T00:00:00Z",
        )
        env_path = Path(temp_dir) / "env-report.json"
        env_path.write_text(json.dumps(env_report), encoding="utf-8")
        return request_path, env_path, request, env_report

    def test_fulfillment_records_missing_credentials_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, request, env_report = self._write_request_and_env(temp_dir, ready=False)
            fulfillment = build_au_p0a_credential_fulfillment(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_request=request,
                env_report=env_report,
                output_path=Path(temp_dir) / "fulfillment.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            verification = verify_au_p0a_credential_fulfillment(fulfillment)
            hard_gate = verify_au_p0a_credential_fulfillment(fulfillment, require_fulfilled=True)

        self.assertEqual(fulfillment["p0a_credential_fulfillment_version"], FULFILLMENT_VERSION)
        self.assertEqual(fulfillment["status"], "pass")
        self.assertTrue(fulfillment["credential_fulfillment_ready"])
        self.assertFalse(fulfillment["credentials_fulfilled"])
        self.assertFalse(fulfillment["ready_for_design_partner"])
        self.assertEqual(fulfillment["summary"]["missing_required_count"], 3)
        self.assertEqual(
            sorted(fulfillment["summary"]["missing_required"]),
            ["DATABASE_URL", "OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
        )
        self.assertEqual(fulfillment["summary"]["next_action"], "populate_required_environment")
        self.assertEqual(fulfillment["runtime_endpoints"]["p0a_credential_fulfillment"], "GET /v1/p0a-credential-fulfillment/au")
        self.assertIn("make verify-au-p0a-credential-fulfillment", fulfillment["hard_gate_commands"])
        self.assertTrue(any("--require-fulfilled" in command for command in fulfillment["hard_gate_commands"]))
        self.assertEqual(
            fulfillment["p0a_credential_fulfillment_hash"],
            compute_p0a_credential_fulfillment_hash(fulfillment),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0a_credentials_not_fulfilled", hard_gate["errors"])
        serialized = json.dumps(fulfillment)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("perplexity-key", serialized)

    def test_fulfillment_passes_strict_gate_when_request_and_env_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, request, env_report = self._write_request_and_env(temp_dir, ready=True)
            fulfillment = build_au_p0a_credential_fulfillment(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_request=request,
                env_report=env_report,
                output_path=Path(temp_dir) / "fulfillment.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            hard_gate = verify_au_p0a_credential_fulfillment(fulfillment, require_fulfilled=True)

        self.assertTrue(fulfillment["credentials_fulfilled"])
        self.assertEqual(fulfillment["summary"]["fulfilled_required_count"], 3)
        self.assertEqual(fulfillment["summary"]["missing_required_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_detects_tampered_missing_count_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, request, env_report = self._write_request_and_env(temp_dir, ready=False)
            fulfillment = build_au_p0a_credential_fulfillment(
                credential_request_path=request_path,
                env_report_path=env_path,
                credential_request=request,
                env_report=env_report,
                output_path=Path(temp_dir) / "fulfillment.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            fulfillment["summary"]["missing_required_count"] = 0
            fulfillment["p0a_credential_fulfillment_hash"] = compute_p0a_credential_fulfillment_hash(fulfillment)
            verification = verify_au_p0a_credential_fulfillment(fulfillment)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_missing_required_count_mismatch", verification["errors"])

    def test_path_verifier_detects_stale_env_source_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, _request, _env_report = self._write_request_and_env(temp_dir, ready=False)
            output_path = Path(temp_dir) / "fulfillment.json"
            fulfillment = build_au_p0a_credential_fulfillment(
                credential_request_path=request_path,
                env_report_path=env_path,
                output_path=output_path,
                generated_at="2026-06-14T00:00:00Z",
            )
            output_path.write_text(json.dumps(fulfillment), encoding="utf-8")
            memory_verification = verify_au_p0a_credential_fulfillment(fulfillment)

            refreshed_env = build_au_p0a_env_report(
                runbook_path=Path(temp_dir) / "runbook.json",
                env_file_path=Path(temp_dir) / "missing.env",
                output_path=env_path,
                env={
                    "PERPLEXITY_API_KEY": "perplexity-key",
                    "OPENAI_API_KEY": "openai-key",
                    "DATABASE_URL": "postgresql://user:pass@example.test/db",
                },
                generated_at="2026-06-14T00:01:00Z",
            )
            env_path.write_text(json.dumps(refreshed_env), encoding="utf-8")
            path_verification = verify_au_p0a_credential_fulfillment(fulfillment, path=output_path)
            explicit_verification = verify_au_p0a_credential_fulfillment(
                fulfillment,
                verify_current_files=True,
            )

        self.assertEqual(memory_verification["status"], "pass")
        self.assertFalse(memory_verification["current_file_check_enabled"])
        self.assertEqual(path_verification["status"], "fail")
        self.assertTrue(path_verification["current_file_check_enabled"])
        self.assertIn("source_p0a_env_report_current_hash_mismatch", path_verification["errors"])
        self.assertIn("source_p0a_env_report_file_sha256_mismatch", path_verification["errors"])
        self.assertEqual(explicit_verification["status"], "fail")
        self.assertTrue(explicit_verification["current_file_check_enabled"])
        self.assertIn("source_p0a_env_report_current_hash_mismatch", explicit_verification["errors"])

    def test_cli_writes_and_verifies_fulfillment_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, _request, _env_report = self._write_request_and_env(temp_dir, ready=False)
            output_path = Path(temp_dir) / "fulfillment.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_credential_fulfillment.py",
                    "--credential-request-path",
                    str(request_path),
                    "--env-report-path",
                    str(env_path),
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
                    "scripts/verify_au_p0a_credential_fulfillment.py",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(build_result.stdout)
            verification = json.loads(verify_result.stdout)
            self.assertTrue(output_path.exists())
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(verification["status"], "pass")


if __name__ == "__main__":
    unittest.main()
