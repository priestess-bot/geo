from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.bootstrap_au_p0b_google_env_file import (
    BOOTSTRAP_VERSION,
    bootstrap_au_p0b_google_env_file,
    compute_env_file_bootstrap_hash,
)
from scripts.verify_au_p0b_google_env_file_bootstrap import verify_au_p0b_google_env_file_bootstrap


class AuP0bGoogleEnvFileBootstrapTest(unittest.TestCase):
    def test_bootstrap_creates_gitignored_0600_env_file_without_secret_leak(self) -> None:
        with TemporaryDirectory(dir=".") as temp_dir:
            env_file = Path(temp_dir) / ".env.au-p0b-google"
            output_path = Path(temp_dir) / "bootstrap.json"
            report = bootstrap_au_p0b_google_env_file(
                template_path=Path(".env.au-p0b-google.example"),
                env_file_path=env_file,
                output_path=output_path,
                generated_at="2026-06-14T00:00:00Z",
            )
            verification = verify_au_p0b_google_env_file_bootstrap(report, require_ready=True)

        self.assertEqual(report["env_file_bootstrap_version"], BOOTSTRAP_VERSION)
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["env_file_bootstrap_ready"])
        self.assertEqual(report["action"], "created_env_file_from_template")
        self.assertTrue(report["env_file"]["exists"])
        self.assertTrue(report["env_file"]["created"])
        self.assertEqual(report["env_file"]["hygiene"]["file_mode"], "0600")
        self.assertTrue(report["env_file"]["hygiene"]["permission_safe"])
        self.assertTrue(report["env_file"]["hygiene"]["git_ignored"])
        self.assertFalse(report["env_file"]["hygiene"]["git_tracked"])
        self.assertEqual(report["summary"]["next_action"], "fill_google_selectors_session_manual_path_and_database_url")
        self.assertIn("make verify-au-p0b-google-env-bootstrap", report["verification_commands"])
        self.assertIn("make au-p0b-google-playwright-env", report["next_commands"])
        self.assertEqual(report["env_file_bootstrap_hash"], compute_env_file_bootstrap_hash(report))
        self.assertEqual(verification["status"], "pass")
        serialized = json.dumps(report)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("postgresql://", serialized)
        self.assertNotIn("AIza", serialized)

    def test_bootstrap_does_not_overwrite_existing_env_file_by_default(self) -> None:
        with TemporaryDirectory(dir=".") as temp_dir:
            env_file = Path(temp_dir) / ".env.au-p0b-google"
            env_file.write_text("GOOGLE_PLAYWRIGHT_ENABLED=1\n", encoding="utf-8")
            env_file.chmod(0o600)
            report = bootstrap_au_p0b_google_env_file(
                template_path=Path(".env.au-p0b-google.example"),
                env_file_path=env_file,
                output_path=Path(temp_dir) / "bootstrap.json",
                generated_at="2026-06-14T00:00:00Z",
            )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["action"], "noop_existing_env_file")
        self.assertFalse(report["env_file"]["created"])
        self.assertFalse(report["env_file"]["overwritten"])
        self.assertNotIn("GOOGLE_PLAYWRIGHT_ENABLED=1", json.dumps(report))

    def test_bootstrap_fails_when_template_verifier_fails(self) -> None:
        with TemporaryDirectory(dir=".") as temp_dir:
            template = Path(temp_dir) / ".env.au-p0b-google.example"
            env_file = Path(temp_dir) / ".env.au-p0b-google"
            template.write_text("GOOGLE_PLAYWRIGHT_ENABLED=1\nDATABASE_URL=postgresql://user:pass@localhost/db\n", encoding="utf-8")
            report = bootstrap_au_p0b_google_env_file(
                template_path=template,
                env_file_path=env_file,
                output_path=Path(temp_dir) / "bootstrap.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            verification = verify_au_p0b_google_env_file_bootstrap(report)

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["action"], "blocked_template_verification")
        self.assertIn("template_verifier_not_pass", report["errors"])
        self.assertEqual(verification["status"], "fail")
        self.assertIn("template_verifier_not_pass", verification["errors"])
        self.assertFalse(env_file.exists())

    def test_verifier_detects_tampered_summary_even_when_hash_recomputed(self) -> None:
        with TemporaryDirectory(dir=".") as temp_dir:
            env_file = Path(temp_dir) / ".env.au-p0b-google"
            report = bootstrap_au_p0b_google_env_file(
                template_path=Path(".env.au-p0b-google.example"),
                env_file_path=env_file,
                output_path=Path(temp_dir) / "bootstrap.json",
                generated_at="2026-06-14T00:00:00Z",
            )
            report["summary"]["env_file_hygiene_ready"] = False
            report["env_file_bootstrap_hash"] = compute_env_file_bootstrap_hash(report)
            verification = verify_au_p0b_google_env_file_bootstrap(report)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("summary_env_file_hygiene_ready_mismatch", verification["errors"])

    def test_cli_writes_bootstrap_json(self) -> None:
        with TemporaryDirectory(dir=".") as temp_dir:
            env_file = Path(temp_dir) / ".env.au-p0b-google"
            output_path = Path(temp_dir) / "bootstrap.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/bootstrap_au_p0b_google_env_file.py",
                    "--template-path",
                    ".env.au-p0b-google.example",
                    "--env-file",
                    str(env_file),
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-14T00:00:00Z",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIn("au_p0b_google_env_file_bootstrap_v1", result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(verify_au_p0b_google_env_file_bootstrap(payload, require_ready=True)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
