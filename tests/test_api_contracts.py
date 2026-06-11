from __future__ import annotations

import base64
import hashlib
import hmac
from io import BytesIO
import json
import time
import unittest
from datetime import UTC, datetime
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes

from geno_api.main import app, close_runtime_resources, reset_runtime_auth_caches, reset_runtime_metrics
from geno_core.runtime import RuntimeComponentDiagnostic, RuntimeDiagnostics
from geno_core.models import (
    RuntimeCollectionRunPage,
    RuntimeAlertEvent,
    RuntimeAlertItem,
    RuntimeAlertNotificationResult,
    RuntimeAlertPage,
    RuntimeFidelityCheck,
    RuntimeFidelityCheckPage,
    RuntimeFidelityTrend,
    RuntimeFidelityTrendPoint,
    RuntimeHumanReviewPage,
    RuntimeHumanReviewQueueItem,
    RuntimeHumanReviewQueuePage,
    RuntimeHumanReviewRecord,
    RuntimeKnowledgeSearchPage,
    RuntimeKnowledgeSearchResult,
    RuntimeNotificationDelivery,
    RuntimeNotificationDeliveryPage,
    RuntimeNotification,
    RuntimeNotificationPage,
    RuntimeNotificationSubscription,
    RuntimeNotificationSubscriptionPage,
    RuntimeProjectBrandAsset,
    RuntimeProjectBrandAssetInput,
    RuntimeProjectBrandAssetPage,
    RuntimeProjectBrandAssetScanInput,
    RuntimeProjectBrandKit,
    RuntimeProjectBrandAssetVersion,
    RuntimeProjectBrandAssetVersionPage,
    RuntimeProjectBrandLogoUpload,
    RuntimeProjectMember,
    RuntimeProjectMemberPage,
    RuntimePromptImportHistoryItem,
    RuntimePromptImportHistoryPage,
    RuntimePromptImportResult,
    RuntimeProjectPage,
    RuntimeReportArtifact,
    RuntimeReportExport,
    RuntimeReportExportJob,
    RuntimeReportExportJobPage,
    RuntimeReportExportJobQueueStats,
    RuntimeScoreWeightConfig,
)


class ApiContractsTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_metrics()
        reset_runtime_auth_caches()
        self.client = TestClient(app)

    def _runtime_jwt(self, *, secret: str = "test-runtime-secret", payload: dict[str, object] | None = None) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        claims = {"sub": "agency-owner", "exp": int(time.time()) + 300}
        if payload:
            claims.update(payload)
        encoded_header = base64.urlsafe_b64encode(
            json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        encoded_payload = base64.urlsafe_b64encode(
            json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        signature = hmac.new(
            secret.encode("utf-8"),
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        return f"{encoded_header}.{encoded_payload}.{encoded_signature}"

    def _runtime_jwks_rs256_token(
        self,
        *,
        payload: dict[str, object] | None = None,
        key_id: str = "runtime-key-1",
    ) -> tuple[str, str]:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_numbers = private_key.public_key().public_numbers()

        def base64url_int(value: int) -> str:
            raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

        jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": key_id,
                    "use": "sig",
                    "alg": "RS256",
                    "n": base64url_int(public_numbers.n),
                    "e": base64url_int(public_numbers.e),
                }
            ]
        }
        header = {"alg": "RS256", "kid": key_id, "typ": "JWT"}
        claims = {"sub": "jwks-owner", "exp": int(time.time()) + 300}
        if payload:
            claims.update(payload)
        encoded_header = base64.urlsafe_b64encode(
            json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        encoded_payload = base64.urlsafe_b64encode(
            json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        signature = private_key.sign(
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        return f"{encoded_header}.{encoded_payload}.{encoded_signature}", json.dumps(jwks)

    def _xlsx_prompt_import_bytes(self) -> bytes:
        buffer = BytesIO()
        with ZipFile(buffer, "w") as workbook:
            workbook.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Prompts" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
            )
            workbook.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
            )
            workbook.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>text</t></is></c><c r="B1" t="inlineStr"><is><t>intent_type</t></is></c><c r="C1" t="inlineStr"><is><t>city</t></is></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>Is ExampleBrand visible in AI answers?</t></is></c><c r="B2" t="inlineStr"><is><t>brand_awareness</t></is></c><c r="C2" t="inlineStr"><is><t>Sydney</t></is></c></row>
  </sheetData>
</worksheet>""",
            )
        return buffer.getvalue()

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_readiness_returns_503_when_database_check_fails(self) -> None:
        with patch(
            "geno_api.main.runtime_database_diagnostic",
            return_value=RuntimeComponentDiagnostic(
                name="database",
                status="fail",
                detail="DATABASE_URL is not configured",
                metadata={"database_url": "missing"},
            ),
        ):
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["checks"][0]["name"], "database")

    def test_readiness_returns_200_when_database_check_passes(self) -> None:
        with patch(
            "geno_api.main.runtime_database_diagnostic",
            return_value=RuntimeComponentDiagnostic(
                name="database",
                status="pass",
                detail="PostgreSQL connection check succeeded",
                metadata={"database_url": "configured"},
            ),
        ):
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pass")

    def test_runtime_diagnostics_endpoint_returns_component_checks(self) -> None:
        diagnostics = RuntimeDiagnostics(
            status="warn",
            checks=(
                RuntimeComponentDiagnostic(
                    name="database",
                    status="pass",
                    detail="PostgreSQL connection check succeeded",
                    metadata={"database_url": "configured"},
                ),
                RuntimeComponentDiagnostic(
                    name="object_store",
                    status="warn",
                    detail="OBJECT_STORE_ENDPOINT is not configured",
                    metadata={"endpoint": "missing"},
                ),
            ),
        )
        with patch("geno_api.main.build_runtime_diagnostics", return_value=diagnostics):
            response = self.client.get("/v1/runtime-diagnostics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "warn")
        self.assertEqual([check["name"] for check in payload["checks"]], ["database", "object_store"])

    def test_metrics_endpoint_exports_request_and_pool_metrics(self) -> None:
        self.client.get("/health")
        with patch(
            "geno_api.main.runtime_postgres_pool_snapshot",
            return_value={
                "enabled": True,
                "max_size": 10,
                "timeout_seconds": 5.0,
                "created": 2,
                "available": 1,
            },
        ):
            response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        body = response.text
        self.assertIn("# TYPE geno_api_requests_total counter", body)
        self.assertIn('geno_api_requests_total{method="GET",path="/health",status="200"} 1', body)
        self.assertIn(
            'geno_api_request_duration_seconds_bucket{method="GET",path="/health",status="200",le="+Inf"} 1',
            body,
        )
        self.assertIn('geno_api_request_duration_seconds_count{method="GET",path="/health",status="200"} 1', body)
        self.assertIn("geno_runtime_postgres_pool_snapshot_ok 1", body)
        self.assertIn("geno_runtime_postgres_pool_enabled 1", body)
        self.assertIn("geno_runtime_postgres_pool_max_size 10", body)
        self.assertIn("geno_runtime_postgres_pool_connections_created 2", body)
        self.assertNotIn('path="/metrics"', body)

    def test_metrics_endpoint_uses_route_path_without_query_values(self) -> None:
        response = self.client.get("/v1/projects/runtime?market_code=AU&limit=5")
        self.assertEqual(response.status_code, 503)

        metrics = self.client.get("/metrics").text

        self.assertIn('geno_api_requests_total{method="GET",path="/v1/projects/runtime",status="503"} 1', metrics)
        self.assertNotIn("market_code", metrics)
        self.assertNotIn("limit=5", metrics)

    def test_runtime_access_log_emits_request_id_and_route_template(self) -> None:
        with self.assertLogs("geno_api.access", level="INFO") as captured:
            response = self.client.get(
                "/v1/projects/runtime?market_code=AU&limit=5",
                headers={"X-GENO-Request-Id": "req-runtime-001"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["X-GENO-Request-Id"], "req-runtime-001")
        payload = json.loads(captured.records[0].getMessage())
        self.assertEqual(payload["event_type"], "runtime_api_request")
        self.assertEqual(payload["log_version"], "runtime_access_log_v1")
        self.assertEqual(payload["request_id"], "req-runtime-001")
        self.assertEqual(payload["method"], "GET")
        self.assertEqual(payload["path"], "/v1/projects/runtime")
        self.assertEqual(payload["route"], "/v1/projects/runtime")
        self.assertEqual(payload["status_code"], 503)
        self.assertIsInstance(payload["duration_ms"], float)
        self.assertNotIn("market_code", captured.records[0].getMessage())

    def test_runtime_access_log_sanitizes_invalid_request_id(self) -> None:
        with self.assertLogs("geno_api.access", level="INFO") as captured:
            response = self.client.get("/health", headers={"X-GENO-Request-Id": "bad request id"})

        response_request_id = response.headers["X-GENO-Request-Id"]
        payload = json.loads(captured.records[0].getMessage())
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["request_id"], response_request_id)
        self.assertNotEqual(response_request_id, "bad request id")
        self.assertEqual(len(response_request_id), 32)
        int(response_request_id, 16)

    def test_shutdown_closes_runtime_postgres_pool(self) -> None:
        with patch("geno_api.main.close_runtime_postgres_pool") as close_pool:
            close_runtime_resources()
        close_pool.assert_called_once_with()

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

    def test_runtime_project_create_endpoint_uses_actor_as_owner_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def save_project_bootstrap(self, bootstrap: object) -> None:
                self.bootstrap = bootstrap

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/projects/runtime/au/dtc-ecommerce",
                json={
                    "target_brand": "Koala",
                    "category": "mattresses",
                    "competitors": ["Emma Sleep", "Sleeping Duck", "Ecosa"],
                    "owner_user_id": "payload-owner",
                },
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["bootstrap"]["members"][0]["user_id"], "agency-owner")

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

    def test_runtime_projects_endpoint_requires_actor_when_access_control_enabled(self) -> None:
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}):
            response = self.client.get("/v1/projects/runtime")

        self.assertEqual(response.status_code, 401)
        self.assertIn("X-GENO-Actor-Id", response.json()["detail"])

    def test_runtime_projects_endpoint_requires_jwt_secret_when_jwt_auth_mode_enabled(self) -> None:
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1", "GENO_RUNTIME_AUTH_MODE": "jwt"}, clear=False):
            response = self.client.get("/v1/projects/runtime")

        self.assertEqual(response.status_code, 503)
        self.assertIn("GENO_RUNTIME_JWT_SECRET", response.json()["detail"])

    def test_runtime_projects_endpoint_requires_bearer_jwt_when_jwt_auth_mode_enabled(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
                "GENO_RUNTIME_JWT_SECRET": "test-runtime-secret",
            },
            clear=False,
        ):
            response = self.client.get("/v1/projects/runtime")

        self.assertEqual(response.status_code, 401)
        self.assertIn("Authorization Bearer JWT", response.json()["detail"])

    def test_runtime_projects_endpoint_rejects_invalid_jwt_signature(self) -> None:
        token = self._runtime_jwt(secret="wrong-secret")
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
                "GENO_RUNTIME_JWT_SECRET": "test-runtime-secret",
            },
            clear=False,
        ):
            response = self.client.get("/v1/projects/runtime", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 401)
        self.assertIn("invalid runtime JWT signature", response.json()["detail"])

    def test_runtime_projects_endpoint_filters_by_actor_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.get("/v1/projects/runtime?market_code=AU", headers={"X-GENO-Actor-Id": "agency-owner"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "agency-owner")

    def test_runtime_projects_endpoint_filters_by_jwt_actor_when_jwt_auth_mode_enabled(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        fake_repository = FakeRepository()
        token = self._runtime_jwt(payload={"sub": "jwt-owner"})
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
                "GENO_RUNTIME_JWT_SECRET": "test-runtime-secret",
            },
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "jwt-owner")

    def test_runtime_projects_endpoint_filters_by_jwks_actor_when_jwks_auth_mode_enabled(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "jwks-owner"})
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": jwks_json,
            },
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "jwks-owner")

    def test_runtime_projects_endpoint_fetches_and_caches_jwks_url(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        class FakeJwksResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                return json.loads(jwks_json)

        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "remote-jwks-owner"})
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_get(url: str, **kwargs: object) -> FakeJwksResponse:
            calls.append((url, kwargs))
            return FakeJwksResponse()

        jwks_url = "https://idp.example.test/.well-known/jwks.json"
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "",
                "GENO_RUNTIME_JWKS_URL": jwks_url,
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "60",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.5",
            },
            clear=False,
        ), patch("geno_api.main.httpx.get", side_effect=fake_get), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            first = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})
            second = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "remote-jwks-owner")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], jwks_url)
        self.assertEqual(calls[0][1]["timeout"], 1.5)
        self.assertEqual(calls[0][1]["follow_redirects"], True)

    def test_runtime_projects_endpoint_rejects_expired_jwks_cache_without_stale_if_error(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        class FakeJwksResponse:
            status_code = 200

            def __init__(self, payload: object | None) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                if self.payload is None:
                    raise ValueError("temporary upstream parse failure")
                return self.payload

        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "remote-jwks-owner"})
        jwks_payload = json.loads(jwks_json)
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeJwksResponse:
            calls.append(url)
            return FakeJwksResponse(jwks_payload if len(calls) == 1 else None)

        jwks_url = "https://idp.example.test/.well-known/jwks.json"
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "",
                "GENO_RUNTIME_JWKS_URL": jwks_url,
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "0",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.5",
            },
            clear=False,
        ), patch("geno_api.main.httpx.get", side_effect=fake_get), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            first = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})
            second = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 503)
        self.assertIn("runtime JWKS URL fetch failed", second.json()["detail"])
        self.assertEqual(calls, [jwks_url, jwks_url])

    def test_runtime_projects_endpoint_uses_stale_jwks_on_refresh_error_when_enabled(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        class FakeJwksResponse:
            status_code = 200

            def __init__(self, payload: object | None) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                if self.payload is None:
                    raise ValueError("temporary upstream parse failure")
                return self.payload

        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "stale-jwks-owner"})
        jwks_payload = json.loads(jwks_json)
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeJwksResponse:
            calls.append(url)
            return FakeJwksResponse(jwks_payload if len(calls) == 1 else None)

        jwks_url = "https://idp.example.test/.well-known/jwks.json"
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "",
                "GENO_RUNTIME_JWKS_URL": jwks_url,
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "0",
                "GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS": "60",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.5",
            },
            clear=False,
        ), patch("geno_api.main.httpx.get", side_effect=fake_get), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            first = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})
            second = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "stale-jwks-owner")
        self.assertEqual(calls, [jwks_url, jwks_url])

    def test_runtime_projects_endpoint_discovers_jwks_uri_from_oidc_issuer(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        class FakeJsonResponse:
            status_code = 200

            def __init__(self, payload: object) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                return self.payload

        issuer = "https://idp.example.test/realms/geno"
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        jwks_url = "https://idp.example.test/realms/geno/protocol/openid-connect/certs"
        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "oidc-owner", "iss": issuer})
        jwks_payload = json.loads(jwks_json)
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_get(url: str, **kwargs: object) -> FakeJsonResponse:
            calls.append((url, kwargs))
            if url == discovery_url:
                return FakeJsonResponse({"issuer": issuer, "jwks_uri": jwks_url})
            if url == jwks_url:
                return FakeJsonResponse(jwks_payload)
            raise AssertionError(f"unexpected runtime auth fetch: {url}")

        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "",
                "GENO_RUNTIME_JWKS_URL": "",
                "GENO_RUNTIME_JWT_ISSUER": issuer,
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "60",
                "GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS": "60",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.25",
            },
            clear=False,
        ), patch("geno_api.main.httpx.get", side_effect=fake_get), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            first = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})
            second = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "oidc-owner")
        self.assertEqual([call[0] for call in calls], [discovery_url, jwks_url])
        self.assertEqual(calls[0][1]["timeout"], 1.25)
        self.assertEqual(calls[1][1]["timeout"], 1.25)
        self.assertEqual(calls[0][1]["follow_redirects"], True)
        self.assertEqual(calls[1][1]["follow_redirects"], True)

    def test_runtime_projects_endpoint_uses_stale_oidc_discovery_and_jwks_on_refresh_error(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        class FakeJsonResponse:
            status_code = 200

            def __init__(self, payload: object | None) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                if self.payload is None:
                    raise ValueError("temporary upstream parse failure")
                return self.payload

        issuer = "https://idp.example.test/realms/geno"
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        jwks_url = "https://idp.example.test/realms/geno/protocol/openid-connect/certs"
        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "stale-oidc-owner", "iss": issuer})
        jwks_payload = json.loads(jwks_json)
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeJsonResponse:
            calls.append(url)
            if len(calls) > 2:
                return FakeJsonResponse(None)
            if url == discovery_url:
                return FakeJsonResponse({"issuer": issuer, "jwks_uri": jwks_url})
            if url == jwks_url:
                return FakeJsonResponse(jwks_payload)
            raise AssertionError(f"unexpected runtime auth fetch: {url}")

        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "",
                "GENO_RUNTIME_JWKS_URL": "",
                "GENO_RUNTIME_JWT_ISSUER": issuer,
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "0",
                "GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS": "60",
                "GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS": "0",
                "GENO_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS": "60",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.25",
            },
            clear=False,
        ), patch("geno_api.main.httpx.get", side_effect=fake_get), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            first = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})
            second = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "stale-oidc-owner")
        self.assertEqual(calls, [discovery_url, jwks_url, discovery_url, jwks_url])

    def test_runtime_projects_endpoint_rejects_jwks_token_signed_by_untrusted_key(self) -> None:
        token, _ = self._runtime_jwks_rs256_token(payload={"sub": "jwks-owner"}, key_id="runtime-key-1")
        _, trusted_jwks_json = self._runtime_jwks_rs256_token(key_id="runtime-key-1")
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": trusted_jwks_json,
            },
            clear=False,
        ):
            response = self.client.get("/v1/projects/runtime", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 401)
        self.assertIn("invalid runtime JWT signature", response.json()["detail"])

    def test_runtime_project_member_save_endpoint_uses_jwt_actor_when_jwt_auth_mode_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "admin"

            def set_runtime_project_access_context(self, **kwargs: object) -> None:
                self.context_kwargs = kwargs

            def save_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                self.member = member
                return RuntimeProjectMember(member={"id": "member-1", "project_id": member.project_id}, audit_events=())

        fake_repository = FakeRepository()
        token = self._runtime_jwt(payload={"sub": "jwt-admin"})
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
                "GENO_RUNTIME_JWT_SECRET": "test-runtime-secret",
            },
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                    "role": "viewer",
                    "updated_by": "payload-user",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "jwt-admin")
        self.assertEqual(fake_repository.context_kwargs["actor_id"], "jwt-admin")
        self.assertEqual(fake_repository.member.updated_by, "jwt-admin")

    def test_runtime_project_members_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/project-members/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_members_endpoint_passes_project_filter(self) -> None:
        class FakeRepository:
            def list_runtime_project_members(self, **kwargs: object) -> RuntimeProjectMemberPage:
                self.kwargs = kwargs
                return RuntimeProjectMemberPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeProjectMember(
                            member={
                                "id": "member-1",
                                "project_id": kwargs["project_id"],
                                "user_id": "analyst@example.com",
                                "role": "analyst",
                            },
                            audit_events=(),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/project-members/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&limit=5&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["records"][0]["member"]["user_id"], "analyst@example.com")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_project_members_endpoint_checks_access_control_when_enabled(self) -> None:
        class FakeRepository:
            def user_can_access_project(self, **kwargs: object) -> bool:
                self.access_kwargs = kwargs
                return False

            def list_runtime_project_members(self, **kwargs: object) -> object:
                raise AssertionError("list_runtime_project_members should not be called when access is denied")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.get(
                "/v1/project-members/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(fake_repository.access_kwargs["actor_id"], "agency-owner")

    def test_runtime_project_member_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                self.member = member
                return RuntimeProjectMember(
                    member={
                        "id": "member-1",
                        "project_id": member.project_id,
                        "user_id": member.user_id,
                        "role": member.role,
                    },
                    audit_events=(
                        {
                            "event_type": "project_member_saved",
                            "target_type": "project_member",
                            "method_version": "project_member_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "analyst@example.com",
                    "role": "analyst",
                    "updated_by": "agency-owner",
                    "reason": "add analyst",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["member"]["role"], "analyst")
        self.assertEqual(response.json()["audit_events"][0]["event_type"], "project_member_saved")
        self.assertEqual(fake_repository.member.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.member.user_id, "analyst@example.com")
        self.assertEqual(fake_repository.member.role, "analyst")

    def test_runtime_project_member_save_endpoint_uses_actor_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "admin"

            def set_runtime_project_access_context(self, **kwargs: object) -> None:
                self.context_kwargs = kwargs

            def save_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                self.member = member
                return RuntimeProjectMember(member={"id": "member-1", "project_id": member.project_id}, audit_events=())

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                    "role": "viewer",
                    "updated_by": "payload-user",
                },
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-owner")
        self.assertEqual(fake_repository.context_kwargs["actor_id"], "agency-owner")
        self.assertEqual(fake_repository.context_kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.member.updated_by, "agency-owner")

    def test_runtime_project_member_save_endpoint_requires_admin_or_owner_role_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "analyst"

            def save_runtime_project_member(self, member: object) -> object:
                raise AssertionError("save_runtime_project_member should not be called for analyst role")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                    "role": "viewer",
                },
                headers={"X-GENO-Actor-Id": "agency-analyst"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("requires owner, admin", response.json()["detail"])
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-analyst")

    def test_runtime_project_member_delete_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def delete_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                self.member = member
                return RuntimeProjectMember(
                    member={
                        "id": "member-1",
                        "project_id": member.project_id,
                        "user_id": member.user_id,
                        "role": "viewer",
                    },
                    audit_events=(
                        {
                            "event_type": "project_member_deleted",
                            "target_type": "project_member",
                            "method_version": "project_member_delete_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.request(
                "DELETE",
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                    "deleted_by": "agency-owner",
                    "reason": "remove viewer",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit_events"][0]["event_type"], "project_member_deleted")
        self.assertEqual(fake_repository.member.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.member.user_id, "viewer@example.com")
        self.assertEqual(fake_repository.member.deleted_by, "agency-owner")

    def test_runtime_project_member_delete_endpoint_uses_actor_and_requires_admin_or_owner_role(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "admin"

            def delete_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                self.member = member
                return RuntimeProjectMember(member={"id": "member-1", "user_id": member.user_id}, audit_events=())

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.request(
                "DELETE",
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                    "deleted_by": "payload-user",
                },
                headers={"X-GENO-Actor-Id": "agency-admin"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-admin")
        self.assertEqual(fake_repository.member.deleted_by, "agency-admin")

    def test_runtime_project_member_delete_endpoint_forbids_viewer_role_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "viewer"

            def delete_runtime_project_member(self, member: object) -> object:
                raise AssertionError("delete_runtime_project_member should not be called for viewer role")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.request(
                "DELETE",
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                },
                headers={"X-GENO-Actor-Id": "agency-viewer"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("requires owner, admin", response.json()["detail"])
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-viewer")

    def test_runtime_project_member_delete_endpoint_maps_last_owner_guard_to_400(self) -> None:
        class FakeRepository:
            def delete_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                raise ValueError("cannot remove or downgrade the last project owner")

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.request(
                "DELETE",
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "owner@example.com",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("last project owner", response.json()["detail"])

    def test_runtime_prompts_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/prompts/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_prompts_endpoint_requires_project_id_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def user_can_access_project(self, **kwargs: object) -> bool:
                return True

        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=FakeRepository()
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.get("/v1/prompts/runtime", headers={"X-GENO-Actor-Id": "agency-owner"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("project_id is required", response.json()["detail"])

    def test_runtime_prompts_endpoint_forbids_project_without_membership_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def user_can_access_project(self, **kwargs: object) -> bool:
                self.access_kwargs = kwargs
                return False

            def list_runtime_prompts(self, **kwargs: object) -> object:
                raise AssertionError("list_runtime_prompts should not be called when access is denied")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.get(
                "/v1/prompts/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(fake_repository.access_kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.access_kwargs["actor_id"], "agency-owner")

    def test_runtime_prompt_import_endpoint_requires_admin_or_owner_role_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "viewer"

            def import_runtime_prompts_csv(self, prompt_import: object) -> object:
                raise AssertionError("import_runtime_prompts_csv should not be called for viewer role")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/prompts/runtime/import.csv",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "csv_content": "text,intent_type\nIs ExampleBrand visible?,brand_awareness\n",
                    "imported_by": "runtime-console",
                    "max_rows": 100,
                },
                headers={"X-GENO-Actor-Id": "agency-viewer"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("requires owner, admin", response.json()["detail"])
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-viewer")

    def test_runtime_human_review_save_endpoint_allows_analyst_role_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "analyst"

            def save_human_review(self, review: object) -> RuntimeHumanReviewRecord:
                self.review = review
                return RuntimeHumanReviewRecord(
                    human_review={
                        "id": "review-1",
                        "project_id": review.project_id,
                        "target_type": review.target_type,
                        "target_id": review.target_id,
                        "review_status": review.review_status,
                        "decision": review.decision,
                        "reviewer_id": review.reviewer_id,
                        "notes": review.notes,
                        "payload": review.payload,
                    },
                    audit_events=({"event_type": "human_review_recorded"},),
                )

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/human-reviews/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "target_type": "visibility_score_snapshot",
                    "target_id": "38f0251c-c380-4197-b6c9-3e630b127844",
                    "review_status": "approved",
                    "decision": "approved_for_report",
                    "reviewer_id": "agency-analyst",
                    "payload": {},
                },
                headers={"X-GENO-Actor-Id": "agency-analyst"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-analyst")
        self.assertEqual(fake_repository.review.decision, "approved_for_report")

    def test_runtime_human_review_save_endpoint_forbids_viewer_role_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "viewer"

            def save_human_review(self, review: object) -> object:
                raise AssertionError("save_human_review should not be called for viewer role")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/human-reviews/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "target_type": "visibility_score_snapshot",
                    "target_id": "38f0251c-c380-4197-b6c9-3e630b127844",
                    "review_status": "approved",
                    "decision": "approved_for_report",
                    "reviewer_id": "agency-viewer",
                    "payload": {},
                },
                headers={"X-GENO-Actor-Id": "agency-viewer"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("requires owner, admin, analyst", response.json()["detail"])
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-viewer")

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

    def test_runtime_prompt_file_import_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/prompts/runtime/import.file"
            "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&filename=prompts.csv",
            content=b"text,intent_type\nIs ExampleBrand visible?,brand_awareness\n",
            headers={"content-type": "text/csv"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_prompt_import_history_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/prompts/runtime/imports?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&limit=5"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_prompt_import_history_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_prompt_imports(self, **kwargs: object) -> RuntimePromptImportHistoryPage:
                self.kwargs = kwargs
                return RuntimePromptImportHistoryPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimePromptImportHistoryItem(
                            prompt_import={
                                "id": "prompt-import-1",
                                "project_id": kwargs["project_id"],
                                "source_format": kwargs["source_format"],
                                "source_filename": "prompts.xlsx",
                                "prompt_count": 1,
                                "csv_sha256": "hash",
                            },
                            audit_events=(
                                {
                                    "event_type": "runtime_prompts_imported",
                                    "method_version": "runtime_prompt_import_xlsx_v1",
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
                "/v1/prompts/runtime/imports"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&source_format=xlsx&limit=5&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["prompt_import"]["source_format"], "xlsx")
        self.assertEqual(payload["records"][0]["audit_events"][0]["method_version"], "runtime_prompt_import_xlsx_v1")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["source_format"], "xlsx")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

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

    def test_runtime_prompt_file_import_endpoint_parses_xlsx_payload(self) -> None:
        class FakeRepository:
            def import_runtime_prompts_csv(self, prompt_import: object) -> RuntimePromptImportResult:
                self.prompt_import = prompt_import
                return RuntimePromptImportResult(
                    prompt_import={
                        "project_id": prompt_import.project_id,
                        "prompt_count": 1,
                        "prompt_ids": ["prompt-1"],
                        "prompt_version": "au_dtc_ecommerce_v1_imported",
                        "source_format": prompt_import.source_format,
                        "source_filename": prompt_import.source_filename,
                    },
                    prompts=(
                        {
                            "id": "prompt-1",
                            "project_id": prompt_import.project_id,
                            "text": "Is ExampleBrand visible in AI answers?",
                            "intent_type": "brand_awareness",
                        },
                    ),
                    audit_events=(
                        {
                            "event_type": "runtime_prompts_imported",
                            "target_type": "prompt_import",
                            "method_version": "runtime_prompt_import_xlsx_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/prompts/runtime/import.file"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&filename=prompts.xlsx&imported_by=runtime-console&max_rows=100",
                content=self._xlsx_prompt_import_bytes(),
                headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["prompt_import"]["source_format"], "xlsx")
        self.assertEqual(payload["audit_events"][0]["method_version"], "runtime_prompt_import_xlsx_v1")
        self.assertEqual(fake_repository.prompt_import.source_filename, "prompts.xlsx")
        self.assertEqual(fake_repository.prompt_import.source_format, "xlsx")
        self.assertIn("Is ExampleBrand visible in AI answers?", fake_repository.prompt_import.csv_content)

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

    def test_runtime_fidelity_trend_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/fidelity-checks/runtime/trend?limit=10")
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

    def test_runtime_fidelity_trend_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def get_runtime_fidelity_trend(self, **kwargs: object) -> RuntimeFidelityTrend:
                self.kwargs = kwargs
                return RuntimeFidelityTrend(
                    project_id=kwargs["project_id"],
                    report_export_id=kwargs["report_export_id"],
                    total_count=2,
                    sampled_count=2,
                    limit=int(kwargs["limit"]),
                    latest_status="sampled",
                    latest_checked_at="2026-06-10T01:00:00+00:00",
                    earliest_checked_at="2026-06-10T00:00:00+00:00",
                    latest_difference_rate=0.5,
                    earliest_difference_rate=0.25,
                    average_difference_rate=0.375,
                    max_difference_rate=0.5,
                    trend_direction="worsening",
                    points=(
                        RuntimeFidelityTrendPoint(
                            id="9d0ccf2f-4058-5efd-a3d3-fef60a73191a",
                            project_id=str(kwargs["project_id"]),
                            report_export_id=str(kwargs["report_export_id"]),
                            status="sampled",
                            official_api_records=10,
                            browser_records=10,
                            comparable_prompt_city_pairs=4,
                            mismatch_count=1,
                            difference_rate=0.25,
                            payload_hash="b" * 64,
                            checked_at="2026-06-10T00:00:00+00:00",
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/fidelity-checks/runtime/trend"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&report_export_id=b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
                "&limit=10"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["trend_direction"], "worsening")
        self.assertEqual(payload["average_difference_rate"], 0.375)
        self.assertEqual(payload["points"][0]["difference_rate"], 0.25)
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["report_export_id"], "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad")
        self.assertEqual(fake_repository.kwargs["limit"], 10)

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

    def test_runtime_project_brand_logo_upload_endpoint_requires_object_store_config(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> object:
                self.kwargs = kwargs
                return type("RuntimeProjectPage", (), {"total_count": 1})()

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-brand-kits/runtime/logo"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&filename=logo.png"
                "&uploaded_by=runtime-console",
                content=b"fake-logo-bytes",
                headers={"content-type": "image/png"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("OBJECT_STORE_ENDPOINT", response.json()["detail"])
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")

    def test_runtime_project_brand_logo_upload_endpoint_archives_and_saves(self) -> None:
        class FakeStore:
            def put_object(self, **kwargs: object) -> object:
                self.kwargs = kwargs
                return type(
                    "StoredObject",
                    (),
                    {
                        "uri": "s3://geno-reports/brand-assets/project/logo-25f766a3e701-logo.png",
                        "content_type": kwargs["content_type"],
                        "content_hash": "25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b",
                    },
                )()

        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> object:
                self.list_kwargs = kwargs
                return type("RuntimeProjectPage", (), {"total_count": 1})()

            def upload_project_brand_logo(self, upload: RuntimeProjectBrandLogoUpload) -> RuntimeProjectBrandKit:
                self.upload = upload
                return RuntimeProjectBrandKit(
                    brand_kit={
                        "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
                        "project_id": upload.project_id,
                        "client_name": "Koala AU",
                        "prepared_by": "Partner Agency",
                        "logo_url": upload.logo_url,
                        "primary_color": "#0f766e",
                        "secondary_color": "#111827",
                        "footer_text": "Prepared for Koala AU board review",
                        "updated_by": upload.uploaded_by,
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_logo_uploaded",
                            "target_type": "project_brand_kit",
                            "method_version": "project_brand_logo_upload_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        fake_store = FakeStore()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.build_object_store_from_env", return_value=fake_store
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/project-brand-kits/runtime/logo"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&filename=Client%20Logo.png"
                "&uploaded_by=agency-user",
                content=b"fake-logo-bytes",
                headers={"content-type": "image/png"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["brand_kit"]["logo_url"], "s3://geno-reports/brand-assets/project/logo-25f766a3e701-logo.png")
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_brand_logo_uploaded")
        self.assertEqual(fake_store.kwargs["content"], b"fake-logo-bytes")
        self.assertEqual(fake_store.kwargs["content_type"], "image/png")
        self.assertEqual(fake_repository.upload.filename, "Client Logo.png")
        self.assertEqual(fake_repository.upload.uploaded_by, "agency-user")
        self.assertEqual(fake_repository.upload.content_hash, "25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b")

    def test_runtime_project_brand_asset_versions_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/project-brand-kits/runtime/assets?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_brand_asset_versions_endpoint_returns_versions(self) -> None:
        class FakeRepository:
            def list_project_brand_asset_versions(self, **kwargs: object) -> RuntimeProjectBrandAssetVersionPage:
                self.kwargs = kwargs
                return RuntimeProjectBrandAssetVersionPage(
                    project_id=str(kwargs["project_id"]),
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeProjectBrandAssetVersion(
                            version_id="ce333139-53e7-44c8-8c85-ce498d841391",
                            project_id=str(kwargs["project_id"]),
                            asset_type="logo",
                            asset_url="s3://geno-reports/brand-assets/project/logo.png",
                            source_filename="Client Logo.png",
                            source_content_type="image/png",
                            content_hash="25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b",
                            uploaded_by="agency-user",
                            uploaded_at=None,
                            is_active=True,
                            audit_event={"event_type": "project_brand_logo_uploaded"},
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/project-brand-kits/runtime/assets"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&limit=5&offset=0"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["asset_type"], "logo")
        self.assertTrue(payload["records"][0]["is_active"])
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_project_brand_assets_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/project-brand-assets/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_brand_assets_endpoint_returns_assets(self) -> None:
        class FakeRepository:
            def list_project_brand_assets(self, **kwargs: object) -> RuntimeProjectBrandAssetPage:
                self.kwargs = kwargs
                return RuntimeProjectBrandAssetPage(
                    project_id=str(kwargs["project_id"]),
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeProjectBrandAsset(
                            asset={
                                "id": "ddc23a34-2ffb-5a56-a81a-3b98aaf843b4",
                                "project_id": str(kwargs["project_id"]),
                                "asset_type": "image",
                                "asset_url": "s3://geno-reports/brand-assets/project/hero.png",
                                "category": "brand_creative",
                                "preview_url": "https://cdn.example.com/project/hero-preview.png",
                                "source_filename": "hero.png",
                                "source_content_type": "image/png",
                                "content_hash": "4d8f0cfa7e4b8f76dd5bce99d403d9fa",
                                "storage_version": "etag-hero-v1",
                                "status": "active",
                                "scan_status": "passed",
                                "scan_checked_at": None,
                                "scan_method_version": "manual_asset_scan_v1",
                                "scan_notes": "Clean preview",
                                "uploaded_by": "agency-user",
                                "metadata": {"source": "runtime_console_asset_register"},
                            },
                            audit_events=(
                                {
                                    "event_type": "project_brand_asset_registered",
                                    "target_type": "project_brand_asset",
                                    "method_version": "project_brand_asset_library_v1",
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
                "/v1/project-brand-assets/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&asset_type=image&category=brand_creative&status=active&limit=5&offset=0"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["asset"]["asset_type"], "image")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "project_brand_asset_registered")
        self.assertEqual(fake_repository.kwargs["asset_type"], "image")
        self.assertEqual(fake_repository.kwargs["category"], "brand_creative")
        self.assertEqual(fake_repository.kwargs["status"], "active")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_project_brand_asset_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_project_brand_asset(self, asset: RuntimeProjectBrandAssetInput) -> RuntimeProjectBrandAsset:
                self.asset = asset
                return RuntimeProjectBrandAsset(
                    asset={
                        "id": "ddc23a34-2ffb-5a56-a81a-3b98aaf843b4",
                        "project_id": asset.project_id,
                        "asset_type": asset.asset_type,
                        "asset_url": asset.asset_url,
                        "category": asset.category,
                        "preview_url": asset.preview_url,
                        "source_filename": asset.source_filename,
                        "source_content_type": asset.source_content_type,
                        "content_hash": asset.content_hash,
                        "storage_version": asset.storage_version,
                        "status": asset.status,
                        "scan_status": "pending",
                        "scan_checked_at": None,
                        "scan_method_version": None,
                        "scan_notes": None,
                        "uploaded_by": asset.uploaded_by,
                        "metadata": asset.metadata,
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_asset_registered",
                            "target_type": "project_brand_asset",
                            "method_version": "project_brand_asset_library_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-brand-assets/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "asset_type": "image",
                    "asset_url": "s3://geno-reports/brand-assets/project/hero.png",
                    "category": "brand_creative",
                    "preview_url": "https://cdn.example.com/project/hero-preview.png",
                    "source_filename": "hero.png",
                    "source_content_type": "image/png",
                    "content_hash": "4d8f0cfa7e4b8f76dd5bce99d403d9fa",
                    "storage_version": "etag-hero-v1",
                    "status": "active",
                    "uploaded_by": "agency-user",
                    "metadata": {"source": "runtime_console_asset_register"},
                    "reason": "register project asset",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["asset"]["asset_url"], "s3://geno-reports/brand-assets/project/hero.png")
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_brand_asset_registered")
        self.assertIsInstance(fake_repository.asset, RuntimeProjectBrandAssetInput)
        self.assertEqual(fake_repository.asset.category, "brand_creative")
        self.assertEqual(fake_repository.asset.preview_url, "https://cdn.example.com/project/hero-preview.png")
        self.assertEqual(fake_repository.asset.reason, "register project asset")

    def test_runtime_project_brand_asset_scan_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def get_project_brand_asset_project_id(self, **kwargs: object) -> str | None:
                self.project_lookup = kwargs
                return "9a50797d-a341-55a4-8bdf-cc255c017e5c"

            def update_project_brand_asset_scan_status(
                self,
                scan: RuntimeProjectBrandAssetScanInput,
            ) -> RuntimeProjectBrandAsset:
                self.scan = scan
                return RuntimeProjectBrandAsset(
                    asset={
                        "id": scan.asset_id,
                        "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                        "asset_type": "image",
                        "asset_url": "s3://geno-reports/brand-assets/project/hero.png",
                        "category": "brand_creative",
                        "preview_url": "https://cdn.example.com/project/hero-preview.png",
                        "source_filename": "hero.png",
                        "source_content_type": "image/png",
                        "content_hash": "4d8f0cfa7e4b8f76dd5bce99d403d9fa",
                        "storage_version": "etag-hero-v1",
                        "status": "active",
                        "scan_status": scan.scan_status,
                        "scan_checked_at": None,
                        "scan_method_version": scan.scan_method_version,
                        "scan_notes": scan.scan_notes,
                        "uploaded_by": "agency-user",
                        "metadata": {"source": "runtime_console_asset_register"},
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_asset_scan_recorded",
                            "target_type": "project_brand_asset",
                            "method_version": scan.scan_method_version,
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-brand-assets/runtime/ddc23a34-2ffb-5a56-a81a-3b98aaf843b4/scan-status",
                json={
                    "scan_status": "passed",
                    "scanned_by": "agency-user",
                    "scan_method_version": "manual_asset_scan_v1",
                    "scan_notes": "Clean preview",
                    "reason": "manual scan passed",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["asset"]["scan_status"], "passed")
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_brand_asset_scan_recorded")
        self.assertEqual(fake_repository.project_lookup["asset_id"], "ddc23a34-2ffb-5a56-a81a-3b98aaf843b4")
        self.assertIsInstance(fake_repository.scan, RuntimeProjectBrandAssetScanInput)
        self.assertEqual(fake_repository.scan.scan_notes, "Clean preview")

    def test_runtime_project_brand_asset_activation_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def activate_project_brand_logo_version(self, activation: object) -> RuntimeProjectBrandKit:
                self.activation = activation
                return RuntimeProjectBrandKit(
                    brand_kit={
                        "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
                        "project_id": activation.project_id,
                        "client_name": "Koala AU",
                        "prepared_by": "Partner Agency",
                        "logo_url": activation.asset_url,
                        "primary_color": "#0f766e",
                        "secondary_color": "#111827",
                        "footer_text": "Prepared for Koala AU board review",
                        "updated_by": activation.activated_by,
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_logo_version_activated",
                            "target_type": "project_brand_kit",
                            "method_version": "project_brand_logo_asset_version_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-brand-kits/runtime/assets/activate",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "asset_url": "s3://geno-reports/brand-assets/project/logo.png",
                    "activated_by": "agency-admin",
                    "reason": "restore previous logo",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["brand_kit"]["logo_url"], "s3://geno-reports/brand-assets/project/logo.png")
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_brand_logo_version_activated")
        self.assertEqual(fake_repository.activation.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.activation.activated_by, "agency-admin")
        self.assertEqual(fake_repository.activation.reason, "restore previous logo")

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

    def test_runtime_human_review_queue_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/human-reviews/runtime/queue?queue_status=pending_review")
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

    def test_runtime_human_review_queue_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_human_review_queue(self, **kwargs: object) -> RuntimeHumanReviewQueuePage:
                self.kwargs = kwargs
                return RuntimeHumanReviewQueuePage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeHumanReviewQueueItem(
                            project_id=str(kwargs["project_id"]),
                            target_type=str(kwargs["target_type"]),
                            target_id="1e53e0b4-7b1a-54d6-a918-fd8774df7bdd",
                            title="AU shipping proof page",
                            queue_status=str(kwargs["queue_status"]),
                            priority=9,
                            reason="content_draft_pending_human_review",
                            created_at="2026-06-10T00:00:00+00:00",
                            latest_review=None,
                            evidence_refs={"answer_run_ids": ["438ab927-5873-5516-8df3-47f6c75ef007"]},
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/human-reviews/runtime/queue"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&target_type=content_draft&queue_status=pending_review&limit=5&offset=1"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["queue_status"], "pending_review")
        self.assertEqual(payload["records"][0]["evidence_refs"]["answer_run_ids"], ["438ab927-5873-5516-8df3-47f6c75ef007"])
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["target_type"], "content_draft")
        self.assertEqual(fake_repository.kwargs["queue_status"], "pending_review")
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

    def test_runtime_human_review_save_endpoint_maps_missing_content_draft_to_404(self) -> None:
        class FakeRepository:
            def save_human_review(self, review: object) -> RuntimeHumanReviewRecord:
                raise ValueError("content draft not found")

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/human-reviews/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "target_type": "content_draft",
                    "target_id": "1e53e0b4-7b1a-54d6-a918-fd8774df7bdd",
                    "review_status": "approved",
                    "decision": "approved_for_publish",
                    "reviewer_id": "runtime-console",
                },
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "content draft not found")

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

    def test_runtime_report_management_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/reports/runtime/report-1/management-events",
            json={"status": "client_ready", "updated_by": "runtime-console"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_management_endpoint_records_status_event(self) -> None:
        class FakeRepository:
            def record_runtime_report_management_event(self, event: object) -> RuntimeReportExport:
                self.event = event
                return RuntimeReportExport(
                    report_export={"id": event.report_export_id, "project_id": "project-1", "report_version": "worker-runtime-v1"},
                    score_snapshots=(),
                    answer_runs=(),
                    citation_graph=None,
                    audit_events=(
                        {
                            "event_type": "report_export_management_recorded",
                            "target_type": "report_export",
                            "target_id": event.report_export_id,
                            "actor_id": event.updated_by,
                            "method_version": "report_export_management_v1",
                            "reason": event.note,
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/reports/runtime/report-1/management-events",
                json={"status": "client_ready", "updated_by": "runtime-console", "note": "Ready for client"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["report_export"]["id"], "report-1")
        self.assertEqual(payload["audit_events"][0]["event_type"], "report_export_management_recorded")
        self.assertEqual(fake_repository.event.report_export_id, "report-1")
        self.assertEqual(fake_repository.event.status, "client_ready")
        self.assertEqual(fake_repository.event.updated_by, "runtime-console")
        self.assertEqual(fake_repository.event.note, "Ready for client")

    def test_runtime_report_export_jobs_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/report-export-jobs/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_export_jobs_endpoint_returns_jobs(self) -> None:
        class FakeRepository:
            def list_runtime_report_export_jobs(self, **kwargs: object) -> RuntimeReportExportJobPage:
                self.kwargs = kwargs
                return RuntimeReportExportJobPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeReportExportJob(
                            report_export_job={
                                "id": "job-1",
                                "project_id": kwargs["project_id"],
                                "status": "queued",
                                "artifact_type": "pdf",
                                "template": "white_label",
                                "filters": {"platform": "perplexity"},
                                "sort": "cost_desc",
                                "requested_by": "runtime-console",
                                "updated_by": "runtime-console",
                            },
                            audit_events=({"event_type": "report_export_job_queued"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/report-export-jobs/runtime?project_id=project-1&status=queued&limit=5&offset=0"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["report_export_job"]["template"], "white_label")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "report_export_job_queued")
        self.assertEqual(fake_repository.kwargs["status"], "queued")

    def test_runtime_report_export_job_stats_endpoint_returns_queue_metrics(self) -> None:
        class FakeRepository:
            def get_runtime_report_export_job_queue_stats(self, **kwargs: object) -> RuntimeReportExportJobQueueStats:
                self.kwargs = kwargs
                return RuntimeReportExportJobQueueStats(
                    total_count=4,
                    status_counts={"queued": 2, "running": 1, "dead_letter": 1},
                    retryable_count=2,
                    expired_running_count=1,
                    max_attempts_reached_count=1,
                    oldest_queued_at=None,
                    generated_at=datetime.now(UTC),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get("/v1/report-export-jobs/runtime/stats?project_id=project-1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 4)
        self.assertEqual(payload["status_counts"]["dead_letter"], 1)
        self.assertEqual(payload["retryable_count"], 2)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")

    def test_runtime_notifications_endpoint_returns_project_inbox(self) -> None:
        class FakeRepository:
            def list_runtime_notifications(self, **kwargs: object) -> RuntimeNotificationPage:
                self.kwargs = kwargs
                return RuntimeNotificationPage(
                    total_count=1,
                    unread_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeNotification(
                            notification={
                                "id": "notification-1",
                                "project_id": kwargs["project_id"],
                                "notification_type": "report_export_job",
                                "severity": "critical",
                                "title": "Report export dead-lettered",
                                "message": "pdf/standard report export job dead_letter.",
                                "target_type": "report_export_job",
                                "target_id": "job-1",
                                "recipient_role": "project_member",
                                "status": "unread",
                                "payload": {"status": "dead_letter"},
                                "created_by": "runtime-worker",
                                "updated_by": "runtime-worker",
                            },
                            audit_events=({"event_type": "runtime_notification_created"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notifications?project_id=project-1&status=unread&notification_type=report_export_job&limit=5"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["unread_count"], 1)
        self.assertEqual(payload["records"][0]["notification"]["severity"], "critical")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "runtime_notification_created")
        self.assertEqual(fake_repository.kwargs["notification_type"], "report_export_job")

    def test_runtime_notification_status_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def get_runtime_notification_project_id(self, *, notification_id: str) -> str:
                self.notification_id = notification_id
                return "project-1"

            def update_runtime_notification_status(self, update: object) -> RuntimeNotification:
                self.update = update
                return RuntimeNotification(
                    notification={
                        "id": update.notification_id,
                        "project_id": "project-1",
                        "notification_type": "report_export_job",
                        "severity": "info",
                        "title": "Report export succeeded",
                        "message": "pdf/standard report export job succeeded.",
                        "target_type": "report_export_job",
                        "target_id": "job-1",
                        "recipient_role": "project_member",
                        "status": update.status,
                        "payload": {"status": "succeeded"},
                        "created_by": "runtime-worker",
                        "updated_by": update.updated_by,
                    },
                    audit_events=({"event_type": "runtime_notification_status_updated"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notifications/notification-1/status",
                json={"status": "read", "updated_by": "runtime-console", "reason": "mark read"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["notification"]["status"], "read")
        self.assertEqual(payload["audit_events"][0]["event_type"], "runtime_notification_status_updated")
        self.assertEqual(fake_repository.notification_id, "notification-1")
        self.assertEqual(fake_repository.update.reason, "mark read")

    def test_runtime_notification_subscriptions_endpoint_returns_page(self) -> None:
        class FakeRepository:
            def list_runtime_notification_subscriptions(self, **kwargs: object) -> RuntimeNotificationSubscriptionPage:
                self.kwargs = kwargs
                return RuntimeNotificationSubscriptionPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeNotificationSubscription(
                            subscription={
                                "id": "subscription-1",
                                "project_id": kwargs["project_id"],
                                "channel": "webhook",
                                "endpoint_url": "https://hooks.example.com/geno",
                                "event_types": ["report_export_job"],
                                "severity_threshold": "warning",
                                "status": "active",
                                "metadata": {"source": "contract"},
                                "created_by": "runtime-console",
                                "updated_by": "runtime-console",
                            },
                            audit_events=({"event_type": "runtime_notification_subscription_saved"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notification-subscriptions?project_id=project-1&status=active&limit=5"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["subscription"]["endpoint_url"], "https://hooks.example.com/geno")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "runtime_notification_subscription_saved")
        self.assertEqual(fake_repository.kwargs["status"], "active")

    def test_runtime_notification_subscription_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_runtime_notification_subscription(self, subscription: object) -> RuntimeNotificationSubscription:
                self.subscription = subscription
                return RuntimeNotificationSubscription(
                    subscription={
                        "id": "subscription-1",
                        "project_id": subscription.project_id,
                        "channel": subscription.channel,
                        "endpoint_url": subscription.endpoint_url,
                        "event_types": list(subscription.event_types),
                        "severity_threshold": subscription.severity_threshold,
                        "status": subscription.status,
                        "metadata": subscription.metadata,
                        "created_by": subscription.updated_by,
                        "updated_by": subscription.updated_by,
                    },
                    audit_events=({"event_type": "runtime_notification_subscription_saved"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-subscriptions",
                json={
                    "project_id": "project-1",
                    "endpoint_url": "https://hooks.example.com/geno",
                    "event_types": ["report_export_job"],
                    "severity_threshold": "critical",
                    "status": "active",
                    "metadata": {"source": "api-test"},
                    "updated_by": "runtime-console",
                    "reason": "save webhook",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subscription"]["severity_threshold"], "critical")
        self.assertEqual(fake_repository.subscription.endpoint_url, "https://hooks.example.com/geno")
        self.assertEqual(fake_repository.subscription.reason, "save webhook")

    def test_runtime_notification_deliveries_endpoint_returns_page(self) -> None:
        class FakeRepository:
            def list_runtime_notification_deliveries(self, **kwargs: object) -> RuntimeNotificationDeliveryPage:
                self.kwargs = kwargs
                return RuntimeNotificationDeliveryPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeNotificationDelivery(
                            delivery={
                                "id": "delivery-1",
                                "project_id": kwargs["project_id"],
                                "notification_id": "notification-1",
                                "subscription_id": "subscription-1",
                                "channel": "webhook",
                                "endpoint_url": "https://hooks.example.com/geno",
                                "status": "queued",
                                "attempt_count": 0,
                                "max_attempts": 3,
                                "payload": {"delivery_version": "runtime_notification_delivery_v1"},
                                "updated_by": "runtime-worker",
                            },
                            notification={"id": "notification-1", "title": "Report export failed"},
                            subscription={"id": "subscription-1", "endpoint_url": "https://hooks.example.com/geno"},
                            audit_events=({"event_type": "runtime_notification_delivery_queued"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notification-deliveries?project_id=project-1&status=queued&limit=5"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["delivery"]["status"], "queued")
        self.assertEqual(payload["records"][0]["notification"]["title"], "Report export failed")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "runtime_notification_delivery_queued")
        self.assertEqual(fake_repository.kwargs["status"], "queued")

    def test_runtime_report_export_job_enqueue_and_status_endpoints_pass_payload(self) -> None:
        class FakeRepository:
            def __init__(self) -> None:
                self.enqueued = None
                self.updated = None

            def get_report_export_job_project_id(self, *, job_id: str) -> str:
                self.job_id = job_id
                return "project-1"

            def enqueue_runtime_report_export_job(self, job: object) -> RuntimeReportExportJob:
                self.enqueued = job
                return RuntimeReportExportJob(
                    report_export_job={
                        "id": "job-1",
                        "project_id": job.project_id,
                        "report_export_id": job.report_export_id,
                        "status": "queued",
                        "artifact_type": job.artifact_type,
                        "template": job.template,
                        "filters": job.filters,
                        "sort": job.sort,
                        "requested_by": job.requested_by,
                        "updated_by": job.requested_by,
                    },
                    audit_events=({"event_type": "report_export_job_queued"},),
                )

            def update_runtime_report_export_job_status(self, update: object) -> RuntimeReportExportJob:
                self.updated = update
                return RuntimeReportExportJob(
                    report_export_job={
                        "id": update.job_id,
                        "project_id": "project-1",
                        "report_export_id": update.report_export_id,
                        "status": update.status,
                        "artifact_type": "pdf",
                        "template": "standard",
                        "filters": {},
                        "sort": "collected_at_desc",
                        "requested_by": "runtime-console",
                        "updated_by": update.updated_by,
                        "artifact_url": update.artifact_url,
                    },
                    audit_events=({"event_type": "report_export_job_status_updated"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            enqueue_response = self.client.post(
                "/v1/report-export-jobs/runtime",
                json={
                    "project_id": "project-1",
                    "report_export_id": "report-1",
                    "artifact_type": "pdf",
                    "template": "standard",
                    "filters": {"city": "Sydney"},
                    "sort": "cost_desc",
                    "requested_by": "runtime-console",
                },
            )
            status_response = self.client.post(
                "/v1/report-export-jobs/runtime/job-1/status",
                json={
                    "status": "succeeded",
                    "updated_by": "runtime-console",
                    "report_export_id": "report-1",
                    "artifact_url": "s3://geno-reports/report.pdf",
                },
            )
        self.assertEqual(enqueue_response.status_code, 200)
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(enqueue_response.json()["audit_events"][0]["event_type"], "report_export_job_queued")
        self.assertEqual(status_response.json()["audit_events"][0]["event_type"], "report_export_job_status_updated")
        self.assertEqual(fake_repository.enqueued.filters["city"], "Sydney")
        self.assertEqual(fake_repository.updated.status, "succeeded")
        self.assertEqual(fake_repository.updated.artifact_url, "s3://geno-reports/report.pdf")

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

    def test_runtime_report_artifact_signed_url_requires_signing_secret(self) -> None:
        class FakeRepository:
            def get_report_export_project_id(self, *, report_export_id: str) -> str:
                return "project-1"

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()), patch(
            "geno_api.main.close_repository_connection"
        ), patch.dict("os.environ", {}, clear=True):
            response = self.client.get("/v1/reports/runtime/report-1/artifact/signed-url?type=pdf")
        self.assertEqual(response.status_code, 503)
        self.assertIn("GENO_REPORT_ARTIFACT_SIGNING_SECRET", response.json()["detail"])

    def test_runtime_report_artifact_signed_url_downloads_and_rejects_tampering(self) -> None:
        class FakeRepository:
            def get_report_export_project_id(self, *, report_export_id: str) -> str:
                self.report_export_id = report_export_id
                return "project-1"

            def get_runtime_report_artifact(self, **kwargs: object) -> RuntimeReportArtifact:
                self.kwargs = kwargs
                return RuntimeReportArtifact(
                    report_export={"id": kwargs["report_export_id"], "report_version": "worker-runtime-v1"},
                    artifact_type=str(kwargs["artifact_type"]),
                    template=str(kwargs["template"]),
                    template_payload={"template": kwargs["template"]},
                    template_hash="template-hash",
                    filename=f"worker-runtime-v1.{kwargs['artifact_type']}",
                    media_type="text/markdown; charset=utf-8",
                    content="signed artifact content",
                    content_hash="artifact-hash",
                    filters={"platform": kwargs["platform"]},
                    filter_hash="filter-hash",
                    sort=str(kwargs["sort"]),
                    total_count=4,
                    row_count=2,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ), patch.dict(
            "os.environ",
            {
                "GENO_REPORT_ARTIFACT_SIGNING_SECRET": "signed-url-secret",
                "GENO_REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS": "600",
            },
            clear=True,
        ):
            signed_response = self.client.get(
                "/v1/reports/runtime/report-1/artifact/signed-url"
                "?type=markdown&platform=perplexity&sort=cost_desc"
            )
            self.assertEqual(signed_response.status_code, 200)
            payload = signed_response.json()
            self.assertEqual(payload["signature_version"], "report_artifact_hmac_sha256_v1")
            self.assertEqual(payload["ttl_seconds"], 600)
            self.assertIn("signature=", payload["download_url"])
            self.assertIn("expires_at=", payload["download_url"])

            download_path = payload["download_url"].replace("http://testserver", "")
            download_response = self.client.get(download_path)
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(download_response.text, "signed artifact content")
            self.assertEqual(download_response.headers["x-geno-report-artifact-signed"], "true")
            self.assertEqual(fake_repository.kwargs["platform"], "perplexity")

            tampered_path = download_path.replace("platform=perplexity", "platform=chatgpt")
            tampered_response = self.client.get(tampered_path)
            self.assertEqual(tampered_response.status_code, 401)
            self.assertIn("signature is invalid", tampered_response.json()["detail"])

    def test_runtime_report_artifact_signed_url_preserves_actor_under_access_control(self) -> None:
        class FakeRepository:
            def set_runtime_project_access_context(self, **kwargs: object) -> None:
                self.context = kwargs

            def get_report_export_project_id(self, *, report_export_id: str) -> str:
                self.report_export_id = report_export_id
                return "project-1"

            def get_project_member_role(self, *, project_id: str, actor_id: str) -> str:
                self.member_check = {"project_id": project_id, "actor_id": actor_id}
                return "owner"

            def get_runtime_report_artifact(self, **kwargs: object) -> RuntimeReportArtifact:
                return RuntimeReportArtifact(
                    report_export={"id": kwargs["report_export_id"], "report_version": "worker-runtime-v1"},
                    artifact_type=str(kwargs["artifact_type"]),
                    template=str(kwargs["template"]),
                    template_payload={"template": kwargs["template"]},
                    template_hash="template-hash",
                    filename="worker-runtime-v1.pdf",
                    media_type="application/pdf",
                    content=b"%PDF-1.4\nsigned\n%%EOF\n",
                    content_hash="artifact-hash",
                    filters={},
                    filter_hash="filter-hash",
                    sort=str(kwargs["sort"]),
                    total_count=1,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ), patch.dict(
            "os.environ",
            {
                "GENO_REPORT_ARTIFACT_SIGNING_SECRET": "signed-url-secret",
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
            },
            clear=True,
        ):
            signed_response = self.client.get(
                "/v1/reports/runtime/report-1/artifact/signed-url?type=pdf",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
            self.assertEqual(signed_response.status_code, 200)
            download_url = signed_response.json()["download_url"]
            self.assertIn("signed_actor_id=agency-owner", download_url)

            download_path = download_url.replace("http://testserver", "")
            download_response = self.client.get(download_path)
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.headers["x-geno-report-artifact-signed"], "true")
        self.assertEqual(fake_repository.context["actor_id"], "agency-owner")
        self.assertEqual(fake_repository.member_check["actor_id"], "agency-owner")

    def test_runtime_action_plans_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/action-plans/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_alerts_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/runtime-alerts")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_alerts_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_alerts(self, **kwargs: object) -> RuntimeAlertPage:
                self.kwargs = kwargs
                return RuntimeAlertPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeAlertItem(
                            alert={
                                "id": "runtime-alert-1",
                                "project_id": kwargs["project_id"],
                                "alert_type": kwargs["alert_type"],
                                "severity": kwargs["severity"],
                                "title": "Brand mention coverage is below threshold",
                                "metric_name": "mention_rate",
                                "metric_value": 0.25,
                                "threshold": 0.5,
                                "rule_version": "runtime_alerts_v1",
                            },
                            evidence_refs=({"target_type": "visibility_score_snapshot", "target_id": "snapshot-1"},),
                            related_actions=({"id": "action-1", "title": "Improve brand mention coverage"},),
                            audit_events=({"event_type": "visibility_score_snapshot_created"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-alerts"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&alert_type=brand_absent&severity=high&limit=5&offset=2"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["records"][0]["alert"]["rule_version"], "runtime_alerts_v1")
        self.assertEqual(payload["records"][0]["evidence_refs"][0]["target_type"], "visibility_score_snapshot")
        self.assertEqual(payload["records"][0]["related_actions"][0]["id"], "action-1")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["alert_type"], "brand_absent")
        self.assertEqual(fake_repository.kwargs["severity"], "high")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 2)

    def test_runtime_alert_event_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def record_runtime_alert_event(self, event: object) -> RuntimeAlertEvent:
                self.event = event
                return RuntimeAlertEvent(
                    alert_event={
                        "id": "alert-event-1",
                        "project_id": event.project_id,
                        "alert_id": event.alert_id,
                        "alert_type": event.alert_type,
                        "source": event.source,
                        "source_id": event.source_id,
                        "status": event.status,
                        "updated_by": event.updated_by,
                        "note": event.note,
                        "metadata": event.metadata,
                        "created_at": datetime(2026, 6, 12, tzinfo=UTC),
                    },
                    audit_events=({"event_type": "runtime_alert_event_recorded"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-alerts/runtime-alert-1/events",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "alert_type": "brand_absent",
                    "source": "visibility_score_snapshot",
                    "source_id": "snapshot-1",
                    "status": "escalated",
                    "updated_by": "analyst-1",
                    "note": "SLA threshold breached",
                    "metadata": {"severity": "high"},
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["alert_event"]["status"], "escalated")
        self.assertEqual(payload["audit_events"][0]["event_type"], "runtime_alert_event_recorded")
        self.assertEqual(fake_repository.event.alert_id, "runtime-alert-1")
        self.assertEqual(fake_repository.event.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.event.updated_by, "analyst-1")

    def test_runtime_alert_notifications_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def enqueue_runtime_alert_notifications(self, **kwargs: object) -> RuntimeAlertNotificationResult:
                self.kwargs = kwargs
                return RuntimeAlertNotificationResult(
                    project_id=str(kwargs["project_id"]),
                    notification_count=2,
                    delivery_count=1,
                    skipped_count=1,
                    notifications=(
                        {
                            "id": "notification-1",
                            "notification_type": "runtime_alert",
                            "severity": "warning",
                            "target_type": "runtime_alert",
                        },
                    ),
                    audit_events=(
                        {"event_type": "runtime_notification_created"},
                        {"event_type": "runtime_notification_delivery_queued"},
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-alerts/notifications",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "alert_type": "brand_absent",
                    "severity": "high",
                    "created_by": "analyst-1",
                    "reason": "notify owner",
                    "include_resolved": True,
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["notification_count"], 2)
        self.assertEqual(payload["delivery_count"], 1)
        self.assertEqual(payload["audit_events"][1]["event_type"], "runtime_notification_delivery_queued")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["alert_type"], "brand_absent")
        self.assertEqual(fake_repository.kwargs["severity"], "high")
        self.assertEqual(fake_repository.kwargs["created_by"], "analyst-1")
        self.assertTrue(fake_repository.kwargs["include_resolved"])

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
        self.assertIn("InMemoryPgVectorStore", payload["m7_content_integrations"])
        self.assertIn("InMemoryQdrantVectorStore", payload["m7_content_integrations"])
        self.assertIn("summarize_vector_search", payload["m7_content_integrations"])
        self.assertIn("InMemoryPostgresAdjacencyGraphStore", payload["m4_graph_benchmark"])
        self.assertIn("InMemoryNeo4jCitationGraphStore", payload["m4_graph_benchmark"])
        self.assertIn("summarize_citation_graph_store", payload["m4_graph_benchmark"])
        self.assertIn("EntityAlias", payload["m1_bootstrap"])
        self.assertIn("EntityAliasInput", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAlias", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasCandidate", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasCandidatePage", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasPage", payload["m1_bootstrap"])
        self.assertIn("TraceabilityBundle", payload["auditability"])
        self.assertIn("RuntimeFidelityCheck", payload["auditability"])
        self.assertIn("RuntimeFidelityTrend", payload["auditability"])
        self.assertIn("RuntimeAlertItem", payload["auditability"])
        self.assertIn("RuntimeAlertPage", payload["auditability"])
        self.assertIn("RuntimeAlertEvent", payload["auditability"])
        self.assertIn("build_traceability_bundle", payload["traceability"])
        self.assertIn("CollectionRunSummary", payload["m2a_evidence"])
        self.assertIn("BrowserFidelitySamplingPlan", payload["m2a_evidence"])
        self.assertIn("P0ACollectionReadinessGate", payload["m2a_evidence"])
        self.assertIn("evaluate_p0a_collection_readiness", payload["m2a_evidence"])
        self.assertIn("build_browser_fidelity_sampling_plan", payload["m2a_evidence"])
        self.assertIn("RuntimeFidelityCheck", payload["m2a_evidence"])
        self.assertIn("RuntimeFidelityCheckPage", payload["m2a_evidence"])
        self.assertIn("RuntimeFidelityTrend", payload["m2a_evidence"])
        self.assertIn("RuntimeFidelityTrendPoint", payload["m2a_evidence"])
        self.assertIn("FixtureChatGPTSearchBrowserCollector", payload["m2a_evidence"])
        self.assertIn("PlaywrightChatGPTSearchCollector", payload["m2a_evidence"])
        self.assertIn("GoogleSpikeReadinessGate", payload["m2b_google_spike"])
        self.assertIn("evaluate_google_spike_readiness_gate", payload["m2b_google_spike"])
        self.assertIn("LLMJudgeAnswerParser", payload["m3_analysis_scoring"])
        self.assertIn("ComparativeAnswerParser", payload["m3_analysis_scoring"])
        self.assertIn("parser_ab_compare_v1", payload["m3_analysis_scoring"])
        self.assertIn("FixtureLLMGateway", payload["m3_analysis_scoring"])
        self.assertIn("LiteLLMGateway", payload["m3_analysis_scoring"])
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
        self.assertIn("RuntimeHumanReviewQueuePage", payload["m3_analysis_scoring"])
        self.assertIn("RuntimeHumanReviewInput", payload["m3_analysis_scoring"])
        self.assertIn("HumanReviewRequest", payload["m3_analysis_scoring"])
        self.assertIn("LLMCallLog", payload["auditability"])
        self.assertIn("RuntimeHumanReviewRecord", payload["auditability"])
        self.assertIn("RuntimeHumanReviewQueuePage", payload["auditability"])
        self.assertIn("RuntimeEvidenceRun", payload["persistence"])
        self.assertIn("RuntimeEvidenceExport", payload["persistence"])
        self.assertIn("RuntimeCollectionRun", payload["persistence"])
        self.assertIn("RuntimeCollectionRunPage", payload["persistence"])
        self.assertIn("RuntimeFidelityCheck", payload["persistence"])
        self.assertIn("RuntimeFidelityCheckPage", payload["persistence"])
        self.assertIn("RuntimeFidelityTrend", payload["persistence"])
        self.assertIn("RuntimeFidelityTrendPoint", payload["persistence"])
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
        self.assertIn("RuntimeProjectMember", payload["persistence"])
        self.assertIn("RuntimeProjectMemberPage", payload["persistence"])
        self.assertIn("RuntimeProjectMemberInput", payload["persistence"])
        self.assertIn("ProjectMemberRequest", payload["persistence"])
        self.assertIn("RuntimeProjectBrandKit", payload["persistence"])
        self.assertIn("RuntimeProjectBrandKitInput", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAsset", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetPage", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetInput", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetScanInput", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetVersion", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetVersionPage", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetActivationInput", payload["persistence"])
        self.assertIn("RuntimeProjectBrandLogoUpload", payload["persistence"])
        self.assertIn("ProjectBrandKitRequest", payload["persistence"])
        self.assertIn("ProjectBrandAssetRequest", payload["persistence"])
        self.assertIn("ProjectBrandAssetScanRequest", payload["persistence"])
        self.assertIn("ProjectBrandAssetActivationRequest", payload["persistence"])
        self.assertIn("RuntimeScoreWeightConfig", payload["persistence"])
        self.assertIn("RuntimeScoreWeightConfigInput", payload["persistence"])
        self.assertIn("ScoreWeightConfigRequest", payload["persistence"])
        self.assertIn("ScoreFormulaDefinition", payload["persistence"])
        self.assertIn("RuntimeHumanReviewRecord", payload["persistence"])
        self.assertIn("RuntimeHumanReviewPage", payload["persistence"])
        self.assertIn("RuntimeHumanReviewQueueItem", payload["persistence"])
        self.assertIn("RuntimeHumanReviewQueuePage", payload["persistence"])
        self.assertIn("RuntimeHumanReviewInput", payload["persistence"])
        self.assertIn("HumanReviewRequest", payload["persistence"])
        self.assertIn("RuntimePromptPage", payload["persistence"])
        self.assertIn("RuntimePromptImportHistoryItem", payload["persistence"])
        self.assertIn("RuntimePromptImportHistoryPage", payload["persistence"])
        self.assertIn("RuntimePromptImportInput", payload["persistence"])
        self.assertIn("RuntimePromptImportResult", payload["persistence"])
        self.assertIn("RuntimePromptImportRequest", payload["persistence"])
        self.assertIn("RuntimeScoreSnapshot", payload["persistence"])
        self.assertIn("RuntimeCitationGraph", payload["persistence"])
        self.assertIn("RuntimeReportArtifact", payload["persistence"])
        self.assertIn("RuntimeReportExport", payload["persistence"])
        self.assertIn("RuntimeReportExportJob", payload["persistence"])
        self.assertIn("RuntimeReportExportJobPage", payload["persistence"])
        self.assertIn("RuntimeReportExportJobQueueStats", payload["persistence"])
        self.assertIn("RuntimeReportExportJobInput", payload["persistence"])
        self.assertIn("RuntimeReportExportJobStatusInput", payload["persistence"])
        self.assertIn("RuntimeReportExportJobRequest", payload["persistence"])
        self.assertIn("RuntimeReportExportJobStatusRequest", payload["persistence"])
        self.assertIn("RuntimeNotification", payload["persistence"])
        self.assertIn("RuntimeNotificationPage", payload["persistence"])
        self.assertIn("RuntimeNotificationStatusInput", payload["persistence"])
        self.assertIn("RuntimeNotificationStatusRequest", payload["persistence"])
        self.assertIn("RuntimeNotificationSubscription", payload["persistence"])
        self.assertIn("RuntimeNotificationSubscriptionPage", payload["persistence"])
        self.assertIn("RuntimeNotificationSubscriptionInput", payload["persistence"])
        self.assertIn("RuntimeNotificationSubscriptionRequest", payload["persistence"])
        self.assertIn("RuntimeNotificationDelivery", payload["persistence"])
        self.assertIn("RuntimeNotificationDeliveryPage", payload["persistence"])
        self.assertIn("RuntimeNotificationDeliveryStatusInput", payload["persistence"])
        self.assertIn("RuntimeReportManagementInput", payload["persistence"])
        self.assertIn("RuntimeReportManagementEventRequest", payload["persistence"])
        self.assertIn("RuntimeActionPlan", payload["persistence"])
        self.assertIn("RuntimeAlertItem", payload["persistence"])
        self.assertIn("RuntimeAlertPage", payload["persistence"])
        self.assertIn("RuntimeAlertEvent", payload["persistence"])
        self.assertIn("RuntimeAlertEventInput", payload["persistence"])
        self.assertIn("RuntimeAlertEventRequest", payload["persistence"])
        self.assertIn("RuntimeAlertNotificationRequest", payload["persistence"])
        self.assertIn("RuntimeAlertNotificationResult", payload["persistence"])
        self.assertIn("RuntimeContentEngine", payload["persistence"])
        self.assertIn("RuntimeKnowledgeSearchResult", payload["persistence"])
        self.assertIn("RuntimeKnowledgeSearchPage", payload["persistence"])
        self.assertIn("RuntimeTraceabilityDetail", payload["persistence"])
        self.assertIn("RuntimeComponentDiagnostic", payload["persistence"])
        self.assertIn("RuntimeDiagnostics", payload["persistence"])
        self.assertIn("build_runtime_diagnostics", payload["persistence"])
        self.assertIn("runtime_database_diagnostic", payload["persistence"])
        self.assertIn("runtime_object_store_diagnostic", payload["persistence"])
        self.assertIn("runtime_auth_diagnostic", payload["persistence"])
        self.assertIn("build_object_store_from_env", payload["persistence"])
        self.assertIn("archive_project_brand_logo", payload["persistence"])
        self.assertIn("/v1/projects/runtime", payload["persistence"])
        self.assertIn("/v1/projects/runtime/au/dtc-ecommerce", payload["persistence"])
        self.assertIn("/v1/project-members/runtime", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/confirm", payload["persistence"])
        self.assertIn("/v1/prompts/runtime", payload["persistence"])
        self.assertIn("/v1/prompts/runtime/imports", payload["persistence"])
        self.assertIn("/v1/prompts/runtime/import.csv", payload["persistence"])
        self.assertIn("/v1/prompts/runtime/import.file", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime", payload["persistence"])
        self.assertIn("/v1/collection-runs/runtime", payload["persistence"])
        self.assertIn("/v1/fidelity-checks/runtime", payload["persistence"])
        self.assertIn("/v1/fidelity-checks/runtime/trend", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime/manual-backfill", payload["persistence"])
        self.assertIn("/v1/runtime-saved-views", payload["persistence"])
        self.assertIn("/v1/project-brand-kits/runtime", payload["persistence"])
        self.assertIn("/v1/project-brand-kits/runtime/logo", payload["persistence"])
        self.assertIn("/v1/project-brand-kits/runtime/assets", payload["persistence"])
        self.assertIn("/v1/project-brand-kits/runtime/assets/activate", payload["persistence"])
        self.assertIn("/v1/project-brand-assets/runtime", payload["persistence"])
        self.assertIn("/v1/score-weight-configs/runtime", payload["persistence"])
        self.assertIn("/v1/score-formulas/runtime", payload["persistence"])
        self.assertIn("/v1/human-reviews/runtime", payload["persistence"])
        self.assertIn("/v1/human-reviews/runtime/queue", payload["persistence"])
        self.assertIn("/v1/visibility-scores/runtime", payload["persistence"])
        self.assertIn("/v1/citation-graphs/runtime", payload["persistence"])
        self.assertIn("/v1/reports/runtime", payload["persistence"])
        self.assertIn("/v1/report-export-jobs/runtime", payload["persistence"])
        self.assertIn("/v1/report-export-jobs/runtime/stats", payload["persistence"])
        self.assertIn("/v1/report-export-jobs/runtime/{job_id}/status", payload["persistence"])
        self.assertIn("/v1/runtime-notifications", payload["persistence"])
        self.assertIn("/v1/runtime-notification-subscriptions", payload["persistence"])
        self.assertIn("/v1/runtime-notification-deliveries", payload["persistence"])
        self.assertIn("/v1/runtime-notifications/{notification_id}/status", payload["persistence"])
        self.assertIn("/v1/reports/runtime/{report_export_id}/management-events", payload["persistence"])
        self.assertIn("/v1/reports/runtime/{report_export_id}/artifact", payload["persistence"])
        self.assertIn("/v1/reports/runtime/{report_export_id}/artifact/signed-url", payload["persistence"])
        self.assertIn("/v1/action-plans/runtime", payload["persistence"])
        self.assertIn("/v1/runtime-alerts", payload["persistence"])
        self.assertIn("/v1/runtime-alerts/notifications", payload["persistence"])
        self.assertIn("/v1/runtime-alerts/{alert_id}/events", payload["persistence"])
        self.assertIn("/v1/content-engines/runtime", payload["persistence"])
        self.assertIn("/v1/knowledge-facts/runtime/search", payload["persistence"])
        self.assertIn("/v1/traceability/runtime", payload["persistence"])
        self.assertIn("/ready", payload["persistence"])
        self.assertIn("/v1/runtime-diagnostics", payload["persistence"])
        self.assertIn("/metrics", payload["persistence"])


if __name__ == "__main__":
    unittest.main()
