from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from geno_core.connector_contract import (
    ConnectorConfig,
    ConnectorPrompt,
    ConnectorRegistry,
    ConnectorRequest,
    ConnectorValidationError,
    RecordedConnectorHarness,
)
from geno_core.collectors import DeepSeekChatCollector, JsonHttpResponse
from geno_core.models import MarketProfile
from geno_core.production_connectors import (
    GoogleManualBackfillConnectorBackend,
    OpenAIWebSearchConnectorBackend,
    PerplexitySonarConnectorBackend,
)
from geno_core.security.secrets import REDACTED_VALUE


def _request(provider: str, prompt_id: str = "prompt-1") -> ConnectorRequest:
    access_method = "manual" if provider == "google_manual" else "official_api"
    return ConnectorRequest(
        request_id=f"request-{provider}",
        project_id="project-1",
        config=ConnectorConfig(
            connector_backend_id=f"{provider}.recorded",
            provider=provider,
            model="recorded-model",
            access_method=access_method,
            market_code="AU",
            locale="en-AU",
            country_code="AU",
            secret_ref="connector-secret:abc123",
            metadata={"api_key": "sk-should-not-leak", "region": "ap-southeast-2"},
        ),
        prompt=ConnectorPrompt(
            prompt_id=prompt_id,
            prompt_text="best mattress for side sleepers in Sydney",
            city="Sydney",
            language="en-AU",
            intent_type="comparison",
        ),
        metadata={"authorization": "Bearer should-not-leak", "batch": "smoke"},
    )


class ConnectorContractTest(unittest.TestCase):
    def test_deepseek_collector_uses_official_identity_without_fake_citations(self) -> None:
        class FakeDeepSeekHttpClient:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []

            def post_json(self, **kwargs: object) -> JsonHttpResponse:
                self.requests.append(kwargs)
                return JsonHttpResponse(
                    status_code=200,
                    payload={
                        "id": "deepseek-response-1",
                        "model": "deepseek-v4-flash",
                        "choices": [{"message": {"content": "Northwind is a relevant outdoor brand."}}],
                        "usage": {"prompt_tokens": 20, "completion_tokens": 9, "total_tokens": 29},
                    },
                )

        http_client = FakeDeepSeekHttpClient()
        collector = DeepSeekChatCollector(api_key="test-deepseek-key", http_client=http_client)
        result = collector.collect(
            prompt="Is Northwind recommended?",
            market=MarketProfile(
                market="United States",
                market_code="US",
                locale="en-US",
                timezone="America/Los_Angeles",
                currency="USD",
                primary_language="English",
                cities=["Seattle"],
                source_types=[],
                platforms=[],
            ),
            city="Seattle",
            language="en-US",
            device="desktop",
        )

        self.assertEqual(collector.id(), "deepseek.chat.api")
        self.assertEqual(collector.capabilities()["platform"], "deepseek")
        self.assertFalse(collector.capabilities()["supports_citation"])
        self.assertEqual(result.model_or_surface, "deepseek-v4-flash")
        self.assertEqual(result.citations, [])
        self.assertTrue(result.answer_present)
        self.assertIn("html_snapshot", result.evidence_asset_hashes or {})
        self.assertNotIn("test-deepseek-key", json.dumps(result.raw_payload))

    def test_recorded_harness_supports_openai_perplexity_and_google_manual(self) -> None:
        harness = RecordedConnectorHarness(
            {
                "openai:*": {
                    "answer_text": "OpenAI recorded answer mentioning KoalaHome.",
                    "citations": [{"url": "https://koalahome.example/au", "position": 1}],
                    "cost": {
                        "total_cost": 0.012,
                        "currency": "USD",
                        "prompt_tokens": 120,
                        "completion_tokens": 80,
                        "vendor_cost": 0.012,
                    },
                    "raw_payload": {"provider_request_id": "openai-rec-1", "api_key": "sk-hidden"},
                    "provider_request_id": "openai-rec-1",
                    "latency_ms": 430,
                },
                "perplexity:*": {
                    "answer_text": "Perplexity recorded answer with citations.",
                    "citations": ["https://reviews.example/mattress"],
                    "cost": {"total_cost": 0.008, "currency": "USD"},
                    "raw_payload": {"citations": ["https://reviews.example/mattress"]},
                },
                "google_manual:*": {
                    "answer_text": "Manual Google AI Mode answer entered by analyst.",
                    "citations": [{"url": "https://google-source.example/result", "source_type": "manual"}],
                    "screenshot_url": "s3://evidence/manual/google-ai-mode.png",
                    "snapshot_url": "s3://evidence/manual/google-ai-mode.html",
                    "cost": {"total_cost": 0, "currency": "USD", "estimate_method": "manual"},
                    "raw_payload": {"submitted_by": "analyst@example.com"},
                },
            }
        )
        registry = ConnectorRegistry()
        for provider in ("openai", "perplexity", "google_manual"):
            registry.register(provider, harness)

        responses = [registry.collect(_request(provider)) for provider in ("openai", "perplexity", "google_manual")]

        self.assertEqual([response.status for response in responses], ["succeeded", "succeeded", "succeeded"])
        self.assertEqual([response.provider for response in responses], ["openai", "perplexity", "google_manual"])
        self.assertEqual([len(response.citations) for response in responses], [1, 1, 1])
        self.assertEqual(responses[0].cost.total_cost, 0.012)
        self.assertEqual(responses[2].evidence.snapshot_url, "s3://evidence/manual/google-ai-mode.html")
        for response in responses:
            public_payload = json.dumps(response.to_public_dict(), sort_keys=True)
            self.assertNotIn("sk-hidden", public_payload)
            self.assertNotIn("sk-should-not-leak", public_payload)
            self.assertIn("raw_payload_hash", response.evidence.metadata)

    def test_recorded_failure_is_sanitized_and_classified(self) -> None:
        harness = RecordedConnectorHarness(
            {
                "openai:*": {
                    "failure": {
                        "category": "auth",
                        "message": "Authorization: Bearer sk-secret-value",
                        "retryable": False,
                        "provider_status_code": 401,
                        "provider_request_id": "req-secret",
                        "metadata": {"raw_secret": "sk-secret-value"},
                    },
                    "cost": {"total_cost": 0, "currency": "USD"},
                }
            }
        )

        response = harness.collect(_request("openai"))

        self.assertEqual(response.status, "failed")
        self.assertIsNotNone(response.failure)
        assert response.failure is not None
        self.assertEqual(response.failure.category, "auth")
        self.assertEqual(response.failure.provider_status_code, 401)
        serialized = json.dumps(response.to_public_dict(), sort_keys=True)
        self.assertNotIn("sk-secret-value", serialized)
        self.assertIn(REDACTED_VALUE, serialized)

    def test_missing_recording_returns_failed_response_not_exception(self) -> None:
        response = RecordedConnectorHarness({}).collect(_request("perplexity", prompt_id="missing"))

        self.assertEqual(response.status, "failed")
        self.assertIsNotNone(response.failure)
        assert response.failure is not None
        self.assertEqual(response.failure.category, "recording_missing")
        self.assertFalse(response.failure.retryable)

    def test_connector_config_rejects_raw_secret_ref(self) -> None:
        with self.assertRaises(ConnectorValidationError):
            ConnectorConfig(
                connector_backend_id="openai.recorded",
                provider="openai",
                model="recorded-model",
                access_method="official_api",
                market_code="AU",
                locale="en-AU",
                country_code="AU",
                secret_ref="sk-raw-provider-key",
            )

    def test_connector_config_accepts_provider_aliases(self) -> None:
        config = ConnectorConfig(
            connector_backend_id="chatgpt.recorded",
            provider="chatgpt",
            model="recorded-model",
            access_method="official_api",
            market_code="AU",
            locale="en-AU",
            country_code="AU",
            timeout_seconds=45,
            max_retries=3,
        )

        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.timeout_seconds, 45)
        self.assertEqual(config.max_retries, 3)

    def test_openai_connector_backend_collects_responses_api_payload(self) -> None:
        class FakeOpenAIHttpClient:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []

            def post_json(self, **kwargs: object) -> JsonHttpResponse:
                self.requests.append(kwargs)
                return JsonHttpResponse(
                    status_code=200,
                    payload={
                        "id": "resp-openai-1",
                        "usage": {"input_tokens": 1000, "output_tokens": 500},
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "OpenAI production answer mentioning KoalaHome.",
                                        "annotations": [
                                            {"type": "url_citation", "url": "https://koalahome.example/au"}
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                )

        http_client = FakeOpenAIHttpClient()
        backend = OpenAIWebSearchConnectorBackend(api_key="test-openai-key", http_client=http_client)
        request = ConnectorRequest(
            request_id="openai-request-1",
            project_id="project-1",
            config=ConnectorConfig(
                connector_backend_id="openai.web_search.api",
                provider="openai",
                model="gpt-test-web-search",
                access_method="official_api",
                market_code="AU",
                locale="en-AU",
                country_code="AU",
                secret_ref="connector-secret:openai",
                rate_card={"input_per_1k_tokens": 0.01, "output_per_1k_tokens": 0.02},
            ),
            prompt=ConnectorPrompt(
                prompt_id="prompt-1",
                prompt_text="best mattress for side sleepers in Sydney",
                city="Sydney",
                language="en-AU",
            ),
        )

        response = backend.collect(request)

        self.assertEqual(response.status, "succeeded")
        self.assertEqual(response.provider, "openai")
        self.assertEqual(response.model, "gpt-test-web-search")
        self.assertEqual(response.provider_request_id, "resp-openai-1")
        self.assertEqual(response.citations[0].domain, "koalahome.example")
        self.assertEqual(response.cost.prompt_tokens, 1000)
        self.assertEqual(response.cost.completion_tokens, 500)
        self.assertEqual(response.cost.total_cost, 0.02)
        self.assertEqual(response.cost.estimate_method, "estimated")
        self.assertTrue(response.evidence.snapshot_url.startswith("geno-api-snapshot://openai.web_search.api/"))
        self.assertIn("html_snapshot", response.evidence.asset_hashes)
        sent_payload = http_client.requests[0]["payload"]
        self.assertIsInstance(sent_payload, dict)
        assert isinstance(sent_payload, dict)
        self.assertEqual(sent_payload["model"], "gpt-test-web-search")
        self.assertIn({"type": "web_search_preview"}, sent_payload["tools"])
        serialized = json.dumps(response.to_public_dict(), sort_keys=True)
        self.assertNotIn("test-openai-key", serialized)

    def test_openai_connector_backend_classifies_provider_auth_failure(self) -> None:
        class FakeUnauthorizedOpenAIHttpClient:
            def post_json(self, **kwargs: object) -> JsonHttpResponse:
                return JsonHttpResponse(
                    status_code=401,
                    payload={"id": "resp-openai-auth-failure", "error": {"message": "bad credentials"}},
                )

        backend = OpenAIWebSearchConnectorBackend(
            api_key="test-openai-key",
            http_client=FakeUnauthorizedOpenAIHttpClient(),
        )
        response = backend.collect(_request("openai"))

        self.assertEqual(response.status, "failed")
        self.assertIsNotNone(response.failure)
        assert response.failure is not None
        self.assertEqual(response.failure.category, "auth")
        self.assertEqual(response.failure.provider_status_code, 401)
        self.assertEqual(response.provider_request_id, "resp-openai-auth-failure")
        self.assertFalse(response.failure.retryable)
        serialized = json.dumps(response.to_public_dict(), sort_keys=True)
        self.assertNotIn("test-openai-key", serialized)

    def test_perplexity_connector_backend_collects_sonar_payload(self) -> None:
        class FakePerplexityHttpClient:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []

            def post_json(self, **kwargs: object) -> JsonHttpResponse:
                self.requests.append(kwargs)
                return JsonHttpResponse(
                    status_code=200,
                    payload={
                        "id": "pplx-sonar-1",
                        "usage": {
                            "prompt_tokens": 600,
                            "completion_tokens": 240,
                            "cost": 0.008,
                        },
                        "choices": [
                            {
                                "message": {
                                    "content": "Perplexity production answer with cited Australian sources."
                                }
                            }
                        ],
                        "citations": [
                            "https://reviews.example/mattress",
                            {"url": "https://koalahome.example/au", "title": "KoalaHome AU"},
                        ],
                    },
                )

        http_client = FakePerplexityHttpClient()
        backend = PerplexitySonarConnectorBackend(api_key="test-perplexity-key", http_client=http_client)
        request = ConnectorRequest(
            request_id="perplexity-request-1",
            project_id="project-1",
            config=ConnectorConfig(
                connector_backend_id="perplexity.sonar.api",
                provider="perplexity",
                model="sonar-pro-test",
                access_method="official_api",
                market_code="AU",
                locale="en-AU",
                country_code="AU",
                secret_ref="connector-secret:perplexity",
            ),
            prompt=ConnectorPrompt(
                prompt_id="prompt-1",
                prompt_text="best mattress for side sleepers in Sydney",
                city="Sydney",
                language="en-AU",
            ),
        )

        response = backend.collect(request)

        self.assertEqual(response.status, "succeeded")
        self.assertEqual(response.provider, "perplexity")
        self.assertEqual(response.model, "sonar-pro-test")
        self.assertEqual(response.provider_request_id, "pplx-sonar-1")
        self.assertEqual(len(response.citations), 2)
        self.assertEqual(response.citations[0].domain, "reviews.example")
        self.assertEqual(response.citations[1].title, "KoalaHome AU")
        self.assertEqual(response.cost.total_cost, 0.008)
        self.assertEqual(response.cost.estimate_method, "provider_reported")
        self.assertTrue(response.evidence.snapshot_url.startswith("geno-api-snapshot://perplexity.sonar.api/"))
        sent_payload = http_client.requests[0]["payload"]
        self.assertIsInstance(sent_payload, dict)
        assert isinstance(sent_payload, dict)
        self.assertEqual(sent_payload["model"], "sonar-pro-test")
        serialized = json.dumps(response.to_public_dict(), sort_keys=True)
        self.assertNotIn("test-perplexity-key", serialized)

    def test_perplexity_connector_backend_classifies_rate_limit_failure(self) -> None:
        class FakeRateLimitedPerplexityHttpClient:
            def post_json(self, **kwargs: object) -> JsonHttpResponse:
                return JsonHttpResponse(
                    status_code=429,
                    payload={"id": "pplx-rate-limit-1", "error": {"message": "rate limited"}},
                )

        backend = PerplexitySonarConnectorBackend(
            api_key="test-perplexity-key",
            http_client=FakeRateLimitedPerplexityHttpClient(),
        )
        response = backend.collect(_request("perplexity"))

        self.assertEqual(response.status, "failed")
        self.assertIsNotNone(response.failure)
        assert response.failure is not None
        self.assertEqual(response.failure.category, "rate_limited")
        self.assertEqual(response.failure.provider_status_code, 429)
        self.assertEqual(response.provider_request_id, "pplx-rate-limit-1")
        self.assertTrue(response.failure.retryable)
        serialized = json.dumps(response.to_public_dict(), sort_keys=True)
        self.assertNotIn("test-perplexity-key", serialized)

    def test_google_manual_connector_backend_collects_jsonl_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backfill_path = Path(temp_dir) / "google-manual.jsonl"
            backfill_path.write_text(
                json.dumps(
                    {
                        "prompt": "best mattress for side sleepers in Sydney",
                        "city": "Sydney",
                        "language": "en-AU",
                        "device": "desktop",
                        "answer_text": "Manual Google AI Mode answer mentioning KoalaHome.",
                        "surface_triggered": True,
                        "answer_present": True,
                        "citation_urls": ["https://source.example/google-ai-mode"],
                        "screenshot_url": "s3://evidence/google/manual/screenshot.png",
                        "html_snapshot_url": "s3://evidence/google/manual/snapshot.html",
                        "submitted_by": "analyst@example.com",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            backend = GoogleManualBackfillConnectorBackend(backfill_path=str(backfill_path), vendor_cost=0)
            request = ConnectorRequest(
                request_id="google-manual-request-1",
                project_id="project-1",
                config=ConnectorConfig(
                    connector_backend_id="google.manual_backfill",
                    provider="google_manual",
                    model="manual_backfill_jsonl",
                    access_method="manual",
                    market_code="AU",
                    locale="en-AU",
                    country_code="AU",
                ),
                prompt=ConnectorPrompt(
                    prompt_id="prompt-1",
                    prompt_text="best mattress for side sleepers in Sydney",
                    city="Sydney",
                    language="en-AU",
                ),
            )

            response = backend.collect(request)

        self.assertEqual(response.status, "succeeded")
        self.assertEqual(response.provider, "google_manual")
        self.assertEqual(response.answer_text, "Manual Google AI Mode answer mentioning KoalaHome.")
        self.assertEqual(response.cost.total_cost, 0)
        self.assertEqual(response.cost.estimate_method, "estimated")
        self.assertEqual(response.citations[0].domain, "source.example")
        self.assertEqual(response.evidence.snapshot_url, "s3://evidence/google/manual/snapshot.html")
        self.assertEqual(response.evidence.screenshot_url, "s3://evidence/google/manual/screenshot.png")
        self.assertIn("html_snapshot", response.evidence.asset_hashes)
        self.assertIn("screenshot", response.evidence.asset_hashes)
        self.assertEqual(response.metadata["collector_version"], "manual-backfill-jsonl-v1")

    def test_google_manual_connector_backend_reports_missing_backfill_file(self) -> None:
        backend = GoogleManualBackfillConnectorBackend(backfill_path="/tmp/geno-missing-google-manual.jsonl")
        response = backend.collect(_request("google_manual"))

        self.assertEqual(response.status, "failed")
        self.assertIsNotNone(response.failure)
        assert response.failure is not None
        self.assertEqual(response.failure.category, "not_configured")
        self.assertFalse(response.failure.retryable)


if __name__ == "__main__":
    unittest.main()
