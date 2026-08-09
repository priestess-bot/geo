from dataclasses import replace
from decimal import Decimal
from email.message import Message
from http.client import IncompleteRead
from pathlib import Path
from typing import cast
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from geo_core.model_gateway.contracts import (
    ModelCallBudget,
    ModelCallBudgetExceeded,
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ModelPolicy,
    OutputSchemaDefinitionError,
    ProviderCapabilities,
    ProviderCapabilityRegistry,
    ProviderPolicyViolation,
    RetryableModelGatewayError,
    StructuredOutputValidationError,
)
from geo_core.model_gateway.deepseek import DeepSeekGateway, JsonResponse
from geo_core.model_gateway.releases import (
    AdapterRelease,
    DataUseDecision,
    ModelRelease,
    ModelReleaseRegistry,
    ModelRoute,
    ProviderDataPolicy,
    ReleaseState,
    ReportedModelPolicy,
)
from geo_core.model_gateway.router import ModelGatewayRouter


class RecordingTransport:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    def post(self, **kwargs: object) -> JsonResponse:
        self.headers = dict(cast(dict[str, str], kwargs["headers"]))
        return JsonResponse(
            body={
                "id": "provider-call-1",
                "model": "deepseek-reported",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"title":"Product review","body":"Evidence-led copy"}'
                        },
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 40, "cost_usd": "0.0042"},
            },
            headers={"X-Request-ID": "deepseek-request-1"},
        )


class IncompleteResponseTransport:
    def post(self, **kwargs: object) -> JsonResponse:
        del kwargs
        raise IncompleteRead(b"", 128)


class EmptyContentTransport:
    def post(self, **kwargs: object) -> JsonResponse:
        del kwargs
        return JsonResponse(
            body={"choices": [{"message": {"content": ""}}]},
            headers={},
        )


class InvalidJsonTransport:
    def post(self, **kwargs: object) -> JsonResponse:
        del kwargs
        return JsonResponse(
            body={"choices": [{"message": {"content": '{"title":'}}]},
            headers={},
        )


class RaisingTransport:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def post(self, **kwargs: object) -> JsonResponse:
        del kwargs
        self.calls += 1
        raise self.error


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
    assert result.provider == "deepseek"
    assert result.adapter_release_id == "deepseek-direct-v1"
    assert result.prompt_tokens == 120
    assert result.completion_tokens == 40
    assert result.cost_usd == Decimal("0.0042")
    assert result.finish_reason == "stop"
    assert len(result.response_hash) == 64
    assert transport.headers["Authorization"] == "Bearer secret-value"
    assert "secret-value" not in repr(result)


def test_deepseek_adapter_runs_through_the_exact_release_router(tmp_path: Path) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("secret-value", encoding="utf-8")
    adapter = DeepSeekGateway(
        api_key_file=key_file,
        capability_registry=registry(),
        transport=RecordingTransport(),
    )
    adapter_release = AdapterRelease(
        provider="deepseek",
        adapter_release_id="deepseek-direct-v1",
        release_hash="a" * 64,
        interface_contract_version="geo-model-gateway-v1",
        expected_capture_method=ModelCaptureMethod.PROVIDER_API,
        capabilities=registry().require("deepseek"),
        data_policy=ProviderDataPolicy(
            storage=DataUseDecision.ALLOWED,
            cache=DataUseDecision.ALLOWED,
            display=DataUseDecision.ALLOWED,
            redistribution=DataUseDecision.PROHIBITED,
            retention_days=30,
            terms_reference="https://evidence.example/deepseek/terms/2026-07-23",
            terms_sha256="c" * 64,
        ),
        state=ReleaseState.APPROVED,
        capability_evidence_reference="https://evidence.example/deepseek/capabilities/v1",
        capability_evidence_sha256="d" * 64,
    )
    model_release = ModelRelease(
        provider="deepseek",
        adapter_release_id="deepseek-direct-v1",
        model_release_id="deepseek-chat-release-v1",
        release_hash="b" * 64,
        configured_model="deepseek-chat",
        state=ReleaseState.APPROVED,
        reported_model_policy=ReportedModelPolicy.ALLOWLIST,
        allowed_reported_models=("deepseek-reported",),
    )
    route = ModelRoute(
        provider="deepseek",
        adapter_release_id="deepseek-direct-v1",
        adapter_release_hash=adapter_release.release_hash,
        model_release_id="deepseek-chat-release-v1",
        model_release_hash=model_release.release_hash,
    )
    router = ModelGatewayRouter(
        release_registry=ModelReleaseRegistry(
            adapter_releases=(adapter_release,), model_releases=(model_release,)
        ),
        adapters=(adapter,),
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "body"],
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
    }

    result = router.bind(route).generate(
        replace(
            request(),
            output_schema=schema,
            capture_method=ModelCaptureMethod.PROVIDER_API,
        ),
        policy=ModelPolicy(),
        budget=ModelCallBudget(1),
    )

    assert result.provider == "deepseek"
    assert result.adapter_release_id == "deepseek-direct-v1"
    assert result.adapter_release_hash == adapter_release.release_hash
    assert result.model_release_id == "deepseek-chat-release-v1"
    assert result.model_release_hash == model_release.release_hash


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


def test_incomplete_provider_response_is_classified_as_retryable(tmp_path: Path) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("secret-value", encoding="utf-8")
    gateway = DeepSeekGateway(
        api_key_file=key_file,
        capability_registry=registry(),
        transport=IncompleteResponseTransport(),
    )

    with pytest.raises(RetryableModelGatewayError, match="could not be completed"):
        gateway.generate(request(), policy=ModelPolicy(), budget=ModelCallBudget(1))


def test_empty_provider_content_is_classified_as_retryable(tmp_path: Path) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("secret-value", encoding="utf-8")
    gateway = DeepSeekGateway(
        api_key_file=key_file,
        capability_registry=registry(),
        transport=EmptyContentTransport(),
    )

    with pytest.raises(RetryableModelGatewayError, match="content is empty"):
        gateway.generate(request(), policy=ModelPolicy(), budget=ModelCallBudget(1))


def test_invalid_provider_json_is_classified_as_retryable(tmp_path: Path) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("secret-value", encoding="utf-8")
    gateway = DeepSeekGateway(
        api_key_file=key_file,
        capability_registry=registry(),
        transport=InvalidJsonTransport(),
    )

    with pytest.raises(RetryableModelGatewayError, match="not valid JSON"):
        gateway.generate(request(), policy=ModelPolicy(), budget=ModelCallBudget(1))


def test_deepseek_validates_frozen_schema_at_the_application_boundary(tmp_path: Path) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("secret-value", encoding="utf-8")
    transport = RecordingTransport()
    gateway = DeepSeekGateway(
        api_key_file=key_file,
        capability_registry=registry(),
        transport=transport,
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "score"],
        "properties": {
            "title": {"type": "string"},
            "score": {"type": "integer"},
        },
    }

    with pytest.raises(
        StructuredOutputValidationError, match="required property score"
    ) as captured:
        gateway.generate(
            replace(request(), output_schema=schema),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    assert captured.value.code is ModelGatewayErrorCode.SCHEMA_INVALID


def test_deepseek_rejects_invalid_schema_before_consuming_budget_or_calling_provider(
    tmp_path: Path,
) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("secret-value", encoding="utf-8")
    transport = RaisingTransport(AssertionError("provider must not be called"))
    gateway = DeepSeekGateway(
        api_key_file=key_file,
        capability_registry=registry(),
        transport=transport,
    )
    budget = ModelCallBudget(1)

    with pytest.raises(OutputSchemaDefinitionError, match="unsupported keyword"):
        gateway.generate(
            replace(request(), output_schema={"type": "object", "unknown": True}),
            policy=ModelPolicy(),
            budget=budget,
        )

    assert budget.consumed_calls == 0
    assert transport.calls == 0


@pytest.mark.parametrize(
    ("status", "error_type", "code", "retryable"),
    (
        (401, ModelGatewayError, ModelGatewayErrorCode.AUTH, False),
        (429, RetryableModelGatewayError, ModelGatewayErrorCode.RATE_LIMIT, True),
        (503, RetryableModelGatewayError, ModelGatewayErrorCode.PROVIDER_UNAVAILABLE, True),
    ),
)
def test_deepseek_http_failures_have_stable_error_classification(
    tmp_path: Path,
    status: int,
    error_type: type[ModelGatewayError],
    code: ModelGatewayErrorCode,
    retryable: bool,
) -> None:
    key_file = tmp_path / "deepseek-key"
    key_file.write_text("secret-value", encoding="utf-8")
    headers = Message()
    headers["Retry-After"] = "2"
    error = HTTPError(
        url="https://api.deepseek.test/chat/completions",
        code=status,
        msg="fixture",
        hdrs=headers,
        fp=None,
    )
    gateway = DeepSeekGateway(
        api_key_file=key_file,
        capability_registry=registry(),
        transport=RaisingTransport(error),
    )

    with pytest.raises(error_type) as captured:
        gateway.generate(request(), policy=ModelPolicy(), budget=ModelCallBudget(1))

    assert captured.value.code is code
    assert captured.value.retryable is retryable
    assert captured.value.provider == "deepseek"
    assert captured.value.status_code == status
    if status == 429:
        assert captured.value.retry_after_seconds == 2
