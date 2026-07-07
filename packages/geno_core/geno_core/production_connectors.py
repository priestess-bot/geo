from __future__ import annotations

from time import perf_counter
from typing import Any

from geno_core.audit import hash_payload
from geno_core.collectors import (
    CollectorConfigurationError,
    CollectorProviderError,
    ManualBackfillCollector,
    OpenAIWebSearchCollector,
    PerplexitySonarCollector,
)
from geno_core.connector_contract import (
    ConnectorCitation,
    ConnectorConfig,
    ConnectorCost,
    ConnectorEvidence,
    ConnectorFailure,
    ConnectorRequest,
    ConnectorResponse,
    normalize_connector_provider,
)
from geno_core.models import MarketProfile


def _market_from_config(config: ConnectorConfig) -> MarketProfile:
    return MarketProfile(
        market=config.metadata.get("market_name", config.market_code)
        if isinstance(config.metadata.get("market_name"), str)
        else config.market_code,
        market_code=config.market_code,
        locale=config.locale,
        timezone=str(config.metadata.get("timezone") or "UTC"),
        currency=str(config.metadata.get("currency") or "USD"),
        primary_language=config.locale,
        cities=[str(config.metadata.get("city") or "Australia")],
        source_types=[],
        platforms=[],
    )


def _estimate_cost(*, config: ConnectorConfig, payload: dict[str, Any]) -> ConnectorCost:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    prompt_tokens = int(
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("total_prompt_tokens")
        or 0
    )
    completion_tokens = int(
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or usage.get("total_completion_tokens")
        or 0
    )
    provider_cost = usage.get("cost") or payload.get("cost")
    if isinstance(provider_cost, dict):
        provider_cost = provider_cost.get("total_cost") or provider_cost.get("amount")
    if provider_cost is not None:
        total_cost = float(provider_cost)
        method = "provider_reported"
    else:
        input_rate = float(config.rate_card.get("input_per_1k_tokens") or 0)
        output_rate = float(config.rate_card.get("output_per_1k_tokens") or 0)
        flat_rate = float(config.rate_card.get("flat_per_request") or 0)
        total_cost = round((prompt_tokens / 1000 * input_rate) + (completion_tokens / 1000 * output_rate) + flat_rate, 6)
        method = "estimated"
    return ConnectorCost(
        total_cost=max(total_cost, 0),
        currency=str(config.rate_card.get("currency") or "USD"),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        vendor_cost=max(total_cost, 0),
        compute_cost=0.0,
        estimate_method=method,
    )


def _citations_from_result(citations: list[dict[str, Any]]) -> tuple[ConnectorCitation, ...]:
    normalized: list[ConnectorCitation] = []
    for index, citation in enumerate(citations, start=1):
        url = str(citation.get("url") or "").strip()
        if not url:
            continue
        normalized.append(
            ConnectorCitation(
                url=url,
                domain=str(citation.get("domain") or ""),
                position=int(citation.get("position") or index),
                title=str(citation["title"]) if citation.get("title") is not None else None,
                snippet=str(citation["snippet"]) if citation.get("snippet") is not None else None,
                source_type=str(citation["source_type"]) if citation.get("source_type") is not None else None,
            )
        )
    return tuple(normalized)


def _provider_request_id(payload: dict[str, Any]) -> str | None:
    for key in ("id", "request_id", "provider_request_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _failure_category(exc: Exception) -> tuple[str, bool, int | None]:
    if isinstance(exc, CollectorConfigurationError):
        return "not_configured", False, None
    if isinstance(exc, CollectorProviderError):
        status = exc.status_code
        if status in {401, 403}:
            return "auth", False, status
        if status == 429:
            return "rate_limited", True, status
        if status and status >= 500:
            return "provider_error", True, status
        return "provider_error", False, status
    if isinstance(exc, (TimeoutError, TimeoutError)):
        return "timeout", True, None
    if isinstance(exc, ValueError):
        return "parse_error", False, None
    return "unknown", True, None


class CollectorConnectorBackend:
    connector_backend_id = "collector.connector.backend"
    provider = ""

    def __init__(self, *, collector: object | None = None) -> None:
        self._collector = collector

    def _collector_for(self, config: ConnectorConfig) -> object:
        if self._collector is None:
            raise ValueError(f"{self.__class__.__name__} has no collector configured")
        return self._collector

    def health(self, config: ConnectorConfig) -> str:
        self.validate(config)
        health = getattr(self._collector_for(config), "health")()
        return str(health)

    def validate(self, config: ConnectorConfig) -> None:
        if normalize_connector_provider(config.provider) != self.provider:
            raise ValueError(f"{self.__class__.__name__} cannot serve provider={config.provider}")

    def collect(self, request: ConnectorRequest) -> ConnectorResponse:
        self.validate(request.config)
        started = perf_counter()
        collector = self._collector_for(request.config)
        try:
            result = getattr(collector, "collect")(
                prompt=request.prompt.prompt_text,
                market=_market_from_config(request.config),
                city=request.prompt.city,
                language=request.prompt.language,
                device=request.prompt.device,
            )
        except Exception as exc:  # noqa: BLE001 - provider errors must be normalized for the contract.
            category, retryable, status_code = _failure_category(exc)
            raw_payload = getattr(exc, "payload", {}) if isinstance(exc, CollectorProviderError) else {}
            raw_payload_hash = hash_payload(
                {
                    "provider": request.config.provider,
                    "request_id": request.request_id,
                    "failure_category": category,
                    "provider_status_code": status_code,
                }
            )
            return ConnectorResponse(
                request_id=request.request_id,
                provider=request.config.provider,
                model=request.config.model,
                status="failed",
                answer_text="",
                answer_present=False,
                surface_triggered=False,
                citations=(),
                cost=ConnectorCost(total_cost=0, estimate_method="failure"),
                evidence=ConnectorEvidence(
                    raw_payload_hash=raw_payload_hash,
                    metadata={
                        "provider": request.config.provider,
                        "connector_backend_id": request.config.connector_backend_id,
                        "failure_category": category,
                    },
                ),
                provider_request_id=_provider_request_id(raw_payload) if isinstance(raw_payload, dict) else None,
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
                failure=ConnectorFailure(
                    category=category,
                    message=str(exc),
                    retryable=retryable,
                    provider_status_code=status_code,
                    provider_request_id=_provider_request_id(raw_payload) if isinstance(raw_payload, dict) else None,
                    metadata={"collector_backend_id": request.config.connector_backend_id},
                ),
                metadata={"collector_backend_id": request.config.connector_backend_id},
            )

        payload = result.raw_payload
        raw_payload_hash = hash_payload(payload)
        return ConnectorResponse(
            request_id=request.request_id,
            provider=request.config.provider,
            model=request.config.model,
            status="succeeded",
            answer_text=result.answer_text,
            answer_present=result.answer_present,
            surface_triggered=result.surface_triggered,
            citations=_citations_from_result(result.citations),
            cost=_estimate_cost(config=request.config, payload=payload),
            evidence=ConnectorEvidence(
                raw_payload_hash=raw_payload_hash,
                snapshot_url=result.html_snapshot_url,
                screenshot_url=result.screenshot_url,
                asset_hashes=result.evidence_asset_hashes or {},
                metadata={
                    "provider": request.config.provider,
                    "connector_backend_id": request.config.connector_backend_id,
                    "model": request.config.model,
                    "collector_version": result.collector_version,
                    "raw_payload_hash": raw_payload_hash,
                    "citation_count": len(result.citations),
                    "asset_count": len(result.evidence_asset_hashes or {}),
                },
            ),
            provider_request_id=_provider_request_id(payload),
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            metadata={
                "collector_backend_id": request.config.connector_backend_id,
                "collector_version": result.collector_version,
                "account_state": result.account_state,
            },
        )


class OpenAIWebSearchConnectorBackend(CollectorConnectorBackend):
    connector_backend_id = "openai.web_search.connector"
    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        http_client: object | None = None,
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self._http_client = http_client

    def _collector_for(self, config: ConnectorConfig) -> OpenAIWebSearchCollector:
        return OpenAIWebSearchCollector(
            api_key=self._api_key,
            model=config.model,
            http_client=self._http_client,
            timeout_seconds=config.timeout_seconds,
        )


class PerplexitySonarConnectorBackend(CollectorConnectorBackend):
    connector_backend_id = "perplexity.sonar.connector"
    provider = "perplexity"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        http_client: object | None = None,
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self._http_client = http_client

    def _collector_for(self, config: ConnectorConfig) -> PerplexitySonarCollector:
        return PerplexitySonarCollector(
            api_key=self._api_key,
            model=config.model,
            http_client=self._http_client,
            timeout_seconds=config.timeout_seconds,
        )


class GoogleManualBackfillConnectorBackend(CollectorConnectorBackend):
    connector_backend_id = "google.manual_backfill.connector"
    provider = "google_manual"

    def __init__(
        self,
        *,
        backfill_path: str | None = None,
        vendor_cost: float | None = None,
    ) -> None:
        super().__init__()
        self._backfill_path = backfill_path
        self._vendor_cost = vendor_cost

    def _collector_for(self, config: ConnectorConfig) -> ManualBackfillCollector:
        return ManualBackfillCollector(
            backfill_path=self._backfill_path or (
                str(config.metadata["manual_backfill_path"])
                if config.metadata.get("manual_backfill_path") is not None
                else None
            ),
            vendor_cost=self._vendor_cost,
        )
