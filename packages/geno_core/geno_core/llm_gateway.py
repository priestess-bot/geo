from __future__ import annotations

import json
import math
import os
from dataclasses import asdict
from datetime import UTC, datetime
from time import perf_counter, sleep
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5
from urllib.request import Request, urlopen

from geno_core.audit import hash_payload
from geno_core.models import LLMCallLog


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


class FixtureLLMGateway:
    provider = "fixture"

    def __init__(
        self,
        *,
        prompt_version: str = "llm_judge_prompt_v1",
        cost_per_1k_tokens: float = 0.0,
    ) -> None:
        self.prompt_version = prompt_version
        self.cost_per_1k_tokens = cost_per_1k_tokens

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = metadata or {}
        started = perf_counter()
        prompt_version = str(metadata.get("prompt_version") or self.prompt_version)
        request_payload = {"messages": messages, "metadata": metadata, "model": model}
        request_hash = hash_payload(request_payload)
        content = json.dumps(
            {
                "gateway": "fixture",
                "model": model,
                "prompt_version": prompt_version,
                "request_hash": request_hash[:16],
                "status": "succeeded",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        response_payload = {"content": content, "model": model, "provider": self.provider}
        response_hash = hash_payload(response_payload)
        prompt_tokens = sum(_estimate_tokens(message.get("content", "")) for message in messages)
        completion_tokens = _estimate_tokens(content)
        total_tokens = prompt_tokens + completion_tokens
        latency_ms = max(0, round((perf_counter() - started) * 1000))
        estimated_cost = round((total_tokens / 1000.0) * self.cost_per_1k_tokens, 6)
        call_log = LLMCallLog(
            id=str(uuid5(NAMESPACE_URL, f"geno:llm-call:{self.provider}:{model}:{request_hash}:{response_hash}")),
            project_id=str(metadata["project_id"]) if metadata.get("project_id") else None,
            answer_run_id=str(metadata["answer_run_id"]) if metadata.get("answer_run_id") else None,
            purpose=str(metadata.get("purpose") or "fixture_chat"),
            provider=self.provider,
            model=model,
            prompt_version=prompt_version,
            request_hash=request_hash,
            response_hash=response_hash,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost=estimated_cost,
            latency_ms=latency_ms,
            status="succeeded",
            error_message=None,
            created_at=datetime.now(UTC),
        )
        return {
            "content": content,
            "provider": self.provider,
            "model": model,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost": estimated_cost,
            },
            "call_log": asdict(call_log),
        }

    def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hash_payload({"model": model, "text": text})
            values = [int(digest[index : index + 2], 16) / 255 for index in range(0, 16, 2)]
            vectors.append(values)
        return vectors


class LLMGatewayConfigurationError(RuntimeError):
    pass


class LLMGatewayRequestError(RuntimeError):
    def __init__(self, message: str, *, call_log: dict[str, Any]) -> None:
        super().__init__(message)
        self.call_log = call_log


class LLMGatewayRetryExhaustedError(RuntimeError):
    def __init__(self, message: str, *, attempt_count: int, prior_errors: tuple[str, ...]) -> None:
        super().__init__(message)
        self.attempt_count = attempt_count
        self.prior_errors = prior_errors


class JsonGatewayHttpClient:
    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        request = Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
            body = response.read().decode("utf-8")
            return json.loads(body)


class LiteLLMGateway:
    provider = "litellm"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        prompt_version: str = "llm_judge_prompt_v1",
        timeout_seconds: float = 30.0,
        cost_per_1k_tokens: float = 0.0,
        max_retries: int = 0,
        retry_backoff_seconds: float = 0.25,
        http_client: JsonGatewayHttpClient | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        configured_base_url = base_url if base_url is not None else os.getenv("LITELLM_BASE_URL")
        self.base_url = (configured_base_url or "http://localhost:4000").rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("LITELLM_API_KEY")
        self.prompt_version = prompt_version
        self.timeout_seconds = timeout_seconds
        self.cost_per_1k_tokens = cost_per_1k_tokens
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.http_client = http_client or JsonGatewayHttpClient()
        self.sleep_fn = sleep_fn

    def health(self) -> str:
        return "ready" if self.base_url and self.api_key else "not_configured"

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise LLMGatewayConfigurationError("LITELLM_API_KEY is required")
        return {"Authorization": f"Bearer {self.api_key}"}

    def _call_log(
        self,
        *,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | None,
        model: str,
        metadata: dict[str, Any],
        started: float,
        status: str,
        error_message: str | None = None,
        attempt_count: int = 1,
        prior_errors: tuple[str, ...] = (),
    ) -> LLMCallLog:
        prompt_version = str(metadata.get("prompt_version") or self.prompt_version)
        request_hash = hash_payload(request_payload)
        response_hash = hash_payload(response_payload or {"error_message": error_message, "status": status})
        prompt_tokens, completion_tokens = _usage_tokens(
            response_payload=response_payload,
            fallback_prompt_tokens=sum(_estimate_tokens(message.get("content", "")) for message in request_payload.get("messages", [])),
            fallback_completion_tokens=_estimate_tokens(str(response_payload or error_message or "")),
        )
        total_tokens = prompt_tokens + completion_tokens
        latency_ms = max(0, round((perf_counter() - started) * 1000))
        estimated_cost = _response_cost(response_payload)
        if estimated_cost is None:
            estimated_cost = round((total_tokens / 1000.0) * self.cost_per_1k_tokens, 6)
        enriched_error_message = error_message
        if enriched_error_message and (attempt_count > 1 or prior_errors):
            enriched_error_message = (
                f"{enriched_error_message}; attempts={attempt_count}; prior_errors={list(prior_errors)}"
            )
        return LLMCallLog(
            id=str(uuid5(NAMESPACE_URL, f"geno:llm-call:{self.provider}:{model}:{request_hash}:{response_hash}")),
            project_id=str(metadata["project_id"]) if metadata.get("project_id") else None,
            answer_run_id=str(metadata["answer_run_id"]) if metadata.get("answer_run_id") else None,
            purpose=str(metadata.get("purpose") or "litellm_chat"),
            provider=self.provider,
            model=model,
            prompt_version=prompt_version,
            request_hash=request_hash,
            response_hash=response_hash,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost=estimated_cost,
            latency_ms=latency_ms,
            status=status,
            error_message=enriched_error_message,
            created_at=datetime.now(UTC),
        )

    def _post_with_retries(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], int, tuple[str, ...]]:
        prior_errors: list[str] = []
        for attempt_index in range(self.max_retries + 1):
            try:
                return (
                    self.http_client.post_json(
                        url=url,
                        headers=headers,
                        payload=payload,
                        timeout_seconds=self.timeout_seconds,
                    ),
                    attempt_index + 1,
                    tuple(prior_errors),
                )
            except Exception as exc:  # noqa: BLE001 - retry policy must capture heterogeneous client errors.
                prior_errors.append(str(exc))
                if attempt_index >= self.max_retries:
                    raise LLMGatewayRetryExhaustedError(
                        str(exc),
                        attempt_count=attempt_index + 1,
                        prior_errors=tuple(prior_errors),
                    ) from exc
                self.sleep_fn(self.retry_backoff_seconds * (2**attempt_index))
        raise RuntimeError("unreachable LiteLLM retry state")

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = metadata or {}
        request_payload = {"model": model, "messages": messages}
        started = perf_counter()
        attempt_count = 1
        prior_errors: tuple[str, ...] = ()
        try:
            response_payload, attempt_count, prior_errors = self._post_with_retries(
                url=f"{self.base_url}/chat/completions",
                headers=self._headers(),
                payload=request_payload,
            )
        except LLMGatewayRetryExhaustedError as exc:
            call_log = self._call_log(
                request_payload=request_payload,
                response_payload=None,
                model=model,
                metadata=metadata,
                started=started,
                status="failed",
                error_message=str(exc),
                attempt_count=exc.attempt_count,
                prior_errors=exc.prior_errors,
            )
            raise LLMGatewayRequestError(f"LiteLLM chat request failed: {exc}", call_log=asdict(call_log)) from exc
        except Exception as exc:  # noqa: BLE001 - configuration/client failures must remain auditable.
            call_log = self._call_log(
                request_payload=request_payload,
                response_payload=None,
                model=model,
                metadata=metadata,
                started=started,
                status="failed",
                error_message=str(exc),
                attempt_count=attempt_count,
                prior_errors=prior_errors,
            )
            raise LLMGatewayRequestError(f"LiteLLM chat request failed: {exc}", call_log=asdict(call_log)) from exc
        try:
            content = _extract_chat_content(response_payload)
        except Exception as exc:  # noqa: BLE001 - malformed upstream responses must remain auditable.
            call_log = self._call_log(
                request_payload=request_payload,
                response_payload=response_payload,
                model=model,
                metadata=metadata,
                started=started,
                status="failed",
                error_message=str(exc),
                attempt_count=attempt_count,
                prior_errors=prior_errors,
            )
            raise LLMGatewayRequestError(f"LiteLLM chat response parsing failed: {exc}", call_log=asdict(call_log)) from exc
        call_log = self._call_log(
            request_payload=request_payload,
            response_payload=response_payload,
            model=model,
            metadata=metadata,
            started=started,
            status="succeeded",
            attempt_count=attempt_count,
            prior_errors=prior_errors,
        )
        return {
            "content": content,
            "provider": self.provider,
            "model": model,
            "usage": {
                "prompt_tokens": call_log.prompt_tokens,
                "completion_tokens": call_log.completion_tokens,
                "total_tokens": call_log.total_tokens,
                "estimated_cost": call_log.estimated_cost,
                "attempt_count": attempt_count,
                "retry_errors": list(prior_errors),
            },
            "raw_response": {
                **response_payload,
                "_geno_retry": {"attempt_count": attempt_count, "prior_errors": list(prior_errors)},
            },
            "call_log": asdict(call_log),
        }

    def embed(self, *, texts: list[str], model: str) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": model, "input": texts}
        response_payload = self.http_client.post_json(
            url=f"{self.base_url}/embeddings",
            headers=self._headers(),
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
        raw_data = response_payload.get("data")
        if not isinstance(raw_data, list):
            raise ValueError("LiteLLM embedding response missing data")
        vectors: list[list[float]] = []
        for item in raw_data:
            if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                raise ValueError("LiteLLM embedding item missing embedding")
            vectors.append([float(value) for value in item["embedding"]])
        return vectors


def _usage_tokens(
    *,
    response_payload: dict[str, Any] | None,
    fallback_prompt_tokens: int,
    fallback_completion_tokens: int,
) -> tuple[int, int]:
    usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
    if isinstance(usage, dict):
        prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or fallback_prompt_tokens)
        completion_tokens = int(
            usage.get("completion_tokens") or usage.get("output_tokens") or fallback_completion_tokens
        )
        return prompt_tokens, completion_tokens
    return fallback_prompt_tokens, fallback_completion_tokens


def _response_cost(response_payload: dict[str, Any] | None) -> float | None:
    if not isinstance(response_payload, dict):
        return None
    candidate_paths = (
        ("usage", "cost"),
        ("usage", "total_cost"),
        ("usage", "estimated_cost"),
        ("_hidden_params", "response_cost"),
        ("response_cost",),
        ("cost",),
    )
    for path in candidate_paths:
        value: object = response_payload
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if value is None:
            continue
        try:
            return round(float(value), 6)
        except (TypeError, ValueError):
            continue
    return None


def _extract_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return str(message["content"])
            if isinstance(first_choice.get("text"), str):
                return str(first_choice["text"])
    if isinstance(payload.get("content"), str):
        return str(payload["content"])
    if isinstance(payload.get("output_text"), str):
        return str(payload["output_text"])
    raise ValueError("LiteLLM chat response missing assistant content")
