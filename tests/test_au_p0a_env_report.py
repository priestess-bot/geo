from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_env_report import (
    ENV_REPORT_VERSION,
    build_au_p0a_env_report,
    compute_env_report_hash,
)
from scripts.build_au_p0a_runbook import build_au_p0a_runbook


class AuP0aEnvReportTest(unittest.TestCase):
    def _write_runbook(self, temp_dir: str) -> Path:
        runbook = build_au_p0a_runbook(
            artifact_dir=str(Path(temp_dir) / "runtime"),
            generated_at="2026-06-11T00:00:00Z",
        )
        runbook_path = Path(temp_dir) / "runbook.json"
        runbook_path.write_text(json.dumps(runbook), encoding="utf-8")
        return runbook_path

    def test_report_records_missing_environment_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            report = build_au_p0a_env_report(
                runbook_path=runbook_path,
                env_file_path=Path(temp_dir) / "missing.env",
                env={},
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(report["environment_report_version"], ENV_REPORT_VERSION)
        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["ready_for_real_batch"])
        self.assertEqual(report["next_action"], "populate_required_environment")
        self.assertIn("PERPLEXITY_API_KEY", report["missing_required"])
        self.assertTrue(report["secrets_redacted"])
        self.assertEqual(report["environment_report_hash"], compute_env_report_hash(report))
        self.assertNotIn("test-openai", json.dumps(report))

    def test_report_can_load_env_file_and_redact_fingerprints(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_file = Path(temp_dir) / ".env.au-p0a"
            env_file.write_text(
                "\n".join(
                    [
                        "PERPLEXITY_API_KEY=perplexity-secret",
                        "OPENAI_API_KEY='openai-secret'",
                        'DATABASE_URL="postgresql://user:pass@example.test/db"',
                    ]
                ),
                encoding="utf-8",
            )
            env_file.chmod(0o600)
            report = build_au_p0a_env_report(
                runbook_path=runbook_path,
                env_file_path=env_file,
                env={},
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["ready_for_real_batch"])
        self.assertEqual(report["missing_required"], [])
        self.assertEqual(report["next_action"], "run_au_p0a_runbook_dry_run")
        self.assertTrue(report["env_file"]["hygiene"]["hygiene_ready"])
        self.assertTrue(report["env_file"]["hygiene"]["permission_safe"])
        self.assertIsNone(report["env_file"]["hygiene"]["git_tracked"])
        self.assertEqual(report["env_file"]["hygiene"]["file_mode"], "0600")
        for check in report["required"]:
            self.assertEqual(check["source"], "env_file")
            self.assertEqual(len(check["sha256_prefix"]), 12)
            self.assertNotIn("value", check)
        self.assertNotIn("openai-secret", json.dumps(report))

    def test_report_blocks_world_readable_env_file_with_secrets(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_file = Path(temp_dir) / ".env.au-p0a"
            env_file.write_text(
                "\n".join(
                    [
                        "PERPLEXITY_API_KEY=perplexity-secret",
                        "OPENAI_API_KEY=openai-secret",
                        "DATABASE_URL=postgresql://user:pass@example.test/db",
                    ]
                ),
                encoding="utf-8",
            )
            env_file.chmod(0o644)
            report = build_au_p0a_env_report(
                runbook_path=runbook_path,
                env_file_path=env_file,
                env={},
                generated_at="2026-06-11T00:00:00Z",
            )

        self.assertEqual(report["status"], "fail")
        self.assertFalse(report["ready_for_real_batch"])
        self.assertEqual(report["next_action"], "fix_environment_file")
        self.assertIn("env_file:env_file_permissions_not_0600", report["errors"])
        self.assertFalse(report["env_file"]["hygiene"]["permission_safe"])
        self.assertNotIn("openai-secret", json.dumps(report))

    def test_process_environment_overrides_env_file_source(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_file = Path(temp_dir) / ".env.au-p0a"
            env_file.write_text(
                "PERPLEXITY_API_KEY=file-key\nOPENAI_API_KEY=file-key\nDATABASE_URL=file-db\n",
                encoding="utf-8",
            )
            report = build_au_p0a_env_report(
                runbook_path=runbook_path,
                env_file_path=env_file,
                env={"OPENAI_API_KEY": "process-openai"},
                generated_at="2026-06-11T00:00:00Z",
            )

        checks = {check["name"]: check for check in report["required"]}
        self.assertEqual(checks["OPENAI_API_KEY"]["source"], "process")
        self.assertEqual(checks["PERPLEXITY_API_KEY"]["source"], "env_file")

    def test_cli_writes_report_without_hard_gate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            output_path = Path(temp_dir) / "env-report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_env_report.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--env-file",
                    str(Path(temp_dir) / "missing.env"),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            written_payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(json.loads(result.stdout), written_payload)

    def test_cli_require_ready_environment_exits_nonzero(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_env_report.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--env-file",
                    str(Path(temp_dir) / "missing.env"),
                    "--output-path",
                    str(Path(temp_dir) / "env-report.json"),
                    "--require-ready-environment",
                    "--generated-at",
                    "2026-06-11T00:00:00Z",
                ],
                capture_output=True,
                check=False,
                text=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
