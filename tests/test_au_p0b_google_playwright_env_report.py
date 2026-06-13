from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0b_google_playwright_env_report import (
    ENV_REPORT_VERSION,
    build_google_playwright_env_report,
    compute_google_playwright_env_report_hash,
)
from scripts.build_au_p0b_google_spike_runbook import build_au_p0b_google_spike_runbook
from scripts.verify_au_p0b_google_playwright_env_report import verify_google_playwright_env_report


class AuP0bGooglePlaywrightEnvReportTest(unittest.TestCase):
    def _write_runbook(self, temp_dir: str) -> Path:
        runbook = build_au_p0b_google_spike_runbook(
            artifact_dir=str(Path(temp_dir) / "runtime"),
            generated_at="2026-06-12T00:00:00Z",
        )
        runbook_path = Path(temp_dir) / "runbook.json"
        runbook_path.write_text(json.dumps(runbook), encoding="utf-8")
        return runbook_path

    def test_report_records_missing_environment_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            report = build_google_playwright_env_report(
                runbook_path=runbook_path,
                env_file_path=Path(temp_dir) / "missing.env",
                env={},
                playwright_available=False,
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(report["environment_report_version"], ENV_REPORT_VERSION)
        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["ready_for_playwright_smoke"])
        self.assertFalse(report["ready_for_full_google_run"])
        self.assertEqual(report["collector_health"], "not_configured")
        self.assertEqual(report["next_action"], "populate_google_playwright_smoke_environment")
        self.assertIn("GOOGLE_PLAYWRIGHT_ENABLED", report["missing_required"])
        self.assertIn("google_aio_prompt_selector", report["missing_selector_groups"])
        self.assertIn("google_aio_answer_selector", report["missing_selector_groups"])
        self.assertIn("python_playwright_package_missing", report["errors"])
        self.assertTrue(report["secrets_redacted"])
        self.assertEqual(report["environment_report_hash"], compute_google_playwright_env_report_hash(report))
        self.assertNotIn("raw_value", json.dumps(report))

        verification = verify_google_playwright_env_report(report)
        self.assertEqual(verification["status"], "pass")
        strict = verify_google_playwright_env_report(report, require_ready_smoke=True)
        self.assertEqual(strict["status"], "fail")
        self.assertIn("playwright_smoke_environment_not_ready", strict["errors"])

    def test_google_playwright_enabled_must_be_truthy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            report = build_google_playwright_env_report(
                runbook_path=runbook_path,
                env_file_path=Path(temp_dir) / "missing.env",
                env={
                    "GOOGLE_PLAYWRIGHT_ENABLED": "0",
                    "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR": "#prompt",
                    "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR": ".answer",
                },
                playwright_available=True,
                generated_at="2026-06-12T00:00:00Z",
            )

        checks = {check["name"]: check for check in report["required"]}
        self.assertTrue(checks["GOOGLE_PLAYWRIGHT_ENABLED"]["present"])
        self.assertFalse(checks["GOOGLE_PLAYWRIGHT_ENABLED"]["truthy"])
        self.assertEqual(report["collector_health"], "not_configured")
        self.assertIn("GOOGLE_PLAYWRIGHT_ENABLED", report["missing_required"])
        self.assertIn("required_env_not_truthy:GOOGLE_PLAYWRIGHT_ENABLED", report["errors"])

        verification = verify_google_playwright_env_report(report)
        self.assertEqual(verification["status"], "pass")
        self.assertIn("GOOGLE_PLAYWRIGHT_ENABLED", verification["missing_required"])

    def test_report_ready_for_smoke_but_not_full_run_without_manual_and_database(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            report = build_google_playwright_env_report(
                runbook_path=runbook_path,
                env_file_path=Path(temp_dir) / "missing.env",
                env={
                    "GOOGLE_PLAYWRIGHT_ENABLED": "true",
                    "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR": "#prompt",
                    "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR": ".answer",
                },
                playwright_available=True,
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["ready_for_playwright_smoke"])
        self.assertFalse(report["ready_for_full_google_run"])
        self.assertEqual(report["collector_health"], "ready")
        self.assertEqual(report["next_action"], "run_au_p0b_google_playwright_smoke")
        self.assertEqual(report["missing_required"], [])
        self.assertEqual(set(report["missing_full_run_required"]), {"DATABASE_URL", "MANUAL_BACKFILL_PATH"})
        self.assertEqual(report["missing_selector_groups"], [])

        verification = verify_google_playwright_env_report(report, require_ready_smoke=True)
        self.assertEqual(verification["status"], "pass")

    def test_storage_state_path_must_exist_when_configured(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            missing_storage = Path(temp_dir) / "missing-storage.json"
            report = build_google_playwright_env_report(
                runbook_path=runbook_path,
                env_file_path=Path(temp_dir) / "missing.env",
                env={
                    "GOOGLE_PLAYWRIGHT_ENABLED": "1",
                    "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR": "#prompt",
                    "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR": ".answer",
                    "GOOGLE_PLAYWRIGHT_STORAGE_STATE": str(missing_storage),
                },
                playwright_available=True,
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(report["collector_health"], "session_state_missing")
        self.assertFalse(report["ready_for_playwright_smoke"])
        self.assertEqual(report["next_action"], "fix_google_playwright_storage_state")
        self.assertIn("storage_state_file_missing", report["errors"])

    def test_report_ready_for_full_google_run_when_manual_file_and_database_are_present(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            manual_path = Path(temp_dir) / "manual.jsonl"
            manual_path.write_text(
                json.dumps(
                    {
                        "prompt": "Best mattresses in Sydney?",
                        "city": "Sydney",
                        "answer_text": "Koala is visible.",
                        "citation_urls": ["https://koala.com/en-au"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            report = build_google_playwright_env_report(
                runbook_path=runbook_path,
                env_file_path=Path(temp_dir) / "missing.env",
                env={
                    "GOOGLE_PLAYWRIGHT_ENABLED": "yes",
                    "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR": "#prompt",
                    "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR": ".answer",
                    "MANUAL_BACKFILL_PATH": str(manual_path),
                    "DATABASE_URL": "postgresql://user:pass@example.test/db",
                },
                playwright_available=True,
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertTrue(report["ready_for_playwright_smoke"])
        self.assertTrue(report["ready_for_full_google_run"])
        self.assertEqual(report["missing_full_run_required"], [])
        self.assertNotIn("postgresql://user", json.dumps(report))

    def test_report_can_load_env_file_and_redact_fingerprints(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_file = Path(temp_dir) / ".env.au-p0b-google"
            env_file.write_text(
                "\n".join(
                    [
                        "export GOOGLE_PLAYWRIGHT_ENABLED=1",
                        "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR='#prompt'",
                        'GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR=".answer"',
                    ]
                ),
                encoding="utf-8",
            )
            env_file.chmod(0o600)
            report = build_google_playwright_env_report(
                runbook_path=runbook_path,
                env_file_path=env_file,
                env={},
                playwright_available=True,
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertTrue(report["ready_for_playwright_smoke"])
        self.assertTrue(report["env_file"]["hygiene"]["hygiene_ready"])
        self.assertTrue(report["env_file"]["hygiene"]["permission_safe"])
        self.assertEqual(report["env_file"]["hygiene"]["file_mode"], "0600")
        self.assertEqual(report["required"][0]["source"], "env_file")
        for group in report["selector_groups"]:
            self.assertEqual(group["source"], "env_file")
            self.assertEqual(len(group["sha256_prefix"]), 12)
        self.assertNotIn("#prompt", json.dumps(report))
        self.assertNotIn(".answer", json.dumps(report))

    def test_report_blocks_world_readable_env_file_with_sensitive_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_file = Path(temp_dir) / ".env.au-p0b-google"
            env_file.write_text(
                "GOOGLE_PLAYWRIGHT_ENABLED=1\n"
                "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR=#prompt\n"
                "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR=.answer\n",
                encoding="utf-8",
            )
            env_file.chmod(0o644)
            report = build_google_playwright_env_report(
                runbook_path=runbook_path,
                env_file_path=env_file,
                env={},
                playwright_available=True,
                generated_at="2026-06-12T00:00:00Z",
            )

        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["ready_for_playwright_smoke"])
        self.assertEqual(report["next_action"], "fix_google_playwright_env_file")
        self.assertIn("env_file:env_file_permissions_not_0600", report["errors"])
        self.assertFalse(report["env_file"]["hygiene"]["permission_safe"])
        self.assertFalse(report["env_file"]["hygiene"]["hygiene_ready"])
        self.assertNotIn("#prompt", json.dumps(report))

    def test_verifier_fails_raw_secret_field_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            report = build_google_playwright_env_report(
                runbook_path=runbook_path,
                env_file_path=Path(temp_dir) / "missing.env",
                env={
                    "GOOGLE_PLAYWRIGHT_ENABLED": "1",
                    "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR": "#prompt",
                    "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR": ".answer",
                },
                playwright_available=True,
                generated_at="2026-06-12T00:00:00Z",
            )
            report["required"][0]["value"] = "leaked"  # type: ignore[index]
            report["environment_report_hash"] = compute_google_playwright_env_report_hash(report)
            result = verify_google_playwright_env_report(report)

        self.assertEqual(result["status"], "fail")
        self.assertIn("required_check_raw_value_leaked:GOOGLE_PLAYWRIGHT_ENABLED", result["errors"])

    def test_verifier_fails_hygiene_error_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            report = build_google_playwright_env_report(
                runbook_path=runbook_path,
                env_file_path=Path(temp_dir) / "missing.env",
                env={
                    "GOOGLE_PLAYWRIGHT_ENABLED": "1",
                    "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR": "#prompt",
                    "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR": ".answer",
                },
                playwright_available=True,
                generated_at="2026-06-12T00:00:00Z",
            )
            report["env_file"]["hygiene"]["hygiene_ready"] = False  # type: ignore[index]
            report["env_file"]["hygiene"]["errors"] = ["env_file_permissions_not_0600"]  # type: ignore[index]
            report["environment_report_hash"] = compute_google_playwright_env_report_hash(report)
            result = verify_google_playwright_env_report(report)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["env_file_hygiene_ready"])
        self.assertIn("env_file_permissions_not_0600", result["env_file_hygiene_errors"])
        self.assertIn("ready_for_playwright_smoke_mismatch", result["errors"])

    def test_cli_writes_report_and_verifier_cli_reads_it(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_file = Path(temp_dir) / ".env.au-p0b-google"
            env_file.write_text(
                "GOOGLE_PLAYWRIGHT_ENABLED=1\n"
                "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR=#prompt\n"
                "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR=.answer\n",
                encoding="utf-8",
            )
            env_file.chmod(0o600)
            output_path = Path(temp_dir) / "env-report.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0b_google_playwright_env_report.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--env-file",
                    str(env_file),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            verify_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0b_google_playwright_env_report.py",
                    str(output_path),
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            written_payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(json.loads(build_result.stdout), written_payload)
        self.assertEqual(json.loads(verify_result.stdout)["status"], "pass")

    def test_repo_example_env_is_safe_to_parse_and_disabled_by_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            report = build_google_playwright_env_report(
                runbook_path=runbook_path,
                env_file_path=Path(".env.au-p0b-google.example"),
                env={},
                playwright_available=True,
                generated_at="2026-06-12T00:00:00Z",
            )

        required = {item["name"]: item for item in report["required"]}
        self.assertTrue(required["GOOGLE_PLAYWRIGHT_ENABLED"]["present"])
        self.assertFalse(required["GOOGLE_PLAYWRIGHT_ENABLED"]["truthy"])
        self.assertEqual(required["GOOGLE_PLAYWRIGHT_ENABLED"]["source"], "env_file")
        self.assertEqual(report["collector_health"], "not_configured")
        self.assertFalse(report["ready_for_playwright_smoke"])
        self.assertFalse(report["ready_for_full_google_run"])
        self.assertEqual(report["next_action"], "populate_google_playwright_smoke_environment")
        self.assertTrue(report["env_file"]["hygiene"]["template_file"])
        self.assertFalse(report["env_file"]["hygiene"]["hygiene_required"])
        self.assertTrue(report["env_file"]["hygiene"]["hygiene_ready"])
        self.assertIn("GOOGLE_PLAYWRIGHT_ENABLED", report["missing_required"])
        self.assertIn("google_aio_prompt_selector", report["missing_selector_groups"])
        self.assertNotIn("raw_value", json.dumps(report))
        self.assertEqual(verify_google_playwright_env_report(report)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
