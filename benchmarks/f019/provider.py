"""Paid-provider bridge for reproducible F-019 candidate execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import threading
from pathlib import Path
import time
from typing import Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from geo_core.model_gateway import (
    ModelCallBudget,
    ModelGatewayRequest,
    ModelPolicy,
    RetryableModelGatewayError,
)
from geo_core.model_gateway.contracts import ModelGatewayError
from geo_core.model_gateway.deepseek import (
    DeepSeekGateway,
    JsonResponse,
    UrlLibJsonTransport,
    default_deepseek_capability_registry,
)


PRICING_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing"
PRICING_SNAPSHOT_DATE = "2026-07-19"
DEEPSEEK_V4_FLASH_INPUT_CACHE_MISS_PER_MILLION_USD = Decimal("0.14")
DEEPSEEK_V4_FLASH_OUTPUT_PER_MILLION_USD = Decimal("0.28")
MAX_REQUEST_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.25


@dataclass(frozen=True)
class ResponseSnapshot:
    provider_reported_model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    estimated_cost_usd: Decimal | None
    cost_source: str
    response_hash: str
    finish_reason: str | None


@dataclass(frozen=True)
class CallEvidence:
    status: str
    request_attempt: int
    purpose: str
    configured_model: str
    provider_reported_model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    estimated_cost_usd: Decimal | None
    cost_source: str
    response_hash: str | None
    finish_reason: str | None
    failure_reason: str | None
    retry_reason: str | None


class _EvidenceTransport:
    """Retain only metering fields and a hash, never provider response content."""

    def __init__(self) -> None:
        self._delegate = UrlLibJsonTransport()
        self._local = threading.local()

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> JsonResponse:
        self._local.snapshot = None
        response = self._delegate.post(
            url=url,
            headers=headers,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        self._local.snapshot = _response_snapshot(response.body)
        return response

    def take_snapshot(self) -> ResponseSnapshot | None:
        snapshot = getattr(self._local, "snapshot", None)
        self._local.snapshot = None
        return snapshot


class DeepSeekJsonInvoker:
    """Use the existing policy/budget gateway and retain non-secret usage evidence."""

    provider = "deepseek"

    def __init__(self, *, key_file: Path, model: str = "deepseek-v4-flash") -> None:
        self.model = model
        self._transport = _EvidenceTransport()
        self._gateway = DeepSeekGateway(
            api_key_file=key_file,
            capability_registry=default_deepseek_capability_registry(),
            transport=self._transport,
        )
        self._calls: list[CallEvidence] = []
        self._lock = threading.Lock()

    def complete_json(
        self,
        *,
        project_id: str,
        purpose: str,
        messages: Sequence[Mapping[str, str]],
        request_hash: str,
        max_output_tokens: int,
    ) -> Mapping[str, object]:
        request = ModelGatewayRequest(
            messages=tuple(dict(item) for item in messages),
            configured_model=self.model,
            prompt_bundle_hash=request_hash,
            project_id=uuid5(NAMESPACE_URL, f"f019:{project_id}"),
            purpose=purpose,
            temperature=0.0,
            max_output_tokens=max_output_tokens,
        )
        budget = ModelCallBudget(MAX_REQUEST_ATTEMPTS)
        for request_attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                result = self._gateway.generate(
                    request,
                    policy=ModelPolicy(),
                    budget=budget,
                )
            except RetryableModelGatewayError as exc:
                snapshot = self._transport.take_snapshot()
                self._record(
                    _failed_call_evidence(
                        snapshot=snapshot,
                        request_attempt=request_attempt,
                        purpose=purpose,
                        configured_model=self.model,
                        reason=type(exc).__name__,
                        retryable=True,
                    )
                )
                if request_attempt == MAX_REQUEST_ATTEMPTS:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            except ModelGatewayError as exc:
                self._record(
                    _failed_call_evidence(
                        snapshot=self._transport.take_snapshot(),
                        request_attempt=request_attempt,
                        purpose=purpose,
                        configured_model=self.model,
                        reason=type(exc).__name__,
                        retryable=False,
                    )
                )
                raise

            self._transport.take_snapshot()
            if result.prompt_tokens is None or result.completion_tokens is None:
                raise RuntimeError("DeepSeek did not return actual token usage")
            provider_cost = result.cost_usd
            cost = provider_cost or _estimated_cost(result.prompt_tokens, result.completion_tokens)
            self._record(
                CallEvidence(
                    status="succeeded",
                    request_attempt=request_attempt,
                    purpose=purpose,
                    configured_model=result.configured_model,
                    provider_reported_model=result.provider_reported_model,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    estimated_cost_usd=cost,
                    cost_source=(
                        "provider_reported"
                        if provider_cost is not None
                        else "checked_in_price_snapshot"
                    ),
                    response_hash=result.response_hash,
                    finish_reason=result.finish_reason,
                    failure_reason=None,
                    retry_reason=None,
                )
            )
            return result.output
        raise AssertionError("bounded request loop ended without a result")

    def _record(self, evidence: CallEvidence) -> None:
        with self._lock:
            self._calls.append(evidence)

    def usage_totals(self) -> dict[str, int | float]:
        with self._lock:
            calls = tuple(self._calls)
        return {
            "input_tokens": sum(item.prompt_tokens or 0 for item in calls),
            "output_tokens": sum(item.completion_tokens or 0 for item in calls),
            "model_calls": len(calls),
            "estimated_cost_usd": float(
                sum((item.estimated_cost_usd or Decimal("0") for item in calls), Decimal("0"))
            ),
        }

    def usage_evidence(self) -> dict[str, object]:
        with self._lock:
            calls = tuple(self._calls)
        measurement_complete = all(
            item.prompt_tokens is not None
            and item.completion_tokens is not None
            and item.estimated_cost_usd is not None
            for item in calls
        )
        return {
            "provider": self.provider,
            "configured_model": self.model,
            "retry_policy": {
                "retryable_exception": "RetryableModelGatewayError",
                "maximum_attempts_per_request": MAX_REQUEST_ATTEMPTS,
                "fixed_backoff_seconds": RETRY_BACKOFF_SECONDS,
                "contract_validation_retried": False,
            },
            "measurement_complete": measurement_complete,
            "pricing": {
                "kind": "provider_usage_times_checked_in_price_snapshot",
                "source": PRICING_SOURCE,
                "snapshot_date": PRICING_SNAPSHOT_DATE,
                "input_cache_miss_per_million_usd": float(
                    DEEPSEEK_V4_FLASH_INPUT_CACHE_MISS_PER_MILLION_USD
                ),
                "output_per_million_usd": float(DEEPSEEK_V4_FLASH_OUTPUT_PER_MILLION_USD),
            },
            "calls": [
                {
                    "ordinal": ordinal,
                    "status": item.status,
                    "request_attempt": item.request_attempt,
                    "purpose": item.purpose,
                    "configured_model": item.configured_model,
                    "provider_reported_model": item.provider_reported_model,
                    "prompt_tokens": item.prompt_tokens,
                    "completion_tokens": item.completion_tokens,
                    "estimated_cost_usd": (
                        float(item.estimated_cost_usd)
                        if item.estimated_cost_usd is not None
                        else None
                    ),
                    "cost_source": item.cost_source,
                    "response_hash": item.response_hash,
                    "finish_reason": item.finish_reason,
                    "failure_reason": item.failure_reason,
                    "retry_reason": item.retry_reason,
                }
                for ordinal, item in enumerate(calls, 1)
            ],
        }


def _response_snapshot(body: Mapping[str, object]) -> ResponseSnapshot:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    usage_value = body.get("usage")
    usage: Mapping[str, object] = usage_value if isinstance(usage_value, Mapping) else {}
    prompt_tokens = _optional_int(usage.get("prompt_tokens"))
    completion_tokens = _optional_int(usage.get("completion_tokens"))
    provider_cost = _optional_decimal(usage.get("cost_usd"))
    if provider_cost is not None:
        cost = provider_cost
        cost_source = "provider_reported"
    elif prompt_tokens is not None and completion_tokens is not None:
        cost = _estimated_cost(prompt_tokens, completion_tokens)
        cost_source = "checked_in_price_snapshot"
    else:
        cost = None
        cost_source = "unavailable"
    choices = body.get("choices")
    first_choice = choices[0] if isinstance(choices, list) and choices else None
    finish_reason = (
        _optional_text(first_choice.get("finish_reason"))
        if isinstance(first_choice, Mapping)
        else None
    )
    return ResponseSnapshot(
        provider_reported_model=_optional_text(body.get("model")),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=cost,
        cost_source=cost_source,
        response_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        finish_reason=finish_reason,
    )


def _failed_call_evidence(
    *,
    snapshot: ResponseSnapshot | None,
    request_attempt: int,
    purpose: str,
    configured_model: str,
    reason: str,
    retryable: bool,
) -> CallEvidence:
    return CallEvidence(
        status="retryable_failure" if retryable else "nonretryable_failure",
        request_attempt=request_attempt,
        purpose=purpose,
        configured_model=configured_model,
        provider_reported_model=(snapshot.provider_reported_model if snapshot else None),
        prompt_tokens=snapshot.prompt_tokens if snapshot else None,
        completion_tokens=snapshot.completion_tokens if snapshot else None,
        estimated_cost_usd=snapshot.estimated_cost_usd if snapshot else None,
        cost_source=snapshot.cost_source if snapshot else "unavailable",
        response_hash=snapshot.response_hash if snapshot else None,
        finish_reason=snapshot.finish_reason if snapshot else None,
        failure_reason=reason,
        retry_reason=reason if retryable else None,
    )


def _optional_text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _optional_int(value: object) -> int | None:
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except (ValueError, ArithmeticError):
        return None


def _estimated_cost(prompt_tokens: int, completion_tokens: int) -> Decimal:
    million = Decimal("1000000")
    return (
        Decimal(prompt_tokens) * DEEPSEEK_V4_FLASH_INPUT_CACHE_MISS_PER_MILLION_USD / million
        + Decimal(completion_tokens) * DEEPSEEK_V4_FLASH_OUTPUT_PER_MILLION_USD / million
    ).quantize(Decimal("0.00000001"))
