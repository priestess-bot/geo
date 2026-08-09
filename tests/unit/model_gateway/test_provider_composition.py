from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from geo_core.model_gateway import (
    ExactProviderAdapterConfig,
    ModelCaptureMethod,
    ModelRelease,
    ModelRoute,
    ModelRouteError,
    ReleaseState,
    SecureHttpxJsonTransport,
    build_exact_provider_composition,
    verify_six_provider_completeness,
)
from geo_core.model_gateway.provider_adapters import (
    DeepSeekChatCompletionsAdapter,
    GeminiGenerateContentAdapter,
    KimiChatCompletionsAdapter,
    MicrosoftAgentReference,
    MicrosoftBingGroundingAdapter,
    OpenAIResponsesAdapter,
    PerplexitySonarAdapter,
    SerpApiGoogleSearchAdapter,
)
from .provider_adapter_test_support import (
    RecordingJsonTransport,
    RecordingProviderArtifactSink,
    StaticCredentialResolver,
    json_response,
    runtime,
)


class _GetCapableTransport(RecordingJsonTransport):
    def get(self, *, url, headers, params, timeout_seconds):
        del url, headers, params, timeout_seconds
        return json_response({})


MODELS = {
    "deepseek": "deepseek-fixture",
    "openai": "gpt-fixture",
    "kimi": "kimi-fixture",
    "gemini": "gemini-3-fixture",
    "perplexity": "sonar-fixture",
    "microsoft": "foundry-fixture",
}


def _config(provider: str) -> ExactProviderAdapterConfig:
    capture = (
        ModelCaptureMethod.PROXY_GROUNDED_API
        if provider == "microsoft"
        else ModelCaptureMethod.PROVIDER_API
    )
    search_mode = {
        "deepseek": "disabled",
        "openai": "web",
        "kimi": "disabled",
        "gemini": "google_search",
        "perplexity": "web",
        "microsoft": "bing_grounding",
    }[provider]
    provider_runtime = runtime(
        provider,
        model=MODELS[provider],
        capture_method=capture,
        search_modes=frozenset({search_mode}),
        supports_search=search_mode != "disabled",
        supports_structured_output_with_tools=provider == "gemini",
    )
    if provider == "microsoft":
        return ExactProviderAdapterConfig(
            runtime=provider_runtime,
            secret_reference_id=uuid4(),
            microsoft_endpoint=(
                "https://fixture.services.ai.azure.com/api/projects/geo/openai/v1/responses"
            ),
            microsoft_agent_reference=MicrosoftAgentReference(
                name="geo-grounding", version="1"
            ),
        )
    return ExactProviderAdapterConfig(
        runtime=provider_runtime,
        secret_reference_id=uuid4(),
    )


def _model(config: ExactProviderAdapterConfig) -> ModelRelease:
    adapter = config.runtime.adapter_release
    release_id = f"{adapter.provider}-model-fixture-v1"
    return ModelRelease(
        provider=adapter.provider,
        adapter_release_id=adapter.adapter_release_id,
        model_release_id=release_id,
        release_hash=hashlib.sha256(release_id.encode()).hexdigest(),
        configured_model=MODELS[adapter.provider],
        state=ReleaseState.APPROVED,
    )


def _route(config: ExactProviderAdapterConfig, model: ModelRelease) -> ModelRoute:
    adapter = config.runtime.adapter_release
    return ModelRoute(
        provider=adapter.provider,
        adapter_release_id=adapter.adapter_release_id,
        adapter_release_hash=adapter.release_hash,
        model_release_id=model.model_release_id,
        model_release_hash=model.release_hash,
    )


def test_partial_composition_starts_and_unconfigured_provider_has_no_fallback() -> None:
    config = _config("openai")
    model = _model(config)
    transports: list[tuple[str, str]] = []

    def factory(provider: str, release_id: str) -> RecordingJsonTransport:
        transports.append((provider, release_id))
        return RecordingJsonTransport(json_response({}))

    composition = build_exact_provider_composition(
        configs=(config,),
        model_releases=(model,),
        credential_resolver=StaticCredentialResolver(),
        artifact_sink=RecordingProviderArtifactSink(),
        transport_factory=factory,
    )

    assert tuple(composition.adapters) == (
        ("openai", config.runtime.adapter_release.adapter_release_id),
    )
    assert isinstance(next(iter(composition.adapters.values())), OpenAIResponsesAdapter)
    assert composition.router.bind(_route(config, model)).provider == "openai"
    assert transports == [("openai", config.runtime.adapter_release.adapter_release_id)]
    with pytest.raises(ModelRouteError, match="six-provider Gate is incomplete"):
        verify_six_provider_completeness(composition)
    unknown_route = ModelRoute(
        provider="kimi",
        adapter_release_id="kimi-missing",
        adapter_release_hash="a" * 64,
        model_release_id="kimi-model-missing",
        model_release_hash="b" * 64,
    )
    with pytest.raises(ModelRouteError, match="not registered"):
        composition.router.bind(unknown_route)


def test_full_composition_binds_six_exact_adapter_types_and_passes_gate() -> None:
    configs = tuple(_config(provider) for provider in MODELS)
    models = tuple(_model(config) for config in configs)
    composition = build_exact_provider_composition(
        configs=configs,
        model_releases=models,
        credential_resolver=StaticCredentialResolver(),
        artifact_sink=RecordingProviderArtifactSink(),
        transport_factory=lambda _provider, _release: RecordingJsonTransport(json_response({})),
    )

    verify_six_provider_completeness(composition)
    assert {type(adapter) for adapter in composition.adapters.values()} == {
        DeepSeekChatCompletionsAdapter,
        OpenAIResponsesAdapter,
        KimiChatCompletionsAdapter,
        GeminiGenerateContentAdapter,
        PerplexitySonarAdapter,
        MicrosoftBingGroundingAdapter,
    }
    assert all(not hasattr(adapter, "api_key_file") for adapter in composition.adapters.values())
    assert all(
        composition.router.bind(_route(config, model)).provider
        == config.runtime.adapter_release.provider
        for config, model in zip(configs, models, strict=True)
    )


def test_optional_serpapi_search_adapter_does_not_change_six_provider_gate() -> None:
    serp_runtime = runtime(
        "serpapi",
        model="google-ai-overview-fixture",
        search_modes=frozenset({"google_search"}),
        supports_search=True,
        purpose="geo_measurement",
    )
    serp_config = ExactProviderAdapterConfig(
        runtime=serp_runtime,
        secret_reference_id=uuid4(),
    )
    serp_model = ModelRelease(
        provider="serpapi",
        adapter_release_id=serp_config.runtime.adapter_release.adapter_release_id,
        model_release_id="serpapi-model-fixture-v1",
        release_hash=hashlib.sha256(b"serpapi-model-fixture-v1").hexdigest(),
        configured_model="google-ai-overview-fixture",
        state=ReleaseState.APPROVED,
    )
    configs = tuple(_config(provider) for provider in MODELS) + (serp_config,)
    models = tuple(_model(config) for config in configs[:-1]) + (serp_model,)
    composition = build_exact_provider_composition(
        configs=configs,
        model_releases=models,
        credential_resolver=StaticCredentialResolver(),
        artifact_sink=RecordingProviderArtifactSink(),
        transport_factory=lambda provider, _release: (
            _GetCapableTransport(json_response({}))
            if provider == "serpapi"
            else RecordingJsonTransport(json_response({}))
        ),
    )

    verify_six_provider_completeness(composition)
    assert isinstance(
        composition.adapters[("serpapi", serp_config.runtime.adapter_release.adapter_release_id)],
        SerpApiGoogleSearchAdapter,
    )


def test_default_composition_uses_secure_transport_and_redacts_config_references() -> None:
    config = _config("openai")
    composition = build_exact_provider_composition(
        configs=(config,),
        model_releases=(_model(config),),
        credential_resolver=StaticCredentialResolver("must-not-appear"),
        artifact_sink=RecordingProviderArtifactSink(),
    )

    adapter = next(iter(composition.adapters.values()))
    assert isinstance(adapter.transport, SecureHttpxJsonTransport)
    rendered = repr((config, composition, adapter.credential_resolver))
    assert str(config.secret_reference_id) not in rendered
    assert "must-not-appear" not in rendered


def test_composition_rejects_empty_or_incomplete_runtime_model_coverage() -> None:
    resolver = StaticCredentialResolver()
    with pytest.raises(ModelRouteError, match="cannot be empty"):
        build_exact_provider_composition(
            configs=(),
            model_releases=(),
            credential_resolver=resolver,
            artifact_sink=RecordingProviderArtifactSink(),
        )

    config = _config("openai")
    with pytest.raises(ModelRouteError, match="coverage differs"):
        build_exact_provider_composition(
            configs=(config,),
            model_releases=(),
            credential_resolver=resolver,
            artifact_sink=RecordingProviderArtifactSink(),
        )
