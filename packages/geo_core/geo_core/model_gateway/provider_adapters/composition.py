"""Production composition for six explicit Secret Store-backed provider adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from geo_core.model_gateway.contracts import ModelRouteError
from geo_core.model_gateway.provider_adapters.base import (
    CredentialResolver,
    JsonTransport,
    ProviderAdapterRuntime,
)
from geo_core.model_gateway.provider_adapters.artifacts import ProviderArtifactSink
from geo_core.model_gateway.provider_adapters.deepseek import (
    DeepSeekChatCompletionsAdapter,
)
from geo_core.model_gateway.provider_adapters.gemini import GeminiGenerateContentAdapter
from geo_core.model_gateway.provider_adapters.http_transport import SecureHttpxJsonTransport
from geo_core.model_gateway.provider_adapters.kimi import KimiChatCompletionsAdapter
from geo_core.model_gateway.provider_adapters.microsoft import (
    MicrosoftAgentReference,
    MicrosoftBingGroundingAdapter,
)
from geo_core.model_gateway.provider_adapters.openai import OpenAIResponsesAdapter
from geo_core.model_gateway.provider_adapters.perplexity import PerplexitySonarAdapter
from geo_core.model_gateway.releases import (
    KNOWN_MODEL_PROVIDERS,
    ModelRelease,
    ModelReleaseRegistry,
    ReleaseState,
)
from geo_core.model_gateway.router import ModelGatewayRouter, ProviderAdapter


TransportFactory = Callable[[str, str], JsonTransport]


@dataclass(frozen=True, repr=False)
class ExactProviderAdapterConfig:
    runtime: ProviderAdapterRuntime
    secret_reference_id: UUID
    timeout_seconds: float = 60.0
    microsoft_endpoint: str | None = None
    microsoft_agent_reference: MicrosoftAgentReference | None = None

    def __post_init__(self) -> None:
        if self.secret_reference_id.int == 0:
            raise ModelRouteError("provider Secret Reference ID cannot be zero")
        if self.timeout_seconds <= 0:
            raise ModelRouteError("provider timeout must be positive")
        microsoft = self.runtime.adapter_release.provider == "microsoft"
        has_microsoft_fields = (
            self.microsoft_endpoint is not None
            and self.microsoft_agent_reference is not None
        )
        if microsoft != has_microsoft_fields:
            raise ModelRouteError(
                "Microsoft exact adapter requires endpoint and Agent Reference together"
            )
        if not microsoft and (
            self.microsoft_endpoint is not None
            or self.microsoft_agent_reference is not None
        ):
            raise ModelRouteError("Microsoft fields cannot be attached to another provider")

    def __repr__(self) -> str:
        release = self.runtime.adapter_release
        return (
            "ExactProviderAdapterConfig("
            f"provider={release.provider!r}, adapter_release_id={release.adapter_release_id!r})"
        )


@dataclass(frozen=True, repr=False)
class ExactProviderComposition:
    router: ModelGatewayRouter
    adapters: Mapping[tuple[str, str], ProviderAdapter]

    def __repr__(self) -> str:
        identities = tuple(sorted(self.adapters))
        return f"ExactProviderComposition(adapters={identities!r})"


def build_exact_provider_composition(
    *,
    configs: tuple[ExactProviderAdapterConfig, ...],
    model_releases: tuple[ModelRelease, ...],
    credential_resolver: CredentialResolver,
    artifact_sink: ProviderArtifactSink,
    transport_factory: TransportFactory | None = None,
) -> ExactProviderComposition:
    """Build an explicit non-empty provider subset without credential fallback."""
    if not configs:
        raise ModelRouteError("provider composition cannot be empty")
    by_provider = {config.runtime.adapter_release.provider: config for config in configs}
    if len(by_provider) != len(configs):
        raise ModelRouteError("provider composition contains duplicate providers")
    extra = sorted(set(by_provider) - set(KNOWN_MODEL_PROVIDERS))
    if extra:
        raise ModelRouteError(f"provider composition contains unknown providers: {extra}")
    adapter_releases = tuple(config.runtime.adapter_release for config in configs)
    _validate_model_coverage(configs, model_releases)
    registry = ModelReleaseRegistry(
        adapter_releases=adapter_releases,
        model_releases=model_releases,
    )
    factory = transport_factory or _secure_transport
    adapters: dict[tuple[str, str], ProviderAdapter] = {}
    for provider in tuple(item for item in KNOWN_MODEL_PROVIDERS if item in by_provider):
        config = by_provider[provider]
        release = config.runtime.adapter_release
        transport = factory(provider, release.adapter_release_id)
        adapter = _adapter(
            config,
            credential_resolver=credential_resolver,
            transport=transport,
            artifact_sink=artifact_sink,
        )
        adapters[(provider, release.adapter_release_id)] = adapter
    router = ModelGatewayRouter(
        release_registry=registry,
        adapters=tuple(adapters.values()),
    )
    return ExactProviderComposition(router, MappingProxyType(adapters))


def _adapter(
    config: ExactProviderAdapterConfig,
    *,
    credential_resolver: CredentialResolver,
    transport: JsonTransport,
    artifact_sink: ProviderArtifactSink,
) -> ProviderAdapter:
    provider = config.runtime.adapter_release.provider
    if provider == "deepseek":
        return DeepSeekChatCompletionsAdapter(
            runtime=config.runtime,
            secret_reference_id=config.secret_reference_id,
            credential_resolver=credential_resolver,
            transport=transport,
            artifact_sink=artifact_sink,
            timeout_seconds=config.timeout_seconds,
        )
    if provider == "openai":
        return OpenAIResponsesAdapter(
            runtime=config.runtime,
            secret_reference_id=config.secret_reference_id,
            credential_resolver=credential_resolver,
            transport=transport,
            artifact_sink=artifact_sink,
            timeout_seconds=config.timeout_seconds,
        )
    if provider == "kimi":
        return KimiChatCompletionsAdapter(
            runtime=config.runtime,
            secret_reference_id=config.secret_reference_id,
            credential_resolver=credential_resolver,
            transport=transport,
            artifact_sink=artifact_sink,
            timeout_seconds=config.timeout_seconds,
        )
    if provider == "gemini":
        return GeminiGenerateContentAdapter(
            runtime=config.runtime,
            secret_reference_id=config.secret_reference_id,
            credential_resolver=credential_resolver,
            transport=transport,
            artifact_sink=artifact_sink,
            timeout_seconds=config.timeout_seconds,
        )
    if provider == "perplexity":
        return PerplexitySonarAdapter(
            runtime=config.runtime,
            secret_reference_id=config.secret_reference_id,
            credential_resolver=credential_resolver,
            transport=transport,
            artifact_sink=artifact_sink,
            timeout_seconds=config.timeout_seconds,
        )
    if provider == "microsoft":
        assert config.microsoft_endpoint is not None
        assert config.microsoft_agent_reference is not None
        return MicrosoftBingGroundingAdapter(
            runtime=config.runtime,
            secret_reference_id=config.secret_reference_id,
            credential_resolver=credential_resolver,
            transport=transport,
            endpoint=config.microsoft_endpoint,
            agent_reference=config.microsoft_agent_reference,
            artifact_sink=artifact_sink,
            timeout_seconds=config.timeout_seconds,
        )
    raise ModelRouteError(f"unsupported exact provider adapter: {provider}")


def _secure_transport(provider: str, adapter_release_id: str) -> JsonTransport:
    del provider, adapter_release_id
    return SecureHttpxJsonTransport()


def verify_six_provider_completeness(composition: ExactProviderComposition) -> None:
    """Fail an M3 release Gate unless every planned provider is bound exactly once."""
    configured = {provider for provider, _ in composition.adapters}
    missing = sorted(set(KNOWN_MODEL_PROVIDERS) - configured)
    extra = sorted(configured - set(KNOWN_MODEL_PROVIDERS))
    if missing or extra:
        raise ModelRouteError(
            f"six-provider Gate is incomplete; missing={missing}, extra={extra}"
        )


def _validate_model_coverage(
    configs: tuple[ExactProviderAdapterConfig, ...],
    model_releases: tuple[ModelRelease, ...],
) -> None:
    if any(release.state is not ReleaseState.APPROVED for release in model_releases):
        raise ModelRouteError("production provider composition requires approved Model Releases")
    models_by_adapter: dict[tuple[str, str], set[str]] = {}
    for release in model_releases:
        key = (release.provider, release.adapter_release_id)
        models_by_adapter.setdefault(key, set()).add(release.configured_model)
    for config in configs:
        adapter = config.runtime.adapter_release
        key = (adapter.provider, adapter.adapter_release_id)
        if models_by_adapter.get(key) != set(config.runtime.allowed_models):
            raise ModelRouteError(
                f"provider runtime/model release coverage differs for {adapter.provider}"
            )


__all__ = [
    "ExactProviderAdapterConfig",
    "ExactProviderComposition",
    "TransportFactory",
    "build_exact_provider_composition",
    "verify_six_provider_completeness",
]
