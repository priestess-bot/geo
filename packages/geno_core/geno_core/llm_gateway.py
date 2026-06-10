from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import NAMESPACE_URL, uuid5

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
