"""Direct OpenAI-compatible DeepSeek adapter."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from geo_core.model_gateway.contracts import (
    ModelCallBudget,
    ModelGatewayError,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
    ProviderCapabilities,
    ProviderCapabilityRegistry,
    RetryableModelGatewayError,
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
            return JsonResponse(body=body, headers=dict(response.headers.items()))


class DeepSeekGateway:
    provider = "deepseek"

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
        policy.validate(capabilities)
        attempt = budget.consume()
        api_key = self._api_key()
        payload: dict[str, object] = {
            "model": request.configured_model,
            "messages": list(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self.transport.post(
                url=self.endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
        except HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code < 600:
                raise RetryableModelGatewayError(
                    f"DeepSeek temporarily rejected the request with HTTP {exc.code}"
                ) from exc
            raise ModelGatewayError(f"DeepSeek rejected the request with HTTP {exc.code}") from exc
        except (TimeoutError, URLError, ConnectionError) as exc:
            raise RetryableModelGatewayError("DeepSeek request could not be completed") from exc
        output, finish_reason = _extract_output(response.body)
        canonical = json.dumps(
            response.body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        response_hash = hashlib.sha256(canonical.encode()).hexdigest()
        usage_value = response.body.get("usage")
        usage: dict[str, object] = usage_value if isinstance(usage_value, dict) else {}
        provider_request_id = response.headers.get("x-request-id") or _optional_text(
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
        raise ModelGatewayError("DeepSeek response has no choices")
    choice: dict[str, object] = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ModelGatewayError("DeepSeek response has no message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ModelGatewayError("DeepSeek response content is empty")
    try:
        output = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ModelGatewayError("DeepSeek response is not valid JSON") from exc
    if not isinstance(output, dict):
        raise ModelGatewayError("DeepSeek response JSON must be an object")
    return output, _optional_text(choice.get("finish_reason"))


def _optional_text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


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
