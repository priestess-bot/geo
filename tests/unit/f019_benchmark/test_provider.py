from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from benchmarks.f019 import provider
from benchmarks.f019.provider import DeepSeekJsonInvoker
from geo_core.model_gateway import ModelGatewayResult, RetryableModelGatewayError
from geo_core.model_gateway.contracts import ModelGatewayError


def test_retryable_provider_response_is_retried_and_fully_metered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("not-used", encoding="utf-8")
    invoker = DeepSeekJsonInvoker(key_file=key_file)
    attempts = 0

    def generate(request, *, policy, budget):
        del request, policy
        nonlocal attempts
        attempts += 1
        budget.consume()
        if attempts == 1:
            invoker._transport._local.snapshot = provider._response_snapshot(
                {
                    "model": "deepseek-v4-flash",
                    "choices": [{"finish_reason": "stop", "message": {"content": "{"}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 7},
                }
            )
            raise RetryableModelGatewayError("invalid structured output")
        return ModelGatewayResult(
            output={"facts": [], "entities": [], "relations": []},
            call_log_id=uuid4(),
            provider_request_id="request-2",
            configured_model="deepseek-v4-flash",
            provider_reported_model="deepseek-v4-flash",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=None,
            finish_reason="stop",
            response_hash="b" * 64,
        )

    monkeypatch.setattr(invoker._gateway, "generate", generate)
    monkeypatch.setattr(provider.time, "sleep", lambda _seconds: None)

    output = invoker.complete_json(
        project_id="project-1",
        purpose="test",
        messages=({"role": "user", "content": "test"},),
        request_hash="a" * 64,
        max_output_tokens=100,
    )

    assert output == {"facts": [], "entities": [], "relations": []}
    assert invoker.usage_totals() == {
        "input_tokens": 30,
        "output_tokens": 12,
        "model_calls": 2,
        "estimated_cost_usd": float(
            provider._estimated_cost(20, 7) + provider._estimated_cost(10, 5)
        ),
    }
    evidence = invoker.usage_evidence()
    assert evidence["measurement_complete"] is True
    assert [item["status"] for item in evidence["calls"]] == [
        "retryable_failure",
        "succeeded",
    ]
    assert evidence["calls"][0]["retry_reason"] == "RetryableModelGatewayError"


def test_nonretryable_provider_error_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("not-used", encoding="utf-8")
    invoker = DeepSeekJsonInvoker(key_file=key_file)
    attempts = 0

    def generate(request, *, policy, budget):
        del request, policy
        nonlocal attempts
        attempts += 1
        budget.consume()
        raise ModelGatewayError("policy failure")

    monkeypatch.setattr(invoker._gateway, "generate", generate)

    with pytest.raises(ModelGatewayError, match="policy failure"):
        invoker.complete_json(
            project_id="project-1",
            purpose="test",
            messages=({"role": "user", "content": "test"},),
            request_hash="a" * 64,
            max_output_tokens=100,
        )

    assert attempts == 1
    evidence = invoker.usage_evidence()
    assert evidence["measurement_complete"] is False
    assert evidence["calls"][0]["status"] == "nonretryable_failure"
    assert evidence["calls"][0]["retry_reason"] is None
