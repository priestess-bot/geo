from __future__ import annotations

import base64
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from geno_api.main import validate_production_runtime_security
from geno_core.report import render_markdown_pdf
from geno_core.task_queue import dispatch_background_task


ROOT = Path(__file__).resolve().parents[1]


def safe_production_environment() -> dict[str, str]:
    return {
        "GENO_DEPLOYMENT_ENVIRONMENT": "production",
        "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
        "GENO_RUNTIME_AUTH_MODE": "session",
        "GENO_RUNTIME_SESSION_COOKIE_SECURE": "1",
        "GENO_AUTH_DELIVERY_MASTER_KEY": base64.urlsafe_b64encode(b"p" * 32).decode("ascii"),
        "GENO_AUTH_DELIVERY_KEY_ID": "production-test-key",
        "GENO_CONNECTOR_SECRET_MASTER_KEY": "production-test-master-key",
        "GENO_REPORT_ARTIFACT_SIGNING_SECRET": "production-test-signing-key",
        "GENO_PDF_RENDERER_URL": "http://report-pdf-renderer:8200",
        "GENO_REPORT_PDF_RENDERER_REQUIRED": "1",
        "GENO_TASK_QUEUE_ENABLED": "1",
        "GENO_TASK_QUEUE_REQUIRED": "1",
        "GENO_TASK_QUEUE_BROKER_URL": "redis://valkey:6379/0",
        "GENO_DEV_TOOLS_ENABLED": "0",
    }


class ProductionRuntimeContractsTest(unittest.TestCase):
    def test_safe_production_runtime_configuration_passes(self) -> None:
        with patch.dict(os.environ, safe_production_environment(), clear=True):
            validate_production_runtime_security()

    def test_production_requires_queue_and_chromium_renderer(self) -> None:
        environment = safe_production_environment()
        environment.pop("GENO_TASK_QUEUE_BROKER_URL")
        environment.pop("GENO_PDF_RENDERER_URL")
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "GENO_PDF_RENDERER_URL is required"):
                validate_production_runtime_security()
            with self.assertRaisesRegex(RuntimeError, "GENO_TASK_QUEUE_BROKER_URL is required"):
                dispatch_background_task("report")

    def test_pdf_renderer_cannot_fall_back_in_production(self) -> None:
        with patch.dict(
            os.environ,
            {"GENO_DEPLOYMENT_ENVIRONMENT": "production", "GENO_REPORT_PDF_RENDERER_REQUIRED": "1"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "GENO_PDF_RENDERER_URL is required"):
                render_markdown_pdf("# Production report")

    def test_local_queue_can_be_explicitly_disabled(self) -> None:
        with patch.dict(os.environ, {"GENO_TASK_QUEUE_ENABLED": "0"}, clear=True):
            receipt = dispatch_background_task("knowledge")
        self.assertEqual(receipt.status, "disabled")
        self.assertIsNone(receipt.message_id)

    def test_compose_contains_valkey_dramatiq_and_pdf_renderer(self) -> None:
        compose = (ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8")
        renderer = (ROOT / "workers/report_export_worker/pdf_renderer_api.py").read_text(encoding="utf-8")
        report = (ROOT / "packages/geno_core/geno_core/report.py").read_text(encoding="utf-8")

        self.assertIn("valkey/valkey:8.0.2-alpine", compose)
        self.assertIn("task-worker-runtime:", compose)
        self.assertIn("task-worker-knowledge:", compose)
        self.assertIn("workers.task_queue.tasks", compose)
        self.assertIn("report-pdf-renderer:", compose)
        self.assertIn("mcr.microsoft.com/playwright/python:v1.53.0-noble", (ROOT / "workers/report_export_worker/Dockerfile.renderer").read_text(encoding="utf-8"))
        self.assertIn("playwright.chromium.launch", renderer)
        self.assertIn("route.abort()", renderer)
        self.assertIn("GENO_PDF_RENDERER_URL", report)
        self.assertIn("_render_minimal_test_pdf", report)


if __name__ == "__main__":
    unittest.main()
