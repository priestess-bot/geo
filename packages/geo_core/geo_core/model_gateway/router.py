"""Exact-release model routing with no implicit provider fallback."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from geo_core.model_gateway.contracts import (
    ModelCallBudget,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelIdentityError,
    ModelPolicy,
    ModelRouteError,
    OutputSchemaDefinitionError,
    ProviderCapabilities,
    ProviderPolicyViolation,
)
from geo_core.model_gateway.releases import (
    AdapterRelease,
    DataUseDecision,
    ModelRelease,
    ModelReleaseRegistry,
    ModelRoute,
    ReportedModelPolicy,
)
from geo_core.model_gateway.schema_validation import (
    validate_output_schema_definition,
    validate_structured_output,
)


class ProviderAdapter(Protocol):
    provider: str
    adapter_release_id: str

    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult: ...


class ModelGatewayRouter:
    """Route a call to exactly one frozen adapter and model release."""

    def __init__(
        self,
        *,
        release_registry: ModelReleaseRegistry,
        adapters: tuple[ProviderAdapter, ...],
    ) -> None:
        self.release_registry = release_registry
        self._adapters: dict[tuple[str, str], ProviderAdapter] = {}
        for adapter in adapters:
            key = (adapter.provider, adapter.adapter_release_id)
            if key in self._adapters:
                raise ModelRouteError(f"duplicate provider adapter binding: {key}")
            self._adapters[key] = adapter

    def bind(self, route: ModelRoute) -> BoundModelGateway:
        """Expose an exact route through the legacy ``ModelGateway`` protocol."""

        self.release_registry.resolve(route)
        self._require_adapter(route)
        return BoundModelGateway(router=self, route=route)

    def generate(
        self,
        route: ModelRoute,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        adapter_release, model_release = self.release_registry.resolve(route)
        if request.configured_model != model_release.configured_model:
            raise ModelIdentityError(
                "request configured model does not match the frozen model release",
                provider=route.provider,
            )
        if request.capture_method is not adapter_release.expected_capture_method:
            raise ModelIdentityError(
                "request capture method does not match the frozen Adapter Release",
                provider=route.provider,
            )
        policy.validate(
            adapter_release.capabilities,
            adapter_release_id=adapter_release.adapter_release_id,
        )
        _validate_request_capabilities(request, adapter_release.capabilities)
        if policy.structured_output_required and request.output_schema is None:
            raise OutputSchemaDefinitionError(
                "a frozen output schema is required for routed structured output",
                provider=route.provider,
            )
        if request.output_schema is not None:
            try:
                validate_output_schema_definition(request.output_schema)
            except OutputSchemaDefinitionError as exc:
                exc.provider = route.provider
                raise
        _validate_deadline(request, provider=route.provider)
        adapter = self._require_adapter(route)
        try:
            result = adapter.generate(request, policy=policy, budget=budget)
        except ModelGatewayError:
            raise
        except Exception as exc:
            raise ModelGatewayError(
                "provider adapter raised an unclassified failure",
                code=ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION,
                provider=route.provider,
            ) from exc
        _validate_result_identity(
            result,
            route=route,
            adapter_release=adapter_release,
            model_release=model_release,
        )
        if request.output_schema is not None:
            try:
                validate_structured_output(result.output, request.output_schema)
            except ModelGatewayError as exc:
                exc.provider = route.provider
                raise
        if (
            adapter_release.data_policy.storage is DataUseDecision.PROHIBITED
            and (
                result.raw_artifact_reference is not None
                or result.derived_artifact_reference is not None
            )
        ):
            raise ProviderPolicyViolation(
                "provider data policy prohibits raw response persistence",
                provider=route.provider,
            )
        return replace(
            result,
            provider=route.provider,
            adapter_release_id=route.adapter_release_id,
            adapter_release_hash=route.adapter_release_hash,
            model_release_id=route.model_release_id,
            model_release_hash=route.model_release_hash,
            raw_artifact_policy_hash=adapter_release.data_policy_hash,
            raw_artifact_storage_decision=adapter_release.data_policy.storage.value,
            raw_artifact_cache_decision=adapter_release.data_policy.cache.value,
            raw_artifact_display_decision=adapter_release.data_policy.display.value,
            raw_artifact_redistribution_decision=(
                adapter_release.data_policy.redistribution.value
            ),
            raw_artifact_retention_days=adapter_release.data_policy.retention_days,
            usage_purpose=request.purpose,
            usage_audience=request.usage_audience,
        )

    def _require_adapter(self, route: ModelRoute) -> ProviderAdapter:
        key = (route.provider, route.adapter_release_id)
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise ModelRouteError(
                f"provider adapter is not bound: {route.provider}/{route.adapter_release_id}"
            ) from exc


class BoundModelGateway:
    """Compatibility facade carrying an immutable route for existing workers."""

    def __init__(self, *, router: ModelGatewayRouter, route: ModelRoute) -> None:
        self._router = router
        self.route = route
        self.provider = route.provider
        self.adapter_release_id = route.adapter_release_id
        self.adapter_release_hash = route.adapter_release_hash
        self.model_release_id = route.model_release_id
        self.model_release_hash = route.model_release_hash

    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        return self._router.generate(self.route, request, policy=policy, budget=budget)


def _validate_request_capabilities(
    request: ModelGatewayRequest, capabilities: ProviderCapabilities
) -> None:
    if request.seed is not None and not capabilities.supports_seed:
        raise ProviderPolicyViolation(
            "adapter release does not support a seed", provider=capabilities.provider
        )
    if request.tool_mode is not None and not capabilities.supports_tools:
        raise ProviderPolicyViolation(
            "adapter release does not support tool mode", provider=capabilities.provider
        )
    if request.search_mode not in (None, "disabled") and not capabilities.supports_search:
        raise ProviderPolicyViolation(
            "adapter release does not support search mode", provider=capabilities.provider
        )
    if request.idempotency_key is not None and not capabilities.supports_idempotency:
        raise ProviderPolicyViolation(
            "adapter release does not support provider idempotency",
            provider=capabilities.provider,
        )


def _validate_deadline(request: ModelGatewayRequest, *, provider: str) -> None:
    if request.deadline_at is None:
        return
    if request.deadline_at.tzinfo is None:
        raise ModelRouteError("model request deadline must be timezone-aware", provider=provider)
    if request.deadline_at <= datetime.now(UTC):
        raise ModelGatewayError(
            "model request deadline has already elapsed",
            code=ModelGatewayErrorCode.CANCELLED,
            provider=provider,
        )


def _validate_result_identity(
    result: ModelGatewayResult,
    *,
    route: ModelRoute,
    adapter_release: AdapterRelease,
    model_release: ModelRelease,
) -> None:
    if result.provider is not None and result.provider != route.provider:
        raise ModelIdentityError("provider result identity does not match the frozen route")
    if (
        result.adapter_release_id is not None
        and result.adapter_release_id != route.adapter_release_id
    ):
        raise ModelIdentityError("adapter result identity does not match the frozen route")
    if (
        result.adapter_release_hash is not None
        and result.adapter_release_hash != route.adapter_release_hash
    ):
        raise ModelIdentityError("adapter result hash does not match the frozen route")
    if result.model_release_id is not None and result.model_release_id != route.model_release_id:
        raise ModelIdentityError("model result release does not match the frozen route")
    if (
        result.model_release_hash is not None
        and result.model_release_hash != route.model_release_hash
    ):
        raise ModelIdentityError("model result hash does not match the frozen route")
    if result.configured_model != model_release.configured_model:
        raise ModelIdentityError("provider result changed the configured model identity")
    if result.capture_method is not adapter_release.expected_capture_method:
        raise ModelIdentityError("provider result changed the frozen capture method")
    reported = result.provider_reported_model
    reported_policy = model_release.reported_model_policy
    if reported_policy is ReportedModelPolicy.RECORD_ONLY:
        return
    if reported is None:
        raise ModelIdentityError("provider did not report a model identity")
    if reported_policy is ReportedModelPolicy.REQUIRE_PRESENT:
        return
    if reported_policy is ReportedModelPolicy.EXACT and reported != model_release.configured_model:
        raise ModelIdentityError("provider-reported model does not match the configured model")
    if (
        reported_policy is ReportedModelPolicy.ALLOWLIST
        and reported not in model_release.allowed_reported_models
    ):
        raise ModelIdentityError("provider-reported model is outside the frozen allowlist")
