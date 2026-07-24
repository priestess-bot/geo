"""Microsoft Foundry Grounding with Bing proxy-grounded adapter abstraction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from urllib.parse import parse_qs, urlparse
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


MICROSOFT_BING_GROUNDING_DOC = (
    "https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools"
)
MICROSOFT_BING_DISPLAY_REQUIREMENTS = (
    "https://www.microsoft.com/en-us/bing/apis/grounding-legal-enterprise"
)
MICROSOFT_FOUNDRY_RESPONSES_API_DOC = (
    "https://learn.microsoft.com/rest/api/aifoundry/project/responses"
)
MICROSOFT_FOUNDRY_HOST_SUFFIX = ".services.ai.azure.com"


@dataclass(frozen=True)
class MicrosoftAgentReference:
    name: str
    version: str
    market: str | None = None
    language: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ProviderPolicyViolation("Microsoft agent name and version must be frozen")
        if (self.market is None) != (self.language is None):
            raise ProviderPolicyViolation(
                "Microsoft agent market and language must be frozen together"
            )
        if self.market is not None and (
            not self.market.strip() or not self.language or not self.language.strip()
        ):
            raise ProviderPolicyViolation("Microsoft agent market configuration is invalid")


class MicrosoftBingGroundingAdapter(ProviderJsonAdapter):
    """A Foundry Responses adapter, never a Bing Copilot consumer-UI adapter."""

    provider = "microsoft"
    expected_capture_method = ModelCaptureMethod.PROXY_GROUNDED_API
    documentation_references = (
        MICROSOFT_BING_GROUNDING_DOC,
        MICROSOFT_BING_DISPLAY_REQUIREMENTS,
        MICROSOFT_FOUNDRY_RESPONSES_API_DOC,
    )

    def __init__(
        self,
        *,
        runtime: ProviderAdapterRuntime,
        secret_reference_id: UUID,
        credential_resolver: CredentialResolver,
        transport: JsonTransport,
        endpoint: str,
        agent_reference: MicrosoftAgentReference,
        artifact_sink: ProviderArtifactSink | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        validate_microsoft_foundry_endpoint(endpoint)
        self.agent_reference = agent_reference
        super().__init__(
            runtime=runtime,
            secret_reference_id=secret_reference_id,
            credential_resolver=credential_resolver,
            transport=transport,
            endpoint=endpoint,
            artifact_sink=artifact_sink,
            timeout_seconds=timeout_seconds,
        )

    def build_payload(self, request: ModelGatewayRequest) -> Mapping[str, object]:
        if request.search_mode != "bing_grounding":
            raise ProviderPolicyViolation(
                "Microsoft Grounding adapter requires bing_grounding search mode",
                provider=self.provider,
            )
        assert request.output_schema is not None
        reference: dict[str, object] = {
            "type": "agent_reference",
            "name": self.agent_reference.name,
            "version": self.agent_reference.version,
        }
        expected = request.expected_effective_location
        requested = request.requested_location
        if expected is not None and expected.control is ModelLocationControl.MARKET_LANGUAGE:
            if (
                requested is None
                or expected.locale != requested.locale
                or expected.language != requested.language
                or self.agent_reference.market != expected.locale
                or self.agent_reference.language != expected.language
            ):
                raise ProviderPolicyViolation(
                    "Microsoft market control differs from the frozen Agent configuration",
                    provider=self.provider,
                )
        elif expected is not None and expected.control is not ModelLocationControl.NOT_CONTROLLED:
            raise ProviderPolicyViolation(
                "Microsoft adapter only proves market-language location control",
                provider=self.provider,
            )
        return {
            "input": [dict(message) for message in request.messages],
            "agent_reference": reference,
            "tool_choice": "required",
            "store": False,
            "max_output_tokens": request.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "geo_structured_output",
                    "strict": True,
                    "schema": dict(request.output_schema),
                }
            },
        }

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
        if expected.control is ModelLocationControl.MARKET_LANGUAGE and any(
            _url_proves_market(url, market=expected.locale, language=expected.language)
            for url in _location_receipt_urls(parsed)
        ):
            return expected
        return uncontrolled_model_location(
            provider=self.provider,
            adapter_release_hash=self.adapter_release_hash,
            reason="bing_query_reference_did_not_prove_market",
        )

    def parse_response(
        self,
        body: Mapping[str, object],
        headers: Mapping[str, str],
        request: ModelGatewayRequest,
    ) -> ParsedProviderResponse:
        del headers, request
        status = required_text(body.get("status"), label="Microsoft response status")
        if status != "completed":
            raise StructuredOutputValidationError(
                f"Microsoft grounded response is incomplete: {status}",
                provider=self.provider,
            )
        texts: list[str] = []
        citations: list[Mapping[str, object]] = []
        events: list[Mapping[str, object]] = []
        for raw_item in require_list(body.get("output"), label="Microsoft response output"):
            item = require_mapping(raw_item, label="Microsoft response output item")
            item_type = required_text(item.get("type"), label="Microsoft output item type")
            if item_type == "message":
                _parse_message(item, texts=texts, citations=citations, provider=self.provider)
            else:
                event, query_citations = _grounding_event(item, provider=self.provider)
                events.append(event)
                citations.extend(query_citations)
        if len(texts) != 1:
            raise StructuredOutputValidationError(
                "Microsoft grounded response must contain one structured output text",
                provider=self.provider,
            )
        citation_types = {str(item.get("citation_type")) for item in citations}
        if not {"url_citation", "bing_search_query"} <= citation_types:
            raise StructuredOutputValidationError(
                "Microsoft grounded response must retain website and Bing query references",
                provider=self.provider,
            )
        usage = require_mapping(body.get("usage"), label="Microsoft response usage")
        return ParsedProviderResponse(
            output=parse_json_object_text(texts[0], provider=self.provider),
            provider_request_id=optional_text(body.get("id")),
            provider_reported_model=optional_text(body.get("model")),
            prompt_tokens=optional_int(usage.get("input_tokens")),
            completion_tokens=optional_int(usage.get("output_tokens")),
            cost_usd=None,
            finish_reason=status,
            citations=tuple(citations),
            tool_events=tuple(events),
            usage_details=_usage_details(usage),
        )


def _parse_message(
    item: Mapping[str, object],
    *,
    texts: list[str],
    citations: list[Mapping[str, object]],
    provider: str,
) -> None:
    for raw_part in require_list(item.get("content"), label="Microsoft message content"):
        part = require_mapping(raw_part, label="Microsoft message content part")
        part_type = required_text(part.get("type"), label="Microsoft content part type")
        if part_type == "refusal":
            raise ModelGatewayError(
                "Microsoft grounded model refused the request",
                code=ModelGatewayErrorCode.CONTENT_REFUSAL,
                provider=provider,
            )
        if part_type != "output_text":
            continue
        texts.append(required_text(part.get("text"), label="Microsoft output text"))
        for raw_annotation in require_list(
            part.get("annotations", []), label="Microsoft output annotations"
        ):
            annotation = require_mapping(raw_annotation, label="Microsoft output annotation")
            if annotation.get("type") != "url_citation":
                continue
            url = required_text(annotation.get("url"), label="Microsoft citation URL")
            citations.append(
                normalized_citation(
                    provider=provider,
                    url=url,
                    title=annotation.get("title"),
                    ordinal=len(citations) + 1,
                    citation_type=(
                        "bing_search_query" if _is_bing_query_url(url) else "url_citation"
                    ),
                    start_index=annotation.get("start_index"),
                    end_index=annotation.get("end_index"),
                )
            )


def _grounding_event(
    item: Mapping[str, object], *, provider: str
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...]]:
    event: dict[str, object] = {
        "type": required_text(item.get("type"), label="Microsoft grounding event type"),
        "provider_event_id": optional_text(item.get("id")) or "",
        "status": optional_text(item.get("status")) or "unknown",
    }
    arguments = _arguments_value(item.get("arguments"))
    urls = tuple(dict.fromkeys(_find_urls(arguments)))
    if urls:
        event["referenced_urls"] = urls
    citations = tuple(
        normalized_citation(
            provider=provider,
            url=url,
            ordinal=index,
            citation_type="bing_search_query",
        )
        for index, url in enumerate(urls, start=1)
        if _is_bing_query_url(url)
    )
    return event, citations


def _arguments_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise StructuredOutputValidationError(
            "Microsoft grounding arguments are not valid JSON"
        ) from exc


def _find_urls(value: object) -> list[str]:
    if isinstance(value, str):
        parsed = urlparse(value)
        return [value] if parsed.scheme in {"http", "https"} and parsed.netloc else []
    if isinstance(value, Mapping):
        urls: list[str] = []
        for nested in value.values():
            urls.extend(_find_urls(nested))
        return urls
    if isinstance(value, list):
        urls = []
        for nested in value:
            urls.extend(_find_urls(nested))
        return urls
    return []


def _location_receipt_urls(parsed: ParsedProviderResponse) -> tuple[str, ...]:
    urls: list[str] = []
    for event in parsed.tool_events:
        urls.extend(_find_urls(event.get("referenced_urls", [])))
    for citation in parsed.citations:
        urls.extend(_find_urls(citation.get("url")))
    return tuple(dict.fromkeys(urls))


def _is_bing_query_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.hostname in {"bing.com", "www.bing.com"} and parsed.path.rstrip("/") == "/search"


def _url_proves_market(
    value: str,
    *,
    market: str | None,
    language: str | None,
) -> bool:
    if market is None or language is None or not _is_bing_query_url(value):
        return False
    query = parse_qs(urlparse(value).query)
    observed_market_values = query.get("mkt") or query.get("market")
    observed_language_values = query.get("setlang") or query.get("set_lang")
    observed_market = observed_market_values[0] if observed_market_values else None
    observed_language = observed_language_values[0] if observed_language_values else None
    return (
        isinstance(observed_market, str)
        and observed_market.casefold() == market.casefold()
        and isinstance(observed_language, str)
        and observed_language.casefold() == language.casefold()
    )


def _usage_details(usage: Mapping[str, object]) -> Mapping[str, object]:
    details: dict[str, object] = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        value = optional_int(usage.get(name))
        if value is not None:
            details[name] = value
    return details


def validate_microsoft_foundry_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    hostname = parsed.hostname
    if (
        hostname is None
        or not hostname.endswith(MICROSOFT_FOUNDRY_HOST_SUFFIX)
        or hostname == MICROSOFT_FOUNDRY_HOST_SUFFIX.lstrip(".")
        or parsed.port not in (None, 443)
    ):
        raise ProviderPolicyViolation(
            "Microsoft endpoint must use an approved Azure AI Foundry project host"
        )
