"""Stable model invocation contracts owned by the application layer."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID


class ModelGatewayError(RuntimeError):
    """Base error for policy, budget, configuration, and provider failures."""


class RetryableModelGatewayError(ModelGatewayError):
    """Transient network, throttling, or provider availability failure."""


class ModelCallBudgetExceeded(ModelGatewayError):
    """Raised before a call would exceed the job-wide paid call budget."""


class ProviderPolicyViolation(ModelGatewayError):
    """Raised when a provider cannot prove the requested data policy."""


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    external_training_allowed: bool
    structured_output: bool
    data_retention_days: int | None
    policy_reference: str


class ProviderCapabilityRegistry:
    def __init__(self, capabilities: tuple[ProviderCapabilities, ...]) -> None:
        self._capabilities = {item.provider: item for item in capabilities}

    def require(self, provider: str) -> ProviderCapabilities:
        try:
            return self._capabilities[provider]
        except KeyError as exc:
            raise ProviderPolicyViolation(
                f"provider capabilities are not registered: {provider}"
            ) from exc


@dataclass(frozen=True)
class ModelPolicy:
    external_training_allowed: bool = False
    structured_output_required: bool = True

    def validate(self, capabilities: ProviderCapabilities) -> None:
        if not self.external_training_allowed and capabilities.external_training_allowed:
            raise ProviderPolicyViolation(
                f"provider {capabilities.provider} does not satisfy external-training policy"
            )
        if self.structured_output_required and not capabilities.structured_output:
            raise ProviderPolicyViolation(
                f"provider {capabilities.provider} does not support structured output"
            )


@dataclass
class ModelCallBudget:
    """One budget shared by initial calls, repairs, retries, and fallback providers."""

    maximum_calls: int
    consumed_calls: int = 0

    def consume(self) -> int:
        if self.maximum_calls < 1 or self.consumed_calls >= self.maximum_calls:
            raise ModelCallBudgetExceeded("model call budget exhausted")
        self.consumed_calls += 1
        return self.consumed_calls


@dataclass(frozen=True)
class ModelGatewayRequest:
    messages: tuple[dict[str, str], ...]
    configured_model: str
    prompt_bundle_hash: str
    project_id: UUID
    purpose: str
    temperature: float = 0.2
    max_output_tokens: int = 4096


@dataclass(frozen=True)
class ModelGatewayResult:
    output: dict[str, object]
    call_log_id: UUID
    provider_request_id: str | None
    configured_model: str
    provider_reported_model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: Decimal | None
    finish_reason: str | None
    response_hash: str


class ModelGateway(Protocol):
    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult: ...
