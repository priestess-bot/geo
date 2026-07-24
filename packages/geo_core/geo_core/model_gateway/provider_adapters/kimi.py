"""Kimi OpenAI-compatible structured Chat Completions adapter."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from geo_core.model_gateway.contracts import (
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ProviderPolicyViolation,
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


KIMI_CHAT_API_DOC = "https://platform.kimi.ai/docs/api/chat"
KIMI_API_OVERVIEW_DOC = "https://platform.kimi.ai/docs/api/overview"
KIMI_STRUCTURED_OUTPUT_DOC = "https://platform.kimi.ai/docs/guide/response_format"
KIMI_WEB_SEARCH_DOC = "https://platform.kimi.ai/docs/guide/use-web-search"


class KimiChatCompletionsAdapter(ProviderJsonAdapter):
    provider = "kimi"
    expected_capture_method = ModelCaptureMethod.PROVIDER_API
    documentation_references = (
        KIMI_CHAT_API_DOC,
        KIMI_API_OVERVIEW_DOC,
        KIMI_STRUCTURED_OUTPUT_DOC,
        KIMI_WEB_SEARCH_DOC,
    )

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
            endpoint="https://api.moonshot.ai/v1/chat/completions",
            artifact_sink=artifact_sink,
            timeout_seconds=timeout_seconds,
        )

    def build_payload(self, request: ModelGatewayRequest) -> Mapping[str, object]:
        if request.search_mode != "disabled":
            raise ProviderPolicyViolation(
                "Kimi native search is not verified for this adapter release",
                provider=self.provider,
            )
        assert request.output_schema is not None
        return {
            "model": request.configured_model,
            "messages": [dict(message) for message in request.messages],
            "max_completion_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "geo_structured_output",
                    "strict": True,
                    "schema": dict(request.output_schema),
                },
            },
        }

    def parse_response(
        self,
        body: Mapping[str, object],
        headers: Mapping[str, str],
        request: ModelGatewayRequest,
    ) -> ParsedProviderResponse:
        del request
        choices = require_list(body.get("choices"), label="Kimi response choices")
        if len(choices) != 1:
            raise StructuredOutputValidationError(
                "Kimi response must contain exactly one choice", provider=self.provider
            )
        choice = require_mapping(choices[0], label="Kimi response choice")
        finish_reason = required_text(choice.get("finish_reason"), label="Kimi finish reason")
        if finish_reason in {"content_filter", "safety"}:
            raise ModelGatewayError(
                "Kimi refused the request",
                code=ModelGatewayErrorCode.CONTENT_REFUSAL,
                provider=self.provider,
            )
        if finish_reason != "stop":
            raise StructuredOutputValidationError(
                f"Kimi response is incomplete: {finish_reason}", provider=self.provider
            )
        message = require_mapping(choice.get("message"), label="Kimi response message")
        usage = require_mapping(body.get("usage"), label="Kimi response usage")
        return ParsedProviderResponse(
            output=parse_json_object_text(message.get("content"), provider=self.provider),
            provider_request_id=_header(headers, "x-request-id") or optional_text(body.get("id")),
            provider_reported_model=optional_text(body.get("model")),
            prompt_tokens=optional_int(usage.get("prompt_tokens")),
            completion_tokens=optional_int(usage.get("completion_tokens")),
            cost_usd=None,
            finish_reason=finish_reason,
            usage_details=_usage_details(usage),
        )


def _usage_details(usage: Mapping[str, object]) -> Mapping[str, object]:
    details: dict[str, object] = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
        value = optional_int(usage.get(name))
        if value is not None:
            details[name] = value
    return details


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next(
        (value for key, value in headers.items() if key.lower() == name.lower() and value),
        None,
    )
