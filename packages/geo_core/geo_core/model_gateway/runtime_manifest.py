"""Governed production manifest registration and exact per-Job composition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from geo_core.model_gateway._runtime_manifest_values import (
    RuntimeManifestValueError as RuntimeManifestError,
    array as _array,
    boolean as _boolean,
    datetime_value as _datetime,
    exact_object as _exact_object,
    integer as _integer,
    list_value as _list,
    text as _text,
    uuid_value as _uuid,
)
from geo_core.model_gateway.contracts import (
    CapabilityVerification,
    ModelCaptureMethod,
    ModelGatewayError,
    ModelPolicy,
    ModelRouteError,
    ProviderCapabilities,
)
from geo_core.model_gateway.governance import validate_evidence
from geo_core.model_gateway.ports import (
    ModelCallJobAdmission,
    canonical_json_hash,
)
from geo_core.model_gateway.provider_adapters.microsoft import (
    MicrosoftAgentReference,
    validate_microsoft_foundry_endpoint,
)
from geo_core.model_gateway.releases import (
    KNOWN_MODEL_PROVIDERS,
    AdapterRelease,
    DataUseDecision,
    ModelRelease,
    ModelReleaseRegistry,
    ProviderDataPolicy,
    ReleaseState,
    ReportedModelPolicy,
)


@dataclass(frozen=True)
class ProviderRuntimeDefinition:
    adapter_release: AdapterRelease
    allowed_purposes: frozenset[str]
    allowed_search_modes: frozenset[str | None]
    secret_reference_id: UUID
    microsoft_endpoint: str | None = None
    microsoft_agent_reference: MicrosoftAgentReference | None = None

    def __post_init__(self) -> None:
        if self.secret_reference_id.int == 0:
            raise RuntimeManifestError("Provider Secret Reference ID cannot be zero")
        if not self.allowed_purposes or any(not value.strip() for value in self.allowed_purposes):
            raise RuntimeManifestError("Provider runtime purposes must be explicit")
        if not self.allowed_search_modes or any(
            value is not None and not value.strip() for value in self.allowed_search_modes
        ):
            raise RuntimeManifestError("Provider runtime search modes must be explicit")
        microsoft = self.adapter_release.provider == "microsoft"
        complete = (
            self.microsoft_endpoint is not None and self.microsoft_agent_reference is not None
        )
        if microsoft != complete:
            raise RuntimeManifestError(
                "Microsoft runtime requires an exact endpoint and Agent Reference"
            )
        if self.microsoft_endpoint is not None:
            validate_microsoft_foundry_endpoint(self.microsoft_endpoint)


@dataclass(frozen=True)
class ModelGatewayRuntimeManifest:
    manifest_id: UUID
    project_id: UUID
    prepared_by: UUID
    prepared_at: datetime
    approved_by: UUID
    approved_at: datetime
    approval_evidence_reference: str
    approval_evidence_sha256: str
    provider_runtimes: tuple[ProviderRuntimeDefinition, ...]
    model_releases: tuple[ModelRelease, ...]
    project_policy: ModelPolicy
    policy_version: int
    previous_policy_version_id: UUID | None
    manifest_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.manifest_id, "runtime manifest"),
            (self.project_id, "runtime manifest Project"),
            (self.prepared_by, "runtime manifest preparer"),
            (self.approved_by, "runtime manifest approver"),
        ):
            if value.int == 0:
                raise RuntimeManifestError(f"{label} ID cannot be zero")
        for timestamp, label in (
            (self.prepared_at, "preparation"),
            (self.approved_at, "approval"),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise RuntimeManifestError(f"runtime manifest {label} time must be timezone-aware")
        if self.prepared_by == self.approved_by:
            raise RuntimeManifestError("runtime manifest maker and checker must be distinct")
        if self.approved_at < self.prepared_at:
            raise RuntimeManifestError("runtime manifest approval precedes preparation")
        try:
            validate_evidence(
                self.approval_evidence_reference,
                self.approval_evidence_sha256,
                label="runtime manifest approval evidence",
            )
        except ValueError as exc:
            raise RuntimeManifestError(str(exc)) from exc
        if self.policy_version < 1:
            raise RuntimeManifestError("runtime manifest policy version must be positive")
        if not self.provider_runtimes or not self.model_releases:
            raise RuntimeManifestError("runtime manifest requires Providers and Model Releases")
        providers = [item.adapter_release.provider for item in self.provider_runtimes]
        if len(providers) != len(set(providers)):
            raise RuntimeManifestError("runtime manifest contains duplicate Providers")
        runtime_keys = {
            (item.adapter_release.provider, item.adapter_release.adapter_release_id)
            for item in self.provider_runtimes
        }
        model_keys = {(item.provider, item.adapter_release_id) for item in self.model_releases}
        if runtime_keys != model_keys:
            raise RuntimeManifestError(
                "every Provider runtime requires exact Model Release coverage"
            )
        policy = self.project_policy
        if policy.allowed_providers != frozenset(
            providers
        ) or policy.allowed_adapter_release_ids != frozenset(
            item.adapter_release.adapter_release_id for item in self.provider_runtimes
        ):
            raise RuntimeManifestError(
                "project policy allowlists must exactly match the runtime manifest"
            )

    def runtime_for_job(
        self, job: ModelCallJobAdmission
    ) -> tuple[ProviderRuntimeDefinition, tuple[ModelRelease, ...]]:
        if job.project_id != self.project_id:
            raise ModelRouteError("runtime manifest Project differs from Job admission")
        if (
            job.policy_version_id != self.project_policy.policy_version_id
            or job.policy_version_hash != self.project_policy.policy_version_hash
        ):
            raise ModelRouteError("runtime manifest policy differs from Job admission")
        matching = tuple(
            item
            for item in self.provider_runtimes
            if item.adapter_release.provider == job.route.provider
            and item.adapter_release.adapter_release_id == job.route.adapter_release_id
            and item.adapter_release.release_hash == job.route.adapter_release_hash
        )
        if len(matching) != 1:
            raise ModelRouteError("Job Adapter Release is absent from runtime manifest")
        definition = matching[0]
        if (
            job.purpose not in definition.allowed_purposes
            or job.provider_secret_handle.reference_id != definition.secret_reference_id
        ):
            raise ModelRouteError("Job purpose or Secret binding differs from runtime manifest")
        models = tuple(
            item
            for item in self.model_releases
            if item.provider == job.route.provider
            and item.adapter_release_id == job.route.adapter_release_id
        )
        registry = ModelReleaseRegistry(
            adapter_releases=(definition.adapter_release,),
            model_releases=models,
        )
        registry.resolve(job.route)
        return definition, models


def parse_runtime_manifest(document: Mapping[str, object]) -> ModelGatewayRuntimeManifest:
    """Parse a closed manifest document behind one public error boundary."""
    try:
        return _parse_runtime_manifest(document)
    except RuntimeManifestError:
        raise
    except (ModelGatewayError, ValueError) as exc:
        raise RuntimeManifestError(str(exc)) from exc


def _parse_runtime_manifest(document: Mapping[str, object]) -> ModelGatewayRuntimeManifest:
    root = _exact_object(
        document,
        label="runtime manifest",
        keys={
            "schema_version",
            "manifest_id",
            "project_id",
            "prepared_by",
            "prepared_at",
            "approved_by",
            "approved_at",
            "approval_evidence_reference",
            "approval_evidence_sha256",
            "provider_runtimes",
            "model_releases",
            "project_policy",
        },
    )
    if _integer(root["schema_version"], "schema_version") != 2:
        raise RuntimeManifestError("unsupported runtime manifest schema version")
    providers = tuple(
        _parse_provider_runtime(item)
        for item in _array(root["provider_runtimes"], "provider_runtimes")
    )
    models = tuple(
        _parse_model_release(item) for item in _array(root["model_releases"], "model_releases")
    )
    policy, version, previous = _parse_policy(root["project_policy"])
    return ModelGatewayRuntimeManifest(
        manifest_id=_uuid(root["manifest_id"], "manifest_id"),
        project_id=_uuid(root["project_id"], "project_id"),
        prepared_by=_uuid(root["prepared_by"], "prepared_by"),
        prepared_at=_datetime(root["prepared_at"], "prepared_at"),
        approved_by=_uuid(root["approved_by"], "approved_by"),
        approved_at=_datetime(root["approved_at"], "approved_at"),
        approval_evidence_reference=_text(
            root["approval_evidence_reference"], "approval_evidence_reference"
        ),
        approval_evidence_sha256=_text(
            root["approval_evidence_sha256"], "approval_evidence_sha256"
        ),
        provider_runtimes=providers,
        model_releases=models,
        project_policy=policy,
        policy_version=version,
        previous_policy_version_id=previous,
        manifest_hash=canonical_json_hash(root),
    )


def _parse_provider_runtime(value: object) -> ProviderRuntimeDefinition:
    item = _exact_object(
        value,
        label="provider runtime",
        keys={
            "provider",
            "adapter_release_id",
            "interface_contract_version",
            "expected_capture_method",
            "capabilities",
            "data_policy",
            "capability_evidence_reference",
            "capability_evidence_sha256",
            "allowed_purposes",
            "allowed_search_modes",
            "secret_reference_id",
            "microsoft",
        },
    )
    provider = _text(item["provider"], "provider")
    if provider not in KNOWN_MODEL_PROVIDERS:
        raise RuntimeManifestError(f"unsupported runtime manifest Provider: {provider}")
    capabilities = _parse_capabilities(item["capabilities"], provider=provider)
    data_policy = _parse_data_policy(item["data_policy"])
    release_value = {key: item[key] for key in item if key != "secret_reference_id"}
    release = AdapterRelease(
        provider=provider,
        adapter_release_id=_text(item["adapter_release_id"], "adapter_release_id"),
        release_hash=canonical_json_hash(release_value),
        interface_contract_version=_text(
            item["interface_contract_version"], "interface_contract_version"
        ),
        expected_capture_method=ModelCaptureMethod(
            _text(item["expected_capture_method"], "expected_capture_method")
        ),
        capabilities=capabilities,
        data_policy=data_policy,
        state=ReleaseState.APPROVED,
        capability_evidence_reference=_text(
            item["capability_evidence_reference"], "capability_evidence_reference"
        ),
        capability_evidence_sha256=_text(
            item["capability_evidence_sha256"], "capability_evidence_sha256"
        ),
    )
    microsoft_endpoint: str | None = None
    microsoft_agent: MicrosoftAgentReference | None = None
    if item["microsoft"] is not None:
        microsoft = _exact_object(
            item["microsoft"],
            label="Microsoft runtime",
            keys={"endpoint", "agent_name", "agent_version", "market", "language"},
        )
        microsoft_endpoint = _text(microsoft["endpoint"], "Microsoft endpoint")
        microsoft_agent = MicrosoftAgentReference(
            name=_text(microsoft["agent_name"], "Microsoft agent name"),
            version=_text(microsoft["agent_version"], "Microsoft agent version"),
            market=_text(microsoft["market"], "Microsoft market"),
            language=_text(microsoft["language"], "Microsoft language"),
        )
    return ProviderRuntimeDefinition(
        adapter_release=release,
        allowed_purposes=frozenset(
            _text(value, "allowed purpose")
            for value in _array(item["allowed_purposes"], "allowed_purposes")
        ),
        allowed_search_modes=frozenset(
            None if value is None else _text(value, "allowed search mode")
            for value in _array(item["allowed_search_modes"], "allowed_search_modes")
        ),
        secret_reference_id=_uuid(item["secret_reference_id"], "secret_reference_id"),
        microsoft_endpoint=microsoft_endpoint,
        microsoft_agent_reference=microsoft_agent,
    )


def _parse_capabilities(value: object, *, provider: str) -> ProviderCapabilities:
    item = _exact_object(
        value,
        label="Provider capabilities",
        keys={
            "external_training_allowed",
            "structured_output",
            "data_retention_days",
            "policy_reference",
            "supports_seed",
            "supports_tools",
            "supports_search",
            "supports_citations",
            "supports_idempotency",
            "supports_structured_output_with_tools",
        },
    )
    retention = item["data_retention_days"]
    return ProviderCapabilities(
        provider=provider,
        external_training_allowed=_boolean(
            item["external_training_allowed"], "external_training_allowed"
        ),
        structured_output=_boolean(item["structured_output"], "structured_output"),
        data_retention_days=(
            None if retention is None else _integer(retention, "data_retention_days")
        ),
        policy_reference=_text(item["policy_reference"], "policy_reference"),
        supports_seed=_boolean(item["supports_seed"], "supports_seed"),
        supports_tools=_boolean(item["supports_tools"], "supports_tools"),
        supports_search=_boolean(item["supports_search"], "supports_search"),
        supports_citations=_boolean(item["supports_citations"], "supports_citations"),
        supports_idempotency=_boolean(item["supports_idempotency"], "supports_idempotency"),
        supports_structured_output_with_tools=_boolean(
            item["supports_structured_output_with_tools"],
            "supports_structured_output_with_tools",
        ),
        verification=CapabilityVerification.VERIFIED,
    )


def _parse_data_policy(value: object) -> ProviderDataPolicy:
    item = _exact_object(
        value,
        label="Provider data policy",
        keys={
            "storage",
            "cache",
            "display",
            "redistribution",
            "retention_days",
            "terms_reference",
            "terms_sha256",
        },
    )
    retention = item["retention_days"]
    return ProviderDataPolicy(
        storage=DataUseDecision(_text(item["storage"], "storage decision")),
        cache=DataUseDecision(_text(item["cache"], "cache decision")),
        display=DataUseDecision(_text(item["display"], "display decision")),
        redistribution=DataUseDecision(_text(item["redistribution"], "redistribution decision")),
        retention_days=(None if retention is None else _integer(retention, "retention_days")),
        terms_reference=_text(item["terms_reference"], "terms_reference"),
        terms_sha256=_text(item["terms_sha256"], "terms_sha256"),
    )


def _parse_model_release(value: object) -> ModelRelease:
    item = _exact_object(
        value,
        label="Model Release",
        keys={
            "provider",
            "adapter_release_id",
            "model_release_id",
            "configured_model",
            "reported_model_policy",
            "allowed_reported_models",
        },
    )
    return ModelRelease(
        provider=_text(item["provider"], "Model Release provider"),
        adapter_release_id=_text(item["adapter_release_id"], "Model Release adapter_release_id"),
        model_release_id=_text(item["model_release_id"], "model_release_id"),
        release_hash=canonical_json_hash(item),
        configured_model=_text(item["configured_model"], "configured_model"),
        state=ReleaseState.APPROVED,
        reported_model_policy=ReportedModelPolicy(
            _text(item["reported_model_policy"], "reported_model_policy")
        ),
        allowed_reported_models=tuple(
            _text(value, "allowed reported model")
            for value in _list(item["allowed_reported_models"], "allowed_reported_models")
        ),
    )


def _parse_policy(value: object) -> tuple[ModelPolicy, int, UUID | None]:
    item = _exact_object(
        value,
        label="project policy",
        keys={
            "policy_version_id",
            "version",
            "previous_version_id",
            "external_training_allowed",
            "structured_output_required",
            "allowed_providers",
            "allowed_adapter_release_ids",
            "maximum_paid_calls",
            "maximum_concurrent_calls",
        },
    )
    previous = item["previous_version_id"]
    return (
        ModelPolicy(
            external_training_allowed=_boolean(
                item["external_training_allowed"], "policy external_training_allowed"
            ),
            structured_output_required=_boolean(
                item["structured_output_required"], "policy structured_output_required"
            ),
            allowed_providers=frozenset(
                _text(value, "allowed Provider")
                for value in _array(item["allowed_providers"], "allowed_providers")
            ),
            allowed_adapter_release_ids=frozenset(
                _text(value, "allowed Adapter Release")
                for value in _array(
                    item["allowed_adapter_release_ids"],
                    "allowed_adapter_release_ids",
                )
            ),
            policy_version_id=_uuid(item["policy_version_id"], "policy_version_id"),
            maximum_paid_calls=_integer(item["maximum_paid_calls"], "maximum_paid_calls"),
            maximum_concurrent_calls=_integer(
                item["maximum_concurrent_calls"], "maximum_concurrent_calls"
            ),
        ),
        _integer(item["version"], "policy version"),
        None if previous is None else _uuid(previous, "previous_version_id"),
    )
