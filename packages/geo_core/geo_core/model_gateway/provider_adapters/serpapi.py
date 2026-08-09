"""SerpAPI Google Search adapter for the governed Model Gateway path.

SerpAPI is a search provider, not one of the six model providers.  This
adapter therefore uses the same Gateway reservation, release, artifact sink,
and terminal event path while keeping its Secret Store purpose as
``search.serpapi``.  A page-token response is one logical provider call but
requires a second bounded GET; the resulting ``request_count`` is recorded in
the immutable usage details.
"""

from __future__ import annotations

from collections.abc import Mapping
import time
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.model_gateway.contracts import (
    ModelCallBudget,
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
    RetryableModelGatewayError,
    StructuredOutputValidationError,
    provider_http_error,
)
from geo_core.model_gateway.location import (
    EffectiveModelLocation,
    ModelLocationControl,
    uncontrolled_model_location,
)
from geo_core.model_gateway.provider_adapters.artifacts import ProviderArtifactSink
from geo_core.model_gateway.provider_adapters.base import (
    CredentialResolver,
    JsonGetTransport,
    JsonResponse,
    JsonResponseInvalid,
    JsonResponseTooLarge,
    ProviderAdapterRuntime,
)
from geo_core.model_gateway.provider_adapters.response_values import (
    canonical_hash,
    error_descriptor,
    normalized_citation,
    require_mapping,
    retry_after_seconds,
)
from geo_core.model_gateway.schema_validation import validate_output_schema_definition
from geo_core.model_gateway.releases import provider_secret_purpose
from geo_core.search_aggregation.serpapi_adapter import (
    _extract_blocks_and_references,
    _find_overview_payload,
    _is_page_token_only,
    _serpapi_language,
    _serpapi_region,
)
from geo_core.secrets.errors import SecretContractError, SecretStoreError
from geo_core.secrets.models import SecretValue


class SerpApiGoogleSearchAdapter:
    """Execute SerpAPI Google/AIO through the exact Model Gateway contract."""

    provider = "serpapi"
    expected_capture_method = ModelCaptureMethod.PROVIDER_API
    documentation_references = (
        "https://serpapi.com/search-api",
        "https://serpapi.com/google-ai-overview-api",
    )

    def __init__(
        self,
        *,
        runtime: ProviderAdapterRuntime,
        secret_reference_id: UUID,
        credential_resolver: CredentialResolver,
        transport: JsonGetTransport,
        artifact_sink: ProviderArtifactSink | None = None,
        endpoint: str = "https://serpapi.com/search.json",
        timeout_seconds: float = 60.0,
    ) -> None:
        if runtime.adapter_release.provider != self.provider:
            raise ModelGatewayError(
                "SerpAPI adapter release provider does not match implementation",
                code=ModelGatewayErrorCode.CONFIGURATION,
                provider=self.provider,
            )
        if runtime.capture_method is not self.expected_capture_method:
            raise ModelGatewayError(
                "SerpAPI adapter requires provider_api capture",
                code=ModelGatewayErrorCode.CONFIGURATION,
                provider=self.provider,
            )
        if secret_reference_id.int == 0 or timeout_seconds <= 0:
            raise ModelGatewayError(
                "SerpAPI adapter configuration is invalid",
                code=ModelGatewayErrorCode.CONFIGURATION,
                provider=self.provider,
            )
        if not endpoint.startswith("https://") or "?" in endpoint or "#" in endpoint:
            raise ModelGatewayError(
                "SerpAPI endpoint must be an HTTPS URL without query or fragment",
                code=ModelGatewayErrorCode.CONFIGURATION,
                provider=self.provider,
            )
        self.runtime = runtime
        self.secret_reference_id = secret_reference_id
        self.credential_resolver = credential_resolver
        self.transport = transport
        self.artifact_sink = artifact_sink
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.adapter_release_id = runtime.adapter_release.adapter_release_id
        self.adapter_release_hash = runtime.adapter_release.release_hash

    def __repr__(self) -> str:
        return (
            "SerpApiGoogleSearchAdapter("
            f"adapter_release_id={self.adapter_release_id!r}, endpoint={self.endpoint!r})"
        )

    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        self.runtime.validate_request(
            request,
            provider=self.provider,
            expected_capture_method=self.expected_capture_method,
        )
        policy.validate(
            self.runtime.adapter_release.capabilities,
            adapter_release_id=self.adapter_release_id,
        )
        if request.output_schema is None:
            raise StructuredOutputValidationError(
                "SerpAPI sampling requires a frozen output schema", provider=self.provider
            )
        validate_output_schema_definition(request.output_schema)
        query = _query_from_request(request)
        language = _serpapi_language(
            request.requested_location.locale if request.requested_location else "en-AU"
        )
        region = _serpapi_region(
            request.requested_location.country_code
            if request.requested_location and request.requested_location.country_code
            else "AU"
        )
        credential = self._resolve_credential(request)
        # The sampling Attempt remains one logical operation, while every paid
        # HTTP request consumes the frozen Model Gateway budget.
        budget.consume()
        started_at = time.perf_counter()
        first = self._get(
            params={
                "engine": "google",
                "q": query,
                "api_key": credential,
                "hl": language,
                "gl": region,
            },
            request=request,
        )
        first_body = require_mapping(first.body, label="SerpAPI response")
        overview = _find_overview_payload(dict(first_body))
        request_count = 1
        combined: dict[str, object] = dict(first_body)
        resolved_page_token = False
        if overview is not None and _is_page_token_only(overview):
            token = overview.get("page_token")
            if not isinstance(token, str) or not token.strip():
                raise StructuredOutputValidationError(
                    "SerpAPI AI Overview page token is empty", provider=self.provider
                )
            # Page-token resolution is a second paid Provider request.  Check
            # the frozen budget before doing any second network I/O.
            budget.consume()
            second = self._get(
                params={
                    "engine": "google_ai_overview",
                    "page_token": token,
                    "api_key": credential,
                },
                request=request,
            )
            second_body = require_mapping(second.body, label="SerpAPI AI Overview response")
            combined = {
                "search_response": dict(first_body),
                "ai_overview_response": dict(second_body),
            }
            overview = _find_overview_payload(dict(second_body))
            request_count = 2
            resolved_page_token = True
        if overview is None:
            raise StructuredOutputValidationError(
                "SerpAPI response did not contain an ai_overview payload",
                provider=self.provider,
            )
        blocks, references = _extract_blocks_and_references(overview)
        answer_parts: list[str] = []
        for block in blocks:
            if block.text:
                answer_parts.append(block.text)
            if block.items:
                answer_parts.extend(item.text for item in block.items)
        answer = "\n".join(part.strip() for part in answer_parts if part.strip()).strip()
        if not answer:
            raise StructuredOutputValidationError(
                "SerpAPI ai_overview payload has no answer text", provider=self.provider
            )
        output: dict[str, object] = {"answer": answer, "recommended": False}
        from geo_core.model_gateway.schema_validation import validate_structured_output

        validate_structured_output(output, request.output_schema)
        response_hash = canonical_hash(combined)
        citations = tuple(
            normalized_citation(
                provider=self.provider,
                url=reference.url,
                title=reference.title,
                ordinal=index,
                citation_type="ai_overview_reference",
            )
            for index, reference in enumerate(references, start=1)
            if reference.url and reference.url.startswith(("http://", "https://"))
        )
        derived = {
            **output,
            "provider": self.provider,
            "surface": "google_search",
            "query": query,
            "request_count": request_count,
        }
        artifacts = self._capture_artifacts(request, combined, response_hash, derived)
        attempt_number = budget.consumed_calls
        call_log_id = uuid5(
            NAMESPACE_URL,
            ":".join(
                (
                    "geo-provider-call",
                    self.provider,
                    self.adapter_release_hash,
                    str(request.project_id),
                    request.prompt_bundle_hash,
                    str(attempt_number),
                    response_hash,
                )
            ),
        )
        return ModelGatewayResult(
            output=output,
            call_log_id=call_log_id,
            provider_request_id=_provider_request_id(first_body),
            configured_model=request.configured_model,
            provider_reported_model="google_ai_overview",
            prompt_tokens=None,
            completion_tokens=None,
            cost_usd=None,
            finish_reason="completed",
            response_hash=response_hash,
            provider=self.provider,
            adapter_release_id=self.adapter_release_id,
            adapter_release_hash=self.adapter_release_hash,
            latency_ms=max(0, round((time.perf_counter() - started_at) * 1000)),
            citations=citations,
            tool_events=(
                {
                    "type": "search",
                    "engine": "google",
                    "query": query,
                    "request_count": request_count,
                },
            ),
            capture_method=self.expected_capture_method,
            search_mode=request.search_mode,
            usage_details={
                "request_count": request_count,
                "logical_call_count": 1,
                "page_token_resolved": resolved_page_token,
                "requested_region": region,
                "requested_language": language,
                "egress_proof": "not_provided_by_serpapi_gl",
            },
            raw_artifact_reference=artifacts[0] if artifacts else None,
            raw_artifact_manifest_hash=artifacts[1] if artifacts else None,
            raw_artifact_content_hash=artifacts[2] if artifacts else None,
            raw_artifact_byte_size=artifacts[3] if artifacts else None,
            derived_artifact_reference=artifacts[4] if artifacts else None,
            derived_artifact_manifest_hash=artifacts[5] if artifacts else None,
            derived_artifact_content_hash=artifacts[6] if artifacts else None,
            derived_artifact_byte_size=artifacts[7] if artifacts else None,
            raw_artifact_policy_hash=(
                self.runtime.adapter_release.data_policy_hash if artifacts else None
            ),
            raw_artifact_storage_decision=(
                self.runtime.adapter_release.data_policy.storage.value if artifacts else None
            ),
            raw_artifact_cache_decision=(
                self.runtime.adapter_release.data_policy.cache.value if artifacts else None
            ),
            raw_artifact_display_decision=(
                self.runtime.adapter_release.data_policy.display.value if artifacts else None
            ),
            raw_artifact_redistribution_decision=(
                self.runtime.adapter_release.data_policy.redistribution.value
                if artifacts
                else None
            ),
            raw_artifact_retention_days=(
                self.runtime.adapter_release.data_policy.retention_days if artifacts else None
            ),
            usage_purpose=(request.purpose if artifacts else None),
            usage_audience=(request.usage_audience if artifacts else None),
            requested_location=request.requested_location,
            effective_location=self.resolve_effective_location(request),
        )

    def _resolve_credential(self, request: ModelGatewayRequest) -> str:
        handle = request.provider_secret_handle
        if (
            handle is None
            or handle.reference_id != self.secret_reference_id
            or handle.project_id != request.project_id
            or handle.purpose != provider_secret_purpose(self.provider)
        ):
            raise ModelGatewayError(
                "SerpAPI request does not carry the exact approved search Secret version",
                code=ModelGatewayErrorCode.AUTH,
                provider=self.provider,
            )
        try:
            secret = self.credential_resolver.resolve(handle)
            if not isinstance(secret, SecretValue):
                raise SecretContractError("credential resolver returned an invalid value")
            value = secret.reveal_text().strip()
        except (SecretStoreError, SecretContractError):
            raise ModelGatewayError(
                "SerpAPI credential could not be resolved",
                code=ModelGatewayErrorCode.AUTH,
                provider=self.provider,
            ) from None
        if not value:
            raise ModelGatewayError(
                "SerpAPI credential is empty",
                code=ModelGatewayErrorCode.AUTH,
                provider=self.provider,
            )
        return value

    def _get(
        self,
        *,
        params: Mapping[str, object],
        request: ModelGatewayRequest,
    ) -> JsonResponse:
        from geo_core.model_gateway.provider_adapters.base import effective_timeout

        try:
            response = self.transport.get(
                url=self.endpoint,
                headers={"Accept": "application/json"},
                params=params,
                timeout_seconds=effective_timeout(
                    request, configured=self.timeout_seconds, provider=self.provider
                ),
            )
        except TimeoutError as exc:
            raise RetryableModelGatewayError(
                "SerpAPI request timed out",
                code=ModelGatewayErrorCode.TIMEOUT,
                provider=self.provider,
            ) from exc
        except (JsonResponseInvalid, JsonResponseTooLarge) as exc:
            raise StructuredOutputValidationError(
                "SerpAPI response is not valid JSON or exceeds the approved size",
                provider=self.provider,
            ) from exc
        except (ConnectionError, OSError) as exc:
            raise RetryableModelGatewayError(
                "SerpAPI request could not be completed",
                code=ModelGatewayErrorCode.PROVIDER_UNAVAILABLE,
                provider=self.provider,
            ) from exc
        if not 200 <= response.status_code < 300:
            descriptor = error_descriptor(response.body)
            if "error" in descriptor and "quota" in descriptor:
                raise provider_http_error(
                    provider=self.provider,
                    status_code=402,
                    message="SerpAPI quota is unavailable",
                )
            raise provider_http_error(
                provider=self.provider,
                status_code=response.status_code,
                message=f"SerpAPI rejected the request with HTTP {response.status_code}",
                retry_after_seconds=retry_after_seconds(response.headers),
            )
        return response

    def _capture_artifacts(
        self,
        request: ModelGatewayRequest,
        raw: Mapping[str, object],
        raw_hash: str,
        derived: Mapping[str, object],
    ) -> tuple[str | None, str, str, int, str | None, str, str, int] | None:
        if self.artifact_sink is None:
            return None
        if request.model_call_job_id is None or request.model_call_attempt_id is None:
            raise ModelGatewayError(
                "governed SerpAPI artifacts require a reserved Model Gateway Attempt",
                code=ModelGatewayErrorCode.CONFIGURATION,
                provider=self.provider,
            )
        try:
            bundle = self.artifact_sink.capture(
                project_id=request.project_id,
                job_id=request.model_call_job_id,
                attempt_id=request.model_call_attempt_id,
                provider=self.provider,
                adapter_release_id=self.adapter_release_id,
                adapter_release_hash=self.adapter_release_hash,
                data_policy=self.runtime.adapter_release.data_policy,
                usage_purpose=request.purpose,
                usage_audience=request.usage_audience,
                raw_payload=raw,
                raw_content_hash=raw_hash,
                derived_payload=derived,
            )
        except Exception as exc:
            raise ModelGatewayError(
                "SerpAPI response artifacts could not be durably persisted",
                code=ModelGatewayErrorCode.CONFIGURATION,
                provider=self.provider,
            ) from exc
        return (
            bundle.raw.manifest_reference,
            bundle.raw.manifest_hash,
            bundle.raw.content_hash,
            bundle.raw.byte_size,
            bundle.derived.manifest_reference,
            bundle.derived.manifest_hash,
            bundle.derived.content_hash,
            bundle.derived.byte_size,
        )

    def resolve_effective_location(
        self, request: ModelGatewayRequest
    ) -> EffectiveModelLocation | None:
        expected = request.expected_effective_location
        if expected is None or expected.control is ModelLocationControl.NOT_CONTROLLED:
            return expected
        return uncontrolled_model_location(
            provider=self.provider,
            adapter_release_hash=self.adapter_release_hash,
            reason="serpapi_gl_is_not_egress_proof",
        )


def _query_from_request(request: ModelGatewayRequest) -> str:
    for message in reversed(request.messages):
        if message.get("role") == "user" and message.get("content", "").strip():
            return message["content"].strip()
    raise StructuredOutputValidationError(
        "SerpAPI request requires a non-empty user query", provider="serpapi"
    )


def _provider_request_id(body: Mapping[str, object]) -> str | None:
    metadata = body.get("search_metadata")
    if isinstance(metadata, Mapping):
        for key in ("id", "status"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    value = body.get("serpapi_search_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = ["SerpApiGoogleSearchAdapter"]
