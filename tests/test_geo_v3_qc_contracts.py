from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path

try:
    import psycopg.rows  # type: ignore[import-not-found]  # noqa: F401
except ModuleNotFoundError:
    psycopg = types.ModuleType("psycopg")
    rows = types.ModuleType("psycopg.rows")
    rows.dict_row = object()
    psycopg.rows = rows
    sys.modules["psycopg"] = psycopg
    sys.modules["psycopg.rows"] = rows

from geo_core.geo_placement import GeoPlacementError, _normalize_claims, _normalize_evidence, _render_prompt


ROOT = Path(__file__).resolve().parents[1]


class GeoV3QualityContractsTest(unittest.TestCase):
    def test_prompt_bundle_rendering_uses_runtime_variables_and_fails_closed(self) -> None:
        self.assertEqual(_render_prompt("Write for {{ product_name }}", {"product_name": "TerraMow V600"}), "Write for TerraMow V600")
        with self.assertRaisesRegex(GeoPlacementError, "missing variables"):
            _render_prompt("Write for {{ product_name }} on {{ channel }}", {"product_name": "TerraMow V600"})

    def test_evidence_requires_rights_https_and_public_disclosure(self) -> None:
        valid = {"source_url": "https://example.com/product", "text": "Product identity fact", "source_kind": "brand_authored",
                 "usage_rights": "owned", "public_disclosure_allowed": True, "subject": "Product", "subject_role": "primary_product"}
        normalized = _normalize_evidence([valid], product_name="Product")
        self.assertEqual(normalized[0]["subject_role"], "primary_product")
        for key, value in (("source_url", "http://example.com"), ("usage_rights", "unknown"), ("public_disclosure_allowed", False)):
            invalid = dict(valid)
            invalid[key] = value
            with self.assertRaises(GeoPlacementError):
                _normalize_evidence([invalid], product_name="Product")

    def test_claims_without_exact_frozen_evidence_are_unsupported(self) -> None:
        evidence = [{"id": "fact-1"}]
        claims = _normalize_claims([{"text": "Supported", "evidence_ids": ["fact-1"]}, {"text": "Unsupported", "evidence_ids": ["other"]}], evidence=evidence)
        self.assertEqual([item["support_status"] for item in claims], ["supported", "unsupported"])
        with self.assertRaisesRegex(GeoPlacementError, "non-empty"):
            _normalize_claims([], evidence=evidence)

    def test_runtime_source_contains_prompt_claim_revision_and_no_publish_runner(self) -> None:
        source = (ROOT / "packages/geo_core/geo_core/geo_placement.py").read_text(encoding="utf-8")
        api = (ROOT / "apps/api/geo_api/main.py").read_text(encoding="utf-8")
        runner = (ROOT / "scripts/run_geo_v3_full_qc.py").read_text(encoding="utf-8")
        self.assertIn('template_instruction=f"{rendered_system}', source)
        self.assertIn('output_schema=dict(prompt["output_schema"])', source)
        self.assertIn("unsupported or conflicting claims", source)
        self.assertIn("def revise_package", source)
        self.assertIn('/v1/geo/placement-packages/{package_id}/versions', api)
        self.assertNotIn("/published-url", runner)
        self.assertNotIn("verify-live", runner)

    def test_latest_qc_report_covers_nine_channels_without_submission_delta(self) -> None:
        report_path = ROOT / "docs/runtime_preflight/geo-v3-full-review/20260714-full-qc-v1/content-qc-report.json"
        if not report_path.exists():
            self.skipTest("live QC report has not been generated")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(len(report["channels"]), 9)
        self.assertEqual(report["started_with_submissions"], report["finished_with_submissions"])
        self.assertEqual(sum(item["status"] == "approved" for item in report["channels"]), 6)
        self.assertEqual(sum(item["status"] == "needs_evidence" for item in report["channels"]), 3)
        self.assertEqual(sum(item.get("task_record_status") == "candidate" for item in report["channels"]), 3)
        for filename in ("channel-readiness-matrix.md", "prompt-bundle-manifest.json", "test-results.md", "final-verdict.md"):
            self.assertTrue((report_path.parent / filename).exists(), filename)


if __name__ == "__main__":
    unittest.main()
