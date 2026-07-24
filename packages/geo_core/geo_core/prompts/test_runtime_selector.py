"""Prompt-specific adapter over the approved Model Gateway runtime catalog."""

from __future__ import annotations

from uuid import UUID

from geo_core.model_gateway.releases import DataUseDecision
from geo_core.model_gateway.runtime_catalog import ApprovedRuntimeCatalog
from geo_core.prompts.test_execution_contracts import (
    PromptTestExecutionError,
    PromptTestModelSelection,
    PromptTestRouteRequest,
    PromptTestRuntimeOption,
    PromptTestRuntimeSelector,
)


PROMPT_TEST_MODEL_PURPOSE = "prompt_release_test"
PROMPT_TEST_SEARCH_MODE = "disabled"


class ApprovedCatalogPromptTestRuntimeSelector(PromptTestRuntimeSelector):
    """Fix Prompt tests to one purpose and non-search execution mode."""

    def __init__(self, catalog: ApprovedRuntimeCatalog) -> None:
        self._catalog = catalog

    def list_approved(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PromptTestRuntimeOption, ...]:
        listed = self._catalog.list_approved_runtime_options(project_id=project_id)
        return tuple(
            self._option(project_id=project_id, runtime_selection_id=item.selection_id)
            for item in listed.items
            if PROMPT_TEST_MODEL_PURPOSE in item.allowed_purposes
            and PROMPT_TEST_SEARCH_MODE in item.allowed_search_modes
        )

    def select(
        self,
        *,
        project_id: UUID,
        request: PromptTestRouteRequest,
    ) -> PromptTestModelSelection:
        selected = self._catalog.resolve_approved_runtime(
            project_id=project_id,
            runtime_selection_id=request.runtime_selection_id,
            required_purpose=PROMPT_TEST_MODEL_PURPOSE,
            search_mode=PROMPT_TEST_SEARCH_MODE,
        )
        if selected.adapter_release.data_policy.storage is not DataUseDecision.ALLOWED:
            raise PromptTestExecutionError(
                "Prompt test runtime must allow governed derived-artifact recovery"
            )
        policy = selected.policy
        if policy.policy_version_id is None or policy.policy_version_hash is None:
            raise PromptTestExecutionError(
                "Prompt test runtime requires a frozen Model policy"
            )
        return PromptTestModelSelection(
            runtime_selection_id=selected.runtime_option_id,
            runtime_selection_hash=selected.runtime_option_hash,
            runtime_manifest_id=selected.runtime_manifest_id,
            runtime_manifest_hash=selected.runtime_manifest_hash,
            route=selected.route,
            configured_model=selected.configured_model,
            capture_method=selected.adapter_release.expected_capture_method,
            policy_version_id=policy.policy_version_id,
            policy_version_hash=policy.policy_version_hash,
            policy=policy,
            provider_secret_handle=selected.provider_secret_handle,
        )

    def _option(
        self,
        *,
        project_id: UUID,
        runtime_selection_id: UUID,
    ) -> PromptTestRuntimeOption:
        selected = self.select(
            project_id=project_id,
            request=PromptTestRouteRequest(runtime_selection_id),
        )
        route = selected.route
        return PromptTestRuntimeOption(
            runtime_selection_id=selected.runtime_selection_id,
            runtime_selection_hash=selected.runtime_selection_hash,
            runtime_manifest_id=selected.runtime_manifest_id,
            runtime_manifest_hash=selected.runtime_manifest_hash,
            provider=route.provider,
            adapter_release_id=route.adapter_release_id,
            adapter_release_hash=route.adapter_release_hash,
            model_release_id=route.model_release_id,
            model_release_hash=route.model_release_hash,
            configured_model=selected.configured_model,
            capture_method=selected.capture_method,
            policy_version_id=selected.policy_version_id,
            policy_version_hash=selected.policy_version_hash,
        )


__all__ = [
    "ApprovedCatalogPromptTestRuntimeSelector",
    "PROMPT_TEST_MODEL_PURPOSE",
    "PROMPT_TEST_SEARCH_MODE",
]
