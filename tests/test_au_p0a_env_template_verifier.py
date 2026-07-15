from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.verify_au_p0a_env_template import (
    TEMPLATE_VERIFIER_VERSION,
    compute_template_verification_hash,
    verify_au_p0a_env_template,
)


class AuP0aEnvTemplateVerifierTest(unittest.TestCase):
    def test_checked_in_template_passes_without_leaking_values(self) -> None:
        result = verify_au_p0a_env_template(
            template_path=Path(".env.au-p0a.example"),
            generated_at="2026-06-12T00:00:00Z",
        )

        self.assertEqual(result["template_verifier_version"], TEMPLATE_VERIFIER_VERSION)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["summary"]["required_present_count"], 3)
        self.assertTrue(result["summary"]["provider_keys_empty"])
        self.assertTrue(result["summary"]["database_url_local_placeholder"])
        self.assertEqual(result["template_verification_hash"], compute_template_verification_hash(result))
        serialized = json.dumps(result)
        self.assertNotIn("geo_runtime_app:geo_runtime_app", serialized)
        self.assertNotIn("minio123", serialized)

    def test_provider_secret_in_template_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env.au-p0a.example"
            path.write_text(
                "\n".join(
                    [
                        "PERPLEXITY_API_KEY=pplx-secret",
                        "OPENAI_API_KEY=",
                        "DATABASE_URL=postgresql://geo_runtime_app:geo_runtime_app@localhost:5432/geo",
                        "OBJECT_STORE_ENDPOINT=http://localhost:9000",
                        "OBJECT_STORE_BUCKET=geo-reports",
                        "OBJECT_STORE_ACCESS_KEY=minio",
                        "OBJECT_STORE_SECRET_KEY=minio123",
                        "OBJECT_STORE_REGION=us-east-1",
                        "GEO_AU_P0A_ENV_OUTPUT_PATH=docs/runtime_preflight/au-p0a-env-latest.json",
                        "GEO_AU_P0A_RUNBOOK_OUTPUT_PATH=docs/runtime_preflight/au-p0a-runbook-latest.json",
                        "GEO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH=docs/runtime_preflight/au-p0a-runbook-execution-latest.json",
                        "GEO_AU_P0A_READINESS_OUTPUT_PATH=docs/runtime_preflight/au-p0a-readiness-latest.json",
                        "GEO_AU_P0A_PACKAGE_OUTPUT_PATH=docs/runtime_preflight/au-p0a-evidence-package-latest.json",
                        "GEO_AU_P0A_STATUS_OUTPUT_PATH=docs/runtime_preflight/au-p0a-status-latest.json",
                    ]
                ),
                encoding="utf-8",
            )
            result = verify_au_p0a_env_template(template_path=path, generated_at="2026-06-12T00:00:00Z")

        self.assertEqual(result["status"], "fail")
        self.assertIn("template_provider_secret_must_be_empty:PERPLEXITY_API_KEY", result["errors"])
        self.assertIn("forbidden_secret_like_template_value:PERPLEXITY_API_KEY:pplx-", result["errors"])
        self.assertNotIn("pplx-secret", json.dumps(result))

    def test_missing_output_path_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env.au-p0a.example"
            path.write_text(
                "\n".join(
                    [
                        "PERPLEXITY_API_KEY=",
                        "OPENAI_API_KEY=",
                        "DATABASE_URL=postgresql://geo_runtime_app:geo_runtime_app@localhost:5432/geo",
                    ]
                ),
                encoding="utf-8",
            )
            result = verify_au_p0a_env_template(template_path=path, generated_at="2026-06-12T00:00:00Z")

        self.assertEqual(result["status"], "fail")
        self.assertIn("template_key_missing:GEO_AU_P0A_ENV_OUTPUT_PATH", result["errors"])

    def test_cli_reads_template(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/verify_au_p0a_env_template.py",
                ".env.au-p0a.example",
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


if __name__ == "__main__":
    unittest.main()
