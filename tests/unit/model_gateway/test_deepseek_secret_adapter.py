from __future__ import annotations

import json
import pytest

from geo_core.model_gateway import (
    DeepSeekChatCompletionsAdapter,
    ModelCallBudget,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelPolicy,
)
from geo_core.secrets import SecretValue, SecretVersionHandle, SecretVersionUnavailable

from .provider_adapter_test_support import (
    OUTPUT_SCHEMA,
    SECRET_REFERENCE_ID,
    RecordingJsonTransport,
    json_response,
    request,
    runtime,
)


MODEL = "deepseek-v4-pro"


def _body() -> dict[str, object]:
    return {
        "id": "deepseek-response-fixture",
        "object": "chat.completion",
        "model": "deepseek-v4-pro-reported",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {"answer": "DeepSeek completed it.", "recommended": True}
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 21,
            "completion_tokens": 7,
            "total_tokens": 28,
            "prompt_cache_hit_tokens": 4,
            "prompt_cache_miss_tokens": 17,
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    }


class RevocableCredentialResolver:
    def __init__(self) -> None:
        self.available = True
        self.calls: list[SecretVersionHandle] = []

    def resolve(self, handle: SecretVersionHandle) -> SecretValue:
        self.calls.append(handle)
        if not self.available:
            raise SecretVersionUnavailable("provider credential version is unavailable")
        return SecretValue("deepseek-secret-fixture")


def _adapter(
    resolver: RevocableCredentialResolver,
) -> tuple[DeepSeekChatCompletionsAdapter, RecordingJsonTransport]:
    transport = RecordingJsonTransport(json_response(_body()))
    adapter = DeepSeekChatCompletionsAdapter(
        runtime=runtime(
            "deepseek",
            model=MODEL,
            search_modes=frozenset({"disabled"}),
            supports_search=False,
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=resolver,
        transport=transport,
    )
    return adapter, transport


def test_deepseek_secret_adapter_uses_official_json_mode_contract() -> None:
    resolver = RevocableCredentialResolver()
    adapter, transport = _adapter(resolver)
    model_request = request(MODEL, search_mode="disabled")

    result = adapter.generate(
        model_request,
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert transport.url == "https://api.deepseek.com/chat/completions"
    assert transport.payload == {
        "model": MODEL,
        "messages": [dict(message) for message in model_request.messages],
        "max_tokens": model_request.max_output_tokens,
        "temperature": model_request.temperature,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    assert transport.headers["Authorization"] == "Bearer deepseek-secret-fixture"
    assert result.output == {"answer": "DeepSeek completed it.", "recommended": True}
    assert result.provider_request_id == "header-request-id"
    assert result.provider_reported_model == "deepseek-v4-pro-reported"
    assert result.usage_details == {
        "prompt_tokens": 21,
        "completion_tokens": 7,
        "total_tokens": 28,
        "prompt_cache_hit_tokens": 4,
        "prompt_cache_miss_tokens": 17,
        "reasoning_tokens": 3,
    }
    assert OUTPUT_SCHEMA not in transport.payload.values()
    assert "deepseek-secret-fixture" not in repr((adapter, result, resolver))


def test_deepseek_resolves_each_call_and_revocation_fails_before_network_io() -> None:
    resolver = RevocableCredentialResolver()
    adapter, transport = _adapter(resolver)
    model_request = request(MODEL, search_mode="disabled")

    adapter.generate(model_request, policy=ModelPolicy(), budget=ModelCallBudget(1))
    resolver.available = False
    with pytest.raises(ModelGatewayError) as captured:
        adapter.generate(model_request, policy=ModelPolicy(), budget=ModelCallBudget(1))

    assert captured.value.code is ModelGatewayErrorCode.AUTH
    assert transport.calls == 1
    assert resolver.calls == [
        model_request.provider_secret_handle,
        model_request.provider_secret_handle,
    ]
    assert not hasattr(adapter, "api_key_file")


def test_deepseek_non_search_generation_accepts_none_without_search_capability() -> None:
    resolver = RevocableCredentialResolver()
    transport = RecordingJsonTransport(json_response(_body()))
    adapter = DeepSeekChatCompletionsAdapter(
        runtime=runtime(
            "deepseek",
            model=MODEL,
            search_modes=frozenset({None}),
            supports_search=False,
            purpose="recommendation",
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=resolver,
        transport=transport,
    )
    model_request = request(
        MODEL,
        search_mode=None,
        purpose="recommendation",
    )

    result = adapter.generate(
        model_request,
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert result.search_mode is None
    assert transport.calls == 1
