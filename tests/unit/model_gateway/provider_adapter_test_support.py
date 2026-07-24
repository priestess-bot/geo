from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from uuid import UUID, uuid4

from geo_core.model_gateway import (
    AdapterRelease,
    DataUseDecision,
    EffectiveModelLocation,
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayRequest,
    ProviderCapabilities,
    ProviderDataPolicy,
    RequestedModelLocation,
    ReleaseState,
)
from geo_core.model_gateway.provider_adapters import JsonResponse, ProviderAdapterRuntime
from geo_core.model_gateway.provider_adapters.artifacts import (
    ProviderArtifactBundle,
    ProviderArtifactRecord,
)
from geo_core.secrets.models import SecretValue, SecretVersionHandle


OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "recommended"],
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "recommended": {"type": "boolean"},
    },
}
SECRET_TEXT = "fixture-provider-secret"
SECRET_REFERENCE_ID = UUID("d3dafd9c-60d8-4df5-8672-4ce88ac6e13d")


class RecordingJsonTransport:
    def __init__(self, response: JsonResponse | Exception) -> None:
        self.response = response
        self.calls = 0
        self.url: str | None = None
        self.headers: Mapping[str, str] = {}
        self.payload: Mapping[str, object] = {}
        self.timeout_seconds: float | None = None

    def __repr__(self) -> str:
        return f"RecordingJsonTransport(calls={self.calls}, url={self.url!r})"

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> JsonResponse:
        self.calls += 1
        self.url = url
        self.headers = dict(headers)
        self.payload = dict(payload)
        self.timeout_seconds = timeout_seconds
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class StaticCredentialResolver:
    def __init__(self, secret: str = SECRET_TEXT) -> None:
        self._secret = SecretValue(secret)
        self.calls: list[SecretVersionHandle] = []

    def __repr__(self) -> str:
        return "StaticCredentialResolver([REDACTED])"

    def resolve(self, handle: SecretVersionHandle) -> SecretValue:
        self.calls.append(handle)
        return self._secret


class RecordingProviderArtifactSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def capture(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        attempt_id: UUID,
        provider: str,
        adapter_release_id: str,
        adapter_release_hash: str,
        data_policy: ProviderDataPolicy,
        usage_purpose: str,
        usage_audience: ModelAudience,
        raw_payload: Mapping[str, object],
        raw_content_hash: str,
        derived_payload: Mapping[str, object],
    ) -> ProviderArtifactBundle:
        del (
            adapter_release_hash,
            raw_payload,
            usage_purpose,
            usage_audience,
            job_id,
        )
        self.calls.append((provider, adapter_release_id))
        derived_hash = hashlib.sha256(
            json.dumps(
                derived_payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        allowed = data_policy.storage is DataUseDecision.ALLOWED

        def record(kind: str, content_hash: str) -> ProviderArtifactRecord:
            manifest_hash = hashlib.sha256(
                f"{project_id}:{provider}:{kind}:{content_hash}".encode()
            ).hexdigest()
            return ProviderArtifactRecord(
                manifest_reference=(
                    f"s3://fixture/{project_id}/{provider}/{kind}/{manifest_hash}.json"
                    if allowed
                    else None
                ),
                manifest_hash=manifest_hash,
                content_hash=content_hash,
                byte_size=1 if allowed else 0,
                retention_days=data_policy.retention_days,
                expires_at=None,
                storage_decision=data_policy.storage,
            )

        return ProviderArtifactBundle(
            raw=record("raw", raw_content_hash),
            derived=record("derived", derived_hash),
            bundle_id=attempt_id if allowed else None,
        )


def runtime(
    provider: str,
    *,
    model: str,
    capture_method: ModelCaptureMethod = ModelCaptureMethod.PROVIDER_API,
    search_modes: frozenset[str | None] = frozenset({"web"}),
    supports_search: bool = True,
    supports_structured_output_with_tools: bool = False,
    purpose: str = "cross_engine_sampling",
) -> ProviderAdapterRuntime:
    release_id = f"{provider}-fixture-adapter-v1"
    release_hash = hashlib.sha256(release_id.encode()).hexdigest()
    return ProviderAdapterRuntime(
        adapter_release=AdapterRelease(
            provider=provider,
            adapter_release_id=release_id,
            release_hash=release_hash,
            interface_contract_version="geo-provider-sampling-v1",
            expected_capture_method=capture_method,
            capabilities=ProviderCapabilities(
                provider=provider,
                external_training_allowed=False,
                structured_output=True,
                data_retention_days=30,
                policy_reference=f"fixture-policy:{provider}",
                supports_search=supports_search,
                supports_citations=supports_search,
                supports_structured_output_with_tools=(
                    supports_structured_output_with_tools
                ),
            ),
            data_policy=ProviderDataPolicy(
                storage=DataUseDecision.ALLOWED,
                cache=DataUseDecision.ALLOWED,
                display=DataUseDecision.ALLOWED,
                redistribution=DataUseDecision.PROHIBITED,
                retention_days=30,
                terms_reference=f"https://evidence.example/{provider}/terms/2026-07-23",
                terms_sha256="a" * 64,
            ),
            state=ReleaseState.APPROVED,
            capability_evidence_reference=(
                f"https://evidence.example/{provider}/capabilities/v1"
            ),
            capability_evidence_sha256="b" * 64,
        ),
        capture_method=capture_method,
        allowed_purposes=frozenset({purpose}),
        allowed_models=frozenset({model}),
        allowed_search_modes=search_modes,
    )


def request(
    model: str,
    *,
    search_mode: str | None,
    capture_method: ModelCaptureMethod = ModelCaptureMethod.PROVIDER_API,
    purpose: str = "cross_engine_sampling",
    requested_location: RequestedModelLocation | None = None,
    expected_effective_location: EffectiveModelLocation | None = None,
) -> ModelGatewayRequest:
    project_id = uuid4()
    return ModelGatewayRequest(
        messages=(
            {"role": "system", "content": "Return only the requested evidence JSON."},
            {"role": "user", "content": "Is the product recommended in Australia?"},
        ),
        configured_model=model,
        prompt_bundle_hash="d" * 64,
        project_id=project_id,
        purpose=purpose,
        output_schema=OUTPUT_SCHEMA,
        search_mode=search_mode,
        capture_method=capture_method,
        provider_secret_handle=SecretVersionHandle(
            reference_id=SECRET_REFERENCE_ID,
            project_id=project_id,
            purpose=f"model_provider.{_provider_for_model(model)}",
            version=1,
        ),
        requested_location=requested_location,
        expected_effective_location=expected_effective_location,
    )


def _provider_for_model(model: str) -> str:
    prefixes = {
        "deepseek": "deepseek",
        "fixture-openai": "openai",
        "openai": "openai",
        "gpt": "openai",
        "moonshot": "kimi",
        "kimi": "kimi",
        "gemini": "gemini",
        "sonar": "perplexity",
        "foundry": "microsoft",
    }
    for prefix, provider in prefixes.items():
        if model.startswith(prefix):
            return provider
    raise ValueError(f"fixture model has no provider mapping: {model}")


def json_response(body: object, *, status_code: int = 200) -> JsonResponse:
    return JsonResponse(
        status_code=status_code,
        body=body,
        headers={"x-request-id": "header-request-id"},
    )
