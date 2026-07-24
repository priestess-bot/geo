"""Gemini generateContent adapter with Google Search grounding lineage."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote
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
    normalized_citation,
    optional_int,
    optional_text,
    parse_json_object_text,
    require_list,
    require_mapping,
    required_text,
)


GEMINI_GENERATE_CONTENT_DOC = "https://ai.google.dev/api/generate-content"
GEMINI_GOOGLE_SEARCH_DOC = "https://ai.google.dev/gemini-api/docs/google-search"
GEMINI_AUTH_DOC = "https://ai.google.dev/api#authentication"


class GeminiGenerateContentAdapter(ProviderJsonAdapter):
    provider = "gemini"
    expected_capture_method = ModelCaptureMethod.PROVIDER_API
    documentation_references = (
        GEMINI_GENERATE_CONTENT_DOC,
        GEMINI_GOOGLE_SEARCH_DOC,
        GEMINI_AUTH_DOC,
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
            endpoint="https://generativelanguage.googleapis.com/v1beta/models",
            artifact_sink=artifact_sink,
            timeout_seconds=timeout_seconds,
        )

    def authorization_headers(self, credential: str) -> Mapping[str, str]:
        return {"x-goog-api-key": credential}

    def request_url(self, request: ModelGatewayRequest) -> str:
        model = quote(request.configured_model, safe="")
        return f"{self.endpoint}/{model}:generateContent"

    def build_payload(self, request: ModelGatewayRequest) -> Mapping[str, object]:
        assert request.output_schema is not None
        contents: list[Mapping[str, object]] = []
        system_parts: list[Mapping[str, str]] = []
        for message in request.messages:
            role = message.get("role")
            content = message.get("content")
            if not isinstance(content, str) or not content:
                raise ProviderPolicyViolation(
                    "Gemini adapter only accepts non-empty text messages",
                    provider=self.provider,
                )
            if role == "system":
                system_parts.append({"text": content})
                continue
            if role not in {"user", "assistant"}:
                raise ProviderPolicyViolation(
                    f"Gemini adapter does not support message role: {role}",
                    provider=self.provider,
                )
            contents.append(
                {"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]}
            )
        if not contents:
            raise ProviderPolicyViolation(
                "Gemini adapter requires at least one non-system message",
                provider=self.provider,
            )
        generation_config: dict[str, object] = {
            "responseMimeType": "application/json",
            "responseJsonSchema": dict(request.output_schema),
            "maxOutputTokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        if request.seed is not None:
            generation_config["seed"] = request.seed
        payload: dict[str, object] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        if request.search_mode == "google_search":
            if not self.runtime.adapter_release.capabilities.supports_structured_output_with_tools:
                raise ProviderPolicyViolation(
                    "Gemini Adapter Release does not approve structured output with Google Search",
                    provider=self.provider,
                )
            payload["tools"] = [{"googleSearch": {}}]
        return payload

    def parse_response(
        self,
        body: Mapping[str, object],
        headers: Mapping[str, str],
        request: ModelGatewayRequest,
    ) -> ParsedProviderResponse:
        del headers
        prompt_feedback_value = body.get("promptFeedback")
        if isinstance(prompt_feedback_value, Mapping) and prompt_feedback_value.get(
            "blockReason"
        ) not in (None, "BLOCK_REASON_UNSPECIFIED"):
            raise ModelGatewayError(
                "Gemini refused the prompt",
                code=ModelGatewayErrorCode.CONTENT_REFUSAL,
                provider=self.provider,
            )
        candidates = require_list(body.get("candidates"), label="Gemini candidates")
        if len(candidates) != 1:
            raise StructuredOutputValidationError(
                "Gemini response must contain exactly one candidate", provider=self.provider
            )
        candidate = require_mapping(candidates[0], label="Gemini candidate")
        finish_reason = required_text(candidate.get("finishReason"), label="Gemini finish reason")
        if finish_reason in {
            "SAFETY",
            "RECITATION",
            "BLOCKLIST",
            "PROHIBITED_CONTENT",
            "SPII",
            "ESCALATION",
        }:
            raise ModelGatewayError(
                "Gemini refused the response",
                code=ModelGatewayErrorCode.CONTENT_REFUSAL,
                provider=self.provider,
            )
        if finish_reason != "STOP":
            raise StructuredOutputValidationError(
                f"Gemini response is incomplete: {finish_reason}", provider=self.provider
            )
        text = _candidate_text(candidate)
        citations, tool_events = _grounding_lineage(candidate, provider=self.provider)
        if request.search_mode == "google_search" and (not citations or not tool_events):
            raise StructuredOutputValidationError(
                "Gemini grounded response lacks grounding or citation lineage",
                provider=self.provider,
            )
        usage = require_mapping(body.get("usageMetadata"), label="Gemini usage metadata")
        return ParsedProviderResponse(
            output=parse_json_object_text(text, provider=self.provider),
            provider_request_id=optional_text(body.get("responseId")),
            provider_reported_model=optional_text(body.get("modelVersion")),
            prompt_tokens=optional_int(usage.get("promptTokenCount")),
            completion_tokens=optional_int(usage.get("candidatesTokenCount")),
            cost_usd=None,
            finish_reason=finish_reason,
            citations=citations,
            tool_events=tool_events,
            usage_details=_usage_details(usage),
        )


def _candidate_text(candidate: Mapping[str, object]) -> str:
    content = require_mapping(candidate.get("content"), label="Gemini candidate content")
    parts = require_list(content.get("parts"), label="Gemini candidate parts")
    text_parts: list[str] = []
    for raw_part in parts:
        value = _part(raw_part).get("text")
        if value is None:
            continue
        if not isinstance(value, str):
            raise StructuredOutputValidationError("Gemini candidate text part is invalid")
        text_parts.append(value)
    if not text_parts:
        raise StructuredOutputValidationError("Gemini candidate has no valid text output")
    return "".join(text_parts)


def _part(value: object) -> Mapping[str, object]:
    return require_mapping(value, label="Gemini candidate part")


def _grounding_lineage(
    candidate: Mapping[str, object], *, provider: str
) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    metadata_value = candidate.get("groundingMetadata")
    if metadata_value is None:
        return (), ()
    metadata = require_mapping(metadata_value, label="Gemini grounding metadata")
    citations: list[Mapping[str, object]] = []
    chunks = require_list(metadata.get("groundingChunks", []), label="Gemini grounding chunks")
    for raw_chunk in chunks:
        chunk = require_mapping(raw_chunk, label="Gemini grounding chunk")
        web_value = chunk.get("web")
        if not isinstance(web_value, Mapping):
            continue
        citations.append(
            normalized_citation(
                provider=provider,
                url=web_value.get("uri"),
                title=web_value.get("title"),
                ordinal=len(citations) + 1,
                source_id=chunk.get("id"),
                citation_type="grounding_chunk",
            )
        )
    events: list[Mapping[str, object]] = []
    queries = metadata.get("webSearchQueries")
    if isinstance(queries, list) and all(isinstance(value, str) for value in queries):
        events.append({"type": "google_search_queries", "queries": tuple(queries)})
    supports = metadata.get("groundingSupports")
    if isinstance(supports, list):
        for raw_support in supports:
            support = require_mapping(raw_support, label="Gemini grounding support")
            segment_value = support.get("segment")
            segment = segment_value if isinstance(segment_value, Mapping) else {}
            indices = support.get("groundingChunkIndices", [])
            if not isinstance(indices, list) or not all(
                isinstance(value, int) and not isinstance(value, bool) for value in indices
            ):
                raise StructuredOutputValidationError(
                    "Gemini grounding support indices are invalid"
                )
            events.append(
                {
                    "type": "grounding_support",
                    "chunk_indices": tuple(indices),
                    "start_index": optional_int(segment.get("startIndex")),
                    "end_index": optional_int(segment.get("endIndex")),
                }
            )
    return tuple(citations), tuple(events)


def _usage_details(usage: Mapping[str, object]) -> Mapping[str, object]:
    details: dict[str, object] = {}
    for name in (
        "promptTokenCount",
        "cachedContentTokenCount",
        "candidatesTokenCount",
        "toolUsePromptTokenCount",
        "thoughtsTokenCount",
        "totalTokenCount",
    ):
        value = optional_int(usage.get(name))
        if value is not None:
            details[name] = value
    return details
