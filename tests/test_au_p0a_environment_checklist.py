from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_environment_checklist import (
    CHECKLIST_VERSION,
    build_au_p0a_environment_checklist,
    compute_environment_checklist_hash,
)
from scripts.build_au_p0a_env_report import build_au_p0a_env_report
from scripts.build_au_p0a_runbook import build_au_p0a_runbook
from scripts.verify_au_p0a_environment_checklist import verify_au_p0a_environment_checklist


class AuP0aEnvironmentChecklistTest(unittest.TestCase):
    def _write_runbook(self, temp_dir: str) -> Path:
        runbook = build_au_p0a_runbook(
            artifact_dir=str(Path(temp_dir) / "runtime"),
            generated_at="2026-06-12T00:00:00Z",
        )
        runbook_path = Path(temp_dir) / "runbook.json"
        runbook_path.write_text(json.dumps(runbook), encoding="utf-8")
        return runbook_path

    def _write_env_report(self, temp_dir: str, runbook_path: Path, *, ready: bool) -> Path:
        env = (
            {
                "PERPLEXITY_API_KEY": "perplexity-key",
                "OPENAI_API_KEY": "openai-key",
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
            }
            if ready
            else {}
        )
        env_path = Path(temp_dir) / "env-report.json"
        report = build_au_p0a_env_report(
            runbook_path=runbook_path,
            env_file_path=Path(temp_dir) / "missing.env",
            output_path=env_path,
            env=env,
            generated_at="2026-06-12T00:00:00Z",
        )
        env_path.write_text(json.dumps(report), encoding="utf-8")
        return env_path

    def test_checklist_records_missing_required_environment_without_secret_leak(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_path = self._write_env_report(temp_dir, runbook_path, ready=False)
            checklist = build_au_p0a_environment_checklist(
                runbook_path=runbook_path,
                environment_path=env_path,
                status_path=Path(temp_dir) / "missing-status.json",
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0a_environment_checklist(checklist)

        self.assertEqual(checklist["environment_checklist_version"], CHECKLIST_VERSION)
        self.assertEqual(checklist["status"], "fail")
        self.assertFalse(checklist["environment_checklist_ready"])
        self.assertEqual(checklist["next_action"], "populate_required_environment")
        self.assertEqual(checklist["summary"]["missing_required_count"], 3)
        self.assertIn("PERPLEXITY_API_KEY", checklist["summary"]["missing_required"])
        self.assertIn("hard_env_gate", {command["id"] for command in checklist["verification_commands"]})
        self.assertEqual(checklist["environment_checklist_hash"], compute_environment_checklist_hash(checklist))
        self.assertEqual(verification["status"], "pass")
        self.assertEqual(verification["environment_checklist_ready"], False)
        self.assertNotIn("perplexity-key", json.dumps(checklist))

    def test_checklist_passes_when_required_environment_is_present(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_path = self._write_env_report(temp_dir, runbook_path, ready=True)
            checklist = build_au_p0a_environment_checklist(
                runbook_path=runbook_path,
                environment_path=env_path,
                status_path=Path(temp_dir) / "missing-status.json",
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-12T00:00:00Z",
            )
            verification = verify_au_p0a_environment_checklist(checklist, require_ready_environment=True)

        self.assertEqual(checklist["status"], "pass")
        self.assertTrue(checklist["environment_checklist_ready"])
        self.assertEqual(checklist["summary"]["missing_required_count"], 0)
        self.assertEqual(checklist["next_action"], "run_au_p0a_runbook_dry_run")
        self.assertEqual(verification["status"], "pass")
        for task in checklist["required_environment"]:
            self.assertTrue(task["secret_redacted"])
            self.assertNotIn("value", task)

    def test_verifier_detects_hash_and_summary_tampering(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_path = self._write_env_report(temp_dir, runbook_path, ready=False)
            checklist = build_au_p0a_environment_checklist(
                runbook_path=runbook_path,
                environment_path=env_path,
                status_path=Path(temp_dir) / "missing-status.json",
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-12T00:00:00Z",
            )
            checklist["summary"]["missing_required_count"] = 0  # type: ignore[index]
            verification = verify_au_p0a_environment_checklist(checklist)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("environment_checklist_hash_mismatch", verification["errors"])
        self.assertIn("summary_missing_required_count_mismatch", verification["errors"])

    def test_verifier_rejects_forbidden_secret_fields_anywhere(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_path = self._write_env_report(temp_dir, runbook_path, ready=False)
            checklist = build_au_p0a_environment_checklist(
                runbook_path=runbook_path,
                environment_path=env_path,
                status_path=Path(temp_dir) / "missing-status.json",
                env_file_path=Path(temp_dir) / "missing.env",
                generated_at="2026-06-12T00:00:00Z",
            )
            checklist["environment_report"]["raw_value"] = "secret"  # type: ignore[index]
            checklist["environment_checklist_hash"] = compute_environment_checklist_hash(checklist)
            verification = verify_au_p0a_environment_checklist(checklist)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("forbidden_secret_field:$.environment_report.raw_value", verification["errors"])

    def test_cli_writes_and_verifies_checklist(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runbook_path = self._write_runbook(temp_dir)
            env_path = self._write_env_report(temp_dir, runbook_path, ready=False)
            output_path = Path(temp_dir) / "checklist.json"
            build_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/build_au_p0a_environment_checklist.py",
                    "--runbook-path",
                    str(runbook_path),
                    "--environment-path",
                    str(env_path),
                    "--status-path",
                    str(Path(temp_dir) / "missing-status.json"),
                    "--env-file",
                    str(Path(temp_dir) / "missing.env"),
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
                [sys.executable, "scripts/verify_au_p0a_environment_checklist.py", str(output_path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(build_result.stdout)
        verifier_payload = json.loads(verify_result.stdout)
        self.assertEqual(payload["environment_checklist_hash"], compute_environment_checklist_hash(payload))
        self.assertEqual(verifier_payload["status"], "pass")
        self.assertEqual(verifier_payload["next_action"], "populate_required_environment")


if __name__ == "__main__":
    unittest.main()
