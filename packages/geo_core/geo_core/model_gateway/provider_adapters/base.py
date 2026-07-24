"""Fixture-ready HTTP adapter boundary shared by external model providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from http.client import HTTPException
import json
import time
from typing import Protocol
from urllib.error import URLError
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.model_gateway.contracts import (
    ModelCallBudget,
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
    ProviderPolicyViolation,
    RetryableModelGatewayError,
    StructuredOutputValidationError,
    provider_http_error,
)
from geo_core.model_gateway.location import (
    EffectiveModelLocation,
    ModelLocationControl,
    uncontrolled_model_location,
)
from geo_core.model_gateway.releases import AdapterRelease, ReleaseState
from geo_core.model_gateway.provider_adapters.artifacts import ProviderArtifactSink
from geo_core.model_gateway.schema_validation import (
    validate_output_schema_definition,
    validate_structured_output,
)
from geo_core.model_gateway.provider_adapters.response_values import (
    canonical_hash,
    error_descriptor,
    normalized_citation,
    optional_decimal,
    optional_int,
    optional_text,
    parse_json_object_text,
    require_list,
    require_mapping,
    required_text,
    retry_after_seconds,
)
from geo_core.secrets.errors import SecretContractError, SecretStoreError
from geo_core.secrets.models import SecretValue, SecretVersionHandle


@dataclass(frozen=True)
class JsonResponse:
    status_code: int
    body: object
    headers: Mapping[str, str]


class JsonResponseInvalid(ValueError):
    """A successful provider response was not valid JSON."""


class JsonResponseTooLarge(ValueError):
    """A provider response exceeded the configured in-memory boundary."""


class JsonTransport(Protocol):
    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> JsonResponse: ...


class CredentialResolver(Protocol):
    """Resolve one frozen Secret Store version for one immediate provider call."""

    def resolve(self, handle: SecretVersionHandle) -> SecretValue: ...


@dataclass(frozen=True)
class ProviderAdapterRuntime:
    adapter_release: AdapterRelease
    capture_method: ModelCaptureMethod
    allowed_purposes: frozenset[str]
    allowed_models: frozenset[str]
    allowed_search_modes: frozenset[str | None]

    def __post_init__(self) -> None:
        if self.adapter_release.state is not ReleaseState.APPROVED:
            raise ProviderPolicyViolation("provider adapter runtime requires an approved release")
        if self.capture_method is not self.adapter_release.expected_capture_method:
            raise ProviderPolicyViolation(
                "provider runtime capture method differs from its Adapter Release"
            )
        if not self.allowed_purposes or any(not value.strip() for value in self.allowed_purposes):
            raise ProviderPolicyViolation("provider adapter purposes must be explicit")
        if not self.allowed_models or any(not value.strip() for value in self.allowed_models):
            raise ProviderPolicyViolation("provider adapter models must be explicit")
        if not self.allowed_search_modes or any(
            value is not None and not value.strip() for value in self.allowed_search_modes
        ):
            raise ProviderPolicyViolation("provider adapter search modes must be explicit")

    def validate_request(
        self,
        request: ModelGatewayRequest,
        *,
        provider: str,
        expected_capture_method: ModelCaptureMethod,
    ) -> None:
        release = self.adapter_release
        if release.provider != provider:
            raise ProviderPolicyViolation("adapter runtime provider does not match implementation")
        if self.capture_method is not expected_capture_method:
            raise ProviderPolicyViolation("adapter runtime capture method is invalid")
        if request.capture_method is not expected_capture_method:
            raise ProviderPolicyViolation(
                f"request capture method must be {expected_capture_method.value}",
                provider=provider,
            )
        if request.purpose not in self.allowed_purposes:
            raise ProviderPolicyViolation(
                f"request purpose is not approved for adapter release: {request.purpose}",
                provider=provider,
            )
        if request.configured_model not in self.allowed_models:
            raise ProviderPolicyViolation(
                "configured model is not approved for adapter release", provider=provider
            )
        if request.search_mode not in self.allowed_search_modes:
            raise ProviderPolicyViolation(
                f"search mode is not approved for adapter release: {request.search_mode}",
                provider=provider,
            )
        if request.output_schema is None:
            raise ProviderPolicyViolation(
                "provider sampling requires a frozen output schema", provider=provider
            )
        if request.tool_mode is not None:
            raise ProviderPolicyViolation(
                "provider sampling adapters do not accept caller-defined tool mode",
                provider=provider,
            )
        capabilities = release.capabilities
        if request.seed is not None and not capabilities.supports_seed:
            raise ProviderPolicyViolation(
                "adapter release does not support seed", provider=provider
            )
        if request.idempotency_key is not None and not capabilities.supports_idempotency:
            raise ProviderPolicyViolation(
                "adapter release does not support provider idempotency", provider=provider
            )
        if request.search_mode not in (None, "disabled") and not capabilities.supports_search:
            raise ProviderPolicyViolation(
                "adapter release does not have verified search capability", provider=provider
            )


@dataclass(frozen=True)
class ParsedProviderResponse:
    output: dict[str, object]
    provider_request_id: str | None
    provider_reported_model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: Decimal | None
    finish_reason: str | None
    citations: tuple[Mapping[str, object], ...] = ()
    tool_events: tuple[Mapping[str, object], ...] = ()
    usage_details: Mapping[str, object] | None = None


class ProviderJsonAdapter(ABC):
    """One-call JSON adapter with no SDK state, caching, or provider fallback."""

    provider: str
    expected_capture_method: ModelCaptureMethod
    documentation_references: tuple[str, ...]

    def __init__(
        self,
        *,
        runtime: ProviderAdapterRuntime,
        secret_reference_id: UUID,
        credential_resolver: CredentialResolver,
        transport: JsonTransport,
        endpoint: str,
        artifact_sink: ProviderArtifactSink | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if runtime.adapter_release.provider != self.provider:
            raise ProviderPolicyViolation("adapter release provider does not match implementation")
        if runtime.capture_method is not self.expected_capture_method:
            raise ProviderPolicyViolation(
                "adapter release capture method does not match implementation"
            )
        if secret_reference_id.int == 0:
            raise ProviderPolicyViolation("provider secret reference cannot be zero")
        _validate_endpoint(endpoint)
        if timeout_seconds <= 0:
            raise ProviderPolicyViolation("provider timeout must be positive")
        self.runtime = runtime
        self.secret_reference_id = secret_reference_id
        self.credential_resolver = credential_resolver
        self.transport = transport
        self.artifact_sink = artifact_sink
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.adapter_release_id = runtime.adapter_release.adapter_release_id
        self.adapter_release_hash = runtime.adapter_release.release_hash

    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        release = self.runtime.adapter_release
        self.runtime.validate_request(
            request,
            provider=self.provider,
            expected_capture_method=self.expected_capture_method,
        )
        policy.validate(release.capabilities, adapter_release_id=self.adapter_release_id)
        assert request.output_schema is not None
        try:
            validate_output_schema_definition(request.output_schema)
        except ModelGatewayError as exc:
            exc.provider = self.provider
            raise
        timeout_seconds = effective_timeout(
            request, configured=self.timeout_seconds, provider=self.provider
        )
        payload = self.build_payload(request)
        url = self.request_url(request)
        credential = self._resolve_credential(request)
        headers = {"Content-Type": "application/json", **self.authorization_headers(credential)}
        attempt = budget.consume()
        started_at = time.perf_counter()
        try:
            response = self.transport.post(
                url=url,
                headers=headers,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError as exc:
            raise RetryableModelGatewayError(
                "provider request timed out",
                code=ModelGatewayErrorCode.TIMEOUT,
                provider=self.provider,
            ) from exc
        except json.JSONDecodeError as exc:
            raise StructuredOutputValidationError(
                "provider response is not valid JSON", provider=self.provider
            ) from exc
        except JsonResponseInvalid as exc:
            raise StructuredOutputValidationError(
                "provider response is not valid JSON", provider=self.provider
            ) from exc
        except JsonResponseTooLarge as exc:
            raise StructuredOutputValidationError(
                "provider response exceeds the approved size limit",
                provider=self.provider,
            ) from exc
        except (URLError, ConnectionError, HTTPException) as exc:
            raise RetryableModelGatewayError(
                "provider request could not be completed",
                code=ModelGatewayErrorCode.PROVIDER_UNAVAILABLE,
                provider=self.provider,
            ) from exc
        if not 200 <= response.status_code < 300:
            raise self.response_error(response)
        try:
            body = require_mapping(response.body, label="provider response")
            parsed = self.parse_response(body, response.headers, request)
            validate_structured_output(parsed.output, request.output_schema)
            effective_location = self.resolve_effective_location(
                request,
                body=body,
                parsed=parsed,
            )
            response_hash = canonical_hash(body)
        except ModelGatewayError as exc:
            exc.provider = self.provider
            raise
        artifacts = None
        if self.artifact_sink is not None:
            if request.model_call_job_id is None or request.model_call_attempt_id is None:
                raise ModelGatewayError(
                    "governed provider artifacts require a reserved model-call Attempt",
                    code=ModelGatewayErrorCode.CONFIGURATION,
                    provider=self.provider,
                )
            try:
                artifacts = self.artifact_sink.capture(
                    project_id=request.project_id,
                    job_id=request.model_call_job_id,
                    attempt_id=request.model_call_attempt_id,
                    provider=self.provider,
                    adapter_release_id=self.adapter_release_id,
                    adapter_release_hash=self.adapter_release_hash,
                    data_policy=release.data_policy,
                    usage_purpose=request.purpose,
                    usage_audience=request.usage_audience,
                    raw_payload=body,
                    raw_content_hash=response_hash,
                    derived_payload=parsed.output,
                )
            except Exception as exc:
                raise ModelGatewayError(
                    "provider response artifacts could not be durably persisted",
                    code=ModelGatewayErrorCode.CONFIGURATION,
                    provider=self.provider,
                ) from exc
        call_log_id = uuid5(
            NAMESPACE_URL,
            ":".join(
                (
                    "geo-provider-call",
                    self.provider,
                    self.adapter_release_hash,
                    str(request.project_id),
                    request.prompt_bundle_hash,
                    str(attempt),
                    response_hash,
                )
            ),
        )
        return ModelGatewayResult(
            output=parsed.output,
            call_log_id=call_log_id,
            provider_request_id=parsed.provider_request_id,
            configured_model=request.configured_model,
            provider_reported_model=parsed.provider_reported_model,
            prompt_tokens=parsed.prompt_tokens,
            completion_tokens=parsed.completion_tokens,
            cost_usd=parsed.cost_usd,
            finish_reason=parsed.finish_reason,
            response_hash=response_hash,
            provider=self.provider,
            adapter_release_id=self.adapter_release_id,
            adapter_release_hash=self.adapter_release_hash,
            latency_ms=max(0, round((time.perf_counter() - started_at) * 1000)),
            citations=parsed.citations,
            tool_events=parsed.tool_events,
            capture_method=self.expected_capture_method,
            search_mode=request.search_mode,
            usage_details=parsed.usage_details,
            raw_artifact_reference=(artifacts.raw.manifest_reference if artifacts else None),
            raw_artifact_manifest_hash=(artifacts.raw.manifest_hash if artifacts else None),
            raw_artifact_content_hash=(artifacts.raw.content_hash if artifacts else None),
            raw_artifact_byte_size=(artifacts.raw.byte_size if artifacts else None),
            derived_artifact_reference=(
                artifacts.derived.manifest_reference if artifacts else None
            ),
            derived_artifact_manifest_hash=(
                artifacts.derived.manifest_hash if artifacts else None
            ),
            derived_artifact_content_hash=(
                artifacts.derived.content_hash if artifacts else None
            ),
            derived_artifact_byte_size=(artifacts.derived.byte_size if artifacts else None),
            raw_artifact_policy_hash=(release.data_policy_hash if artifacts else None),
            raw_artifact_storage_decision=(
                release.data_policy.storage.value if artifacts else None
            ),
            raw_artifact_cache_decision=(
                release.data_policy.cache.value if artifacts else None
            ),
            raw_artifact_display_decision=(
                release.data_policy.display.value if artifacts else None
            ),
            raw_artifact_redistribution_decision=(
                release.data_policy.redistribution.value if artifacts else None
            ),
            raw_artifact_retention_days=(
                release.data_policy.retention_days if artifacts else None
            ),
            usage_purpose=(request.purpose if artifacts else None),
            usage_audience=(request.usage_audience if artifacts else None),
            requested_location=request.requested_location,
            effective_location=effective_location,
        )

    def resolve_effective_location(
        self,
        request: ModelGatewayRequest,
        *,
        body: Mapping[str, object],
        parsed: ParsedProviderResponse,
    ) -> EffectiveModelLocation | None:
        del body, parsed
        expected = request.expected_effective_location
        if expected is None or expected.control is ModelLocationControl.NOT_CONTROLLED:
            return expected
        return uncontrolled_model_location(
            provider=self.provider,
            adapter_release_hash=self.adapter_release_hash,
            reason="adapter_does_not_apply_requested_location",
        )

    def _resolve_credential(self, request: ModelGatewayRequest) -> str:
        try:
            handle = request.provider_secret_handle
            if (
                handle is None
                or handle.reference_id != self.secret_reference_id
                or handle.project_id != request.project_id
                or handle.purpose != f"model_provider.{self.provider}"
            ):
                raise SecretContractError(
                    "provider request does not carry the exact approved secret version"
                )
            secret = self.credential_resolver.resolve(handle)
            if not isinstance(secret, SecretValue):
                raise SecretContractError("credential resolver returned an invalid value")
            return secret.reveal_text()
        except (SecretStoreError, SecretContractError) as exc:
            raise ModelGatewayError(
                "provider credential could not be resolved",
                code=ModelGatewayErrorCode.AUTH,
                provider=self.provider,
            ) from exc

    def response_error(self, response: JsonResponse) -> ModelGatewayError:
        descriptor = error_descriptor(response.body)
        if any(token in descriptor for token in ("content_filter", "refusal", "safety")):
            return ModelGatewayError(
                "provider refused the request",
                code=ModelGatewayErrorCode.CONTENT_REFUSAL,
                provider=self.provider,
                status_code=response.status_code,
            )
        if "quota" in descriptor or "insufficient_balance" in descriptor:
            return ModelGatewayError(
                "provider quota is unavailable",
                code=ModelGatewayErrorCode.QUOTA,
                provider=self.provider,
                status_code=response.status_code,
            )
        return provider_http_error(
            provider=self.provider,
            status_code=response.status_code,
            message=f"provider rejected request with HTTP {response.status_code}",
            retry_after_seconds=retry_after_seconds(response.headers),
        )

    def authorization_headers(self, credential: str) -> Mapping[str, str]:
        return {"Authorization": f"Bearer {credential}"}

    def request_url(self, request: ModelGatewayRequest) -> str:
        del request
        return self.endpoint

    @abstractmethod
    def build_payload(self, request: ModelGatewayRequest) -> Mapping[str, object]: ...

    @abstractmethod
    def parse_response(
        self,
        body: Mapping[str, object],
        headers: Mapping[str, str],
        request: ModelGatewayRequest,
    ) -> ParsedProviderResponse: ...


def effective_timeout(request: ModelGatewayRequest, *, configured: float, provider: str) -> float:
    if request.deadline_at is None:
        return configured
    if request.deadline_at.tzinfo is None:
        raise ProviderPolicyViolation(
            "model request deadline must be timezone-aware", provider=provider
        )
    remaining = (request.deadline_at - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise ModelGatewayError(
            "model request deadline has already elapsed",
            code=ModelGatewayErrorCode.CANCELLED,
            provider=provider,
        )
    return min(configured, remaining)


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ProviderPolicyViolation("provider endpoint must be an HTTPS URL without credentials")


__all__ = [
    "CredentialResolver",
    "JsonResponse",
    "JsonResponseInvalid",
    "JsonResponseTooLarge",
    "JsonTransport",
    "ParsedProviderResponse",
    "ProviderAdapterRuntime",
    "ProviderJsonAdapter",
    "canonical_hash",
    "effective_timeout",
    "error_descriptor",
    "normalized_citation",
    "optional_decimal",
    "optional_int",
    "optional_text",
    "parse_json_object_text",
    "require_list",
    "require_mapping",
    "required_text",
    "retry_after_seconds",
]
