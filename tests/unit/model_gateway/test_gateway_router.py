from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
import hashlib
from uuid import uuid4

import pytest

from geo_core.model_gateway import (
    KNOWN_MODEL_PROVIDERS,
    AdapterRelease,
    CapabilityVerification,
    DataUseDecision,
    ModelCallBudget,
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelGatewayRouter,
    ModelIdentityError,
    ModelPolicy,
    ModelRelease,
    ModelReleaseRegistry,
    ModelRoute,
    ModelRouteError,
    OutputSchemaDefinitionError,
    ProviderCapabilities,
    ProviderDataPolicy,
    ProviderPolicyViolation,
    ReleaseState,
    ReportedModelPolicy,
    RetryableModelGatewayError,
    StructuredOutputValidationError,
    draft_provider_adapter_releases,
)


OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "score"],
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "score": {"type": "integer", "minimum": 0, "maximum": 5},
    },
}


@dataclass
class RecordedAdapter:
    provider: str
    adapter_release_id: str
    output: dict[str, object]
    reported_model: str | None
    failure: Exception | None = None
    raw_artifact_reference: str | None = None
    calls: int = 0

    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        del policy
        self.calls += 1
        budget.consume()
        if self.failure is not None:
            raise self.failure
        return ModelGatewayResult(
            output=self.output,
            call_log_id=uuid4(),
            provider_request_id=f"{self.provider}-request-1",
            configured_model=request.configured_model,
            provider_reported_model=self.reported_model,
            prompt_tokens=12,
            completion_tokens=5,
            cost_usd=Decimal("0.001"),
            finish_reason="stop",
            response_hash="f" * 64,
            raw_artifact_reference=self.raw_artifact_reference,
            capture_method=request.capture_method,
        )


def _release_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _adapter_release(
    provider: str,
    *,
    storage: DataUseDecision = DataUseDecision.ALLOWED,
    capabilities: ProviderCapabilities | None = None,
) -> AdapterRelease:
    release_id = f"{provider}-adapter-v1"
    return AdapterRelease(
        provider=provider,
        adapter_release_id=release_id,
        release_hash=_release_hash(f"adapter:{provider}"),
        interface_contract_version="geo-model-gateway-v1",
        expected_capture_method=(
            ModelCaptureMethod.PROXY_GROUNDED_API
            if provider == "microsoft"
            else ModelCaptureMethod.PROVIDER_API
        ),
        capabilities=capabilities
        or ProviderCapabilities(
            provider=provider,
            external_training_allowed=False,
            structured_output=True,
            data_retention_days=30,
            policy_reference=f"fixture-policy:{provider}",
        ),
        data_policy=ProviderDataPolicy(
            storage=storage,
            cache=DataUseDecision.ALLOWED,
            display=DataUseDecision.ALLOWED,
            redistribution=DataUseDecision.PROHIBITED,
            retention_days=30,
            terms_reference=f"https://evidence.example/{provider}/terms/2026-07-23",
            terms_sha256="a" * 64,
        ),
        state=ReleaseState.APPROVED,
        capability_evidence_reference=(
            f"https://evidence.example/{provider}/capabilities/v1"
        ),
        capability_evidence_sha256="b" * 64,
    )


def _model_release(
    provider: str,
    *,
    reported_policy: ReportedModelPolicy = ReportedModelPolicy.EXACT,
    allowed_reported_models: tuple[str, ...] = (),
) -> ModelRelease:
    return ModelRelease(
        provider=provider,
        adapter_release_id=f"{provider}-adapter-v1",
        model_release_id=f"{provider}-model-release-v1",
        release_hash=_release_hash(f"model:{provider}"),
        configured_model=f"{provider}-model",
        state=ReleaseState.APPROVED,
        reported_model_policy=reported_policy,
        allowed_reported_models=allowed_reported_models,
    )


def _request(
    provider: str, *, output_schema: dict[str, object] | None = None
) -> ModelGatewayRequest:
    return ModelGatewayRequest(
        messages=({"role": "user", "content": "Return a structured evaluation."},),
        configured_model=f"{provider}-model",
        prompt_bundle_hash="a" * 64,
        project_id=uuid4(),
        purpose="metric_judge",
        output_schema=output_schema or OUTPUT_SCHEMA,
        capture_method=(
            ModelCaptureMethod.PROXY_GROUNDED_API
            if provider == "microsoft"
            else ModelCaptureMethod.PROVIDER_API
        ),
    )


def _route(provider: str) -> ModelRoute:
    return ModelRoute(
        provider=provider,
        adapter_release_id=f"{provider}-adapter-v1",
        adapter_release_hash=_release_hash(f"adapter:{provider}"),
        model_release_id=f"{provider}-model-release-v1",
        model_release_hash=_release_hash(f"model:{provider}"),
    )


def _router(
    provider: str,
    adapter: RecordedAdapter,
    *,
    adapter_release: AdapterRelease | None = None,
    model_release: ModelRelease | None = None,
) -> ModelGatewayRouter:
    return ModelGatewayRouter(
        release_registry=ModelReleaseRegistry(
            adapter_releases=(adapter_release or _adapter_release(provider),),
            model_releases=(model_release or _model_release(provider),),
        ),
        adapters=(adapter,),
    )


@pytest.mark.parametrize("provider", KNOWN_MODEL_PROVIDERS)
def test_each_provider_contract_routes_only_an_explicit_approved_release(provider: str) -> None:
    adapter = RecordedAdapter(
        provider=provider,
        adapter_release_id=f"{provider}-adapter-v1",
        output={"answer": "evidence-led", "score": 5},
        reported_model=f"{provider}-model",
    )
    router = _router(provider, adapter)
    policy = ModelPolicy(
        allowed_providers=frozenset({provider}),
        allowed_adapter_release_ids=frozenset({f"{provider}-adapter-v1"}),
    )

    result = router.bind(_route(provider)).generate(
        _request(provider), policy=policy, budget=ModelCallBudget(1)
    )

    assert adapter.calls == 1
    assert result.identity.provider == provider
    assert result.identity.adapter_release_id == f"{provider}-adapter-v1"
    assert result.identity.adapter_release_hash == _release_hash(f"adapter:{provider}")
    assert result.identity.model_release_id == f"{provider}-model-release-v1"
    assert result.identity.model_release_hash == _release_hash(f"model:{provider}")
    assert result.identity.configured_model == f"{provider}-model"
    assert result.identity.provider_reported_model == f"{provider}-model"
    expected_policy = _adapter_release(provider).data_policy
    assert result.raw_artifact_policy_hash == expected_policy.data_policy_hash
    assert result.raw_artifact_storage_decision == expected_policy.storage.value
    assert result.raw_artifact_retention_days == expected_policy.retention_days


def test_catalog_templates_cover_every_provider_but_cannot_be_routed_as_live() -> None:
    templates = draft_provider_adapter_releases()

    assert tuple(release.provider for release in templates) == KNOWN_MODEL_PROVIDERS
    assert all(release.state is ReleaseState.DRAFT for release in templates)
    assert all(
        release.capabilities.verification is CapabilityVerification.UNVERIFIED
        for release in templates
    )
    assert all(not release.data_policy.verified for release in templates)

    template = templates[1]
    model = ModelRelease(
        provider=template.provider,
        adapter_release_id=template.adapter_release_id,
        model_release_id="fixture-model-v1",
        release_hash="1" * 64,
        configured_model="fixture-model",
        state=ReleaseState.APPROVED,
    )
    registry = ModelReleaseRegistry(adapter_releases=(template,), model_releases=(model,))
    with pytest.raises(ModelRouteError, match="adapter release is not approved"):
        registry.resolve(
            ModelRoute(
                provider=template.provider,
                adapter_release_id=template.adapter_release_id,
                adapter_release_hash=template.release_hash,
                model_release_id=model.model_release_id,
                model_release_hash=model.release_hash,
            )
        )


def test_approved_release_requires_verified_capabilities_and_provider_terms() -> None:
    capabilities = ProviderCapabilities(
        provider="openai",
        external_training_allowed=False,
        structured_output=True,
        data_retention_days=None,
        policy_reference="unverified",
        verification=CapabilityVerification.UNVERIFIED,
    )
    with pytest.raises(ProviderPolicyViolation, match="unverified capabilities"):
        _adapter_release("openai", capabilities=capabilities)

    with pytest.raises(ProviderPolicyViolation, match="unresolved data terms"):
        AdapterRelease(
            provider="openai",
            adapter_release_id="openai-adapter-v1",
            release_hash="a" * 64,
            interface_contract_version="geo-model-gateway-v1",
            expected_capture_method=ModelCaptureMethod.PROVIDER_API,
            capabilities=ProviderCapabilities(
                provider="openai",
                external_training_allowed=False,
                structured_output=True,
                data_retention_days=None,
                policy_reference="fixture-policy",
            ),
            data_policy=ProviderDataPolicy(
                storage=DataUseDecision.UNVERIFIED,
                cache=DataUseDecision.UNVERIFIED,
                display=DataUseDecision.UNVERIFIED,
                redistribution=DataUseDecision.UNVERIFIED,
                retention_days=None,
                terms_reference="",
            ),
            state=ReleaseState.APPROVED,
            capability_evidence_reference="https://evidence.example/provider/capabilities/v1",
            capability_evidence_sha256="c" * 64,
        )


def test_retryable_failure_does_not_fall_back_to_another_bound_provider() -> None:
    first = RecordedAdapter(
        provider="openai",
        adapter_release_id="openai-adapter-v1",
        output={},
        reported_model=None,
        failure=RetryableModelGatewayError("rate limited", code=ModelGatewayErrorCode.RATE_LIMIT),
    )
    second = RecordedAdapter(
        provider="gemini",
        adapter_release_id="gemini-adapter-v1",
        output={"answer": "fallback", "score": 5},
        reported_model="gemini-model",
    )
    router = ModelGatewayRouter(
        release_registry=ModelReleaseRegistry(
            adapter_releases=(_adapter_release("openai"), _adapter_release("gemini")),
            model_releases=(_model_release("openai"), _model_release("gemini")),
        ),
        adapters=(first, second),
    )

    with pytest.raises(RetryableModelGatewayError) as captured:
        router.generate(
            _route("openai"),
            _request("openai"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(2),
        )

    assert captured.value.code is ModelGatewayErrorCode.RATE_LIMIT
    assert first.calls == 1
    assert second.calls == 0


def test_invalid_schema_fails_before_budget_or_provider_call() -> None:
    adapter = RecordedAdapter(
        provider="openai",
        adapter_release_id="openai-adapter-v1",
        output={"answer": "unused", "score": 5},
        reported_model="openai-model",
    )
    router = _router("openai", adapter)
    budget = ModelCallBudget(1)
    request = _request("openai", output_schema={"type": "object", "unknown": True})

    with pytest.raises(OutputSchemaDefinitionError) as captured:
        router.generate(_route("openai"), request, policy=ModelPolicy(), budget=budget)

    assert captured.value.code is ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION
    assert budget.consumed_calls == 0
    assert adapter.calls == 0


def test_release_hash_mismatch_fails_before_budget_or_provider_call() -> None:
    adapter = RecordedAdapter(
        provider="openai",
        adapter_release_id="openai-adapter-v1",
        output={"answer": "unused", "score": 5},
        reported_model="openai-model",
    )
    router = _router("openai", adapter)
    budget = ModelCallBudget(1)

    with pytest.raises(ModelRouteError, match="adapter release hash"):
        router.generate(
            replace(_route("openai"), adapter_release_hash="0" * 64),
            _request("openai"),
            policy=ModelPolicy(),
            budget=budget,
        )

    assert budget.consumed_calls == 0
    assert adapter.calls == 0


def test_schema_invalid_provider_payload_is_retryable_and_path_specific() -> None:
    adapter = RecordedAdapter(
        provider="openai",
        adapter_release_id="openai-adapter-v1",
        output={"answer": "present", "score": 7},
        reported_model="openai-model",
    )
    router = _router("openai", adapter)

    with pytest.raises(StructuredOutputValidationError, match=r"\$\.score") as captured:
        router.generate(
            _route("openai"),
            _request("openai"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    assert captured.value.code is ModelGatewayErrorCode.SCHEMA_INVALID
    assert captured.value.retryable is True


def test_configured_and_reported_model_identities_are_both_enforced() -> None:
    adapter = RecordedAdapter(
        provider="openai",
        adapter_release_id="openai-adapter-v1",
        output={"answer": "present", "score": 4},
        reported_model="unexpected-model",
    )
    router = _router("openai", adapter)

    with pytest.raises(ModelIdentityError, match="provider-reported model"):
        router.generate(
            _route("openai"),
            _request("openai"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    wrong_request = ModelGatewayRequest(
        messages=({"role": "user", "content": "test"},),
        configured_model="different-configured-model",
        prompt_bundle_hash="b" * 64,
        project_id=uuid4(),
        purpose="metric_judge",
        output_schema=OUTPUT_SCHEMA,
    )
    with pytest.raises(ModelIdentityError, match="request configured model"):
        router.generate(
            _route("openai"),
            wrong_request,
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )


def test_unclassified_adapter_failure_is_normalized_without_trying_another_route() -> None:
    adapter = RecordedAdapter(
        provider="openai",
        adapter_release_id="openai-adapter-v1",
        output={},
        reported_model=None,
        failure=ValueError("fixture bug"),
    )
    router = _router("openai", adapter)

    with pytest.raises(ModelGatewayError, match="unclassified") as captured:
        router.generate(
            _route("openai"),
            _request("openai"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    assert captured.value.code is ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION
    assert captured.value.retryable is False
    assert captured.value.provider == "openai"


def test_forbidden_raw_persistence_and_unsupported_request_features_fail_closed() -> None:
    adapter = RecordedAdapter(
        provider="openai",
        adapter_release_id="openai-adapter-v1",
        output={"answer": "present", "score": 4},
        reported_model="openai-model",
        raw_artifact_reference="minio://raw/provider-response.json",
    )
    router = _router(
        "openai",
        adapter,
        adapter_release=_adapter_release("openai", storage=DataUseDecision.PROHIBITED),
    )

    with pytest.raises(ProviderPolicyViolation, match="prohibits raw response persistence"):
        router.generate(
            _route("openai"),
            _request("openai"),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )

    request = ModelGatewayRequest(
        messages=({"role": "user", "content": "test"},),
        configured_model="openai-model",
        prompt_bundle_hash="c" * 64,
        project_id=uuid4(),
        purpose="metric_judge",
        output_schema=OUTPUT_SCHEMA,
        search_mode="grounded",
        capture_method=ModelCaptureMethod.PROVIDER_API,
    )
    before = adapter.calls
    with pytest.raises(ProviderPolicyViolation, match="search mode"):
        router.generate(_route("openai"), request, policy=ModelPolicy(), budget=ModelCallBudget(1))
    assert adapter.calls == before
