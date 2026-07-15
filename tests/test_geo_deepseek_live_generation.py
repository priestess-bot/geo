"""Opt-in live DeepSeek verification for an approved GEO placement fixture.

This test intentionally never runs in the default suite because it consumes a
real provider call. It proves that v3 persists a real model result rather than
a local template fallback.
"""

from __future__ import annotations

import json
import os
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise AssertionError(f"{name} is required for the live DeepSeek test")
    return value


class GeoDeepSeekLiveGenerationTest(unittest.TestCase):
    def test_geo_package_is_generated_by_deepseek_when_explicitly_enabled(self) -> None:
        if os.environ.get("GEO_RUN_LIVE_DEEPSEEK_TEST") != "1":
            self.skipTest("set GEO_RUN_LIVE_DEEPSEEK_TEST=1 to execute a paid provider call")
        api_url = os.environ.get("GEO_LIVE_API_URL", "http://localhost:8000").rstrip("/")
        project_id = _required("GEO_LIVE_PROJECT_ID")
        opportunity_id = _required("GEO_LIVE_OPPORTUNITY_ID")
        prompt_version_id = _required("GEO_LIVE_PROMPT_VERSION_ID")
        actor_id = os.environ.get("GEO_LIVE_ACTOR_ID", "runtime-console")
        payload = {
            "project_id": project_id,
            "prompt_template_version_id": prompt_version_id,
            "generate_with_model": True,
            "model": "deepseek-chat",
            "title": "Live DeepSeek GEO verification package",
            "disclosure_text": "Disclosure: I am posting on behalf of the brand.",
            "evidence": [{
                "source_url": _required("GEO_LIVE_EVIDENCE_URL"),
                "text": _required("GEO_LIVE_EVIDENCE_TEXT"),
                "source_kind": "brand_authored",
                "usage_rights": "owned",
                "subject": "TerraMow V600",
                "subject_role": "primary_product",
                "public_disclosure_allowed": True,
            }],
        }
        request = Request(
            f"{api_url}/v1/geo/placement-opportunities/{opportunity_id}/packages",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-GENO-Actor-Id": actor_id},
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:  # nosec B310 - local configured API endpoint.
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise AssertionError(f"live GEO DeepSeek request failed with HTTP {exc.code}") from exc
        package = body["placement_package"]
        self.assertEqual(package["generation_model"], "deepseek-chat")
        self.assertEqual(len(package["model_response_hash"]), 64)
        self.assertTrue(package["rendered_text"].strip())
        self.assertEqual(package["status"], "draft")
