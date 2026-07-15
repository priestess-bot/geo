from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from geo_core.audit import hash_payload
from geo_core.security.secrets import redact_secret_text, redact_secrets


SUPPORTED_CONNECTOR_PROVIDERS = ("openai", "perplexity", "google_manual")
SUPPORTED_CONNECTOR_ACCESS_METHODS = ("official_api", "manual", "browser", "third_party_api")
CONNECTOR_FAILURE_CATEGORIES = (
    "auth",
    "rate_limited",
    "timeout",
    "provider_error",
    "parse_error",
    "not_configured",
    "recording_missing",
    "unknown",
)
CONNECTOR_RESPONSE_STATUSES = ("succeeded", "failed", "skipped")
SECRET_REF_PREFIXES = ("connector-secret:", "secret-manager:", "env:")


class ConnectorValidationError(ValueError):
    pass


def normalize_connector_provider(provider: str) -> str:
    normalized = provider.strip().lower().replace("-", "_").replace(".", "_")
    aliases = {
        "chatgpt": "openai",
        "openai_web_search": "openai",
        "openai_web_search_api": "openai",
        "perplexity_sonar": "perplexity",
        "perplexity_sonar_api": "perplexity",
        "google": "google_manual",
        "google_manual": "google_manual",
        "google_manual_backfill": "google_manual",
        "google_ai_mode_manual": "google_manual",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_CONNECTOR_PROVIDERS:
        raise ConnectorValidationError(f"unsupported connector provider: {provider}")
    return normalized


def _clean_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    cleaned = redact_secrets(dict(value))
    if not isinstance(cleaned, dict):
        return {}
    return cleaned


def _sanitize_text(value: str) -> str:
    redacted = redact_secret_text(value)
    return str(redacted)


def _looks_like_raw_secret_ref(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if stripped.startswith(SECRET_REF_PREFIXES):
        return False
    lower = stripped.lower()
    provider_prefixes = ("s" + "k-", "p" + "plx-", "ai" + "za")
    return lower.startswith(provider_prefixes) or "secret" in lower or "token" in lower


def _domain_from_url(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].lower()


@dataclass(frozen=True)
class ConnectorConfig:
    connector_backend_id: str
    provider: str
    model: str
    access_method: str
    market_code: str
    locale: str
    country_code: str
    timeout_seconds: float = 30.0
    max_retries: int = 2
    secret_ref: str | None = None
    rate_card: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", normalize_connector_provider(self.provider))
        if self.access_method not in SUPPORTED_CONNECTOR_ACCESS_METHODS:
            raise ConnectorValidationError(f"unsupported access method: {self.access_method}")
        required = {
            "connector_backend_id": self.connector_backend_id,
            "model": self.model,
            "market_code": self.market_code,
            "locale": self.locale,
            "country_code": self.country_code,
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if missing:
            raise ConnectorValidationError(f"missing connector config fields: {', '.join(missing)}")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 120:
            raise ConnectorValidationError("timeout_seconds must be > 0 and <= 120")
        if self.max_retries < 0 or self.max_retries > 5:
            raise ConnectorValidationError("max_retries must be between 0 and 5")
        if self.secret_ref and _looks_like_raw_secret_ref(self.secret_ref):
            raise ConnectorValidationError("secret_ref must be a reference, not a raw provider key")
        object.__setattr__(self, "metadata", _clean_mapping(self.metadata))
        object.__setattr__(self, "rate_card", dict(self.rate_card or {}))


@dataclass(frozen=True)
class ConnectorPrompt:
    prompt_id: str
    prompt_text: str
    city: str
    language: str
    device: str = "desktop"
    intent_type: str | None = None
    prompt_version: str | None = None
    sample_index: int = 1
    sample_size: int = 1

    def __post_init__(self) -> None:
        if not self.prompt_id.strip():
            raise ConnectorValidationError("prompt_id is required")
        if not self.prompt_text.strip():
            raise ConnectorValidationError("prompt_text is required")
        if self.sample_index < 1:
            raise ConnectorValidationError("sample_index must be >= 1")
        if self.sample_size < self.sample_index:
            raise ConnectorValidationError("sample_size must be >= sample_index")


@dataclass(frozen=True)
class ConnectorRequest:
    request_id: str
    project_id: str
    config: ConnectorConfig
    prompt: ConnectorPrompt
    trace_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ConnectorValidationError("request_id is required")
        if not self.project_id.strip():
            raise ConnectorValidationError("project_id is required")
        object.__setattr__(self, "metadata", _clean_mapping(self.metadata))


@dataclass(frozen=True)
class ConnectorCitation:
    url: str
    domain: str
    position: int
    title: str | None = None
    snippet: str | None = None
    source_type: str | None = None

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise ConnectorValidationError("citation url is required")
        if self.position < 1:
            raise ConnectorValidationError("citation position must be >= 1")
        if not self.domain.strip():
            object.__setattr__(self, "domain", _domain_from_url(self.url))


@dataclass(frozen=True)
class ConnectorCost:
    total_cost: float
    currency: str = "USD"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    vendor_cost: float = 0.0
    compute_cost: float = 0.0
    estimate_method: str = "recorded"

    def __post_init__(self) -> None:
        if self.total_cost < 0:
            raise ConnectorValidationError("total_cost must be >= 0")
        if not self.currency.strip():
            raise ConnectorValidationError("currency is required")


@dataclass(frozen=True)
class ConnectorFailure:
    category: str
    message: str
    retryable: bool
    provider_status_code: int | None = None
    provider_request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.category not in CONNECTOR_FAILURE_CATEGORIES:
            raise ConnectorValidationError(f"unsupported connector failure category: {self.category}")
        object.__setattr__(self, "message", _sanitize_text(self.message))
        object.__setattr__(self, "metadata", _clean_mapping(self.metadata))


@dataclass(frozen=True)
class ConnectorEvidence:
    raw_payload_hash: str
    snapshot_url: str | None = None
    screenshot_url: str | None = None
    asset_hashes: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.raw_payload_hash.strip():
            raise ConnectorValidationError("raw_payload_hash is required")
        object.__setattr__(self, "asset_hashes", dict(self.asset_hashes or {}))
        object.__setattr__(self, "metadata", _clean_mapping(self.metadata))


@dataclass(frozen=True)
class ConnectorResponse:
    request_id: str
    provider: str
    model: str
    status: str
    answer_text: str
    answer_present: bool
    surface_triggered: bool
    citations: tuple[ConnectorCitation, ...]
    cost: ConnectorCost
    evidence: ConnectorEvidence
    provider_request_id: str | None = None
    latency_ms: int | None = None
    failure: ConnectorFailure | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", normalize_connector_provider(self.provider))
        if self.status not in CONNECTOR_RESPONSE_STATUSES:
            raise ConnectorValidationError(f"unsupported connector response status: {self.status}")
        if self.status == "failed" and self.failure is None:
            raise ConnectorValidationError("failed connector response requires failure")
        object.__setattr__(self, "metadata", _clean_mapping(self.metadata))

    def to_public_dict(self) -> dict[str, Any]:
        return _clean_mapping(asdict(self))


@runtime_checkable
class ProductionConnectorBackend(Protocol):
    connector_backend_id: str

    def health(self, config: ConnectorConfig) -> str: ...

    def validate(self, config: ConnectorConfig) -> None: ...

    def collect(self, request: ConnectorRequest) -> ConnectorResponse: ...


class ConnectorRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, ProductionConnectorBackend] = {}

    def register(self, provider: str, backend: ProductionConnectorBackend) -> None:
        self._backends[normalize_connector_provider(provider)] = backend

    def backend_for(self, provider: str) -> ProductionConnectorBackend:
        normalized = normalize_connector_provider(provider)
        try:
            return self._backends[normalized]
        except KeyError as exc:
            raise ConnectorValidationError(f"connector backend is not registered: {normalized}") from exc

    def collect(self, request: ConnectorRequest) -> ConnectorResponse:
        return self.backend_for(request.config.provider).collect(request)


def _normalize_citation(item: Any, position: int) -> ConnectorCitation:
    if isinstance(item, str):
        url = item
        return ConnectorCitation(url=url, domain=_domain_from_url(url), position=position)
    if not isinstance(item, Mapping):
        raise ConnectorValidationError("recorded citation must be a URL string or object")
    url = str(item.get("url") or "").strip()
    if not url:
        raise ConnectorValidationError("recorded citation missing url")
    return ConnectorCitation(
        url=url,
        domain=str(item.get("domain") or _domain_from_url(url)),
        position=int(item.get("position") or position),
        title=str(item["title"]) if item.get("title") is not None else None,
        snippet=str(item["snippet"]) if item.get("snippet") is not None else None,
        source_type=str(item["source_type"]) if item.get("source_type") is not None else None,
    )


def _cost_from_record(record: Mapping[str, Any]) -> ConnectorCost:
    raw_cost = record.get("cost") or {}
    if not isinstance(raw_cost, Mapping):
        raw_cost = {}
    return ConnectorCost(
        total_cost=float(raw_cost.get("total_cost") or raw_cost.get("amount") or 0),
        currency=str(raw_cost.get("currency") or "USD"),
        prompt_tokens=int(raw_cost.get("prompt_tokens") or 0),
        completion_tokens=int(raw_cost.get("completion_tokens") or 0),
        vendor_cost=float(raw_cost.get("vendor_cost") or 0),
        compute_cost=float(raw_cost.get("compute_cost") or 0),
        estimate_method=str(raw_cost.get("estimate_method") or "recorded"),
    )


def _response_from_recording(
    *,
    request: ConnectorRequest,
    recording_key: str,
    record: Mapping[str, Any],
) -> ConnectorResponse:
    redacted_record = _clean_mapping(record)
    raw_payload = redacted_record.get("raw_payload") if isinstance(redacted_record.get("raw_payload"), dict) else redacted_record
    raw_payload_hash = hash_payload(raw_payload)
    failure_payload = redacted_record.get("failure")
    if failure_payload:
        if not isinstance(failure_payload, Mapping):
            failure_payload = {"message": str(failure_payload)}
        failure = ConnectorFailure(
            category=str(failure_payload.get("category") or "provider_error"),
            message=str(failure_payload.get("message") or "recorded connector failure"),
            retryable=bool(failure_payload.get("retryable", False)),
            provider_status_code=(
                int(failure_payload["provider_status_code"])
                if failure_payload.get("provider_status_code") is not None
                else None
            ),
            provider_request_id=(
                str(failure_payload["provider_request_id"])
                if failure_payload.get("provider_request_id") is not None
                else None
            ),
            metadata=_clean_mapping(failure_payload.get("metadata") if isinstance(failure_payload, Mapping) else {}),
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
            cost=_cost_from_record(redacted_record),
            evidence=ConnectorEvidence(
                raw_payload_hash=raw_payload_hash,
                metadata={
                    "provider": request.config.provider,
                    "connector_backend_id": request.config.connector_backend_id,
                    "recording_key": recording_key,
                    "failure_category": failure.category,
                },
            ),
            provider_request_id=failure.provider_request_id,
            failure=failure,
            latency_ms=int(redacted_record["latency_ms"]) if redacted_record.get("latency_ms") is not None else None,
            metadata={"recording_key": recording_key},
        )
    citations = tuple(
        _normalize_citation(item, index)
        for index, item in enumerate(redacted_record.get("citations") or (), start=1)
    )
    answer_text = str(redacted_record.get("answer_text") or "")
    evidence = ConnectorEvidence(
        raw_payload_hash=raw_payload_hash,
        snapshot_url=str(redacted_record["snapshot_url"]) if redacted_record.get("snapshot_url") else None,
        screenshot_url=str(redacted_record["screenshot_url"]) if redacted_record.get("screenshot_url") else None,
        asset_hashes={
            key: str(value)
            for key, value in (
                redacted_record.get("asset_hashes") if isinstance(redacted_record.get("asset_hashes"), Mapping) else {}
            ).items()
        },
        metadata={
            "provider": request.config.provider,
            "connector_backend_id": request.config.connector_backend_id,
            "model": request.config.model,
            "market_code": request.config.market_code,
            "locale": request.config.locale,
            "country_code": request.config.country_code,
            "prompt_id": request.prompt.prompt_id,
            "prompt_hash": hash_payload({"prompt_text": request.prompt.prompt_text}),
            "recording_key": recording_key,
            "citation_count": len(citations),
            "raw_payload_hash": raw_payload_hash,
        },
    )
    return ConnectorResponse(
        request_id=request.request_id,
        provider=request.config.provider,
        model=request.config.model,
        status=str(redacted_record.get("status") or "succeeded"),
        answer_text=answer_text,
        answer_present=bool(redacted_record.get("answer_present", bool(answer_text))),
        surface_triggered=bool(redacted_record.get("surface_triggered", bool(answer_text))),
        citations=citations,
        cost=_cost_from_record(redacted_record),
        evidence=evidence,
        provider_request_id=(
            str(redacted_record["provider_request_id"])
            if redacted_record.get("provider_request_id") is not None
            else None
        ),
        latency_ms=int(redacted_record["latency_ms"]) if redacted_record.get("latency_ms") is not None else None,
        metadata={"recording_key": recording_key},
    )


class RecordedConnectorHarness:
    connector_backend_id = "recorded.connector.harness"

    def __init__(self, recordings: Mapping[str, Mapping[str, Any]]) -> None:
        self._recordings = {str(key): dict(value) for key, value in recordings.items()}

    def health(self, config: ConnectorConfig) -> str:
        try:
            self._find_recording(config.provider, "*", "*")
        except ConnectorValidationError:
            return "recording_missing"
        return "ready"

    def validate(self, config: ConnectorConfig) -> None:
        normalize_connector_provider(config.provider)

    def _find_recording(self, provider: str, prompt_id: str, prompt_text: str) -> tuple[str, Mapping[str, Any]]:
        normalized = normalize_connector_provider(provider)
        candidates = (
            f"{normalized}:{prompt_id}",
            f"{normalized}:{prompt_text}",
            f"{normalized}:*",
            prompt_id,
            "*",
        )
        for key in candidates:
            if key in self._recordings:
                return key, self._recordings[key]
        raise ConnectorValidationError(f"recording missing for provider={normalized} prompt_id={prompt_id}")

    def collect(self, request: ConnectorRequest) -> ConnectorResponse:
        try:
            recording_key, record = self._find_recording(
                request.config.provider,
                request.prompt.prompt_id,
                request.prompt.prompt_text,
            )
        except ConnectorValidationError as exc:
            failure = ConnectorFailure(
                category="recording_missing",
                message=str(exc),
                retryable=False,
                metadata={"provider": request.config.provider, "prompt_id": request.prompt.prompt_id},
            )
            raw_payload_hash = hash_payload(
                {
                    "provider": request.config.provider,
                    "prompt_id": request.prompt.prompt_id,
                    "failure_category": failure.category,
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
                cost=ConnectorCost(total_cost=0, estimate_method="recording_missing"),
                evidence=ConnectorEvidence(
                    raw_payload_hash=raw_payload_hash,
                    metadata={
                        "provider": request.config.provider,
                        "connector_backend_id": request.config.connector_backend_id,
                        "prompt_id": request.prompt.prompt_id,
                        "failure_category": failure.category,
                    },
                ),
                failure=failure,
                metadata={"recording_key": None},
            )
        return _response_from_recording(request=request, recording_key=recording_key, record=record)
