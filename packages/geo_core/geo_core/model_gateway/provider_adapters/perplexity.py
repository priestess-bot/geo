"""Perplexity Sonar chat-completion adapter with citation lineage."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from geo_core.model_gateway.contracts import (
    ModelCaptureMethod,
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
    optional_decimal,
    optional_int,
    optional_text,
    parse_json_object_text,
    require_list,
    require_mapping,
    required_text,
)


PERPLEXITY_SONAR_API_DOC = "https://docs.perplexity.ai/api-reference/sonar-post"
PERPLEXITY_STRUCTURED_OUTPUT_DOC = "https://docs.perplexity.ai/docs/sonar/features"


class PerplexitySonarAdapter(ProviderJsonAdapter):
    provider = "perplexity"
    expected_capture_method = ModelCaptureMethod.PROVIDER_API
    documentation_references = (PERPLEXITY_SONAR_API_DOC, PERPLEXITY_STRUCTURED_OUTPUT_DOC)

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
            endpoint="https://api.perplexity.ai/v1/sonar",
            artifact_sink=artifact_sink,
            timeout_seconds=timeout_seconds,
        )

    def build_payload(self, request: ModelGatewayRequest) -> Mapping[str, object]:
        assert request.output_schema is not None
        payload: dict[str, object] = {
            "model": request.configured_model,
            "messages": [dict(message) for message in request.messages],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "geo_structured_output",
                    "schema": dict(request.output_schema),
                },
            },
        }
        if request.search_mode == "disabled":
            payload["web_search_options"] = {"disable_search": True}
        elif request.search_mode == "web":
            payload["web_search_options"] = {
                "search_mode": "web",
                "disable_search": False,
            }
        expected = request.expected_effective_location
        requested = request.requested_location
        if expected is not None and expected.control is ModelLocationControl.COUNTRY:
            if (
                request.search_mode != "web"
                or requested is None
                or requested.country_code is None
                or requested.country_code != expected.country_code
            ):
                raise ProviderPolicyViolation(
                    "Perplexity country control requires web search and an exact country",
                    provider=self.provider,
                )
            options = payload["web_search_options"]
            assert isinstance(options, dict)
            options["user_location"] = {"country": expected.country_code}
            payload["search_language_filter"] = [requested.language]
        elif expected is not None and expected.control is not ModelLocationControl.NOT_CONTROLLED:
            raise ProviderPolicyViolation(
                "Perplexity adapter only proves country-level location control",
                provider=self.provider,
            )
        return payload

    def resolve_effective_location(
        self,
        request: ModelGatewayRequest,
        *,
        body: Mapping[str, object],
        parsed: ParsedProviderResponse,
    ) -> EffectiveModelLocation | None:
        del body
        expected = request.expected_effective_location
        if expected is None or expected.control is ModelLocationControl.NOT_CONTROLLED:
            return expected
        if (
            expected.control is ModelLocationControl.COUNTRY
            and parsed.provider_request_id is not None
        ):
            return expected
        return uncontrolled_model_location(
            provider=self.provider,
            adapter_release_hash=self.adapter_release_hash,
            reason="provider_response_lacks_location_acceptance_receipt",
        )

    def parse_response(
        self,
        body: Mapping[str, object],
        headers: Mapping[str, str],
        request: ModelGatewayRequest,
    ) -> ParsedProviderResponse:
        del headers
        choices = require_list(body.get("choices"), label="Perplexity response choices")
        if len(choices) != 1:
            raise StructuredOutputValidationError(
                "Perplexity response must contain exactly one choice",
                provider=self.provider,
            )
        choice = require_mapping(choices[0], label="Perplexity response choice")
        finish_reason = required_text(choice.get("finish_reason"), label="Perplexity finish reason")
        if finish_reason != "stop":
            raise StructuredOutputValidationError(
                f"Perplexity response is incomplete: {finish_reason}",
                provider=self.provider,
            )
        message = require_mapping(choice.get("message"), label="Perplexity response message")
        usage = require_mapping(body.get("usage"), label="Perplexity response usage")
        citations, search_events = _citation_lineage(body, provider=self.provider)
        if request.search_mode == "web" and not citations:
            raise StructuredOutputValidationError(
                "Perplexity web response lacks citation lineage", provider=self.provider
            )
        cost_value = usage.get("cost")
        cost = cost_value if isinstance(cost_value, Mapping) else {}
        return ParsedProviderResponse(
            output=parse_json_object_text(message.get("content"), provider=self.provider),
            provider_request_id=optional_text(body.get("id")),
            provider_reported_model=optional_text(body.get("model")),
            prompt_tokens=optional_int(usage.get("prompt_tokens")),
            completion_tokens=optional_int(usage.get("completion_tokens")),
            cost_usd=optional_decimal(cost.get("total_cost")),
            finish_reason=finish_reason,
            citations=citations,
            tool_events=search_events,
            usage_details=_usage_details(usage),
        )


def _citation_lineage(
    body: Mapping[str, object], *, provider: str
) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    result_by_url: dict[str, Mapping[str, object]] = {}
    events: list[Mapping[str, object]] = []
    for ordinal, raw_result in enumerate(
        require_list(body.get("search_results", []), label="Perplexity search results"),
        start=1,
    ):
        result = require_mapping(raw_result, label="Perplexity search result")
        url = required_text(result.get("url"), label="Perplexity search result URL")
        result_by_url[url] = result
        event: dict[str, object] = {
            "type": "search_result",
            "ordinal": ordinal,
            "url": url,
        }
        for name in ("title", "date", "last_updated", "source"):
            value = optional_text(result.get(name))
            if value is not None:
                event[name] = value
        events.append(event)
    citations: list[Mapping[str, object]] = []
    for ordinal, raw_url in enumerate(
        require_list(body.get("citations", []), label="Perplexity citations"), start=1
    ):
        url = required_text(raw_url, label="Perplexity citation URL")
        result = result_by_url.get(url, {})
        citations.append(
            normalized_citation(
                provider=provider,
                url=url,
                title=result.get("title"),
                ordinal=ordinal,
                citation_type="sonar_citation",
            )
        )
    return tuple(citations), tuple(events)


def _usage_details(usage: Mapping[str, object]) -> Mapping[str, object]:
    details: dict[str, object] = {}
    for name in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "citation_tokens",
        "num_search_queries",
        "reasoning_tokens",
    ):
        value = optional_int(usage.get(name))
        if value is not None:
            details[name] = value
    cost_value = usage.get("cost")
    if isinstance(cost_value, Mapping):
        cost_details: dict[str, object] = {}
        for name, value in cost_value.items():
            amount = optional_decimal(value)
            if amount is not None:
                cost_details[str(name)] = str(amount)
        if cost_details:
            details["cost"] = cost_details
    search_context_size = optional_text(usage.get("search_context_size"))
    if search_context_size is not None:
        details["search_context_size"] = search_context_size
    return details
