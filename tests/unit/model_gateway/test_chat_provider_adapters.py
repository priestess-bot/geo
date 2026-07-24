from __future__ import annotations

from decimal import Decimal
import json
import pytest

from geo_core.model_gateway import (
    EffectiveModelLocation,
    ModelCallBudget,
    ModelCaptureMethod,
    ModelPolicy,
    ModelLocationControl,
    ProviderPolicyViolation,
    RequestedModelLocation,
    StructuredOutputValidationError,
)
from geo_core.model_gateway.provider_adapters import (
    KimiChatCompletionsAdapter,
    PerplexitySonarAdapter,
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


def test_kimi_chat_completions_is_structured_and_search_disabled() -> None:
    body = {
        "id": "cmpl-kimi-fixture",
        "object": "chat.completion",
        "model": "kimi-fixture-reported",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {"answer": "The fixture is positive.", "recommended": True}
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 8,
            "total_tokens": 28,
            "cached_tokens": 4,
        },
    }
    transport = RecordingJsonTransport(json_response(body))
    adapter = KimiChatCompletionsAdapter(
        runtime=runtime(
            "kimi",
            model="kimi-fixture",
            search_modes=frozenset({"disabled"}),
            supports_search=False,
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
    )

    result = adapter.generate(
        request("kimi-fixture", search_mode="disabled"),
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert transport.url == "https://api.moonshot.ai/v1/chat/completions"
    assert transport.headers["Authorization"] == f"Bearer {SECRET_TEXT}"
    assert transport.payload["max_completion_tokens"] == 4096
    response_format = transport.payload["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"]["required"] == [
        "answer",
        "recommended",
    ]
    assert "tools" not in transport.payload
    assert result.output["recommended"] is True
    assert result.search_mode == "disabled"
    assert result.citations == ()
    assert result.usage_details == {
        "prompt_tokens": 20,
        "completion_tokens": 8,
        "total_tokens": 28,
        "cached_tokens": 4,
    }


def test_kimi_search_cannot_be_enabled_without_verified_native_capability() -> None:
    transport = RecordingJsonTransport(json_response({}))
    adapter = KimiChatCompletionsAdapter(
        runtime=runtime(
            "kimi",
            model="kimi-fixture",
            search_modes=frozenset({"disabled"}),
            supports_search=False,
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
    )

    with pytest.raises(ProviderPolicyViolation, match="search mode"):
        adapter.generate(
            request("kimi-fixture", search_mode="web"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    assert transport.calls == 0


def test_kimi_length_finish_is_not_accepted_as_complete_json() -> None:
    body = {
        "id": "cmpl-kimi-fixture",
        "model": "kimi-fixture",
        "choices": [
            {
                "message": {"content": '{"answer":"truncated"'},
                "finish_reason": "length",
            }
        ],
        "usage": {},
    }
    adapter = KimiChatCompletionsAdapter(
        runtime=runtime(
            "kimi",
            model="kimi-fixture",
            search_modes=frozenset({"disabled"}),
            supports_search=False,
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=RecordingJsonTransport(json_response(body)),
    )

    with pytest.raises(StructuredOutputValidationError, match="incomplete: length"):
        adapter.generate(
            request("kimi-fixture", search_mode="disabled"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )


def test_perplexity_sonar_preserves_citation_search_and_cost_lineage() -> None:
    body = {
        "id": "sonar-fixture-1",
        "object": "chat.completion",
        "model": "sonar-pro-reported",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"answer": "Sources recommend it.", "recommended": True}),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 40,
            "completion_tokens": 15,
            "total_tokens": 55,
            "citation_tokens": 7,
            "num_search_queries": 1,
            "cost": {
                "input_tokens_cost": 0.001,
                "output_tokens_cost": 0.002,
                "total_cost": 0.003,
            },
        },
        "citations": ["https://example.org/source"],
        "search_results": [
            {
                "title": "Australian product review",
                "url": "https://example.org/source",
                "date": "2026-07-22",
                "source": "web",
            }
        ],
    }
    transport = RecordingJsonTransport(json_response(body))
    adapter = PerplexitySonarAdapter(
        runtime=runtime("perplexity", model="sonar-pro-fixture"),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
    )

    result = adapter.generate(
        request("sonar-pro-fixture", search_mode="web"),
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert transport.url == "https://api.perplexity.ai/v1/sonar"
    assert transport.payload["web_search_options"] == {
        "search_mode": "web",
        "disable_search": False,
    }
    assert "search_mode" not in transport.payload
    assert "disable_search" not in transport.payload
    assert result.provider_request_id == "sonar-fixture-1"
    assert result.provider_reported_model == "sonar-pro-reported"
    assert result.cost_usd == Decimal("0.003")
    assert result.citations[0]["title"] == "Australian product review"
    assert result.tool_events[0] == {
        "type": "search_result",
        "ordinal": 1,
        "url": "https://example.org/source",
        "title": "Australian product review",
        "date": "2026-07-22",
        "source": "web",
    }
    assert result.capture_method is ModelCaptureMethod.PROVIDER_API
    assert "consumer" not in repr(result).lower()


def test_perplexity_sonar_applies_au_country_and_language_controls() -> None:
    body = {
        "id": "sonar-au-fixture",
        "model": "sonar-pro-reported",
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"answer": "Australian sources recommend it.", "recommended": True}
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {},
        "citations": ["https://example.org/au-source"],
        "search_results": [{"url": "https://example.org/au-source"}],
    }
    transport = RecordingJsonTransport(json_response(body))
    adapter = PerplexitySonarAdapter(
        runtime=runtime("perplexity", model="sonar-pro-fixture"),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
    )
    requested = RequestedModelLocation("AU", "NSW", "en-AU", "en")
    expected = EffectiveModelLocation(
        ModelLocationControl.COUNTRY,
        "AU",
        None,
        None,
        None,
        "b" * 64,
    )

    result = adapter.generate(
        request(
            "sonar-pro-fixture",
            search_mode="web",
            requested_location=requested,
            expected_effective_location=expected,
        ),
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert transport.payload["web_search_options"] == {
        "search_mode": "web",
        "disable_search": False,
        "user_location": {"country": "AU"},
    }
    assert transport.payload["search_language_filter"] == ["en"]
    assert result.requested_location == requested
    assert result.effective_location == expected


def test_perplexity_web_mode_requires_provider_citations() -> None:
    body = {
        "id": "sonar-fixture-1",
        "model": "sonar-pro-fixture",
        "choices": [
            {
                "message": {"content": json.dumps({"answer": "No source", "recommended": False})},
                "finish_reason": "stop",
            }
        ],
        "usage": {},
        "citations": [],
        "search_results": [],
    }
    adapter = PerplexitySonarAdapter(
        runtime=runtime("perplexity", model="sonar-pro-fixture"),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=RecordingJsonTransport(json_response(body)),
    )

    with pytest.raises(StructuredOutputValidationError, match="citation lineage"):
        adapter.generate(
            request("sonar-pro-fixture", search_mode="web"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )
