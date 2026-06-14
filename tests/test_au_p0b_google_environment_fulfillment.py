from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_environment_fulfillment import (
    FULFILLMENT_VERSION,
    build_au_p0b_google_environment_fulfillment,
    compute_p0b_google_environment_fulfillment_hash,
)
from scripts.build_au_p0b_google_playwright_env_report import build_google_playwright_env_report
from scripts.build_au_p0b_google_spike_runbook import build_au_p0b_google_spike_runbook
from scripts.verify_au_p0b_google_environment_fulfillment import verify_au_p0b_google_environment_fulfillment
from tests.test_au_p0b_google_environment_request_packet import AuP0bGoogleEnvironmentRequestPacketTest


class AuP0bGoogleEnvironmentFulfillmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._request_helper = AuP0bGoogleEnvironmentRequestPacketTest()
        self._request_helper.setUp()

    def _write_runbook(self, temp_dir: str) -> Path:
        runbook = build_au_p0b_google_spike_runbook(
            artifact_dir=str(Path(temp_dir) / "runtime"),
            generated_at="2026-06-14T00:00:00Z",
        )
        path = Path(temp_dir) / "runbook.json"
        path.write_text(json.dumps(runbook), encoding="utf-8")
        return path

    def _write_request_and_env(
        self,
        temp_dir: str,
        *,
        ready: bool,
    ) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
        checklist_path, checklist = self._request_helper._write_execution_checklist(temp_dir, ready=ready)
        p0a_env_path, p0a_env_report = self._request_helper._write_p0a_env_report_with_database(temp_dir)
        from scripts.build_au_p0b_google_environment_request_packet import build_au_p0b_google_environment_request_packet

        request = build_au_p0b_google_environment_request_packet(
            p0b_google_execution_checklist_path=checklist_path,
            p0b_google_execution_checklist=checklist,
            p0a_env_report_path=p0a_env_path,
            p0a_env_report=p0a_env_report,
            output_path=Path(temp_dir) / "environment-request.json",
            generated_at="2026-06-14T00:00:00Z",
        )
        request_path = Path(temp_dir) / "environment-request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        runbook_path = self._write_runbook(temp_dir)
        manual_path = Path(temp_dir) / "manual.jsonl"
        if ready:
            manual_path.write_text("{}", encoding="utf-8")
        env_report = build_google_playwright_env_report(
            runbook_path=runbook_path,
            env_file_path=Path(temp_dir) / "missing.env",
            env={
                "GOOGLE_PLAYWRIGHT_ENABLED": "true",
                "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR": "#prompt",
                "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR": ".answer",
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
                "MANUAL_BACKFILL_PATH": str(manual_path),
            }
            if ready
            else {},
            playwright_available=True,
            generated_at="2026-06-14T00:00:00Z",
        )
        env_path = Path(temp_dir) / "playwright-env.json"
        env_path.write_text(json.dumps(env_report), encoding="utf-8")
        return request_path, env_path, request, env_report

    def test_fulfillment_records_missing_google_environment_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, request, env_report = self._write_request_and_env(temp_dir, ready=False)
            fulfillment = build_au_p0b_google_environment_fulfillment(
                environment_request_path=request_path,
                playwright_env_report_path=env_path,
                environment_request=request,
                playwright_env_report=env_report,
                output_path=Path(temp_dir) / "fulfillment.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            verification = verify_au_p0b_google_environment_fulfillment(fulfillment)
            hard_gate = verify_au_p0b_google_environment_fulfillment(fulfillment, require_fulfilled=True)

        self.assertEqual(fulfillment["p0b_google_environment_fulfillment_version"], FULFILLMENT_VERSION)
        self.assertEqual(fulfillment["status"], "pass")
        self.assertTrue(fulfillment["environment_fulfillment_ready"])
        self.assertFalse(fulfillment["environment_fulfilled"])
        self.assertFalse(fulfillment["ready_for_playwright_smoke"])
        self.assertEqual(fulfillment["summary"]["missing_required_count"], 6)
        self.assertIn("environment:DATABASE_URL", fulfillment["summary"]["missing_required"])
        self.assertIn("selector:google_aio_prompt_selector", fulfillment["summary"]["missing_required"])
        self.assertTrue(fulfillment["summary"]["database_url_reuse_available"])
        self.assertEqual(
            fulfillment["runtime_endpoints"]["p0b_google_environment_fulfillment"],
            "GET /v1/p0b-google-environment-fulfillment/au",
        )
        self.assertIn("make verify-au-p0b-google-environment-fulfillment", fulfillment["hard_gate_commands"])
        self.assertTrue(any("--require-fulfilled" in command for command in fulfillment["hard_gate_commands"]))
        self.assertEqual(
            fulfillment["p0b_google_environment_fulfillment_hash"],
            compute_p0b_google_environment_fulfillment_hash(fulfillment),
        )
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(hard_gate["status"], "fail")
        self.assertIn("p0b_google_environment_not_fulfilled", hard_gate["errors"])
        serialized = json.dumps(fulfillment)
        self.assertNotIn("postgresql://", serialized)
        self.assertNotIn("#prompt", serialized)
        self.assertNotIn(".answer", serialized)

    def test_fulfillment_passes_strict_gate_when_request_and_env_are_ready(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, request, env_report = self._write_request_and_env(temp_dir, ready=True)
            fulfillment = build_au_p0b_google_environment_fulfillment(
                environment_request_path=request_path,
                playwright_env_report_path=env_path,
                environment_request=request,
                playwright_env_report=env_report,
                output_path=Path(temp_dir) / "fulfillment.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            hard_gate = verify_au_p0b_google_environment_fulfillment(fulfillment, require_fulfilled=True)

        self.assertTrue(fulfillment["environment_fulfilled"])
        self.assertTrue(fulfillment["ready_for_playwright_smoke"])
        self.assertTrue(fulfillment["ready_for_full_google_run"])
        self.assertEqual(fulfillment["summary"]["missing_required_count"], 0)
        self.assertEqual(hard_gate["status"], "pass")

    def test_verifier_detects_tampered_missing_count_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, request, env_report = self._write_request_and_env(temp_dir, ready=False)
            fulfillment = build_au_p0b_google_environment_fulfillment(
                environment_request_path=request_path,
                playwright_env_report_path=env_path,
                environment_request=request,
                playwright_env_report=env_report,
                output_path=Path(temp_dir) / "fulfillment.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            fulfillment["summary"]["missing_required_count"] = 0
            fulfillment["p0b_google_environment_fulfillment_hash"] = compute_p0b_google_environment_fulfillment_hash(
                fulfillment
            )
            verification = verify_au_p0b_google_environment_fulfillment(fulfillment)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_missing_required_count_mismatch", verification["errors"])

    def test_cli_writes_and_verifies_fulfillment_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            request_path, env_path, _request, _env_report = self._write_request_and_env(temp_dir, ready=False)
            output_path = Path(temp_dir) / "fulfillment.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_environment_fulfillment.py",
                    "--environment-request-path",
                    str(request_path),
                    "--playwright-env-report-path",
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
                    "scripts/verify_au_p0b_google_environment_fulfillment.py",
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
