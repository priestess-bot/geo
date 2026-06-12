from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from geno_core.market import build_au_broader_platform_registry, build_au_market_profile
from scripts.build_au_broader_platform_registry import (
    build_au_broader_platform_registry as build_registry_payload,
    compute_broader_platform_registry_hash,
)
from scripts.verify_au_broader_platform_registry import verify_au_broader_platform_registry


class AuBroaderPlatformRegistryTest(unittest.TestCase):
    def test_market_profile_registers_broader_candidates_without_enabling_them(self) -> None:
        profile = build_au_market_profile()
        surfaces = {f"{item.platform}:{item.surface}": item for item in profile.platforms}

        self.assertEqual(surfaces["chatgpt:chatgpt_search"].build_stage, "P0a")
        self.assertTrue(surfaces["chatgpt:chatgpt_search"].enabled)
        self.assertEqual(surfaces["google:google_aio"].build_stage, "P0b")
        self.assertFalse(surfaces["google:google_aio"].enabled)
        for key in (
            "gemini:gemini_search",
            "bing_copilot:copilot_search",
            "claude:claude_search",
            "youtube:youtube_search",
            "reddit:reddit_search",
            "productreview:productreview_reviews",
        ):
            self.assertIn(key, surfaces)
            self.assertFalse(surfaces[key].enabled)
            self.assertEqual(surfaces[key].weight, 0.0)

    def test_registry_payload_is_auditable_and_keeps_p0a_scope_stable(self) -> None:
        registry = build_registry_payload(generated_at="2026-06-12T00:00:00Z")
        verification = verify_au_broader_platform_registry(registry)

        self.assertEqual(verification["status"], "pass")
        self.assertEqual(registry["registry_version"], "au_broader_platform_registry_v1")
        self.assertTrue(registry["broader_platform_registry_ready"])
        self.assertEqual(registry["summary"]["candidate_count"], 6)
        self.assertEqual(registry["summary"]["enabled_candidate_count"], 0)
        self.assertEqual(
            set(registry["summary"]["p0a_enabled_platform_surfaces"]),
            {"chatgpt:chatgpt_search", "perplexity:sonar"},
        )
        self.assertEqual(registry["summary"]["stage_counts"], {"P1": 3, "P2": 3})
        self.assertEqual(registry["candidate_platforms"][0]["id"], "gemini_ai_search")
        self.assertEqual(registry["candidate_platforms"][-1]["id"], "productreview_au_reviews")
        self.assertEqual(registry["broader_platform_registry_hash"], compute_broader_platform_registry_hash(registry))

    def test_verifier_detects_scope_drift(self) -> None:
        registry = build_au_broader_platform_registry()
        registry["candidate_platforms"][0]["enabled"] = True
        registry["broader_platform_registry_hash"] = compute_broader_platform_registry_hash(registry)

        verification = verify_au_broader_platform_registry(registry)

        self.assertEqual(verification["status"], "fail")
        self.assertIn("candidate_must_be_disabled:gemini_ai_search", verification["errors"])

    def test_cli_writes_and_verifies_registry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "registry.json"
            build_result = subprocess.run(
                [
                    "python3",
                    "scripts/build_au_broader_platform_registry.py",
                    "--output-path",
                    str(output_path),
                    "--generated-at",
                    "2026-06-12T00:00:00Z",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            verify_result = subprocess.run(
                ["python3", "scripts/verify_au_broader_platform_registry.py", str(output_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        payload = json.loads(build_result.stdout)
        verifier = json.loads(verify_result.stdout)
        self.assertEqual(payload["summary"]["candidate_count"], 6)
        self.assertEqual(verifier["status"], "pass")
        self.assertTrue(verifier["hash_valid"])


if __name__ == "__main__":
    unittest.main()
