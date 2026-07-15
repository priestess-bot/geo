from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from geo_core.model_gateway.contracts import (
    ModelCallBudget,
    ModelCallBudgetExceeded,
    ModelGatewayRequest,
    ModelPolicy,
    ProviderCapabilities,
    ProviderCapabilityRegistry,
    ProviderPolicyViolation,
)
from geo_core.model_gateway.deepseek import DeepSeekGateway, JsonResponse


class RecordingTransport:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    def post(self, **kwargs: object) -> JsonResponse:
        self.headers = dict(kwargs["headers"])  # type: ignore[arg-type]
        return JsonResponse(
            body={
                "id": "provider-call-1",
                "model": "deepseek-reported",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"title":"Product review","body":"Evidence-led copy"}'},
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 40, "cost_usd": "0.0042"},
            },
            headers={"x-request-id": "deepseek-request-1"},
        )


def registry(*, external_training_allowed: bool = False) -> ProviderCapabilityRegistry:
    return ProviderCapabilityRegistry(
        (
            ProviderCapabilities(
                provider="deepseek",
                external_training_allowed=external_training_allowed,
                structured_output=True,
                data_retention_days=None,
                policy_reference="contract:test",
            ),
        )
    )


def request() -> ModelGatewayRequest:
    return ModelGatewayRequest(
        messages=({"role": "user", "content": "Generate one placement package."},),
        configured_model="deepseek-chat",
        prompt_bundle_hash="a" * 64,
        project_id=uuid4(),
        purpose="placement_generation",
    )


def test_deepseek_gateway_returns_complete_result_and_never_exposes_key(tmp_path: Path) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("secret-value", encoding="utf-8")
    transport = RecordingTransport()
    gateway = DeepSeekGateway(
        api_key_file=key_file,
        capability_registry=registry(),
        transport=transport,
    )

    result = gateway.generate(request(), policy=ModelPolicy(), budget=ModelCallBudget(1))

    assert result.output["body"] == "Evidence-led copy"
    assert result.provider_request_id == "deepseek-request-1"
    assert result.configured_model == "deepseek-chat"
    assert result.provider_reported_model == "deepseek-reported"
    assert result.prompt_tokens == 120
    assert result.completion_tokens == 40
    assert result.cost_usd == Decimal("0.0042")
    assert result.finish_reason == "stop"
    assert len(result.response_hash) == 64
    assert transport.headers["Authorization"] == "Bearer secret-value"
    assert "secret-value" not in repr(result)


def test_job_wide_budget_includes_every_gateway_attempt(tmp_path: Path) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("secret-value", encoding="utf-8")
    gateway = DeepSeekGateway(
        api_key_file=key_file,
        capability_registry=registry(),
        transport=RecordingTransport(),
    )
    budget = ModelCallBudget(1)

    gateway.generate(request(), policy=ModelPolicy(), budget=budget)
    with pytest.raises(ModelCallBudgetExceeded):
        gateway.generate(request(), policy=ModelPolicy(), budget=budget)


def test_provider_policy_must_be_registered_and_proven_before_call(tmp_path: Path) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("secret-value", encoding="utf-8")
    gateway = DeepSeekGateway(
        api_key_file=key_file,
        capability_registry=registry(external_training_allowed=True),
        transport=RecordingTransport(),
    )

    with pytest.raises(ProviderPolicyViolation, match="external-training"):
        gateway.generate(request(), policy=ModelPolicy(), budget=ModelCallBudget(1))
