"""Fixture-ready external Provider and Grounded API adapters."""

from geo_core.model_gateway.provider_adapters.artifacts import (
    IndependentProviderArtifactEncryptor,
    MinioProviderArtifactSink,
    ProviderArtifactBundle,
    ProviderArtifactError,
    ProviderArtifactKeyVault,
    ProviderArtifactRecord,
    ProviderArtifactSink,
    StrictProviderArtifactGovernance,
)
from geo_core.model_gateway.provider_adapters.base import (
    CredentialResolver,
    JsonResponse,
    JsonTransport,
    ProviderAdapterRuntime,
)
from geo_core.model_gateway.provider_adapters.deepseek import DeepSeekChatCompletionsAdapter
from geo_core.model_gateway.provider_adapters.credentials import (
    SecretStoreCredentialResolver,
    build_secret_store_credential_resolver,
)
from geo_core.model_gateway.provider_adapters.composition import (
    ExactProviderAdapterConfig,
    ExactProviderComposition,
    build_exact_provider_composition,
    verify_six_provider_completeness,
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

__all__ = [
    "CredentialResolver",
    "DeepSeekChatCompletionsAdapter",
    "ExactProviderAdapterConfig",
    "ExactProviderComposition",
    "GeminiGenerateContentAdapter",
    "IndependentProviderArtifactEncryptor",
    "JsonResponse",
    "JsonTransport",
    "KimiChatCompletionsAdapter",
    "MicrosoftAgentReference",
    "MicrosoftBingGroundingAdapter",
    "MinioProviderArtifactSink",
    "OpenAIResponsesAdapter",
    "PerplexitySonarAdapter",
    "ProviderArtifactBundle",
    "ProviderArtifactError",
    "ProviderArtifactKeyVault",
    "ProviderArtifactRecord",
    "ProviderArtifactSink",
    "ProviderAdapterRuntime",
    "SecureHttpxJsonTransport",
    "SecretStoreCredentialResolver",
    "StrictProviderArtifactGovernance",
    "build_exact_provider_composition",
    "build_secret_store_credential_resolver",
    "verify_six_provider_completeness",
]
