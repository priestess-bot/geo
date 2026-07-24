"""Secret Store-backed DeepSeek Chat Completions adapter for new workflows."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from geo_core.model_gateway.contracts import (
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ProviderPolicyViolation,
    RetryableModelGatewayError,
    StructuredOutputValidationError,
)
from geo_core.model_gateway.provider_adapters.artifacts import ProviderArtifactSink
from geo_core.model_gateway.provider_adapters.base import (
    CredentialResolver,
    JsonTransport,
    ParsedProviderResponse,
    ProviderAdapterRuntime,
    ProviderJsonAdapter,
)
from geo_core.model_gateway.provider_adapters.response_values import (
    optional_int,
    optional_text,
    parse_json_object_text,
    require_list,
    require_mapping,
    required_text,
)


DEEPSEEK_CHAT_API_DOC = "https://api-docs.deepseek.com/api/create-chat-completion"
DEEPSEEK_JSON_OUTPUT_DOC = "https://api-docs.deepseek.com/guides/json_mode"


class DeepSeekChatCompletionsAdapter(ProviderJsonAdapter):
    """Resolve a scoped credential immediately before every DeepSeek request."""

    provider = "deepseek"
    expected_capture_method = ModelCaptureMethod.PROVIDER_API
    documentation_references = (DEEPSEEK_CHAT_API_DOC, DEEPSEEK_JSON_OUTPUT_DOC)

    def __init__(
        self,
        *,
        runtime: ProviderAdapterRuntime,
        secret_reference_id: UUID,
        credential_resolver: CredentialResolver,
        transport: JsonTransport,
        artifact_sink: ProviderArtifactSink | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(
            runtime=runtime,
            secret_reference_id=secret_reference_id,
            credential_resolver=credential_resolver,
            transport=transport,
            endpoint="https://api.deepseek.com/chat/completions",
            artifact_sink=artifact_sink,
            timeout_seconds=timeout_seconds,
        )

    def build_payload(self, request: ModelGatewayRequest) -> Mapping[str, object]:
        if request.search_mode not in {None, "disabled"}:
            raise ProviderPolicyViolation(
                "DeepSeek Chat Completions has no approved native search mode",
                provider=self.provider,
            )
        assert request.output_schema is not None
        return {
            "model": request.configured_model,
            "messages": [dict(message) for message in request.messages],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "stream": False,
            "response_format": {"type": "json_object"},
        }

    def parse_response(
        self,
        body: Mapping[str, object],
        headers: Mapping[str, str],
        request: ModelGatewayRequest,
    ) -> ParsedProviderResponse:
        del request
        choices = require_list(body.get("choices"), label="DeepSeek response choices")
        if len(choices) != 1:
            raise StructuredOutputValidationError(
                "DeepSeek response must contain exactly one choice", provider=self.provider
            )
        choice = require_mapping(choices[0], label="DeepSeek response choice")
        finish_reason = required_text(
            choice.get("finish_reason"), label="DeepSeek finish reason"
        )
        if finish_reason == "content_filter":
            raise ModelGatewayError(
                "DeepSeek refused the request",
                code=ModelGatewayErrorCode.CONTENT_REFUSAL,
                provider=self.provider,
            )
        if finish_reason == "insufficient_system_resource":
            raise RetryableModelGatewayError(
                "DeepSeek reported insufficient system resources",
                code=ModelGatewayErrorCode.PROVIDER_UNAVAILABLE,
                provider=self.provider,
                status_code=503,
            )
        if finish_reason != "stop":
            raise StructuredOutputValidationError(
                f"DeepSeek response is incomplete: {finish_reason}",
                provider=self.provider,
            )
        message = require_mapping(choice.get("message"), label="DeepSeek response message")
        usage = require_mapping(body.get("usage"), label="DeepSeek response usage")
        return ParsedProviderResponse(
            output=parse_json_object_text(message.get("content"), provider=self.provider),
            provider_request_id=_header(headers, "x-request-id")
            or optional_text(body.get("id")),
            provider_reported_model=optional_text(body.get("model")),
            prompt_tokens=optional_int(usage.get("prompt_tokens")),
            completion_tokens=optional_int(usage.get("completion_tokens")),
            cost_usd=None,
            finish_reason=finish_reason,
            usage_details=_usage_details(usage),
        )


def _usage_details(usage: Mapping[str, object]) -> Mapping[str, object]:
    details: dict[str, object] = {}
    for name in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    ):
        value = optional_int(usage.get(name))
        if value is not None:
            details[name] = value
    completion_details = usage.get("completion_tokens_details")
    if isinstance(completion_details, Mapping):
        reasoning_tokens = optional_int(completion_details.get("reasoning_tokens"))
        if reasoning_tokens is not None:
            details["reasoning_tokens"] = reasoning_tokens
    return details


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next(
        (value for key, value in headers.items() if key.lower() == name.lower() and value),
        None,
    )


__all__ = ["DeepSeekChatCompletionsAdapter"]
