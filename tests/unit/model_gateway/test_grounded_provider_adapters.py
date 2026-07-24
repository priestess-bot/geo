from __future__ import annotations

import json
import pytest

from geo_core.model_gateway import (
    EffectiveModelLocation,
    ModelCallBudget,
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelPolicy,
    ModelLocationControl,
    ProviderPolicyViolation,
    RequestedModelLocation,
    StructuredOutputValidationError,
)
from geo_core.model_gateway.provider_adapters import (
    GeminiGenerateContentAdapter,
    MicrosoftAgentReference,
    MicrosoftBingGroundingAdapter,
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


def _gemini_body() -> dict[str, object]:
    return {
        "responseId": "gemini-response-fixture",
        "modelVersion": "gemini-fixture-2026-07-23",
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "text": json.dumps(
                                {"answer": "Grounded reviews are positive.", "recommended": True}
                            )
                        }
                    ],
                },
                "groundingMetadata": {
                    "webSearchQueries": ["product review Australia"],
                    "groundingChunks": [
                        {
                            "web": {
                                "uri": "https://example.net/au-review",
                                "title": "AU product review",
                            }
                        }
                    ],
                    "groundingSupports": [
                        {
                            "segment": {"startIndex": 0, "endIndex": 18},
                            "groundingChunkIndices": [0],
                        }
                    ],
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 31,
            "candidatesTokenCount": 13,
            "toolUsePromptTokenCount": 5,
            "totalTokenCount": 49,
        },
    }


def test_gemini_generate_content_maps_grounding_metadata_and_usage() -> None:
    transport = RecordingJsonTransport(json_response(_gemini_body()))
    adapter = GeminiGenerateContentAdapter(
        runtime=runtime(
            "gemini",
            model="gemini-3.1-pro-preview",
            search_modes=frozenset({"google_search"}),
            supports_structured_output_with_tools=True,
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
    )

    result = adapter.generate(
        request("gemini-3.1-pro-preview", search_mode="google_search"),
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert transport.url is not None
    assert transport.url.endswith("/gemini-3.1-pro-preview:generateContent")
    assert transport.headers["x-goog-api-key"] == SECRET_TEXT
    assert "Authorization" not in transport.headers
    assert transport.payload["tools"] == [{"googleSearch": {}}]
    config = transport.payload["generationConfig"]
    assert isinstance(config, dict)
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer", "recommended"],
        "properties": {
            "answer": {"type": "string", "minLength": 1},
            "recommended": {"type": "boolean"},
        },
    }
    assert "responseFormat" not in config
    assert result.provider_request_id == "gemini-response-fixture"
    assert result.provider_reported_model == "gemini-fixture-2026-07-23"
    assert result.citations[0]["citation_type"] == "grounding_chunk"
    assert result.citations[0]["url"] == "https://example.net/au-review"
    assert result.tool_events == (
        {"type": "google_search_queries", "queries": ("product review Australia",)},
        {
            "type": "grounding_support",
            "chunk_indices": (0,),
            "start_index": 0,
            "end_index": 18,
        },
    )
    assert result.usage_details == {
        "promptTokenCount": 31,
        "candidatesTokenCount": 13,
        "toolUsePromptTokenCount": 5,
        "totalTokenCount": 49,
    }


def test_gemini_2_5_cannot_combine_structured_output_with_google_search() -> None:
    transport = RecordingJsonTransport(json_response(_gemini_body()))
    resolver = StaticCredentialResolver()
    adapter = GeminiGenerateContentAdapter(
        runtime=runtime(
            "gemini",
            model="gemini-2.5-flash",
            search_modes=frozenset({"google_search"}),
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=resolver,
        transport=transport,
    )

    with pytest.raises(ProviderPolicyViolation, match="structured output with Google Search"):
        adapter.generate(
            request("gemini-2.5-flash", search_mode="google_search"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    assert transport.calls == 0
    assert resolver.calls == []


def test_gemini_safety_finish_is_a_content_refusal() -> None:
    body = _gemini_body()
    body["candidates"] = [
        {
            "finishReason": "SAFETY",
            "content": {"parts": []},
        }
    ]
    adapter = GeminiGenerateContentAdapter(
        runtime=runtime(
            "gemini",
            model="gemini-3.1-pro-preview",
            search_modes=frozenset({"google_search"}),
            supports_structured_output_with_tools=True,
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=RecordingJsonTransport(json_response(body)),
    )

    with pytest.raises(ModelGatewayError) as captured:
        adapter.generate(
            request("gemini-3.1-pro-preview", search_mode="google_search"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    assert captured.value.code is ModelGatewayErrorCode.CONTENT_REFUSAL


def _microsoft_body(
    *, include_bing_query: bool = True, prove_au_market: bool = False
) -> dict[str, object]:
    arguments: dict[str, object] = {"website_urls": ["https://example.edu/evidence"]}
    if include_bing_query:
        arguments["bing_search_query_url"] = (
            "https://www.bing.com/search?q=product+review+australia"
            + ("&mkt=en-AU&setlang=en" if prove_au_market else "")
        )
    return {
        "id": "microsoft-response-fixture",
        "status": "completed",
        "model": "foundry-deployment-reported",
        "output": [
            {
                "type": "bing_grounding_call",
                "id": "bing-call-fixture",
                "status": "completed",
                "arguments": json.dumps(arguments),
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {"answer": "Bing-grounded evidence is positive.", "recommended": True}
                        ),
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.edu/evidence",
                                "title": "Evidence page",
                                "start_index": 0,
                                "end_index": 12,
                            }
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 45, "output_tokens": 16, "total_tokens": 61},
    }


def _microsoft_adapter(
    response: dict[str, object],
) -> tuple[MicrosoftBingGroundingAdapter, RecordingJsonTransport]:
    transport = RecordingJsonTransport(json_response(response))
    adapter = MicrosoftBingGroundingAdapter(
        runtime=runtime(
            "microsoft",
            model="foundry-deployment",
            capture_method=ModelCaptureMethod.PROXY_GROUNDED_API,
            search_modes=frozenset({"bing_grounding"}),
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
        endpoint=(
            "https://fixture.services.ai.azure.com/api/projects/geo/openai/v1/responses"
        ),
        agent_reference=MicrosoftAgentReference(name="geo-bing-grounding-agent", version="1"),
    )
    return adapter, transport


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://attacker.example/api/projects/geo/openai/v1/responses",
        "https://127.0.0.1/api/projects/geo/openai/v1/responses",
        "https://localhost/api/projects/geo/openai/v1/responses",
        "https://services.ai.azure.com/api/projects/geo/openai/v1/responses",
        "https://fixture.openai.azure.com/openai/v1/responses",
        "https://fixture.services.ai.azure.com:444/api/projects/geo/openai/v1/responses",
        "https://user:pass@fixture.services.ai.azure.com/api/projects/geo/openai/v1/responses",
    ),
)
def test_microsoft_endpoint_rejects_hosts_that_cannot_receive_foundry_credentials(
    endpoint: str,
) -> None:
    with pytest.raises(ProviderPolicyViolation, match="endpoint"):
        MicrosoftBingGroundingAdapter(
            runtime=runtime(
                "microsoft",
                model="foundry-deployment",
                capture_method=ModelCaptureMethod.PROXY_GROUNDED_API,
                search_modes=frozenset({"bing_grounding"}),
            ),
            secret_reference_id=SECRET_REFERENCE_ID,
            credential_resolver=StaticCredentialResolver(),
            transport=RecordingJsonTransport(json_response(_microsoft_body())),
            endpoint=endpoint,
            agent_reference=MicrosoftAgentReference(name="geo-agent", version="1"),
        )


def test_microsoft_grounding_is_proxy_api_and_retains_display_references() -> None:
    adapter, transport = _microsoft_adapter(_microsoft_body())

    result = adapter.generate(
        request(
            "foundry-deployment",
            search_mode="bing_grounding",
            capture_method=ModelCaptureMethod.PROXY_GROUNDED_API,
        ),
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert transport.headers["Authorization"] == f"Bearer {SECRET_TEXT}"
    assert transport.payload["agent_reference"] == {
        "type": "agent_reference",
        "name": "geo-bing-grounding-agent",
        "version": "1",
    }
    assert result.capture_method is ModelCaptureMethod.PROXY_GROUNDED_API
    assert result.search_mode == "bing_grounding"
    assert {citation["citation_type"] for citation in result.citations} == {
        "url_citation",
        "bing_search_query",
    }
    assert result.tool_events[0]["type"] == "bing_grounding_call"
    assert "copilot" not in repr(result).lower()
    assert "consumer_ui" not in repr(result).lower()


def test_microsoft_grounding_uses_frozen_au_agent_and_proves_market() -> None:
    transport = RecordingJsonTransport(
        json_response(_microsoft_body(prove_au_market=True))
    )
    adapter = MicrosoftBingGroundingAdapter(
        runtime=runtime(
            "microsoft",
            model="foundry-deployment",
            capture_method=ModelCaptureMethod.PROXY_GROUNDED_API,
            search_modes=frozenset({"bing_grounding"}),
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
        endpoint=(
            "https://fixture.services.ai.azure.com/api/projects/geo/openai/v1/responses"
        ),
        agent_reference=MicrosoftAgentReference(
            name="geo-bing-grounding-au-agent",
            version="1",
            market="en-AU",
            language="en",
        ),
    )
    requested = RequestedModelLocation("AU", "NSW", "en-AU", "en")
    expected = EffectiveModelLocation(
        ModelLocationControl.MARKET_LANGUAGE,
        None,
        None,
        "en-AU",
        "en",
        "c" * 64,
    )

    result = adapter.generate(
        request(
            "foundry-deployment",
            search_mode="bing_grounding",
            capture_method=ModelCaptureMethod.PROXY_GROUNDED_API,
            requested_location=requested,
            expected_effective_location=expected,
        ),
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert transport.payload["agent_reference"] == {
        "type": "agent_reference",
        "name": "geo-bing-grounding-au-agent",
        "version": "1",
    }
    assert result.requested_location == requested
    assert result.effective_location == expected


def test_microsoft_grounding_fails_without_required_bing_query_display_reference() -> None:
    adapter, _ = _microsoft_adapter(_microsoft_body(include_bing_query=False))

    with pytest.raises(StructuredOutputValidationError, match="Bing query references"):
        adapter.generate(
            request(
                "foundry-deployment",
                search_mode="bing_grounding",
                capture_method=ModelCaptureMethod.PROXY_GROUNDED_API,
            ),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )
