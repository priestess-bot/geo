"""Fail-closed composition contract for the Prompt Program Internal API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.model_gateway.runtime_catalog import ApprovedRuntimeCatalog
from geo_core.prompts.application import (
    BoundPromptProgram,
    CommandReceipt,
    CreatedPromptProgram,
    CreatedPromptRelease,
    TransitionedPromptProgram,
)
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramKind,
    ProgramReleaseDiff,
    ProgramReleaseState,
    ProgramSchemaContract,
    PromptProgram,
    PromptProgramRelease,
)
from geo_core.prompts.ports import PromptBindingPageRead
from geo_core.prompts.test_execution_contracts import (
    PromptTestJobReceipt,
    PromptTestRouteRequest,
    PromptTestRuntimeOption,
)
from geo_core.prompts.test_runtime_selector import (
    ApprovedCatalogPromptTestRuntimeSelector,
)
from geo_core.prompts.workspace import (
    PromptFlowWorkspaceItem,
    PromptRenderPreview,
    PromptSuiteRunReceipt,
    PromptTestRunSummary,
    PromptWorkingDraft,
    PublishedPromptDraft,
)


@dataclass(frozen=True)
class PromptReleaseRead:
    release: PromptProgramRelease
    state: ProgramReleaseState


@dataclass(frozen=True)
class PromptReleasePageRead:
    items: tuple[PromptReleaseRead, ...]
    total: int


@dataclass(frozen=True)
class PromptProgramPageRead:
    items: tuple[PromptProgram, ...]
    total: int


class PromptProgramApi(Protocol):
    def list_flow_workspace(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
    ) -> tuple[PromptFlowWorkspaceItem, ...]: ...

    def get_working_draft(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
    ) -> PromptWorkingDraft: ...

    def save_working_draft(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        display_name: str,
        system_template: str,
        user_template: str,
        expected_revision: int,
    ) -> PromptWorkingDraft: ...

    def render_working_draft(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        fixture_id: str | None,
    ) -> PromptRenderPreview: ...

    def enqueue_working_draft_suite(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        runtime_selection_id: UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> PromptSuiteRunReceipt: ...

    def list_working_draft_tests(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        limit: int,
    ) -> tuple[PromptTestRunSummary, ...]: ...

    def publish_working_draft(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> PublishedPromptDraft: ...

    def list_test_runtimes(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
    ) -> tuple[PromptTestRuntimeOption, ...]: ...

    def list_bindings(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_kind: ProgramKind | None,
        limit: int,
        offset: int,
    ) -> PromptBindingPageRead: ...

    def list_programs(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> PromptProgramPageRead: ...

    def create_program(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_kind: ProgramKind,
        purpose: str,
        system_template: str,
        user_template: str,
        schemas: ProgramSchemaContract,
        model_policy: ModelPolicySnapshot,
        test_set_id: UUID,
        test_set_version: int,
        test_set_hash: str,
        compiler_version: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[CreatedPromptProgram]: ...

    def create_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        system_template: str,
        user_template: str,
        schemas: ProgramSchemaContract,
        model_policy: ModelPolicySnapshot,
        test_set_id: UUID,
        test_set_version: int,
        test_set_hash: str,
        compiler_version: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[CreatedPromptRelease]: ...

    def get_program(
        self, principal: AccessPrincipal, *, project_id: UUID, program_id: UUID
    ) -> PromptProgram: ...

    def list_releases(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        limit: int,
        offset: int,
    ) -> PromptReleasePageRead: ...

    def get_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
    ) -> PromptReleaseRead: ...

    def enqueue_test(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        test_set_id: UUID,
        test_set_version: int,
        test_set_hash: str,
        route: PromptTestRouteRequest,
        expected_version: int,
        idempotency_key: str,
    ) -> PromptTestJobReceipt: ...

    def approve_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[TransitionedPromptProgram]: ...

    def freeze_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[TransitionedPromptProgram]: ...

    def retire_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[TransitionedPromptProgram]: ...

    def diff_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        candidate_release_id: UUID,
        baseline_release_id: UUID,
        fixed_variables: Mapping[str, object],
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[ProgramReleaseDiff]: ...

    def bind_release(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        program_id: UUID,
        release_id: UUID,
        purpose: str,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt[BoundPromptProgram]: ...


def build_prompt_program_application() -> PromptProgramApi | None:
    """Load the PostgreSQL adapter only after its migration-backed slice exists."""

    database_url = _secret("GEO_DATABASE_URL")
    if not database_url or not os.getenv("OBJECT_STORE_ENDPOINT", "").strip():
        return None
    module_name = "geo_core.prompts.postgres"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        return None
    builder = getattr(module, "build_prompt_program_api", None)
    if not callable(builder):
        return None
    from geo_core.object_store_config import build_object_store
    selector_module_name = "geo_core.model_gateway.postgres_catalog"
    try:
        selector_module = importlib.import_module(selector_module_name)
    except ModuleNotFoundError as exc:
        if exc.name != selector_module_name:
            raise
        return None
    selector_builder = getattr(selector_module, "build_model_gateway_persistence", None)
    if not callable(selector_builder):
        return None
    persistence = selector_builder(database_url)
    if persistence is None:
        return None
    catalog_module_name = "geo_core.model_gateway.postgres_runtime_catalog"
    try:
        catalog_module = importlib.import_module(catalog_module_name)
    except ModuleNotFoundError as exc:
        if exc.name != catalog_module_name:
            raise
        return None
    catalog_type = getattr(catalog_module, "PostgresRuntimeCatalog", None)
    if not callable(catalog_type):
        return None
    catalog = catalog_type(database_url, persistence=persistence)
    if catalog is None or any(
        not callable(getattr(catalog, name, None))
        for name in (
            "list_approved_runtime_options",
            "resolve_approved_runtime",
            "load_frozen_runtime_option",
        )
    ):
        return None
    selector = ApprovedCatalogPromptTestRuntimeSelector(
        cast(ApprovedRuntimeCatalog, catalog)
    )
    return cast(
        PromptProgramApi,
        builder(
            database_url=database_url,
            runtime_selector=selector,
            test_object_store=build_object_store(),
        ),
    )


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct
