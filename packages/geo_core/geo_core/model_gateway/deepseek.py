"""Direct OpenAI-compatible DeepSeek adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
from http.client import HTTPException
import json
from pathlib import Path
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from geo_core.model_gateway.contracts import (
    ModelCallBudget,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
    ProviderCapabilities,
    ProviderCapabilityRegistry,
    ProviderPolicyViolation,
    RetryableModelGatewayError,
    StructuredOutputValidationError,
    provider_http_error,
)
from geo_core.model_gateway.schema_validation import (
    validate_output_schema_definition,
    validate_structured_output,
)


@dataclass(frozen=True)
class JsonResponse:
    body: dict[str, object]
    headers: dict[str, str]


class JsonTransport(Protocol):
    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> JsonResponse: ...


class UrlLibJsonTransport:
    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> JsonResponse:
        request = Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
            body = json.loads(response.read().decode())
            if not isinstance(body, dict):
                raise StructuredOutputValidationError(
                    "DeepSeek HTTP response JSON must be an object", provider="deepseek"
                )
            return JsonResponse(body=body, headers=dict(response.headers.items()))


class DeepSeekGateway:
    provider = "deepseek"
    adapter_release_id = "deepseek-direct-v1"

    def __init__(
        self,
        *,
        api_key_file: Path,
        capability_registry: ProviderCapabilityRegistry,
        endpoint: str = "https://api.deepseek.com/chat/completions",
        timeout_seconds: float = 60.0,
        transport: JsonTransport | None = None,
    ) -> None:
        self.api_key_file = api_key_file
        self.capability_registry = capability_registry
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.transport = transport or UrlLibJsonTransport()

    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        capabilities = self.capability_registry.require(self.provider)
        policy.validate(capabilities, adapter_release_id=self.adapter_release_id)
        _validate_supported_request(request)
        if request.output_schema is not None:
            try:
                validate_output_schema_definition(request.output_schema)
            except ModelGatewayError as exc:
                exc.provider = self.provider
                raise
        timeout_seconds = _effective_timeout(request, configured=self.timeout_seconds)
        attempt = budget.consume()
        api_key = self._api_key()
        payload: dict[str, object] = {
            "model": request.configured_model,
            "messages": list(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        started_at = time.perf_counter()
        try:
            response = self.transport.post(
                url=self.endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
        except HTTPError as exc:
            error = provider_http_error(
                provider=self.provider,
                status_code=exc.code,
                message=f"DeepSeek rejected the request with HTTP {exc.code}",
                retry_after_seconds=_retry_after_seconds(exc),
            )
            raise error from exc
        except TimeoutError as exc:
            raise RetryableModelGatewayError(
                "DeepSeek request timed out",
                code=ModelGatewayErrorCode.TIMEOUT,
                provider=self.provider,
            ) from exc
        except json.JSONDecodeError as exc:
            raise StructuredOutputValidationError(
                "DeepSeek response is not valid JSON", provider=self.provider
            ) from exc
        except (URLError, ConnectionError, HTTPException) as exc:
            raise RetryableModelGatewayError(
                "DeepSeek request could not be completed",
                code=ModelGatewayErrorCode.PROVIDER_UNAVAILABLE,
                provider=self.provider,
            ) from exc
        output, finish_reason = _extract_output(response.body)
        if request.output_schema is not None:
            try:
                validate_structured_output(output, request.output_schema)
            except ModelGatewayError as exc:
                exc.provider = self.provider
                raise
        canonical = json.dumps(
            response.body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        response_hash = hashlib.sha256(canonical.encode()).hexdigest()
        usage_value = response.body.get("usage")
        usage: dict[str, object] = usage_value if isinstance(usage_value, dict) else {}
        provider_request_id = _header(response.headers, "x-request-id") or _optional_text(
            response.body.get("id")
        )
        call_log_id = uuid5(
            NAMESPACE_URL,
            ":".join(
                (
                    "geo-model-call",
                    str(request.project_id),
                    request.prompt_bundle_hash,
                    str(attempt),
                    response_hash,
                )
            ),
        )
        return ModelGatewayResult(
            output=output,
            call_log_id=call_log_id,
            provider_request_id=provider_request_id,
            configured_model=request.configured_model,
            provider_reported_model=_optional_text(response.body.get("model")),
            prompt_tokens=_optional_int(usage.get("prompt_tokens")),
            completion_tokens=_optional_int(usage.get("completion_tokens")),
            cost_usd=_optional_decimal(usage.get("cost_usd")),
            finish_reason=finish_reason,
            response_hash=response_hash,
            provider=self.provider,
            adapter_release_id=self.adapter_release_id,
            capture_method=request.capture_method,
            search_mode=request.search_mode,
            latency_ms=max(0, round((time.perf_counter() - started_at) * 1000)),
        )

    def _api_key(self) -> str:
        try:
            value = self.api_key_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ModelGatewayError("unable to read DeepSeek API key file") from exc
        if not value:
            raise ModelGatewayError("DeepSeek API key file is empty")
        return value


def default_deepseek_capability_registry() -> ProviderCapabilityRegistry:
    return ProviderCapabilityRegistry(
        (
            ProviderCapabilities(
                provider="deepseek",
                external_training_allowed=False,
                structured_output=True,
                data_retention_days=None,
                policy_reference="deployment-contract:deepseek",
            ),
        )
    )


def _extract_output(body: dict[str, object]) -> tuple[dict[str, object], str | None]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RetryableModelGatewayError("DeepSeek response has no choices", provider="deepseek")
    choice: dict[str, object] = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise RetryableModelGatewayError("DeepSeek response has no message", provider="deepseek")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RetryableModelGatewayError("DeepSeek response content is empty", provider="deepseek")
    try:
        output = json.loads(content)
    except json.JSONDecodeError as exc:
        raise StructuredOutputValidationError(
            "DeepSeek response is not valid JSON", provider="deepseek"
        ) from exc
    if not isinstance(output, dict):
        raise StructuredOutputValidationError(
            "DeepSeek response JSON must be an object", provider="deepseek"
        )
    return output, _optional_text(choice.get("finish_reason"))


def _validate_supported_request(request: ModelGatewayRequest) -> None:
    unsupported = (
        (request.seed is not None, "seed"),
        (request.tool_mode is not None, "tool mode"),
        (request.search_mode is not None, "search mode"),
        (request.idempotency_key is not None, "provider idempotency"),
    )
    for enabled, name in unsupported:
        if enabled:
            raise ProviderPolicyViolation(f"DeepSeek direct adapter does not support {name}")


def _effective_timeout(request: ModelGatewayRequest, *, configured: float) -> float:
    if request.deadline_at is None:
        return configured
    if request.deadline_at.tzinfo is None:
        raise ModelGatewayError(
            "model request deadline must be timezone-aware",
            code=ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION,
            provider="deepseek",
        )
    remaining = (request.deadline_at - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise ModelGatewayError(
            "model request deadline has already elapsed",
            code=ModelGatewayErrorCode.CANCELLED,
            provider="deepseek",
        )
    return min(configured, remaining)


def _retry_after_seconds(error: HTTPError) -> float | None:
    value = error.headers.get("Retry-After") if error.headers is not None else None
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _optional_text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _header(headers: dict[str, str], name: str) -> str | None:
    expected = name.casefold()
    return next(
        (value for key, value in headers.items() if key.casefold() == expected and value),
        None,
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except InvalidOperation:
        return None
