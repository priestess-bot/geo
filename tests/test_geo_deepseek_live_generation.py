"""Opt-in paid-provider test through the stable asynchronous placement chain."""

from __future__ import annotations

import json
import os
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise AssertionError(f"{name} is required for the live DeepSeek test")
    return value


def _json_request(url: str, *, headers: dict[str, str], payload: dict | None = None) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            **headers,
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=30) as response:  # nosec B310 - configured test API.
            return json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise AssertionError(f"live GEO request failed with HTTP {exc.code}: {detail}") from exc


class GeoDeepSeekLiveGenerationTest(unittest.TestCase):
    def test_stable_job_worker_package_and_claim_lineage(self) -> None:
        if os.environ.get("GEO_RUN_LIVE_DEEPSEEK_TEST") != "1":
            self.skipTest("set GEO_RUN_LIVE_DEEPSEEK_TEST=1 to execute a paid provider call")
        api_url = os.environ.get("GEO_LIVE_API_URL", "http://localhost:8000").rstrip("/")
        project_id = _required("GEO_LIVE_PROJECT_ID")
        prompt_bundle_id = _required("GEO_LIVE_PROMPT_BUNDLE_ID")
        opportunity_id = _required("GEO_LIVE_OPPORTUNITY_ID")
        headers = {
            "X-GEO-Actor-ID": _required("GEO_LIVE_IDENTITY_ID"),
            "X-GEO-Tenant-ID": _required("GEO_LIVE_TENANT_ID"),
            "Idempotency-Key": f"deepseek-live-{uuid4()}",
        }
        accepted = _json_request(
            f"{api_url}/v1/projects/{project_id}/geo/prompt-bundles/"
            f"{prompt_bundle_id}/generation-jobs",
            headers=headers,
            payload={"configured_model": "deepseek-v4-flash", "model_call_budget": 2},
        )
        job_id = accepted["job_id"]
        terminal = None
        for _ in range(90):
            terminal = _json_request(f"{api_url}/v1/jobs/{job_id}", headers=headers)
            if terminal["status"] in {"succeeded", "failed", "dead_lettered", "cancelled"}:
                break
            time.sleep(2)
        self.assertIsNotNone(terminal)
        self.assertEqual(terminal["status"], "succeeded")
        details = terminal["result_details"]
        self.assertEqual(details["configured_model"], "deepseek-v4-flash")
        self.assertTrue(details["provider_reported_model"])
        self.assertEqual(len(details["response_hash"]), 64)
        self.assertEqual(len(details["prompt_bundle_hash"]), 64)

        versions = _json_request(
            f"{api_url}/v1/projects/{project_id}/geo/opportunities/"
            f"{opportunity_id}/package-versions",
            headers=headers,
        )
        generated = next(item for item in versions if item["generated_by_job_id"] == job_id)
        detail = _json_request(
            f"{api_url}/v1/projects/{project_id}/geo/package-versions/{generated['id']}",
            headers=headers,
        )
        claims = _json_request(
            f"{api_url}/v1/projects/{project_id}/geo/package-versions/" f"{generated['id']}/claims",
            headers=headers,
        )
        self.assertTrue(detail["rendered_text"].strip())
        self.assertEqual(len(detail["content_hash"]), 64)
        self.assertIsInstance(claims, list)
