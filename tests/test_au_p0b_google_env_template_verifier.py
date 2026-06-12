from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.verify_au_p0b_google_env_template import (
    TEMPLATE_VERIFIER_VERSION,
    compute_template_verification_hash,
    verify_au_p0b_google_env_template,
)


class AuP0bGoogleEnvTemplateVerifierTest(unittest.TestCase):
    def test_checked_in_template_passes_without_leaking_values(self) -> None:
        result = verify_au_p0b_google_env_template(
            template_path=Path(".env.au-p0b-google.example"),
            generated_at="2026-06-12T00:00:00Z",
        )

        self.assertEqual(result["template_verifier_version"], TEMPLATE_VERIFIER_VERSION)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["summary"]["google_playwright_default_disabled"])
        self.assertTrue(result["summary"]["runtime_values_empty"])
        self.assertEqual(result["summary"]["failed_check_count"], 0)
        self.assertEqual(result["template_verification_hash"], compute_template_verification_hash(result))
        serialized = json.dumps(result)
        self.assertNotIn("#prompt", serialized)
        self.assertNotIn("postgresql://user", serialized)

    def test_enabled_google_playwright_template_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env.au-p0b-google.example"
            path.write_text(
                _minimal_template(
                    {
                        "GOOGLE_PLAYWRIGHT_ENABLED": "1",
                    }
                ),
                encoding="utf-8",
            )
            result = verify_au_p0b_google_env_template(template_path=path, generated_at="2026-06-12T00:00:00Z")

        self.assertEqual(result["status"], "fail")
        self.assertIn("google_playwright_must_default_disabled", result["errors"])

    def test_selector_secret_and_database_in_template_fail_without_leaking_value(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env.au-p0b-google.example"
            path.write_text(
                _minimal_template(
                    {
                        "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR": "#prompt",
                        "DATABASE_URL": "postgresql://user:pass@example.test/db",
                    }
                ),
                encoding="utf-8",
            )
            result = verify_au_p0b_google_env_template(template_path=path, generated_at="2026-06-12T00:00:00Z")

        serialized = json.dumps(result)
        self.assertEqual(result["status"], "fail")
        self.assertIn("template_runtime_value_must_be_empty:GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR", result["errors"])
        self.assertIn("template_runtime_value_must_be_empty:DATABASE_URL", result["errors"])
        self.assertIn("forbidden_secret_like_template_value:DATABASE_URL:postgresql://user:pass@", result["errors"])
        self.assertNotIn("#prompt", serialized)
        self.assertNotIn("example.test/db", serialized)

    def test_missing_output_path_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env.au-p0b-google.example"
            template = _minimal_template({})
            template = template.replace("GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH=docs/runtime_preflight/au-p0b-google-spike-status-latest.json\n", "")
            path.write_text(template, encoding="utf-8")
            result = verify_au_p0b_google_env_template(template_path=path, generated_at="2026-06-12T00:00:00Z")

        self.assertEqual(result["status"], "fail")
        self.assertIn("template_key_missing:GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH", result["errors"])

    def test_cli_reads_template(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/verify_au_p0b_google_env_template.py",
                ".env.au-p0b-google.example",
                "--generated-at",
                "2026-06-12T00:00:00Z",
            ],
            capture_output=True,
            check=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["template_verification_hash"], compute_template_verification_hash(payload))


def _minimal_template(overrides: dict[str, str]) -> str:
    values = {
        "GOOGLE_PLAYWRIGHT_ENABLED": "0",
        "GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR": "",
        "GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR": "",
        "GOOGLE_PLAYWRIGHT_SUBMIT_SELECTOR": "",
        "GOOGLE_PLAYWRIGHT_CITATION_SELECTOR": "",
        "GOOGLE_AIO_PLAYWRIGHT_PROMPT_SELECTOR": "",
        "GOOGLE_AIO_PLAYWRIGHT_ANSWER_SELECTOR": "",
        "GOOGLE_AI_MODE_PLAYWRIGHT_PROMPT_SELECTOR": "",
        "GOOGLE_AI_MODE_PLAYWRIGHT_ANSWER_SELECTOR": "",
        "GOOGLE_PLAYWRIGHT_STORAGE_STATE": "",
        "GOOGLE_AIO_PLAYWRIGHT_START_URL": "",
        "GOOGLE_AI_MODE_PLAYWRIGHT_START_URL": "",
        "GOOGLE_PLAYWRIGHT_BROWSER_NAME": "chromium",
        "GOOGLE_PLAYWRIGHT_TIMEOUT_SECONDS": "45",
        "GOOGLE_PLAYWRIGHT_VENDOR_COST": "",
        "MANUAL_BACKFILL_PATH": "",
        "DATABASE_URL": "",
        "SERP_API_KEY": "",
        "SERP_API_ENDPOINT": "",
        "SERP_API_ENGINE": "google_ai_overview",
        "SERP_API_GL": "au",
        "SERP_API_HL": "en",
        "SERP_API_LOCATION": "Australia",
        "SERP_API_VENDOR_COST": "",
        "GENO_BROWSER_ARTIFACT_DIR": "",
        "OBJECT_STORE_ENDPOINT": "",
        "OBJECT_STORE_BUCKET": "",
        "OBJECT_STORE_ACCESS_KEY": "",
        "OBJECT_STORE_SECRET_KEY": "",
        "GENO_AU_P0B_GOOGLE_ENV_FILE": ".env.au-p0b-google",
        "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": "docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json",
        "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": "docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json",
        "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": "docs/runtime_preflight/au-p0b-google-playwright-env-latest.json",
        "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_SMOKE_OUTPUT_PATH": "docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json",
        "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_TEMPLATE_PATH": "docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl",
        "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_TEMPLATE_MANIFEST_PATH": "docs/runtime_preflight/au-p0b-google-manual-backfill-template-manifest.json",
        "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_VERIFICATION_PATH": "docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json",
        "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": "docs/runtime_preflight/au-p0b-google-spike-status-latest.json",
    }
    values.update(overrides)
    return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


if __name__ == "__main__":
    unittest.main()
