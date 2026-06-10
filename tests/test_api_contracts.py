from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from geno_api.main import app
from geno_core.models import (
    RuntimeCollectionRunPage,
    RuntimeFidelityCheck,
    RuntimeFidelityCheckPage,
    RuntimeHumanReviewPage,
    RuntimeHumanReviewRecord,
    RuntimeKnowledgeSearchPage,
    RuntimeKnowledgeSearchResult,
    RuntimeProjectBrandKit,
    RuntimePromptImportResult,
    RuntimeProjectPage,
    RuntimeReportArtifact,
    RuntimeScoreWeightConfig,
)


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

    def test_runtime_project_create_endpoint_accepts_client_configuration(self) -> None:
        class FakeRepository:
            def save_project_bootstrap(self, bootstrap: object) -> None:
                self.bootstrap = bootstrap

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/projects/runtime/au/dtc-ecommerce",
                json={
                    "tenant_name": "Agency Client AU",
                    "project_name": "Koala Mattress GEO Pilot",
                    "target_brand": "Koala",
                    "category": "mattresses",
                    "competitors": ["Emma Sleep", "Sleeping Duck", "Ecosa"],
                    "brand_official_domains": ["koala.com"],
                    "brand_parent_company": "Koala",
                    "brand_product_lines": ["Mattress", "Sofa Bed"],
                    "owner_user_id": "agency-owner",
                },
            )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["market_code"], "AU")
        self.assertEqual(payload["prompt_count"], 100)
        self.assertEqual(payload["competitor_count"], 3)
        self.assertEqual(payload["bootstrap"]["tenant"]["name"], "Agency Client AU")
        self.assertEqual(payload["bootstrap"]["project"]["name"], "Koala Mattress GEO Pilot")
        self.assertEqual(payload["bootstrap"]["project"]["target_brand"], "Koala")
        self.assertEqual(payload["bootstrap"]["brand"]["official_domains"], ["koala.com"])
        self.assertEqual(payload["bootstrap"]["brand"]["product_lines"], ["Mattress", "Sofa Bed"])
        self.assertEqual(payload["bootstrap"]["members"][0]["user_id"], "agency-owner")

    def test_runtime_project_create_endpoint_rejects_invalid_competitor_count(self) -> None:
        response = self.client.post(
            "/v1/projects/runtime/au/dtc-ecommerce",
            json={
                "target_brand": "Koala",
                "category": "mattresses",
                "competitors": ["Only One"],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("3-5 competitors", response.json()["detail"])

    def test_runtime_projects_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/projects/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_projects_endpoint_passes_project_id_filter(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/projects/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&market_code=AU&limit=2&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_count"], 0)
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["market_code"], "AU")
        self.assertEqual(fake_repository.kwargs["limit"], 2)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_prompts_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/prompts/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_prompt_import_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/prompts/runtime/import.csv",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "csv_content": "text,intent_type\nIs ExampleBrand visible?,brand_awareness\n",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_prompt_import_endpoint_passes_csv_payload(self) -> None:
        class FakeRepository:
            def import_runtime_prompts_csv(self, prompt_import: object) -> RuntimePromptImportResult:
                self.prompt_import = prompt_import
                return RuntimePromptImportResult(
                    prompt_import={
                        "project_id": prompt_import.project_id,
                        "prompt_count": 1,
                        "prompt_ids": ["prompt-1"],
                        "prompt_version": "au_dtc_ecommerce_v1_imported",
                    },
                    prompts=(
                        {
                            "id": "prompt-1",
                            "project_id": prompt_import.project_id,
                            "text": "Is ExampleBrand visible?",
                            "intent_type": "brand_awareness",
                        },
                    ),
                    audit_events=(
                        {
                            "event_type": "runtime_prompts_imported",
                            "target_type": "prompt_import",
                            "method_version": "runtime_prompt_import_csv_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/prompts/runtime/import.csv",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "csv_content": "text,intent_type\nIs ExampleBrand visible?,brand_awareness\n",
                    "imported_by": "runtime-console",
                    "max_rows": 100,
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["prompt_import"]["prompt_count"], 1)
        self.assertEqual(payload["audit_events"][0]["event_type"], "runtime_prompts_imported")
        self.assertEqual(fake_repository.prompt_import.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertIn("Is ExampleBrand visible?", fake_repository.prompt_import.csv_content)

    def test_runtime_evidence_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/evidence-runs/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_evidence_filter_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/evidence-runs/runtime?platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_collection_runs_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/collection-runs/runtime?run_type=p0a_slice")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_collection_runs_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_collection_runs(self, **kwargs: object) -> RuntimeCollectionRunPage:
                self.kwargs = kwargs
                return RuntimeCollectionRunPage(
                    total_count=0,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/collection-runs/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&run_type=p0a_slice&limit=2&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_count"], 0)
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["run_type"], "p0a_slice")
        self.assertEqual(fake_repository.kwargs["limit"], 2)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_fidelity_checks_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/fidelity-checks/runtime?status=not_run")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_fidelity_check_create_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/fidelity-checks/runtime",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "checked_by": "runtime-console",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_fidelity_checks_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_fidelity_checks(self, **kwargs: object) -> RuntimeFidelityCheckPage:
                self.kwargs = kwargs
                return RuntimeFidelityCheckPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeFidelityCheck(
                            fidelity_check={
                                "id": "9128c59e-54ca-5ceb-9272-3efe226bd07b",
                                "project_id": kwargs["project_id"],
                                "report_export_id": kwargs["report_export_id"],
                                "status": kwargs["status"],
                                "official_api_records": 4,
                                "browser_records": 0,
                                "comparable_prompt_city_pairs": 0,
                                "mismatch_count": 0,
                                "difference_rate": None,
                                "payload_hash": "f" * 64,
                            },
                            audit_events=(
                                {
                                    "event_type": "api_browser_fidelity_checked",
                                    "target_type": "api_browser_fidelity_check",
                                    "method_version": "api_browser_fidelity_check_v1",
                                },
                            ),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/fidelity-checks/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&report_export_id=b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
                "&status=not_run&limit=5&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "api_browser_fidelity_checked")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["report_export_id"], "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad")
        self.assertEqual(fake_repository.kwargs["status"], "not_run")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_fidelity_check_create_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def create_runtime_fidelity_check(self, **kwargs: object) -> RuntimeFidelityCheck:
                self.kwargs = kwargs
                return RuntimeFidelityCheck(
                    fidelity_check={
                        "id": "9128c59e-54ca-5ceb-9272-3efe226bd07b",
                        "project_id": kwargs["project_id"],
                        "report_export_id": kwargs["report_export_id"],
                        "status": "sampled",
                        "official_api_records": 1,
                        "browser_records": 1,
                        "comparable_prompt_city_pairs": 1,
                        "mismatch_count": 1,
                        "difference_rate": 1.0,
                        "payload_hash": "a" * 64,
                        "checked_by": kwargs["checked_by"],
                    },
                    audit_events=(
                        {
                            "event_type": "api_browser_fidelity_checked",
                            "target_type": "api_browser_fidelity_check",
                            "method_version": "api_browser_fidelity_check_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/fidelity-checks/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "report_export_id": "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad",
                    "checked_by": "runtime-console",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["fidelity_check"]["status"], "sampled")
        self.assertEqual(payload["audit_events"][0]["event_type"], "api_browser_fidelity_checked")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["report_export_id"], "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad")
        self.assertEqual(fake_repository.kwargs["checked_by"], "runtime-console")

    def test_runtime_evidence_export_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/evidence-runs/runtime/export.csv?platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_manual_backfill_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/evidence-runs/runtime/manual-backfill",
            json={
                "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                "platform": "google",
                "surface": "google_ai_mode",
                "answer_text": "Manual answer",
                "citation_urls": ["https://examplebrand.example/au/manual"],
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_aliases_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/entity-aliases/runtime?entity_kind=brand")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_candidates_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/entity-aliases/runtime/candidates?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&entity_kind=brand"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_confirm_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/entity-aliases/runtime/confirm",
            json={
                "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                "entity_kind": "brand",
                "alias": "ExampleBrand Australia",
                "alias_type": "alias",
                "confirmed_by": "runtime-console",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_saved_views_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/runtime-saved-views?view_type=runtime_evidence")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_saved_view_save_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/runtime-saved-views",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "name": "Perplexity Sydney",
                "view_type": "runtime_evidence",
                "filters": {"platform": "perplexity", "city": "Sydney"},
                "sort": "cost_desc",
                "query_path": "/v1/evidence-runs/runtime?platform=perplexity&city=Sydney&sort=cost_desc&limit=5",
                "export_path": "/v1/evidence-runs/runtime/export.csv?platform=perplexity&city=Sydney&sort=cost_desc&limit=200",
                "created_by": "runtime-console",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_brand_kit_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/project-brand-kits/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_brand_kit_save_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/project-brand-kits/runtime",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "client_name": "Koala AU",
                "prepared_by": "Partner Agency",
                "logo_url": "https://koala.example/logo.png",
                "primary_color": "#0f766e",
                "secondary_color": "#111827",
                "footer_text": "Prepared for Koala AU board review",
                "updated_by": "runtime-console",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_brand_kit_endpoint_returns_saved_configuration(self) -> None:
        class FakeRepository:
            def get_project_brand_kit(self, **kwargs: object) -> RuntimeProjectBrandKit:
                self.kwargs = kwargs
                return RuntimeProjectBrandKit(
                    brand_kit={
                        "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
                        "project_id": kwargs["project_id"],
                        "client_name": "Koala AU",
                        "prepared_by": "Partner Agency",
                        "logo_url": "https://koala.example/logo.png",
                        "primary_color": "#0f766e",
                        "secondary_color": "#111827",
                        "footer_text": "Prepared for Koala AU board review",
                        "updated_by": "runtime-console",
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_kit_saved",
                            "target_type": "project_brand_kit",
                            "method_version": "project_brand_kit_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/project-brand-kits/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["brand_kit"]["client_name"], "Koala AU")
        self.assertEqual(payload["brand_kit"]["primary_color"], "#0f766e")
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_brand_kit_saved")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")

    def test_runtime_project_brand_kit_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_project_brand_kit(self, brand_kit: object) -> RuntimeProjectBrandKit:
                self.brand_kit = brand_kit
                return RuntimeProjectBrandKit(
                    brand_kit={
                        "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
                        "project_id": brand_kit.project_id,
                        "client_name": brand_kit.client_name,
                        "prepared_by": brand_kit.prepared_by,
                        "logo_url": brand_kit.logo_url,
                        "primary_color": brand_kit.primary_color,
                        "secondary_color": brand_kit.secondary_color,
                        "footer_text": brand_kit.footer_text,
                        "updated_by": brand_kit.updated_by,
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_kit_saved",
                            "target_type": "project_brand_kit",
                            "method_version": "project_brand_kit_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-brand-kits/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "client_name": "Koala AU",
                    "prepared_by": "Partner Agency",
                    "logo_url": "https://koala.example/logo.png",
                    "primary_color": "#0f766e",
                    "secondary_color": "#111827",
                    "footer_text": "Prepared for Koala AU board review",
                    "updated_by": "runtime-console",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["brand_kit"]["prepared_by"], "Partner Agency")
        self.assertEqual(fake_repository.brand_kit.client_name, "Koala AU")
        self.assertEqual(fake_repository.brand_kit.logo_url, "https://koala.example/logo.png")

    def test_runtime_score_weight_config_endpoint_returns_default_when_missing(self) -> None:
        class FakeRepository:
            def get_score_weight_config(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                return None

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/score-weight-configs/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["score_weight_config"]["updated_by"], "system-default")
        self.assertEqual(round(sum(payload["score_weight_config"]["weights"].values()), 6), 1.0)
        self.assertEqual(fake_repository.kwargs["formula_version"], "au_visibility_v1")

    def test_runtime_score_formula_catalog_endpoint_lists_registered_versions(self) -> None:
        response = self.client.get("/v1/score-formulas/runtime")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        versions = {item["formula_version"] for item in payload["formulas"]}
        self.assertIn("au_visibility_v1", versions)
        self.assertIn("au_visibility_v1_1_local_boost", versions)
        local_boost = next(item for item in payload["formulas"] if item["formula_version"] == "au_visibility_v1_1_local_boost")
        self.assertEqual(local_boost["status"], "candidate")
        self.assertEqual(round(sum(local_boost["weights"].values()), 6), 1.0)

    def test_runtime_score_weight_config_endpoint_returns_formula_default_when_missing(self) -> None:
        class FakeRepository:
            def get_score_weight_config(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                return None

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/score-weight-configs/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&formula_version=au_visibility_v1_1_local_boost"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["score_weight_config"]["formula_version"], "au_visibility_v1_1_local_boost")
        self.assertEqual(payload["score_weight_config"]["weights"]["LocalRelevanceScore"], 0.18)
        self.assertEqual(fake_repository.kwargs["formula_version"], "au_visibility_v1_1_local_boost")

    def test_runtime_score_weight_config_save_endpoint_passes_payload(self) -> None:
        weights = {
            "MentionScore": 0.20,
            "RecommendationScore": 0.22,
            "PositionScore": 0.12,
            "CitationScore": 0.16,
            "LocalRelevanceScore": 0.14,
            "SentimentScore": 0.08,
            "FreshnessScore": 0.03,
            "CompetitorShareScore": 0.05,
        }

        class FakeRepository:
            def save_score_weight_config(self, config: object) -> RuntimeScoreWeightConfig:
                self.config = config
                return RuntimeScoreWeightConfig(
                    score_weight_config={
                        "id": "7daa9492-8fb2-565e-827a-bfd3de846cde",
                        "project_id": config.project_id,
                        "formula_version": config.formula_version,
                        "weights": config.weights,
                        "updated_by": config.updated_by,
                        "notes": config.notes,
                    },
                    audit_events=(
                        {
                            "event_type": "score_weight_config_saved",
                            "target_type": "score_weight_config",
                            "method_version": "score_weight_config_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/score-weight-configs/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "weights": weights,
                    "updated_by": "runtime-console",
                    "notes": "prioritize mention",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["score_weight_config"]["weights"]["MentionScore"], 0.20)
        self.assertEqual(fake_repository.config.notes, "prioritize mention")

    def test_runtime_score_weight_config_save_endpoint_passes_formula_version(self) -> None:
        weights = {
            "MentionScore": 0.17,
            "RecommendationScore": 0.21,
            "PositionScore": 0.11,
            "CitationScore": 0.15,
            "LocalRelevanceScore": 0.18,
            "SentimentScore": 0.07,
            "FreshnessScore": 0.06,
            "CompetitorShareScore": 0.05,
        }

        class FakeRepository:
            def save_score_weight_config(self, config: object) -> RuntimeScoreWeightConfig:
                self.config = config
                return RuntimeScoreWeightConfig(
                    score_weight_config={
                        "id": "74ef8cfb-06e4-5659-a178-d1e3ee7dc7cb",
                        "project_id": config.project_id,
                        "formula_version": config.formula_version,
                        "weights": config.weights,
                        "updated_by": config.updated_by,
                        "notes": config.notes,
                    },
                    audit_events=(
                        {
                            "event_type": "score_weight_config_saved",
                            "target_type": "score_weight_config",
                            "method_version": "score_weight_config_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/score-weight-configs/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "formula_version": "au_visibility_v1_1_local_boost",
                    "weights": weights,
                    "updated_by": "runtime-console",
                    "notes": "test local boost formula",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["score_weight_config"]["formula_version"], "au_visibility_v1_1_local_boost")
        self.assertEqual(fake_repository.config.formula_version, "au_visibility_v1_1_local_boost")

    def test_runtime_human_reviews_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/human-reviews/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&target_type=content_draft"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_human_review_save_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/human-reviews/runtime",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "target_type": "visibility_score_snapshot",
                "target_id": "38f0251c-c380-4197-b6c9-3e630b127844",
                "review_status": "approved",
                "decision": "approved_for_report",
                "reviewer_id": "runtime-console",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_human_reviews_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_human_reviews(self, **kwargs: object) -> RuntimeHumanReviewPage:
                self.kwargs = kwargs
                return RuntimeHumanReviewPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeHumanReviewRecord(
                            human_review={
                                "id": "f25cdddc-c3e7-4fcb-90b8-557fd6465ea7",
                                "project_id": kwargs["project_id"],
                                "target_type": kwargs["target_type"],
                                "target_id": "1e53e0b4-7b1a-54d6-a918-fd8774df7bdd",
                                "review_status": kwargs["review_status"],
                                "decision": "rewrite_local_examples",
                                "reviewer_id": "editor@example.com",
                            },
                            audit_events=(
                                {
                                    "event_type": "human_review_recorded",
                                    "target_type": "human_review_record",
                                    "method_version": "human_review_v1",
                                },
                            ),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/human-reviews/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&target_type=content_draft&review_status=needs_changes&limit=5&offset=1"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "human_review_recorded")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["target_type"], "content_draft")
        self.assertEqual(fake_repository.kwargs["review_status"], "needs_changes")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_human_review_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_human_review(self, review: object) -> RuntimeHumanReviewRecord:
                self.review = review
                return RuntimeHumanReviewRecord(
                    human_review={
                        "id": "f25cdddc-c3e7-4fcb-90b8-557fd6465ea7",
                        "project_id": review.project_id,
                        "target_type": review.target_type,
                        "target_id": review.target_id,
                        "review_status": review.review_status,
                        "decision": review.decision,
                        "reviewer_id": review.reviewer_id,
                        "notes": review.notes,
                        "payload": review.payload,
                    },
                    audit_events=(
                        {
                            "event_type": "human_review_recorded",
                            "target_type": "human_review_record",
                            "method_version": "human_review_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/human-reviews/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "target_type": "visibility_score_snapshot",
                    "target_id": "38f0251c-c380-4197-b6c9-3e630b127844",
                    "review_status": "approved",
                    "decision": "approved_for_report",
                    "reviewer_id": "runtime-console",
                    "notes": "reviewed score evidence",
                    "payload": {"source": "runtime-console"},
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["human_review"]["decision"], "approved_for_report")
        self.assertEqual(payload["audit_events"][0]["event_type"], "human_review_recorded")
        self.assertEqual(fake_repository.review.target_type, "visibility_score_snapshot")
        self.assertEqual(fake_repository.review.payload["source"], "runtime-console")

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
        response = self.client.get(
            "/v1/reports/runtime/report-1/artifact?type=markdown&platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_pdf_artifact_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/reports/runtime/report-1/artifact?type=pdf")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_white_label_pdf_artifact_endpoint_returns_template_headers(self) -> None:
        class FakeRepository:
            def get_runtime_report_artifact(self, **kwargs: object) -> RuntimeReportArtifact:
                self.kwargs = kwargs
                return RuntimeReportArtifact(
                    report_export={"id": kwargs["report_export_id"], "report_version": "worker-runtime-v1"},
                    artifact_type="pdf",
                    template="white_label",
                    template_payload={
                        "template": "white_label",
                        "client_name": kwargs["client_name"],
                        "prepared_by": kwargs["prepared_by"],
                    },
                    template_hash="template-hash",
                    filename="worker-runtime-v1-white-label.pdf",
                    media_type="application/pdf",
                    content=b"%PDF-1.4\nwhite-label\n%%EOF\n",
                    content_hash="artifact-hash",
                    filters={"platform": kwargs["platform"]},
                    filter_hash="filter-hash",
                    sort="cost_desc",
                    total_count=4,
                    row_count=2,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/reports/runtime/report-1/artifact"
                "?type=pdf&template=white_label&client_name=ExampleBrand%20AU"
                "&prepared_by=Partner%20Agency&platform=perplexity&sort=cost_desc"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="worker-runtime-v1-white-label.pdf"',
        )
        self.assertEqual(response.headers["x-geno-report-artifact-template"], "white_label")
        self.assertEqual(response.headers["x-geno-report-artifact-template-hash"], "template-hash")
        self.assertEqual(response.headers["x-geno-report-artifact-row-count"], "2")
        self.assertEqual(response.headers["x-geno-report-artifact-total-count"], "4")
        self.assertEqual(fake_repository.kwargs["template"], "white_label")
        self.assertEqual(fake_repository.kwargs["client_name"], "ExampleBrand AU")
        self.assertEqual(fake_repository.kwargs["prepared_by"], "Partner Agency")

    def test_runtime_action_plans_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/action-plans/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_content_engines_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/content-engines/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_knowledge_fact_search_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/knowledge-facts/runtime/search"
            "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&query=Australia%20shipping"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_knowledge_fact_search_endpoint_passes_query(self) -> None:
        class FakeRepository:
            def search_runtime_knowledge_facts(self, **kwargs: object) -> RuntimeKnowledgeSearchPage:
                self.kwargs = kwargs
                return RuntimeKnowledgeSearchPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    query=str(kwargs["query"]),
                    market_code=str(kwargs["market_code"]),
                    city=str(kwargs["city"]) if kwargs["city"] else None,
                    embedding_model=str(kwargs["embedding_model"]),
                    records=(
                        RuntimeKnowledgeSearchResult(
                            fact={
                                "id": "06975d61-853b-5a25-ae0e-b62bbfe82c15",
                                "market_code": "AU",
                                "fact_type": "australian_shipping_policy",
                                "subject": "ExampleBrand",
                                "predicate": "supports_market",
                                "object_value": "AU shipping",
                            },
                            score=0.91,
                            fallback_used=False,
                            embedding_model=str(kwargs["embedding_model"]),
                        ),
                    ),
                    audit_events=(
                        {
                            "event_type": "knowledge_fact_embeddings_indexed",
                            "target_type": "knowledge_fact_embedding_index",
                            "method_version": "knowledge_fact_embedding_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/knowledge-facts/runtime/search"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&query=Australia%20shipping&market_code=AU&city=Sydney&limit=5&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["fact"]["fact_type"], "australian_shipping_policy")
        self.assertEqual(payload["audit_events"][0]["event_type"], "knowledge_fact_embeddings_indexed")
        self.assertEqual(fake_repository.kwargs["query"], "Australia shipping")
        self.assertEqual(fake_repository.kwargs["city"], "Sydney")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

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
        self.assertEqual(payload["readiness_gate"]["gate_status"], "fail")
        self.assertIn("insufficient_collection_paths=1/2", payload["readiness_gate"]["failure_reasons"])

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
        self.assertIn("### Method Disclosure", payload["markdown"])
        self.assertIn("Google spike gate: fail", payload["markdown"])
        self.assertIn("Google limited coverage: yes", payload["markdown"])
        self.assertIn("API-vs-browser fidelity: not_run", payload["markdown"])
        self.assertIn("Trigger rate denominator: all attempted evidence records in this report window", payload["markdown"])
        self.assertIn("Mention rate denominator: surface_triggered evidence records, not all attempted records", payload["markdown"])
        self.assertIn("Report evidence attempted records:", payload["markdown"])
        score_rate_disclosure = payload["report_export"]["method_disclosure"]["score_rate_denominators"]
        self.assertEqual(
            score_rate_disclosure["definitions"]["recommendation_rate"]["formula"],
            "brand_recommended_records / surface_triggered_records",
        )
        self.assertGreater(score_rate_disclosure["evidence_denominators"]["attempted_records"], 0)
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
        self.assertIn("CollectorBackend", payload["interfaces"])
        self.assertIn("ParserEngine", payload["interfaces"])
        self.assertIn("ScoringFormula", payload["interfaces"])
        self.assertIn("ReportExporter", payload["interfaces"])
        self.assertIn("NotConfiguredCollectorBackend", payload["interfaces"])
        self.assertIn("NotConfiguredParserEngine", payload["interfaces"])
        self.assertIn("NotConfiguredScoringFormula", payload["interfaces"])
        self.assertIn("NotConfiguredReportExporter", payload["interfaces"])
        self.assertIn("RegistryScoringFormula", payload["interfaces"])
        self.assertIn("LocalizedKnowledgeFact", payload["m7_content_integrations"])
        self.assertIn("ContentDraft", payload["m7_content_integrations"])
        self.assertIn("ManualDistributionRecord", payload["m7_content_integrations"])
        self.assertIn("KnowledgeFactEmbedding", payload["m7_content_integrations"])
        self.assertIn("RuntimeKnowledgeSearchResult", payload["m7_content_integrations"])
        self.assertIn("RuntimeKnowledgeSearchPage", payload["m7_content_integrations"])
        self.assertIn("EntityAlias", payload["m1_bootstrap"])
        self.assertIn("EntityAliasInput", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAlias", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasCandidate", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasCandidatePage", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasPage", payload["m1_bootstrap"])
        self.assertIn("TraceabilityBundle", payload["auditability"])
        self.assertIn("RuntimeFidelityCheck", payload["auditability"])
        self.assertIn("build_traceability_bundle", payload["traceability"])
        self.assertIn("CollectionRunSummary", payload["m2a_evidence"])
        self.assertIn("P0ACollectionReadinessGate", payload["m2a_evidence"])
        self.assertIn("evaluate_p0a_collection_readiness", payload["m2a_evidence"])
        self.assertIn("RuntimeFidelityCheck", payload["m2a_evidence"])
        self.assertIn("RuntimeFidelityCheckPage", payload["m2a_evidence"])
        self.assertIn("GoogleSpikeReadinessGate", payload["m2b_google_spike"])
        self.assertIn("evaluate_google_spike_readiness_gate", payload["m2b_google_spike"])
        self.assertIn("LLMJudgeAnswerParser", payload["m3_analysis_scoring"])
        self.assertIn("ComparativeAnswerParser", payload["m3_analysis_scoring"])
        self.assertIn("parser_ab_compare_v1", payload["m3_analysis_scoring"])
        self.assertIn("FixtureLLMGateway", payload["m3_analysis_scoring"])
        self.assertIn("LLMCallLog", payload["m3_analysis_scoring"])
        self.assertIn("RuntimeScoreWeightConfig", payload["m3_analysis_scoring"])
        self.assertIn("ScoreWeightConfigRequest", payload["m3_analysis_scoring"])
        self.assertIn("ScoreFormulaDefinition", payload["m3_analysis_scoring"])
        self.assertIn("RegistryScoringFormula", payload["m3_analysis_scoring"])
        self.assertIn("SCORE_FORMULA_REGISTRY", payload["m3_analysis_scoring"])
        self.assertIn("list_score_formulas", payload["m3_analysis_scoring"])
        self.assertIn("build_score_input_policy", payload["m3_analysis_scoring"])
        self.assertIn("rescore_snapshot_with_formula", payload["m3_analysis_scoring"])
        self.assertIn("RuntimeHumanReviewRecord", payload["m3_analysis_scoring"])
        self.assertIn("RuntimeHumanReviewInput", payload["m3_analysis_scoring"])
        self.assertIn("HumanReviewRequest", payload["m3_analysis_scoring"])
        self.assertIn("LLMCallLog", payload["auditability"])
        self.assertIn("RuntimeHumanReviewRecord", payload["auditability"])
        self.assertIn("RuntimeEvidenceRun", payload["persistence"])
        self.assertIn("RuntimeEvidenceExport", payload["persistence"])
        self.assertIn("RuntimeCollectionRun", payload["persistence"])
        self.assertIn("RuntimeCollectionRunPage", payload["persistence"])
        self.assertIn("RuntimeFidelityCheck", payload["persistence"])
        self.assertIn("RuntimeFidelityCheckPage", payload["persistence"])
        self.assertIn("RuntimeFidelityCheckRequest", payload["persistence"])
        self.assertIn("ManualBackfillInput", payload["persistence"])
        self.assertIn("EntityAliasInput", payload["persistence"])
        self.assertIn("RuntimeEntityAlias", payload["persistence"])
        self.assertIn("RuntimeEntityAliasCandidate", payload["persistence"])
        self.assertIn("RuntimeEntityAliasCandidatePage", payload["persistence"])
        self.assertIn("RuntimeEntityAliasPage", payload["persistence"])
        self.assertIn("RuntimeSavedView", payload["persistence"])
        self.assertIn("RuntimeSavedViewInput", payload["persistence"])
        self.assertIn("RuntimeSavedViewPage", payload["persistence"])
        self.assertIn("RuntimeProject", payload["persistence"])
        self.assertIn("RuntimeProjectPage", payload["persistence"])
        self.assertIn("RuntimeProjectBrandKit", payload["persistence"])
        self.assertIn("RuntimeProjectBrandKitInput", payload["persistence"])
        self.assertIn("ProjectBrandKitRequest", payload["persistence"])
        self.assertIn("RuntimeScoreWeightConfig", payload["persistence"])
        self.assertIn("RuntimeScoreWeightConfigInput", payload["persistence"])
        self.assertIn("ScoreWeightConfigRequest", payload["persistence"])
        self.assertIn("ScoreFormulaDefinition", payload["persistence"])
        self.assertIn("RuntimeHumanReviewRecord", payload["persistence"])
        self.assertIn("RuntimeHumanReviewPage", payload["persistence"])
        self.assertIn("RuntimeHumanReviewInput", payload["persistence"])
        self.assertIn("HumanReviewRequest", payload["persistence"])
        self.assertIn("RuntimePromptPage", payload["persistence"])
        self.assertIn("RuntimePromptImportInput", payload["persistence"])
        self.assertIn("RuntimePromptImportResult", payload["persistence"])
        self.assertIn("RuntimePromptImportRequest", payload["persistence"])
        self.assertIn("RuntimeScoreSnapshot", payload["persistence"])
        self.assertIn("RuntimeCitationGraph", payload["persistence"])
        self.assertIn("RuntimeReportArtifact", payload["persistence"])
        self.assertIn("RuntimeReportExport", payload["persistence"])
        self.assertIn("RuntimeActionPlan", payload["persistence"])
        self.assertIn("RuntimeContentEngine", payload["persistence"])
        self.assertIn("RuntimeKnowledgeSearchResult", payload["persistence"])
        self.assertIn("RuntimeKnowledgeSearchPage", payload["persistence"])
        self.assertIn("RuntimeTraceabilityDetail", payload["persistence"])
        self.assertIn("build_object_store_from_env", payload["persistence"])
        self.assertIn("/v1/projects/runtime", payload["persistence"])
        self.assertIn("/v1/projects/runtime/au/dtc-ecommerce", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/confirm", payload["persistence"])
        self.assertIn("/v1/prompts/runtime", payload["persistence"])
        self.assertIn("/v1/prompts/runtime/import.csv", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime", payload["persistence"])
        self.assertIn("/v1/collection-runs/runtime", payload["persistence"])
        self.assertIn("/v1/fidelity-checks/runtime", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime/manual-backfill", payload["persistence"])
        self.assertIn("/v1/runtime-saved-views", payload["persistence"])
        self.assertIn("/v1/project-brand-kits/runtime", payload["persistence"])
        self.assertIn("/v1/score-weight-configs/runtime", payload["persistence"])
        self.assertIn("/v1/score-formulas/runtime", payload["persistence"])
        self.assertIn("/v1/human-reviews/runtime", payload["persistence"])
        self.assertIn("/v1/visibility-scores/runtime", payload["persistence"])
        self.assertIn("/v1/citation-graphs/runtime", payload["persistence"])
        self.assertIn("/v1/reports/runtime", payload["persistence"])
        self.assertIn("/v1/reports/runtime/{report_export_id}/artifact", payload["persistence"])
        self.assertIn("/v1/action-plans/runtime", payload["persistence"])
        self.assertIn("/v1/content-engines/runtime", payload["persistence"])
        self.assertIn("/v1/knowledge-facts/runtime/search", payload["persistence"])
        self.assertIn("/v1/traceability/runtime", payload["persistence"])


if __name__ == "__main__":
    unittest.main()
