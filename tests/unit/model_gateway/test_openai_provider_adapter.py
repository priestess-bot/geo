from __future__ import annotations

from dataclasses import replace
import json
import pytest

from geo_core.model_gateway import (
    EffectiveModelLocation,
    ModelCallBudget,
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelLocationControl,
    ModelPolicy,
    ProviderPolicyViolation,
    ReleaseState,
    RequestedModelLocation,
    RetryableModelGatewayError,
    StructuredOutputValidationError,
)
from geo_core.model_gateway.provider_adapters import (
    OpenAIResponsesAdapter,
    ProviderAdapterRuntime,
)

from .provider_adapter_test_support import (
    SECRET_REFERENCE_ID,
    SECRET_TEXT,
    RecordingJsonTransport,
    StaticCredentialResolver,
    json_response,
    request,
    runtime,
)


MODEL = "fixture-openai-model"


def _success_body(*, text: str | None = None) -> dict[str, object]:
    return {
        "id": "resp_fixture_1",
        "status": "completed",
        "model": "fixture-openai-model-2026-07-23",
        "output": [
            {
                "type": "web_search_call",
                "id": "ws_fixture_1",
                "status": "completed",
                "action": {"type": "search", "queries": ["product reviews australia"]},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": text
                        or json.dumps(
                            {"answer": "It is commonly recommended.", "recommended": True}
                        ),
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.com/review",
                                "title": "Independent review",
                                "start_index": 4,
                                "end_index": 20,
                            }
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 30, "output_tokens": 12, "total_tokens": 42},
    }


def _adapter(
    response: object,
) -> tuple[OpenAIResponsesAdapter, RecordingJsonTransport, StaticCredentialResolver]:
    transport = RecordingJsonTransport(json_response(response))
    resolver = StaticCredentialResolver()
    adapter = OpenAIResponsesAdapter(
        runtime=runtime("openai", model=MODEL),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=resolver,
        transport=transport,
    )
    return adapter, transport, resolver


def test_openai_responses_payload_and_lineage_follow_official_contract() -> None:
    adapter, transport, resolver = _adapter(_success_body())
    model_request = request(MODEL, search_mode="web")

    result = adapter.generate(
        model_request,
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert transport.url == "https://api.openai.com/v1/responses"
    assert transport.headers["Authorization"] == f"Bearer {SECRET_TEXT}"
    assert SECRET_TEXT not in repr(transport)
    assert transport.payload["model"] == MODEL
    assert transport.payload["tools"] == [{"type": "web_search"}]
    assert transport.payload["tool_choice"] == "required"
    text_contract = transport.payload["text"]
    assert isinstance(text_contract, dict)
    assert text_contract["format"]["type"] == "json_schema"
    assert text_contract["format"]["strict"] is True
    assert result.output["recommended"] is True
    assert result.provider_request_id == "header-request-id"
    assert result.provider_reported_model == "fixture-openai-model-2026-07-23"
    assert result.capture_method is ModelCaptureMethod.PROVIDER_API
    assert result.search_mode == "web"
    assert result.prompt_tokens == 30
    assert result.completion_tokens == 12
    assert result.citations[0]["url"] == "https://example.com/review"
    assert result.tool_events[0]["type"] == "web_search_call"
    assert result.usage_details == {
        "input_tokens": 30,
        "output_tokens": 12,
        "total_tokens": 42,
    }
    assert resolver.calls == [model_request.provider_secret_handle]
    assert "chatgpt" not in repr(result).lower()


def test_openai_web_search_applies_and_proves_au_country_control() -> None:
    body = _success_body()
    body["tools"] = [
        {
            "type": "web_search",
            "user_location": {"type": "approximate", "country": "AU"},
        }
    ]
    adapter, transport, _ = _adapter(body)
    requested = RequestedModelLocation(
        country_code="AU",
        region_code="NSW",
        locale="en-AU",
        language="en",
    )
    expected = EffectiveModelLocation(
        control=ModelLocationControl.COUNTRY,
        country_code="AU",
        region_code=None,
        locale=None,
        language=None,
        evidence_hash="a" * 64,
    )

    result = adapter.generate(
        request(
            MODEL,
            search_mode="web",
            requested_location=requested,
            expected_effective_location=expected,
        ),
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert transport.payload["tools"] == [
        {
            "type": "web_search",
            "user_location": {"type": "approximate", "country": "AU"},
        }
    ]
    assert result.requested_location == requested
    assert result.effective_location == expected


def test_openai_missing_location_receipt_downgrades_to_not_controlled() -> None:
    adapter, _, _ = _adapter(_success_body())
    requested = RequestedModelLocation("AU", None, "en-AU", "en")
    expected = EffectiveModelLocation(
        ModelLocationControl.COUNTRY,
        "AU",
        None,
        None,
        None,
        "a" * 64,
    )

    result = adapter.generate(
        request(
            MODEL,
            search_mode="web",
            requested_location=requested,
            expected_effective_location=expected,
        ),
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert result.effective_location is not None
    assert result.effective_location.control is ModelLocationControl.NOT_CONTROLLED
    assert result.effective_location.evidence_hash != expected.evidence_hash


def test_openai_refusal_is_distinct_from_schema_failure() -> None:
    body = _success_body()
    body["output"] = [
        {
            "type": "message",
            "content": [{"type": "refusal", "refusal": "cannot comply"}],
        }
    ]
    adapter, _, _ = _adapter(body)

    with pytest.raises(ModelGatewayError) as captured:
        adapter.generate(
            request(MODEL, search_mode="web"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    assert captured.value.code is ModelGatewayErrorCode.CONTENT_REFUSAL
    assert captured.value.retryable is False


def test_openai_invalid_structured_text_fails_closed() -> None:
    adapter, _, _ = _adapter(_success_body(text='{"answer":'))

    with pytest.raises(StructuredOutputValidationError) as captured:
        adapter.generate(
            request(MODEL, search_mode="web"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    assert captured.value.code is ModelGatewayErrorCode.SCHEMA_INVALID
    assert captured.value.provider == "openai"


@pytest.mark.parametrize(
    ("status", "body", "error_type", "code"),
    (
        (
            401,
            {"error": {"type": "authentication_error"}},
            ModelGatewayError,
            ModelGatewayErrorCode.AUTH,
        ),
        (
            429,
            {"error": {"type": "rate_limit"}},
            RetryableModelGatewayError,
            ModelGatewayErrorCode.RATE_LIMIT,
        ),
        (
            429,
            {"error": {"type": "insufficient_quota"}},
            ModelGatewayError,
            ModelGatewayErrorCode.QUOTA,
        ),
        (
            503,
            {"error": {"type": "server_error"}},
            RetryableModelGatewayError,
            ModelGatewayErrorCode.PROVIDER_UNAVAILABLE,
        ),
        (
            504,
            {"error": {"type": "gateway_timeout"}},
            RetryableModelGatewayError,
            ModelGatewayErrorCode.TIMEOUT,
        ),
        (422, {"error": {"type": "bad_request"}}, ModelGatewayError, ModelGatewayErrorCode.POLICY),
    ),
)
def test_provider_http_errors_are_normalized(
    status: int,
    body: dict[str, object],
    error_type: type[ModelGatewayError],
    code: ModelGatewayErrorCode,
) -> None:
    transport = RecordingJsonTransport(json_response(body, status_code=status))
    adapter = OpenAIResponsesAdapter(
        runtime=runtime("openai", model=MODEL),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
    )

    with pytest.raises(error_type) as captured:
        adapter.generate(
            request(MODEL, search_mode="web"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    assert captured.value.code is code
    assert captured.value.provider == "openai"
    assert captured.value.status_code == status


@pytest.mark.parametrize(
    ("purpose", "capture_method", "message"),
    (
        (
            "candidate_generation",
            ModelCaptureMethod.PROVIDER_API,
            "purpose",
        ),
        (
            "cross_engine_sampling",
            ModelCaptureMethod.PROXY_GROUNDED_API,
            "capture method",
        ),
    ),
)
def test_wrong_purpose_or_capture_method_never_resolves_secret_or_calls_transport(
    purpose: str,
    capture_method: ModelCaptureMethod,
    message: str,
) -> None:
    adapter, transport, resolver = _adapter(_success_body())
    wrong = replace(
        request(MODEL, search_mode="web"),
        purpose=purpose,
        capture_method=capture_method,
    )
    budget = ModelCallBudget(1)

    with pytest.raises(ProviderPolicyViolation, match=message):
        adapter.generate(wrong, policy=ModelPolicy(), budget=budget)

    assert resolver.calls == []
    assert transport.calls == 0
    assert budget.consumed_calls == 0


def test_malformed_provider_envelope_keeps_provider_identity() -> None:
    adapter, _, _ = _adapter([{"not": "an object envelope"}])

    with pytest.raises(StructuredOutputValidationError) as captured:
        adapter.generate(
            request(MODEL, search_mode="web"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    assert captured.value.provider == "openai"


def test_provider_runtime_rejects_a_draft_adapter_release() -> None:
    approved_runtime = runtime("openai", model=MODEL)

    with pytest.raises(ProviderPolicyViolation, match="approved release"):
        ProviderAdapterRuntime(
            adapter_release=replace(
                approved_runtime.adapter_release,
                state=ReleaseState.DRAFT,
            ),
            capture_method=approved_runtime.capture_method,
            allowed_purposes=approved_runtime.allowed_purposes,
            allowed_models=approved_runtime.allowed_models,
            allowed_search_modes=approved_runtime.allowed_search_modes,
        )
