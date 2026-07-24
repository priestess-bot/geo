"""Stable model invocation contracts owned by the application layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from typing import Mapping, Protocol
from uuid import UUID

from geo_core.secrets.models import SecretVersionHandle
from geo_core.model_gateway.location import (
    EffectiveModelLocation,
    RequestedModelLocation,
)


class ModelGatewayErrorCode(StrEnum):
    """Stable failure classes consumed by retry and audit policy."""

    AUTH = "auth"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    SCHEMA_INVALID = "schema_invalid"
    CONTENT_REFUSAL = "content_refusal"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CANCELLED = "cancelled"
    NON_RETRYABLE_VALIDATION = "non_retryable_validation"
    CONFIGURATION = "configuration"
    POLICY = "policy"
    BUDGET_EXCEEDED = "budget_exceeded"
    CONCURRENCY_LIMIT = "concurrency_limit"


class ModelCaptureMethod(StrEnum):
    """Provider-facing sampling identities; consumer UI is intentionally absent."""

    PROVIDER_API = "provider_api"
    PROXY_GROUNDED_API = "proxy_grounded_api"


class ModelAudience(StrEnum):
    INTERNAL_WORKER = "internal_worker"
    ADMIN = "admin"
    CUSTOMER = "customer"
    EXPORT = "export"


class ModelGatewayError(RuntimeError):
    """Base error for policy, budget, configuration, and provider failures."""

    default_code = ModelGatewayErrorCode.CONFIGURATION
    default_retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: ModelGatewayErrorCode | None = None,
        provider: str | None = None,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.default_code
        self.retryable = self.default_retryable
        self.provider = provider
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


class RetryableModelGatewayError(ModelGatewayError):
    """Transient network, throttling, or provider availability failure."""

    default_code = ModelGatewayErrorCode.PROVIDER_UNAVAILABLE
    default_retryable = True


class ModelCallBudgetExceeded(ModelGatewayError):
    """Raised before a call would exceed the job-wide paid call budget."""

    default_code = ModelGatewayErrorCode.BUDGET_EXCEEDED


class ModelCallConcurrencyExceeded(ModelGatewayError):
    """Raised before I/O when unresolved calls occupy the frozen concurrency budget."""

    default_code = ModelGatewayErrorCode.CONCURRENCY_LIMIT


class ProviderPolicyViolation(ModelGatewayError):
    """Raised when a provider cannot prove the requested data policy."""

    default_code = ModelGatewayErrorCode.POLICY


class ModelRouteError(ModelGatewayError):
    """Raised before I/O when an exact provider or release cannot be resolved."""


class OutputSchemaDefinitionError(ModelGatewayError):
    """The caller supplied an invalid or unsupported JSON Schema."""

    default_code = ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION


class StructuredOutputValidationError(RetryableModelGatewayError):
    """A provider payload did not satisfy the frozen application schema."""

    default_code = ModelGatewayErrorCode.SCHEMA_INVALID


class ModelIdentityError(ModelGatewayError):
    """Configured, routed, and provider-reported model identities conflict."""

    default_code = ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION


def provider_http_error(
    *,
    provider: str,
    status_code: int,
    message: str,
    retry_after_seconds: float | None = None,
) -> ModelGatewayError:
    """Normalize HTTP failures identically across provider adapters."""

    if status_code in (401, 403):
        code = ModelGatewayErrorCode.AUTH
        retryable = False
    elif status_code == 402:
        code = ModelGatewayErrorCode.QUOTA
        retryable = False
    elif status_code in (408, 504):
        code = ModelGatewayErrorCode.TIMEOUT
        retryable = True
    elif status_code == 429:
        code = ModelGatewayErrorCode.RATE_LIMIT
        retryable = True
    elif 500 <= status_code < 600:
        code = ModelGatewayErrorCode.PROVIDER_UNAVAILABLE
        retryable = True
    elif 400 <= status_code < 500:
        code = ModelGatewayErrorCode.POLICY
        retryable = False
    else:
        code = ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION
        retryable = False
    error_type = RetryableModelGatewayError if retryable else ModelGatewayError
    return error_type(
        message,
        code=code,
        provider=provider,
        status_code=status_code,
        retry_after_seconds=retry_after_seconds if retryable else None,
    )


class CapabilityVerification(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    external_training_allowed: bool
    structured_output: bool
    data_retention_days: int | None
    policy_reference: str
    supports_seed: bool = False
    supports_tools: bool = False
    supports_search: bool = False
    supports_citations: bool = False
    supports_idempotency: bool = False
    supports_structured_output_with_tools: bool = False
    verification: CapabilityVerification = CapabilityVerification.VERIFIED

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ProviderPolicyViolation("provider capability name cannot be empty")
        if self.data_retention_days is not None and self.data_retention_days < 0:
            raise ProviderPolicyViolation("provider data retention cannot be negative")
        if not self.policy_reference.strip():
            raise ProviderPolicyViolation("provider capability policy reference cannot be empty")


class ProviderCapabilityRegistry:
    def __init__(self, capabilities: tuple[ProviderCapabilities, ...]) -> None:
        self._capabilities: dict[str, ProviderCapabilities] = {}
        for item in capabilities:
            if item.provider in self._capabilities:
                raise ProviderPolicyViolation(
                    f"provider capabilities are duplicated: {item.provider}"
                )
            self._capabilities[item.provider] = item

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
    allowed_providers: frozenset[str] | None = None
    allowed_adapter_release_ids: frozenset[str] | None = None
    policy_version_id: UUID | None = None
    maximum_paid_calls: int | None = None
    maximum_concurrent_calls: int | None = None
    policy_version_hash: str | None = field(init=False)

    def __post_init__(self) -> None:
        versioned = self.policy_version_id is not None
        has_paid_limit = self.maximum_paid_calls is not None
        has_concurrency_limit = self.maximum_concurrent_calls is not None
        if versioned != has_paid_limit or versioned != has_concurrency_limit:
            raise ProviderPolicyViolation(
                "versioned model policy requires paid-call and concurrency limits"
            )
        if self.policy_version_id is not None and self.policy_version_id.int == 0:
            raise ProviderPolicyViolation("model policy version ID cannot be zero")
        for value, label in (
            (self.maximum_paid_calls, "paid-call"),
            (self.maximum_concurrent_calls, "concurrency"),
        ):
            if value is not None and value < 1:
                raise ProviderPolicyViolation(f"model policy {label} limit must be positive")
        for values, label in (
            (self.allowed_providers, "provider"),
            (self.allowed_adapter_release_ids, "Adapter Release"),
        ):
            if values is not None and (not values or any(not item.strip() for item in values)):
                raise ProviderPolicyViolation(
                    f"model policy {label} allowlist must be non-empty and explicit"
                )
        policy_hash = _canonical_hash(self.canonical_value()) if versioned else None
        object.__setattr__(self, "policy_version_hash", policy_hash)

    @property
    def versioned(self) -> bool:
        return self.policy_version_id is not None

    def canonical_value(self) -> dict[str, object]:
        return {
            "external_training_allowed": self.external_training_allowed,
            "structured_output_required": self.structured_output_required,
            "allowed_providers": (
                sorted(self.allowed_providers) if self.allowed_providers is not None else None
            ),
            "allowed_adapter_release_ids": (
                sorted(self.allowed_adapter_release_ids)
                if self.allowed_adapter_release_ids is not None
                else None
            ),
            "maximum_paid_calls": self.maximum_paid_calls,
            "maximum_concurrent_calls": self.maximum_concurrent_calls,
        }

    def validate(
        self,
        capabilities: ProviderCapabilities,
        *,
        adapter_release_id: str | None = None,
    ) -> None:
        if capabilities.verification is not CapabilityVerification.VERIFIED:
            raise ProviderPolicyViolation(
                f"provider {capabilities.provider} capabilities are not verified"
            )
        if (
            self.allowed_providers is not None
            and capabilities.provider not in self.allowed_providers
        ):
            raise ProviderPolicyViolation(
                f"provider {capabilities.provider} is not allowed by the frozen policy"
            )
        if (
            self.allowed_adapter_release_ids is not None
            and adapter_release_id not in self.allowed_adapter_release_ids
        ):
            raise ProviderPolicyViolation(
                f"adapter release {adapter_release_id or '<missing>'} is not allowed by the frozen policy"
            )
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
    """One budget shared by initial calls, repairs, retries, and explicit alternate routes."""

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
    usage_audience: ModelAudience = ModelAudience.INTERNAL_WORKER
    temperature: float = 0.2
    max_output_tokens: int = 4096
    output_schema: Mapping[str, object] | None = None
    application_output_schema: Mapping[str, object] | None = None
    seed: int | None = None
    tool_mode: str | None = None
    search_mode: str | None = None
    deadline_at: datetime | None = None
    idempotency_key: str | None = None
    capture_method: ModelCaptureMethod | None = None
    provider_secret_handle: SecretVersionHandle | None = None
    model_call_job_id: UUID | None = None
    model_call_attempt_id: UUID | None = None
    requested_location: RequestedModelLocation | None = None
    expected_effective_location: EffectiveModelLocation | None = None

    def __post_init__(self) -> None:
        if (self.requested_location is None) != (
            self.expected_effective_location is None
        ):
            raise ValueError(
                "model location request and expected effective location must be paired"
            )


@dataclass(frozen=True)
class ModelIdentity:
    provider: str | None
    adapter_release_id: str | None
    adapter_release_hash: str | None
    model_release_id: str | None
    model_release_hash: str | None
    configured_model: str
    provider_reported_model: str | None


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
    provider: str | None = None
    adapter_release_id: str | None = None
    adapter_release_hash: str | None = None
    model_release_id: str | None = None
    model_release_hash: str | None = None
    latency_ms: int | None = None
    citations: tuple[Mapping[str, object], ...] = ()
    tool_events: tuple[Mapping[str, object], ...] = ()
    raw_artifact_reference: str | None = None
    raw_artifact_manifest_hash: str | None = None
    raw_artifact_content_hash: str | None = None
    raw_artifact_byte_size: int | None = None
    derived_artifact_reference: str | None = None
    derived_artifact_manifest_hash: str | None = None
    derived_artifact_content_hash: str | None = None
    derived_artifact_byte_size: int | None = None
    raw_artifact_policy_hash: str | None = None
    raw_artifact_storage_decision: str | None = None
    raw_artifact_cache_decision: str | None = None
    raw_artifact_display_decision: str | None = None
    raw_artifact_redistribution_decision: str | None = None
    raw_artifact_retention_days: int | None = None
    usage_purpose: str | None = None
    usage_audience: ModelAudience | None = None
    capture_method: ModelCaptureMethod | None = None
    search_mode: str | None = None
    usage_details: Mapping[str, object] | None = None
    requested_location: RequestedModelLocation | None = None
    effective_location: EffectiveModelLocation | None = None

    @property
    def identity(self) -> ModelIdentity:
        return ModelIdentity(
            provider=self.provider,
            adapter_release_id=self.adapter_release_id,
            adapter_release_hash=self.adapter_release_hash,
            model_release_id=self.model_release_id,
            model_release_hash=self.model_release_hash,
            configured_model=self.configured_model,
            provider_reported_model=self.provider_reported_model,
        )


class ModelGateway(Protocol):
    provider: str

    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult: ...


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
