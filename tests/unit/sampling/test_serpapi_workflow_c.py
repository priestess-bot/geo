from __future__ import annotations

import hashlib

from geo_core.model_gateway import (
    ModelGatewayRouter,
    ModelRelease,
    ModelReleaseRegistry,
    ReleaseState,
)
from geo_core.model_gateway.provider_adapters import JsonResponse, SerpApiGoogleSearchAdapter
from geo_core.sampling import SamplingTaskStatus

from tests.unit.model_gateway.provider_adapter_test_support import (
    SECRET_REFERENCE_ID,
    RecordingProviderArtifactSink,
    StaticCredentialResolver,
    runtime,
)
from tests.unit.sampling.provider_execution_test_support import (
    ProviderIdentity,
    execution_fixture,
)


class RecordingGetTransport:
    def __init__(self, responses: list[JsonResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(
        self,
        *,
        url: str,
        headers: dict[str, str],
        params: dict[str, object],
        timeout_seconds: float,
    ) -> JsonResponse:
        del headers, timeout_seconds
        self.calls.append((url, dict(params)))
        return self.responses.pop(0)


def _model_release(identity: ProviderIdentity, adapter: SerpApiGoogleSearchAdapter) -> ModelRelease:
    release_id = f"{identity.provider}-sampling-model-v1"
    return ModelRelease(
        provider=identity.provider,
        adapter_release_id=adapter.adapter_release_id,
        model_release_id=release_id,
        release_hash=hashlib.sha256(release_id.encode()).hexdigest(),
        configured_model=identity.model,
        state=ReleaseState.APPROVED,
    )


def test_serpapi_runs_through_workflow_c_and_persists_observation() -> None:
    identity = ProviderIdentity(
        provider="serpapi",
        source_platform="serpapi",
        model="google-ai-overview-fixture",
        reported_model="google_ai_overview",
        search_mode="google_search",
        surface="google_search",
    )
    transport = RecordingGetTransport(
        [
            JsonResponse(
                status_code=200,
                body={"ai_overview": {"page_token": "token-1"}},
                headers={},
            ),
            JsonResponse(
                status_code=200,
                body={
                    "ai_overview": {
                        "text_blocks": [
                            {"type": "paragraph", "text": "The answer is available."}
                        ],
                        "references": [
                            {"title": "Source", "link": "https://example.test/source"}
                        ],
                    }
                },
                headers={},
            ),
        ]
    )
    runtime_value = runtime(
        "serpapi",
        model=identity.model,
        search_modes=frozenset({"google_search"}),
        supports_search=True,
        purpose="geo_measurement",
    )
    adapter = SerpApiGoogleSearchAdapter(
        runtime=runtime_value,
        secret_reference_id=SECRET_REFERENCE_ID,
        credential_resolver=StaticCredentialResolver(),
        transport=transport,
        artifact_sink=RecordingProviderArtifactSink(),
    )
    model_release = _model_release(identity, adapter)
    registry = ModelReleaseRegistry(
        adapter_releases=(runtime_value.adapter_release,),
        model_releases=(model_release,),
    )
    fixture = execution_fixture(
        identity=identity,
        adapter_release=runtime_value.adapter_release,
        model_release=model_release,
        maximum_paid_calls=2,
        gateway_factory=lambda _: ModelGatewayRouter(
            release_registry=registry,
            adapters=(adapter,),
        ),
    )

    result = fixture.service.execute(fixture.command, policy=fixture.policy)

    assert result.sampling.task.status is SamplingTaskStatus.SUCCEEDED
    assert result.sampling.observation is not None
    assert result.lineage.provider == "serpapi"
    assert result.lineage.capture_method.value == "provider_api"
    assert len(transport.calls) == 2
    assert transport.calls[0][1]["gl"] == "au"
    assert transport.calls[1][1]["engine"] == "google_ai_overview"
    model_attempts = fixture.model_store.attempts(
        project_id=fixture.suite.project_id,
        job_id=fixture.attempt.id,
    )
    assert len(model_attempts) == 1
    event = fixture.model_store.terminal_event(
        project_id=fixture.suite.project_id,
        attempt_id=model_attempts[0].spec.id,
    )
    assert event is not None
    assert event.paid_call_count == 2
    assert result.sampling.observation.evidence.result_parameters_hash
    assert result.sampling.observation.evidence.result_parameters_hash != hashlib.sha256(
        b""
    ).hexdigest()
