from __future__ import annotations

import json
import unittest

from geno_core.connector_contract import (
    ConnectorConfig,
    ConnectorPrompt,
    ConnectorRegistry,
    ConnectorRequest,
    ConnectorValidationError,
    RecordedConnectorHarness,
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


if __name__ == "__main__":
    unittest.main()
