from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from geo_core.model_gateway.contracts import (
    CapabilityVerification,
    ModelCaptureMethod,
    ModelPolicy,
    ProviderCapabilities,
)
from geo_core.model_gateway.releases import (
    AdapterRelease,
    DataUseDecision,
    ModelRelease,
    ModelRoute,
    ProviderDataPolicy,
    ReleaseState,
)
from geo_core.model_gateway.runtime_catalog import (
    ApprovedRuntimeOption,
    ApprovedRuntimeOptions,
    NewModelCallJobSelection,
)
from geo_core.prompts.test_execution_contracts import (
    PROMPT_TEST_MAXIMUM_PAID_CALLS,
    PromptTestExecutionError,
    PromptTestRouteRequest,
)
from geo_core.prompts.test_runtime_selector import (
    ApprovedCatalogPromptTestRuntimeSelector,
)
from geo_core.secrets.models import SecretVersionHandle


def test_prompt_selector_enriches_sanitized_options_from_server_resolution() -> None:
    catalog = _Catalog(_selection())
    selector = ApprovedCatalogPromptTestRuntimeSelector(catalog)  # type: ignore[arg-type]

    options = selector.list_approved(project_id=catalog.project_id)
    selected = selector.select(
        project_id=catalog.project_id,
        request=PromptTestRouteRequest(options[0].runtime_selection_id),
    )

    assert len(options) == 1
    assert options[0].runtime_selection_hash == catalog.selection.runtime_option_hash
    assert options[0].runtime_manifest_hash == catalog.selection.runtime_manifest_hash
    assert options[0].capture_method is ModelCaptureMethod.PROVIDER_API
    assert selected.runtime_selection_id == options[0].runtime_selection_id
    assert selected.policy == catalog.selection.policy
    assert catalog.resolve_calls == 2


def test_prompt_selector_rejects_runtime_without_derived_artifact_storage() -> None:
    selection = _selection()
    prohibited = replace(
        selection,
        adapter_release=replace(
            selection.adapter_release,
            data_policy=replace(
                selection.adapter_release.data_policy,
                storage=DataUseDecision.PROHIBITED,
            ),
        ),
    )
    catalog = _Catalog(prohibited)
    selector = ApprovedCatalogPromptTestRuntimeSelector(catalog)  # type: ignore[arg-type]

    with pytest.raises(PromptTestExecutionError, match="derived-artifact recovery"):
        selector.select(
            project_id=catalog.project_id,
            request=PromptTestRouteRequest(prohibited.runtime_option_id),
        )


class _Catalog:
    def __init__(self, selection: NewModelCallJobSelection) -> None:
        self.selection = selection
        self.project_id = selection.provider_secret_handle.project_id
        self.resolve_calls = 0

    def list_approved_runtime_options(self, *, project_id):
        assert project_id == self.project_id
        selection = self.selection
        route = selection.route
        return ApprovedRuntimeOptions(
            project_id,
            selection.runtime_manifest_id,
            (
                ApprovedRuntimeOption(
                    selection_id=selection.runtime_option_id,
                    manifest_id=selection.runtime_manifest_id,
                    provider=route.provider,
                    adapter_release_id=route.adapter_release_id,
                    model_release_id=route.model_release_id,
                    configured_model=selection.configured_model,
                    capture_method=selection.adapter_release.expected_capture_method,
                    allowed_purposes=("prompt_release_test",),
                    allowed_search_modes=("disabled",),
                ),
            ),
        )

    def resolve_approved_runtime(self, **values):
        assert values == {
            "project_id": self.project_id,
            "runtime_selection_id": self.selection.runtime_option_id,
            "required_purpose": "prompt_release_test",
            "search_mode": "disabled",
        }
        self.resolve_calls += 1
        return self.selection

    def load_frozen_runtime_option(self, *, job):
        raise AssertionError(job)


def _selection() -> NewModelCallJobSelection:
    project_id = uuid4()
    adapter = AdapterRelease(
        provider="openai",
        adapter_release_id="openai-adapter-v1",
        release_hash="1" * 64,
        interface_contract_version="geo-model-provider-v1",
        expected_capture_method=ModelCaptureMethod.PROVIDER_API,
        capabilities=ProviderCapabilities(
            provider="openai",
            external_training_allowed=False,
            structured_output=True,
            data_retention_days=30,
            policy_reference="policy:openai:fixture",
            supports_search=False,
            verification=CapabilityVerification.VERIFIED,
        ),
        data_policy=ProviderDataPolicy(
            storage=DataUseDecision.ALLOWED,
            cache=DataUseDecision.ALLOWED,
            display=DataUseDecision.ALLOWED,
            redistribution=DataUseDecision.PROHIBITED,
            retention_days=30,
            terms_reference="https://evidence.example/openai/terms/fixture",
            terms_sha256="a" * 64,
        ),
        state=ReleaseState.APPROVED,
        capability_evidence_reference="https://evidence.example/openai/capabilities/fixture",
        capability_evidence_sha256="b" * 64,
    )
    model = ModelRelease(
        provider="openai",
        adapter_release_id=adapter.adapter_release_id,
        model_release_id="openai-model-v1",
        release_hash="2" * 64,
        configured_model="gpt-fixture",
        state=ReleaseState.APPROVED,
    )
    policy = ModelPolicy(
        allowed_providers=frozenset({"openai"}),
        allowed_adapter_release_ids=frozenset({adapter.adapter_release_id}),
        policy_version_id=uuid4(),
        maximum_paid_calls=PROMPT_TEST_MAXIMUM_PAID_CALLS,
        maximum_concurrent_calls=1,
    )
    return NewModelCallJobSelection(
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash="3" * 64,
        runtime_option_id=uuid4(),
        runtime_option_hash="4" * 64,
        route=ModelRoute(
            provider="openai",
            adapter_release_id=adapter.adapter_release_id,
            adapter_release_hash=adapter.release_hash,
            model_release_id=model.model_release_id,
            model_release_hash=model.release_hash,
        ),
        configured_model=model.configured_model,
        policy=policy,
        provider_secret_handle=SecretVersionHandle(
            reference_id=uuid4(),
            project_id=project_id,
            purpose="model_provider.openai",
            version=1,
        ),
        adapter_release=adapter,
        allowed_purposes=frozenset({"prompt_release_test"}),
        allowed_search_modes=frozenset({"disabled"}),
        provider_config_hash="5" * 64,
    )
