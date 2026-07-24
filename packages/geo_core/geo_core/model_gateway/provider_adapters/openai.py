"""OpenAI Responses API adapter with structured output and web-search lineage."""

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
from geo_core.model_gateway.location import (
    EffectiveModelLocation,
    ModelLocationControl,
    uncontrolled_model_location,
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


OPENAI_STRUCTURED_OUTPUTS_DOC = "https://developers.openai.com/api/docs/guides/structured-outputs"
OPENAI_WEB_SEARCH_DOC = "https://developers.openai.com/api/docs/guides/tools-web-search"


class OpenAIResponsesAdapter(ProviderJsonAdapter):
    provider = "openai"
    expected_capture_method = ModelCaptureMethod.PROVIDER_API
    documentation_references = (OPENAI_STRUCTURED_OUTPUTS_DOC, OPENAI_WEB_SEARCH_DOC)

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
            endpoint="https://api.openai.com/v1/responses",
            artifact_sink=artifact_sink,
            timeout_seconds=timeout_seconds,
        )

    def build_payload(self, request: ModelGatewayRequest) -> Mapping[str, object]:
        assert request.output_schema is not None
        payload: dict[str, object] = {
            "model": request.configured_model,
            "input": [dict(message) for message in request.messages],
            "max_output_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "geo_structured_output",
                    "strict": True,
                    "schema": dict(request.output_schema),
                }
            },
        }
        if request.search_mode == "web":
            tool: dict[str, object] = {"type": "web_search"}
            expected = request.expected_effective_location
            requested = request.requested_location
            if expected is not None and expected.control is ModelLocationControl.COUNTRY:
                if (
                    requested is None
                    or requested.country_code is None
                    or expected.country_code != requested.country_code
                ):
                    raise ProviderPolicyViolation(
                        "OpenAI country control requires the exact requested country",
                        provider=self.provider,
                    )
                tool["user_location"] = {
                    "type": "approximate",
                    "country": expected.country_code,
                }
            elif expected is not None and expected.control is not ModelLocationControl.NOT_CONTROLLED:
                raise ProviderPolicyViolation(
                    "OpenAI adapter only proves country-level location control",
                    provider=self.provider,
                )
            payload.update(
                {
                    "tools": [tool],
                    "tool_choice": "required",
                    "include": ["web_search_call.action.sources"],
                }
            )
        return payload

    def resolve_effective_location(
        self,
        request: ModelGatewayRequest,
        *,
        body: Mapping[str, object],
        parsed: ParsedProviderResponse,
    ) -> EffectiveModelLocation | None:
        del parsed
        expected = request.expected_effective_location
        if expected is None or expected.control is ModelLocationControl.NOT_CONTROLLED:
            return expected
        if expected.control is not ModelLocationControl.COUNTRY:
            return uncontrolled_model_location(
                provider=self.provider,
                adapter_release_hash=self.adapter_release_hash,
                reason="unsupported_location_control",
            )
        raw_tools = body.get("tools", [])
        if not isinstance(raw_tools, list):
            raw_tools = []
        for raw_tool in raw_tools:
            if not isinstance(raw_tool, Mapping):
                continue
            location = raw_tool.get("user_location")
            if (
                raw_tool.get("type") in {"web_search", "web_search_preview"}
                and isinstance(location, Mapping)
                and location.get("type") == "approximate"
                and location.get("country") == expected.country_code
            ):
                return expected
        return uncontrolled_model_location(
            provider=self.provider,
            adapter_release_hash=self.adapter_release_hash,
            reason="provider_response_did_not_echo_country",
        )

    def parse_response(
        self,
        body: Mapping[str, object],
        headers: Mapping[str, str],
        request: ModelGatewayRequest,
    ) -> ParsedProviderResponse:
        status = required_text(body.get("status"), label="OpenAI response status")
        if status != "completed":
            raise StructuredOutputValidationError(
                f"OpenAI response is incomplete: {status}", provider=self.provider
            )
        text_values: list[str] = []
        citations: list[Mapping[str, object]] = []
        tool_events: list[Mapping[str, object]] = []
        for raw_item in require_list(body.get("output"), label="OpenAI response output"):
            item = require_mapping(raw_item, label="OpenAI response output item")
            item_type = required_text(item.get("type"), label="OpenAI output item type")
            if item_type == "message":
                self._parse_message(item, text_values=text_values, citations=citations)
            elif item_type == "web_search_call":
                tool_events.append(_web_search_event(item))
        if len(text_values) != 1:
            raise StructuredOutputValidationError(
                "OpenAI response must contain exactly one structured output text",
                provider=self.provider,
            )
        if request.search_mode == "web" and (not tool_events or not citations):
            raise StructuredOutputValidationError(
                "OpenAI web-search response lacks search or citation lineage",
                provider=self.provider,
            )
        usage = require_mapping(body.get("usage"), label="OpenAI response usage")
        request_id = _header(headers, "x-request-id") or optional_text(body.get("id"))
        return ParsedProviderResponse(
            output=parse_json_object_text(text_values[0], provider=self.provider),
            provider_request_id=request_id,
            provider_reported_model=optional_text(body.get("model")),
            prompt_tokens=optional_int(usage.get("input_tokens")),
            completion_tokens=optional_int(usage.get("output_tokens")),
            cost_usd=None,
            finish_reason=status,
            citations=tuple(citations),
            tool_events=tuple(tool_events),
            usage_details=_usage_details(usage),
        )

    def _parse_message(
        self,
        item: Mapping[str, object],
        *,
        text_values: list[str],
        citations: list[Mapping[str, object]],
    ) -> None:
        for raw_part in require_list(item.get("content"), label="OpenAI message content"):
            part = require_mapping(raw_part, label="OpenAI message content part")
            part_type = required_text(part.get("type"), label="OpenAI content part type")
            if part_type == "refusal":
                raise ModelGatewayError(
                    "OpenAI refused the request",
                    code=ModelGatewayErrorCode.CONTENT_REFUSAL,
                    provider=self.provider,
                )
            if part_type != "output_text":
                continue
            text_values.append(required_text(part.get("text"), label="OpenAI output text"))
            annotations = part.get("annotations", [])
            for raw_annotation in require_list(annotations, label="OpenAI output text annotations"):
                annotation = require_mapping(raw_annotation, label="OpenAI output text annotation")
                if annotation.get("type") != "url_citation":
                    continue
                citations.append(
                    normalized_citation(
                        provider=self.provider,
                        url=annotation.get("url"),
                        title=annotation.get("title"),
                        ordinal=len(citations) + 1,
                        source_id=annotation.get("id"),
                        start_index=annotation.get("start_index"),
                        end_index=annotation.get("end_index"),
                    )
                )


def _web_search_event(item: Mapping[str, object]) -> Mapping[str, object]:
    action = require_mapping(item.get("action"), label="OpenAI web search action")
    event: dict[str, object] = {
        "type": "web_search_call",
        "provider_event_id": optional_text(item.get("id")) or "",
        "status": optional_text(item.get("status")) or "unknown",
        "action_type": optional_text(action.get("type")) or "unknown",
    }
    query = optional_text(action.get("query"))
    if query is not None:
        event["query"] = query
    queries = action.get("queries")
    if isinstance(queries, list) and all(isinstance(value, str) for value in queries):
        event["queries"] = tuple(queries)
    return event


def _usage_details(usage: Mapping[str, object]) -> Mapping[str, object]:
    details: dict[str, object] = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        value = optional_int(usage.get(name))
        if value is not None:
            details[name] = value
    return details


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next(
        (value for key, value in headers.items() if key.lower() == name.lower() and value),
        None,
    )
