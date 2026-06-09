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


if __name__ == "__main__":
    unittest.main()
