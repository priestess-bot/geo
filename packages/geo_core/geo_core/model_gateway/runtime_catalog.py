"""Database-backed runtime catalog contracts for exact Model Gateway execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Protocol
from uuid import UUID, uuid5

from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelPolicy, ModelRouteError
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.model_gateway.ports import ModelCallJobAdmission, ModelCallUnitOfWorkFactory
from geo_core.model_gateway.provider_adapters.microsoft import MicrosoftAgentReference
from geo_core.model_gateway.releases import AdapterRelease, ModelRelease, ModelRoute
from geo_core.model_gateway.runtime_manifest import (
    ModelGatewayRuntimeManifest,
    ProviderRuntimeDefinition,
)
from geo_core.secrets import SecretVersionHandle


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RuntimeOptionDefinition:
    """One deterministic selectable Provider/Model option in a manifest."""

    option_id: UUID
    option_hash: str
    manifest_id: UUID
    project_id: UUID
    provider_runtime: ProviderRuntimeDefinition
    model_release: ModelRelease
    provider_config_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.option_id, "runtime option"),
            (self.manifest_id, "runtime option manifest"),
            (self.project_id, "runtime option Project"),
        ):
            if value.int == 0:
                raise ValueError(f"{label} ID cannot be zero")
        _require_hash(self.option_hash, "runtime option")
        _require_hash(self.provider_config_hash, "runtime Provider configuration")
        adapter = self.provider_runtime.adapter_release
        if (
            self.model_release.provider != adapter.provider
            or self.model_release.adapter_release_id != adapter.adapter_release_id
        ):
            raise ValueError("runtime option Model Release differs from Adapter Release")

    @property
    def route(self) -> ModelRoute:
        adapter = self.provider_runtime.adapter_release
        model = self.model_release
        return ModelRoute(
            provider=adapter.provider,
            adapter_release_id=adapter.adapter_release_id,
            adapter_release_hash=adapter.release_hash,
            model_release_id=model.model_release_id,
            model_release_hash=model.release_hash,
        )


@dataclass(frozen=True)
class NewModelCallJobSelection:
    """Server-resolved, approved selection frozen into a newly admitted Job."""

    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    route: ModelRoute
    configured_model: str
    policy: ModelPolicy
    provider_secret_handle: SecretVersionHandle
    adapter_release: AdapterRelease
    allowed_purposes: frozenset[str]
    allowed_search_modes: frozenset[str | None]
    provider_config_hash: str
    microsoft_endpoint: str | None = None
    microsoft_agent_reference: MicrosoftAgentReference | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.runtime_manifest_id, "runtime manifest"),
            (self.runtime_option_id, "runtime option"),
        ):
            if value.int == 0:
                raise ValueError(f"{label} ID cannot be zero")
        for digest, label in (
            (self.runtime_manifest_hash, "runtime manifest"),
            (self.runtime_option_hash, "runtime option"),
            (self.provider_config_hash, "runtime Provider configuration"),
        ):
            _require_hash(digest, label)
        if not self.configured_model.strip():
            raise ValueError("runtime configured model is required")
        if not self.allowed_purposes or not self.allowed_search_modes:
            raise ValueError("runtime selection must freeze purpose and search-mode allowlists")
        if self.route.provider != self.adapter_release.provider:
            raise ValueError("runtime selection route differs from Adapter Release")
        if self.provider_secret_handle.purpose != f"model_provider.{self.route.provider}":
            raise ValueError("runtime selection Secret purpose differs from Provider")


@dataclass(frozen=True)
class ApprovedRuntimeOption:
    """Sanitized Admin projection; Secret and endpoint details are intentionally absent."""

    selection_id: UUID
    manifest_id: UUID
    provider: str
    adapter_release_id: str
    model_release_id: str
    configured_model: str
    capture_method: ModelCaptureMethod
    allowed_purposes: tuple[str, ...]
    allowed_search_modes: tuple[str | None, ...]


@dataclass(frozen=True)
class ApprovedRuntimeOptions:
    project_id: UUID
    current_manifest_id: UUID | None
    items: tuple[ApprovedRuntimeOption, ...]


@dataclass(frozen=True)
class FrozenRuntimeOption:
    """Historical option loaded by exact Job IDs/hashes, independent of current status."""

    manifest_id: UUID
    manifest_hash: str
    option_id: UUID
    option_hash: str
    policy: ModelPolicy
    adapter_release: AdapterRelease
    model_release: ModelRelease
    secret_reference_id: UUID
    allowed_purposes: frozenset[str]
    allowed_search_modes: frozenset[str | None]
    provider_config_hash: str
    microsoft_endpoint: str | None = None
    microsoft_agent_reference: MicrosoftAgentReference | None = None


class RuntimeManifestRegistrationCatalog(Protocol):
    """Provisioning port; manifest and all options commit atomically."""

    @property
    def uow_factory(self) -> ModelCallUnitOfWorkFactory: ...

    def register_adapter_release(
        self, release: AdapterRelease, *, registered_by: UUID, registered_at: datetime
    ) -> AdapterRelease: ...

    def register_model_release(
        self, release: ModelRelease, *, registered_by: UUID, registered_at: datetime
    ) -> ModelRelease: ...

    def register_project_policy(
        self,
        *,
        project_id: UUID,
        policy: ModelPolicy,
        version: int,
        previous_version_id: UUID | None,
        created_by: UUID,
        created_at: datetime,
    ) -> ModelPolicy: ...

    def require_active_provider_secret_handle(
        self, *, project_id: UUID, provider: str, reference_id: UUID
    ) -> SecretVersionHandle: ...

    def register_runtime_manifest_record(
        self,
        *,
        manifest: ModelGatewayRuntimeManifest,
        options: tuple[RuntimeOptionDefinition, ...],
    ) -> None: ...


class ApprovedRuntimeCatalog(Protocol):
    def list_approved_runtime_options(self, *, project_id: UUID) -> ApprovedRuntimeOptions: ...

    def resolve_approved_runtime(
        self,
        *,
        project_id: UUID,
        runtime_selection_id: UUID,
        required_purpose: str,
        search_mode: str | None,
    ) -> NewModelCallJobSelection: ...

    def load_frozen_runtime_option(self, *, job: ModelCallJobAdmission) -> FrozenRuntimeOption: ...


def runtime_options_for_manifest(
    manifest: ModelGatewayRuntimeManifest,
) -> tuple[RuntimeOptionDefinition, ...]:
    """Derive reproducible IDs and hashes for every Provider/Model combination."""
    runtimes = {
        (item.adapter_release.provider, item.adapter_release.adapter_release_id): item
        for item in manifest.provider_runtimes
    }
    options: list[RuntimeOptionDefinition] = []
    for model in sorted(
        manifest.model_releases,
        key=lambda item: (item.provider, item.adapter_release_id, item.model_release_id),
    ):
        runtime = runtimes[(model.provider, model.adapter_release_id)]
        provider_config = _provider_config(runtime)
        provider_config_hash = canonical_json_hash(provider_config)
        option_hash = canonical_json_hash(
            {
                "schema_version": 1,
                "manifest_id": manifest.manifest_id,
                "project_id": manifest.project_id,
                "provider": model.provider,
                "adapter_release_id": model.adapter_release_id,
                "adapter_release_hash": runtime.adapter_release.release_hash,
                "model_release_id": model.model_release_id,
                "model_release_hash": model.release_hash,
                "secret_reference_id": runtime.secret_reference_id,
                "provider_config_hash": provider_config_hash,
                "allowed_purposes": sorted(runtime.allowed_purposes),
                "allowed_search_modes": _ordered_search_modes(runtime.allowed_search_modes),
            }
        )
        options.append(
            RuntimeOptionDefinition(
                option_id=uuid5(manifest.manifest_id, option_hash),
                option_hash=option_hash,
                manifest_id=manifest.manifest_id,
                project_id=manifest.project_id,
                provider_runtime=runtime,
                model_release=model,
                provider_config_hash=provider_config_hash,
            )
        )
    return tuple(options)


def register_runtime_manifest(
    catalog: RuntimeManifestRegistrationCatalog,
    manifest: ModelGatewayRuntimeManifest,
) -> tuple[SecretVersionHandle, ...]:
    """Provision immutable releases, then atomically publish manifest plus options."""
    handles = tuple(
        catalog.require_active_provider_secret_handle(
            project_id=manifest.project_id,
            provider=definition.adapter_release.provider,
            reference_id=definition.secret_reference_id,
        )
        for definition in manifest.provider_runtimes
    )
    for definition in manifest.provider_runtimes:
        catalog.register_adapter_release(
            definition.adapter_release,
            registered_by=manifest.approved_by,
            registered_at=manifest.approved_at,
        )
    for release in manifest.model_releases:
        catalog.register_model_release(
            release,
            registered_by=manifest.approved_by,
            registered_at=manifest.approved_at,
        )
    catalog.register_project_policy(
        project_id=manifest.project_id,
        policy=manifest.project_policy,
        version=manifest.policy_version,
        previous_version_id=manifest.previous_policy_version_id,
        created_by=manifest.approved_by,
        created_at=manifest.approved_at,
    )
    catalog.register_runtime_manifest_record(
        manifest=manifest,
        options=runtime_options_for_manifest(manifest),
    )
    return handles


def select_approved_runtime(
    *,
    catalog: ApprovedRuntimeCatalog,
    project_id: UUID,
    runtime_selection_id: UUID,
    required_purpose: str,
    search_mode: str | None,
) -> NewModelCallJobSelection:
    """Resolve an opaque Admin selection only through the approved DB gate."""
    if project_id.int == 0 or runtime_selection_id.int == 0:
        raise ModelRouteError("runtime Project and selection IDs cannot be zero")
    if not required_purpose.strip():
        raise ModelRouteError("runtime purpose is required")
    return catalog.resolve_approved_runtime(
        project_id=project_id,
        runtime_selection_id=runtime_selection_id,
        required_purpose=required_purpose,
        search_mode=search_mode,
    )


def select_new_job_runtime(**values: object) -> NewModelCallJobSelection:
    """Compatibility name for the DB-authoritative new-Job selector."""
    return select_approved_runtime(**values)  # type: ignore[arg-type]


def _provider_config(runtime: ProviderRuntimeDefinition) -> dict[str, object]:
    agent = runtime.microsoft_agent_reference
    return {
        "capture_method": runtime.adapter_release.expected_capture_method.value,
        "microsoft_endpoint": runtime.microsoft_endpoint,
        "microsoft_agent_name": agent.name if agent is not None else None,
        "microsoft_agent_version": agent.version if agent is not None else None,
        "microsoft_market": agent.market if agent is not None else None,
        "microsoft_language": agent.language if agent is not None else None,
    }


def _ordered_search_modes(values: frozenset[str | None]) -> list[str | None]:
    return sorted(values, key=lambda value: (value is not None, value or ""))


def _require_hash(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} hash must be lowercase SHA-256")


__all__ = [
    "ApprovedRuntimeCatalog",
    "ApprovedRuntimeOption",
    "ApprovedRuntimeOptions",
    "FrozenRuntimeOption",
    "NewModelCallJobSelection",
    "RuntimeManifestRegistrationCatalog",
    "RuntimeOptionDefinition",
    "register_runtime_manifest",
    "runtime_options_for_manifest",
    "select_approved_runtime",
    "select_new_job_runtime",
]
