from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from geo_core.audit import hash_payload
from geo_core.models import MarketProfile, RawCollectResult
from scripts.run_au_p0b_google_playwright_smoke import (
    SMOKE_VERSION,
    compute_smoke_payload_hash,
    run_google_playwright_smoke,
    write_smoke_payload,
)
from scripts.verify_au_p0b_google_playwright_smoke import verify_google_playwright_smoke


class FakeReadyGoogleAIOCollector:
    vendor_cost = 0.004

    def id(self) -> str:
        return "google_aio.playwright"

    def capabilities(self) -> dict[str, object]:
        return {
            "platform": "google",
            "surface": "google_aio",
            "supports_geo": True,
            "supports_citation": True,
            "supports_screenshot": True,
            "supports_html_snapshot": True,
            "access_method": "browser",
        }

    def health(self) -> str:
        return "ready"

    def collect(
        self,
        *,
        prompt: str,
        market: MarketProfile,
        city: str,
        language: str,
        device: str,
    ) -> RawCollectResult:
        html_hash = hash_payload({"html": "<html><body>Koala answer</body></html>"})
        screenshot_hash = hash_payload({"png": "fake-screenshot"})
        return RawCollectResult(
            answer_present=True,
            surface_triggered=True,
            answer_text="Koala is visible in this Google AI Overview smoke capture.",
            citations=[
                {
                    "url": "https://koala.com/en-au",
                    "domain": "koala.com",
                    "position": 1,
                    "source_type": "brand_official",
                }
            ],
            screenshot_url="geo-browser-screenshot://google_aio.playwright/fake.png",
            html_snapshot_url="geo-browser-snapshot://google_aio.playwright/fake.html",
            raw_payload={
                "prompt": prompt,
                "market_code": market.market_code,
                "city": city,
                "language": language,
                "device": device,
                "platform": "google",
                "surface": "google_aio",
                "collector_backend_id": self.id(),
                "_geo_browser_capture": {
                    "capture_type": "google_browser_ui",
                    "start_url": "https://www.google.com/search?udm=14",
                    "final_url": "https://www.google.com/search?q=koala",
                    "page_title": "Google",
                    "html_snapshot_hash": html_hash,
                    "screenshot_hash": screenshot_hash,
                    "citation_count": 1,
                },
            },
            model_or_surface="google-aio-browser",
            account_state="browser_default",
            collector_version="google-playwright-browser-v1",
            evidence_asset_hashes={
                "html_snapshot": html_hash,
                "screenshot": screenshot_hash,
            },
        )


class FakeUnreadyGoogleAIOCollector(FakeReadyGoogleAIOCollector):
    def health(self) -> str:
        return "selector_missing"

    def collect(self, **kwargs: Any) -> RawCollectResult:
        raise AssertionError("collect should not be called when collector health is not ready")


class GooglePlaywrightSmokeTest(unittest.TestCase):
    def test_runner_collects_one_auditable_record(self) -> None:
        payload = run_google_playwright_smoke(
            collector=FakeReadyGoogleAIOCollector(),
            generated_at="2026-06-12T00:00:00Z",
        )

        self.assertEqual(payload["smoke_version"], SMOKE_VERSION)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["phase"], "collection_completed")
        self.assertEqual(payload["planned_runs"], 1)
        self.assertEqual(payload["record_count"], 1)
        self.assertTrue(payload["answer_present"])
        self.assertTrue(payload["surface_triggered"])
        self.assertEqual(payload["collector_backend_id"], "google_aio.playwright")
        self.assertEqual(payload["collector_version"], "google-playwright-browser-v1")
        self.assertEqual(payload["smoke_payload_hash"], compute_smoke_payload_hash(payload))
        self.assertEqual(
            payload["evidence"]["raw_answer"]["raw_payload"]["_geo_browser_capture"]["capture_type"],
            "google_browser_ui",
        )
        self.assertIn("html_snapshot", payload["evidence_asset_hashes"])
        self.assertIn("screenshot", payload["evidence_asset_hashes"])
        self.assertTrue(
            any(
                event["event_type"] == "answer_run_collected"
                for event in payload["evidence"]["audit_events"]
            )
        )

        verification = verify_google_playwright_smoke(payload, require_success=True)
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(verification["hash_valid"])
        self.assertTrue(verification["smoke_success"])

    def test_runner_records_health_failure_without_collection(self) -> None:
        payload = run_google_playwright_smoke(
            collector=FakeUnreadyGoogleAIOCollector(),
            generated_at="2026-06-12T00:00:00Z",
        )

        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["phase"], "collector_health")
        self.assertEqual(payload["collector_health"], "selector_missing")
        self.assertEqual(payload["record_count"], 0)
        self.assertEqual(payload["errors"], ["collector_health:selector_missing"])
        self.assertEqual(payload["smoke_payload_hash"], compute_smoke_payload_hash(payload))

        audit_verification = verify_google_playwright_smoke(payload)
        self.assertEqual(audit_verification["status"], "pass")
        strict_verification = verify_google_playwright_smoke(payload, require_success=True)
        self.assertEqual(strict_verification["status"], "fail")
        self.assertIn("smoke_not_successful", strict_verification["errors"])

    def test_verifier_fails_when_hash_is_tampered(self) -> None:
        payload = run_google_playwright_smoke(
            collector=FakeReadyGoogleAIOCollector(),
            generated_at="2026-06-12T00:00:00Z",
        )
        payload["asset_count"] = 0

        result = verify_google_playwright_smoke(payload, require_success=True)

        self.assertEqual(result["status"], "fail")
        self.assertIn("smoke_payload_hash_mismatch", result["errors"])

    def test_verifier_cli_reads_payload_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "smoke.json"
            payload = run_google_playwright_smoke(
                collector=FakeReadyGoogleAIOCollector(),
                generated_at="2026-06-12T00:00:00Z",
            )
            write_smoke_payload(payload, path)
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_au_p0b_google_playwright_smoke.py",
                    str(path),
                    "--require-success",
                ],
                capture_output=True,
                check=True,
                text=True,
            )

        verification = json.loads(result.stdout)
        self.assertEqual(verification["status"], "pass")
        self.assertTrue(verification["smoke_success"])


if __name__ == "__main__":
    unittest.main()
