from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from geno_api.main import app


class ApiContractsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_m1_project_bootstrap_endpoint(self) -> None:
        response = self.client.get("/v1/project-bootstraps/au/dtc-ecommerce")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["project"]["market_code"], "AU")
        self.assertEqual(payload["industry_profile"]["industry_code"], "dtc_ecommerce")
        self.assertEqual(len(payload["competitors"]), 4)
        self.assertEqual(len(payload["prompt_questions"]), 100)
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_bootstrap_created")

    def test_m1_prompt_pack_endpoint(self) -> None:
        response = self.client.get("/v1/prompt-packs/au/dtc-ecommerce")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 100)
        self.assertEqual(payload["market_code"], "AU")
        self.assertEqual(payload["prompt_version"], "au_dtc_ecommerce_v1")

    def test_m2a_collection_plan_endpoint(self) -> None:
        response = self.client.get("/v1/collection-plans/au/p0a")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["planned_runs"], 2400)
        self.assertEqual(payload["sample_size"], 3)
        self.assertEqual(set(payload["platform_surfaces"]), {"chatgpt:chatgpt_search", "perplexity:sonar"})

    def test_m2a_fixture_evidence_slice_endpoint(self) -> None:
        response = self.client.get("/v1/evidence-runs/au/p0a-fixture-slice")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["record_count"], 8)
        first = payload["records"][0]
        self.assertTrue(first["answer_run"]["answer_present"])
        self.assertTrue(first["answer_run"]["surface_triggered"])
        self.assertEqual(len(first["citations"]), 3)
        self.assertEqual(len(first["evidence_assets"]), 2)
        self.assertGreater(first["collection_cost"]["total_cost"], 0)
        self.assertEqual(first["audit_events"][0]["event_type"], "answer_run_collected")

    def test_runtime_project_create_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post("/v1/projects/runtime/au/dtc-ecommerce")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_projects_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/projects/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_prompts_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/prompts/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_evidence_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/evidence-runs/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_evidence_filter_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/evidence-runs/runtime?platform=perplexity&city=Sydney&intent_type=brand_awareness"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_evidence_export_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/evidence-runs/runtime/export.csv?platform=perplexity&city=Sydney&intent_type=brand_awareness"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_visibility_scores_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/visibility-scores/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_citation_graphs_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/citation-graphs/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_reports_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/reports/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_artifact_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/reports/runtime/report-1/artifact?type=markdown")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_pdf_artifact_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/reports/runtime/report-1/artifact?type=pdf")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_action_plans_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/action-plans/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_content_engines_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/content-engines/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_traceability_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/traceability/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_m2b_google_spike_plan_endpoint(self) -> None:
        response = self.client.get("/v1/google-spikes/au/plan")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["planned_runs"], 240)
        self.assertEqual(payload["prompt_count"], 30)
        self.assertEqual(payload["surfaces"], ["google_aio", "google_ai_mode"])

    def test_m2b_google_spike_fixture_gate_endpoint(self) -> None:
        response = self.client.get("/v1/google-spikes/au/fixture-gate")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["record_count"], 240)
        self.assertEqual(payload["gate"]["gate_status"], "pass")
        self.assertFalse(payload["gate"]["limited_coverage"])

    def test_m3_visibility_score_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/visibility-scores/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["analysis_count"], 40)
        self.assertEqual(payload["snapshot"]["formula_version"], "au_visibility_v1")
        self.assertEqual(len(payload["contributions"]), 8)
        self.assertEqual(payload["audit_event"]["event_type"], "visibility_score_snapshot_created")

    def test_m4_citation_graph_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/citation-graphs/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["node_count"], 3)
        self.assertGreater(payload["evidence_link_count"], 0)
        self.assertGreater(payload["source_gap_count"], 0)
        self.assertEqual(payload["competitor_count"], 4)
        self.assertTrue(any(item["answer_run_ids"] for item in payload["competitor_benchmarks"]))

    def test_m5_report_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/reports/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["report_export"]["report_version"], "p0a-fixture-v1")
        self.assertTrue(payload["report_export"]["markdown_url"].endswith(".md"))
        self.assertTrue(payload["report_export"]["pdf_url"].endswith(".pdf"))
        self.assertTrue(payload["report_export"]["csv_url"].endswith(".csv"))
        self.assertIn("GENO AU Evidence Report", payload["markdown"])
        self.assertIn("answer_run_id", payload["csv_content"])
        self.assertGreater(payload["pdf_size_bytes"], 0)
        self.assertEqual(len(payload["pdf_content_hash"]), 64)
        self.assertEqual(payload["audit_event"]["event_type"], "report_export_created")
        self.assertEqual(
            payload["report_evidence_answer_run_ids"],
            payload["report_export"]["answer_run_ids"],
        )

    def test_m6_action_plan_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/action-plans/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreater(payload["action_count"], 0)
        self.assertEqual(payload["retest_schedule"]["offsets_days"], [0, 7, 14, 30])
        self.assertEqual(payload["retest_comparison"]["trend"], "improved")
        self.assertEqual(payload["audit_event"]["event_type"], "action_plan_created")
        self.assertEqual(payload["comparison_audit_event"]["event_type"], "retest_comparison_created")

    def test_m7_content_engine_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/content-engines/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreater(payload["knowledge_fact_count"], 0)
        self.assertGreater(payload["content_draft_count"], 0)
        self.assertEqual(payload["audit_event"]["event_type"], "content_engine_fixture_created")
        self.assertTrue(all(item["review_status"] == "pending_human_review" for item in payload["content_drafts"]))
        self.assertTrue(all(item["used_knowledge_fact_ids"] for item in payload["content_drafts"]))
        self.assertTrue(all(item["evidence_answer_run_ids"] for item in payload["content_drafts"]))
        self.assertEqual(len(payload["integration_connectors"]), 7)
        self.assertEqual(len(payload["manual_distribution_records"]), payload["content_draft_count"])

    def test_traceability_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/traceability/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        bundle = payload["traceability_bundle"]
        self.assertEqual(payload["answer_run_count"], 40)
        self.assertEqual(payload["score_contribution_count"], 8)
        self.assertEqual(bundle["report_export_ids"], [payload["report_export"]["id"]])
        self.assertEqual(bundle["answer_run_ids"], payload["report_export"]["answer_run_ids"])
        self.assertEqual(len(bundle["raw_answer_ids"]), payload["answer_run_count"])
        self.assertGreater(len(bundle["answer_citation_ids"]), 0)
        self.assertGreater(len(bundle["evidence_asset_ids"]), 0)
        self.assertTrue(any(link["relation_type"] == "explained_by" for link in bundle["evidence_links"]))
        self.assertTrue(any(link["relation_type"] == "supports_draft" for link in bundle["evidence_links"]))

    def test_contracts_include_m7_content_integrations(self) -> None:
        response = self.client.get("/v1/contracts")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("LocalizedKnowledgeFact", payload["m7_content_integrations"])
        self.assertIn("ContentDraft", payload["m7_content_integrations"])
        self.assertIn("ManualDistributionRecord", payload["m7_content_integrations"])
        self.assertIn("TraceabilityBundle", payload["auditability"])
        self.assertIn("build_traceability_bundle", payload["traceability"])
        self.assertIn("RuntimeEvidenceRun", payload["persistence"])
        self.assertIn("RuntimeEvidenceExport", payload["persistence"])
        self.assertIn("RuntimeProject", payload["persistence"])
        self.assertIn("RuntimeProjectPage", payload["persistence"])
        self.assertIn("RuntimePromptPage", payload["persistence"])
        self.assertIn("RuntimeScoreSnapshot", payload["persistence"])
        self.assertIn("RuntimeCitationGraph", payload["persistence"])
        self.assertIn("RuntimeReportArtifact", payload["persistence"])
        self.assertIn("RuntimeReportExport", payload["persistence"])
        self.assertIn("RuntimeActionPlan", payload["persistence"])
        self.assertIn("RuntimeContentEngine", payload["persistence"])
        self.assertIn("RuntimeTraceabilityDetail", payload["persistence"])
        self.assertIn("build_object_store_from_env", payload["persistence"])
        self.assertIn("/v1/projects/runtime", payload["persistence"])
        self.assertIn("/v1/projects/runtime/au/dtc-ecommerce", payload["persistence"])
        self.assertIn("/v1/prompts/runtime", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/visibility-scores/runtime", payload["persistence"])
        self.assertIn("/v1/citation-graphs/runtime", payload["persistence"])
        self.assertIn("/v1/reports/runtime", payload["persistence"])
        self.assertIn("/v1/reports/runtime/{report_export_id}/artifact", payload["persistence"])
        self.assertIn("/v1/action-plans/runtime", payload["persistence"])
        self.assertIn("/v1/content-engines/runtime", payload["persistence"])
        self.assertIn("/v1/traceability/runtime", payload["persistence"])


if __name__ == "__main__":
    unittest.main()
