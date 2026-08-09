from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping
from uuid import UUID, uuid4

import pytest

from geo_core.model_gateway import (
    EffectiveModelLocation,
    ModelCallBudget,
    ModelCaptureMethod,
    ModelCallBudgetExceeded,
    ModelGatewayRequest,
    ModelPolicy,
    ModelLocationControl,
    RequestedModelLocation,
    SerpApiGoogleSearchAdapter,
    StructuredOutputValidationError,
)
from geo_core.model_gateway.provider_adapters import JsonResponse
from geo_core.secrets import SecretVersionHandle

from tests.unit.model_gateway.provider_adapter_test_support import (
    OUTPUT_SCHEMA,
    SECRET_REFERENCE_ID,
    RecordingProviderArtifactSink,
    StaticCredentialResolver,
    runtime,
)


PROJECT_ID = UUID("51000000-0000-4000-8000-000000000001")
LOCATION_HASH = hashlib.sha256(b"serpapi-location-not-controlled").hexdigest()


@dataclass
class RecordingGetTransport:
    responses: list[JsonResponse]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def get(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, object],
        timeout_seconds: float,
    ) -> JsonResponse:
        del headers, timeout_seconds
        self.calls.append((url, dict(params)))
        return self.responses.pop(0)


def _response(body: object, status_code: int = 200) -> JsonResponse:
    return JsonResponse(status_code=status_code, body=body, headers={"x-request-id": "fixture"})


def _request() -> ModelGatewayRequest:
    return ModelGatewayRequest(
        messages=(
            {"role": "system", "content": "Return the frozen evidence JSON."},
            {"role": "user", "content": "Which pool cleaner is suitable in Australia?"},
        ),
        configured_model="google-ai-overview-fixture",
        prompt_bundle_hash="a" * 64,
        project_id=PROJECT_ID,
        purpose="geo_measurement",
        output_schema=OUTPUT_SCHEMA,
        application_output_schema=OUTPUT_SCHEMA,
        search_mode="google_search",
        capture_method=ModelCaptureMethod.PROVIDER_API,
        provider_secret_handle=SecretVersionHandle(
            project_id=PROJECT_ID,
            reference_id=SECRET_REFERENCE_ID,
            purpose="search.serpapi",
            version=1,
        ),
        model_call_job_id=uuid4(),
        model_call_attempt_id=uuid4(),
        requested_location=RequestedModelLocation(
            country_code="AU", region_code=None, locale="en-AU", language="en"
        ),
        expected_effective_location=EffectiveModelLocation(
            control=ModelLocationControl.NOT_CONTROLLED,
            country_code=None,
            region_code=None,
            locale=None,
            language=None,
            evidence_hash=LOCATION_HASH,
        ),
    )


def _adapter(transport: RecordingGetTransport, sink: RecordingProviderArtifactSink):
    return SerpApiGoogleSearchAdapter(
        runtime=runtime(
            "serpapi",
            model="google-ai-overview-fixture",
            search_modes=frozenset({"google_search"}),
            supports_search=True,
            purpose="geo_measurement",
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
        artifact_sink=sink,
    )


def test_page_token_resolution_is_one_gateway_call_but_two_gets_and_records_usage() -> None:
    transport = RecordingGetTransport(
        [
            _response({"ai_overview": {"page_token": "page-token-1"}}),
            _response(
                {
                    "ai_overview": {
                        "text_blocks": [{"type": "paragraph", "text": "Resolved answer"}],
                        "references": [
                            {"title": "Source", "link": "https://example.test/source"}
                        ],
                    }
                }
            ),
        ]
    )
    sink = RecordingProviderArtifactSink()
    result = _adapter(transport, sink).generate(
        _request(),
        policy=ModelPolicy(
            allowed_providers=frozenset({"serpapi"}),
            allowed_adapter_release_ids=frozenset({"serpapi-fixture-adapter-v1"}),
            policy_version_id=uuid4(),
            maximum_paid_calls=2,
            maximum_concurrent_calls=1,
        ),
        budget=ModelCallBudget(2),
    )

    assert len(transport.calls) == 2
    assert transport.calls[0][1]["engine"] == "google"
    assert transport.calls[0][1]["gl"] == "au"
    assert transport.calls[1][1] == {
        "engine": "google_ai_overview",
        "page_token": "page-token-1",
        "api_key": "fixture-provider-secret",
    }
    assert result.output == {"answer": "Resolved answer", "recommended": False}
    assert result.usage_details == {
        "request_count": 2,
        "logical_call_count": 1,
        "page_token_resolved": True,
        "requested_region": "au",
        "requested_language": "en",
        "egress_proof": "not_provided_by_serpapi_gl",
    }
    assert result.effective_location is not None
    assert result.effective_location.control is ModelLocationControl.NOT_CONTROLLED
    assert sink.calls == [("serpapi", "serpapi-fixture-adapter-v1")]


def test_page_token_second_get_is_blocked_by_one_request_budget() -> None:
    transport = RecordingGetTransport(
        [_response({"ai_overview": {"page_token": "page-token-1"}})]
    )
    with pytest.raises(ModelCallBudgetExceeded):
        _adapter(transport, RecordingProviderArtifactSink()).generate(
            _request(),
            policy=ModelPolicy(
                allowed_providers=frozenset({"serpapi"}),
                allowed_adapter_release_ids=frozenset({"serpapi-fixture-adapter-v1"}),
                policy_version_id=uuid4(),
                maximum_paid_calls=1,
                maximum_concurrent_calls=1,
            ),
            budget=ModelCallBudget(1),
        )
    assert len(transport.calls) == 1


def test_answer_box_does_not_become_a_serpapi_ai_overview_observation() -> None:
    transport = RecordingGetTransport([_response({"answer_box": {"answer": "wrong surface"}})])
    with pytest.raises(StructuredOutputValidationError, match="ai_overview"):
        _adapter(transport, RecordingProviderArtifactSink()).generate(
            _request(),
            policy=ModelPolicy(
                allowed_providers=frozenset({"serpapi"}),
                allowed_adapter_release_ids=frozenset({"serpapi-fixture-adapter-v1"}),
                policy_version_id=uuid4(),
                maximum_paid_calls=1,
                maximum_concurrent_calls=1,
            ),
            budget=ModelCallBudget(1),
        )
