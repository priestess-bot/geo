from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import pytest

from geo_core.model_gateway import (
    ModelCaptureMethod,
    ModelGatewayRouter,
    ModelRelease,
    ModelReleaseRegistry,
    ReleaseState,
)
from geo_core.model_gateway.provider_adapters import (
    GeminiGenerateContentAdapter,
    KimiChatCompletionsAdapter,
    MicrosoftAgentReference,
    MicrosoftBingGroundingAdapter,
    OpenAIResponsesAdapter,
    PerplexitySonarAdapter,
)
from geo_core.model_gateway.provider_adapters.base import ProviderJsonAdapter
from geo_core.sampling import CaptureMethod, SamplingTaskStatus

from tests.unit.model_gateway.provider_adapter_test_support import (
    SECRET_REFERENCE_ID,
    RecordingJsonTransport,
    RecordingProviderArtifactSink,
    StaticCredentialResolver,
    json_response,
    runtime,
)
from tests.unit.sampling.provider_execution_test_support import (
    ProviderIdentity,
    execution_fixture,
)


@dataclass(frozen=True)
class AdapterCase:
    identity: ProviderIdentity
    adapter: ProviderJsonAdapter
    model_release: ModelRelease
    transport: RecordingJsonTransport
    expected_citations: int


def _model_release(identity: ProviderIdentity, adapter: ProviderJsonAdapter) -> ModelRelease:
    release_id = f"{identity.provider}-sampling-model-v1"
    return ModelRelease(
        provider=identity.provider,
        adapter_release_id=adapter.adapter_release_id,
        model_release_id=release_id,
        release_hash=hashlib.sha256(release_id.encode()).hexdigest(),
        configured_model=identity.model,
        state=ReleaseState.APPROVED,
    )


def _openai_case() -> AdapterCase:
    identity = ProviderIdentity(
        provider="openai",
        model="gpt-fixture",
        reported_model="gpt-fixture-reported",
    )
    body = {
        "id": "openai-body-id",
        "status": "completed",
        "model": identity.reported_model,
        "output": [
            {
                "type": "web_search_call",
                "id": "search-1",
                "status": "completed",
                "action": {"type": "search", "queries": ["fixture Australia"]},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {"answer": "OpenAI recommends it.", "recommended": True}
                        ),
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.test/openai",
                                "title": "OpenAI source",
                                "start_index": 0,
                                "end_index": 6,
                            }
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 20, "output_tokens": 8, "total_tokens": 28},
    }
    transport = RecordingJsonTransport(json_response(body))
    adapter = OpenAIResponsesAdapter(
        runtime=runtime("openai", model=identity.model, purpose="geo_measurement"),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
        artifact_sink=RecordingProviderArtifactSink(),
    )
    return AdapterCase(identity, adapter, _model_release(identity, adapter), transport, 1)


def _kimi_case() -> AdapterCase:
    identity = ProviderIdentity(
        provider="kimi",
        model="kimi-fixture",
        reported_model="kimi-fixture-reported",
        search_mode="disabled",
        surface="chat_completion",
    )
    body = {
        "id": "kimi-response-id",
        "model": identity.reported_model,
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"answer": "Kimi completed it.", "recommended": True}
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
    }
    transport = RecordingJsonTransport(json_response(body))
    adapter = KimiChatCompletionsAdapter(
        runtime=runtime(
            "kimi",
            model=identity.model,
            search_modes=frozenset({"disabled"}),
            supports_search=False,
            purpose="geo_measurement",
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
        artifact_sink=RecordingProviderArtifactSink(),
    )
    return AdapterCase(identity, adapter, _model_release(identity, adapter), transport, 0)


def _gemini_case() -> AdapterCase:
    identity = ProviderIdentity(
        provider="gemini",
        model="gemini-3.1-pro-preview",
        reported_model="gemini-3.1-pro-reported",
        search_mode="google_search",
        surface="google_search_grounding",
    )
    body = {
        "responseId": "gemini-response-id",
        "modelVersion": identity.reported_model,
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {"answer": "Gemini recommends it.", "recommended": True}
                            )
                        }
                    ]
                },
                "groundingMetadata": {
                    "webSearchQueries": ["fixture Australia"],
                    "groundingChunks": [
                        {
                            "web": {
                                "uri": "https://example.test/gemini",
                                "title": "Gemini source",
                            }
                        }
                    ],
                    "groundingSupports": [
                        {
                            "segment": {"startIndex": 0, "endIndex": 6},
                            "groundingChunkIndices": [0],
                        }
                    ],
                },
            }
        ],
        "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 8},
    }
    transport = RecordingJsonTransport(json_response(body))
    adapter = GeminiGenerateContentAdapter(
        runtime=runtime(
            "gemini",
            model=identity.model,
            search_modes=frozenset({"google_search"}),
            supports_structured_output_with_tools=True,
            purpose="geo_measurement",
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
        artifact_sink=RecordingProviderArtifactSink(),
    )
    return AdapterCase(identity, adapter, _model_release(identity, adapter), transport, 1)


def _perplexity_case() -> AdapterCase:
    identity = ProviderIdentity(
        provider="perplexity",
        model="sonar-pro-fixture",
        reported_model="sonar-pro-reported",
        surface="sonar_web",
    )
    url = "https://example.test/perplexity"
    body = {
        "id": "perplexity-response-id",
        "model": identity.reported_model,
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"answer": "Sonar recommends it.", "recommended": True}
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
        "citations": [url],
        "search_results": [{"url": url, "title": "Sonar source", "source": "web"}],
    }
    transport = RecordingJsonTransport(json_response(body))
    adapter = PerplexitySonarAdapter(
        runtime=runtime("perplexity", model=identity.model, purpose="geo_measurement"),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
        artifact_sink=RecordingProviderArtifactSink(),
    )
    return AdapterCase(identity, adapter, _model_release(identity, adapter), transport, 1)


def _microsoft_case() -> AdapterCase:
    identity = ProviderIdentity(
        provider="microsoft",
        model="foundry-fixture",
        reported_model="foundry-fixture-reported",
        capture_method=CaptureMethod.PROXY_GROUNDED_API,
        search_mode="bing_grounding",
        surface="bing_grounding",
    )
    body = {
        "id": "microsoft-response-id",
        "status": "completed",
        "model": identity.reported_model,
        "output": [
            {
                "type": "bing_grounding_call",
                "id": "bing-call-1",
                "status": "completed",
                "arguments": json.dumps(
                    {
                        "website_urls": ["https://example.test/microsoft"],
                        "bing_search_query_url": "https://www.bing.com/search?q=fixture+australia",
                    }
                ),
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {"answer": "Bing recommends it.", "recommended": True}
                        ),
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.test/microsoft",
                                "title": "Bing source",
                                "start_index": 0,
                                "end_index": 6,
                            }
                        ],
                    }
                ],
            },
        ],
        "usage": {"input_tokens": 20, "output_tokens": 8, "total_tokens": 28},
    }
    transport = RecordingJsonTransport(json_response(body))
    adapter = MicrosoftBingGroundingAdapter(
        runtime=runtime(
            "microsoft",
            model=identity.model,
            capture_method=ModelCaptureMethod.PROXY_GROUNDED_API,
            search_modes=frozenset({"bing_grounding"}),
            purpose="geo_measurement",
        ),
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
        artifact_sink=RecordingProviderArtifactSink(),
        endpoint=(
            "https://fixture.services.ai.azure.com/api/projects/geo/openai/v1/responses"
        ),
        agent_reference=MicrosoftAgentReference(name="geo-grounding", version="1"),
    )
    return AdapterCase(identity, adapter, _model_release(identity, adapter), transport, 2)


@pytest.mark.parametrize(
    "case",
    (_openai_case(), _kimi_case(), _gemini_case(), _perplexity_case(), _microsoft_case()),
    ids=("openai", "kimi", "gemini", "perplexity", "microsoft"),
)
def test_five_provider_adapters_execute_through_sampling_core(case: AdapterCase) -> None:
    registry = ModelReleaseRegistry(
        adapter_releases=(case.adapter.runtime.adapter_release,),
        model_releases=(case.model_release,),
    )

    fixture = execution_fixture(
        identity=case.identity,
        adapter_release=case.adapter.runtime.adapter_release,
        model_release=case.model_release,
        gateway_factory=lambda _: ModelGatewayRouter(
            release_registry=registry,
            adapters=(case.adapter,),
        ),
    )
    result = fixture.service.execute(fixture.command, policy=fixture.policy)

    assert result.sampling.task.status is SamplingTaskStatus.SUCCEEDED
    assert result.lineage.provider == case.identity.provider
    assert result.lineage.configured_model == case.identity.model
    assert result.lineage.provider_reported_model == case.identity.reported_model
    assert result.lineage.capture_method is case.identity.model_capture_method
    assert result.lineage.search_mode == case.identity.search_mode
    assert result.lineage.citation_count == case.expected_citations
    assert case.transport.calls == 1
    assert result.sampling.task.identity.task_key in fixture.run.planned_task_keys
