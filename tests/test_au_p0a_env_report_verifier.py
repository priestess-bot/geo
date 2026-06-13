from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_au_p0a_env_report import build_au_p0a_env_report, compute_env_report_hash
from scripts.build_au_p0a_runbook import build_au_p0a_runbook
from scripts.verify_au_p0a_env_report import verify_au_p0a_env_report


class AuP0aEnvReportVerifierTest(unittest.TestCase):
    def _report(self, temp_dir: str, *, ready: bool) -> dict[str, object]:
        runbook = build_au_p0a_runbook(
            artifact_dir=str(Path(temp_dir) / "runtime"),
            generated_at="2026-06-11T00:00:00Z",
        )
        runbook_path = Path(temp_dir) / "runbook.json"
        runbook_path.write_text(json.dumps(runbook), encoding="utf-8")
        env = (
            {
                "PERPLEXITY_API_KEY": "perplexity-secret",
                "OPENAI_API_KEY": "openai-secret",
                "DATABASE_URL": "postgresql://user:pass@example.test/db",
            }
            if ready
            else {}
        )
        return build_au_p0a_env_report(
            runbook_path=runbook_path,
            env_file_path=Path(temp_dir) / "missing.env",
            env=env,
            generated_at="2026-06-11T00:00:00Z",
        )

    def test_ready_report_passes_hard_gate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._report(temp_dir, ready=True)
            result = verify_au_p0a_env_report(report, require_ready_environment=True)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["hash_valid"])
        self.assertTrue(result["ready_for_real_batch"])

    def test_hash_mismatch_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._report(temp_dir, ready=True)
            report["next_action"] = "tampered"
            result = verify_au_p0a_env_report(report)

        self.assertEqual(result["status"], "fail")
        self.assertIn("environment_report_hash_mismatch", result["errors"])
        self.assertIn("next_action_mismatch", result["errors"])

    def test_raw_secret_field_fails_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._report(temp_dir, ready=True)
            report["required"][0]["value"] = "leaked"  # type: ignore[index]
            report["environment_report_hash"] = compute_env_report_hash(report)
            result = verify_au_p0a_env_report(report)

        self.assertEqual(result["status"], "fail")
        self.assertIn("required_check_raw_value_leaked:PERPLEXITY_API_KEY", result["errors"])

    def test_hygiene_error_fails_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._report(temp_dir, ready=True)
            report["env_file"]["hygiene"]["errors"] = ["env_file_permissions_not_0600"]  # type: ignore[index]
            report["env_file"]["hygiene"]["hygiene_ready"] = False  # type: ignore[index]
            report["environment_report_hash"] = compute_env_report_hash(report)
            result = verify_au_p0a_env_report(report)

        self.assertEqual(result["status"], "fail")
        self.assertIn("ready_for_real_batch_mismatch", result["errors"])
        self.assertEqual(result["env_file_hygiene_errors"], ["env_file_permissions_not_0600"])

    def test_require_ready_environment_fails_incomplete_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = self._report(temp_dir, ready=False)
            result = verify_au_p0a_env_report(report, require_ready_environment=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("environment_not_ready", result["errors"])

    def test_cli_reads_env_report_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "env-report.json"
            path.write_text(json.dumps(self._report(temp_dir, ready=True)), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/verify_au_p0a_env_report.py", str(path)],
                capture_output=True,
                check=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["hash_valid"])


if __name__ == "__main__":
    unittest.main()
