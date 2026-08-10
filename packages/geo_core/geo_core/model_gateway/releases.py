"""Immutable provider, adapter, and model release routing contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json

from geo_core.model_gateway.contracts import (
    CapabilityVerification,
    ModelCaptureMethod,
    ModelRouteError,
    ProviderCapabilities,
    ProviderPolicyViolation,
)
from geo_core.model_gateway.governance import validate_evidence


KNOWN_MODEL_PROVIDERS = (
    "deepseek",
    "openai",
    "kimi",
    "gemini",
    "perplexity",
    "microsoft",
)

def provider_secret_purpose(provider: str) -> str:
    """Return the frozen Secret Store purpose for a Gateway provider."""

    normalized = provider.strip()
    if normalized not in KNOWN_MODEL_PROVIDERS:
        raise ModelRouteError(f"unsupported Gateway provider: {normalized}")
    return f"model_provider.{normalized}"


class ReleaseState(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class DataUseDecision(StrEnum):
    ALLOWED = "allowed"
    PROHIBITED = "prohibited"
    UNVERIFIED = "unverified"


class ReportedModelPolicy(StrEnum):
    """How an approved model release interprets provider-reported identity."""

    RECORD_ONLY = "record_only"
    REQUIRE_PRESENT = "require_present"
    EXACT = "exact"
    ALLOWLIST = "allowlist"


@dataclass(frozen=True)
class ProviderDataPolicy:
    """Terms evidence required before an adapter release can be approved."""

    storage: DataUseDecision
    cache: DataUseDecision
    display: DataUseDecision
    redistribution: DataUseDecision
    retention_days: int | None
    terms_reference: str
    terms_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.retention_days is not None and self.retention_days < 0:
            raise ProviderPolicyViolation("provider data retention cannot be negative")

    @property
    def verified(self) -> bool:
        decisions = (self.storage, self.cache, self.display, self.redistribution)
        if any(decision is DataUseDecision.UNVERIFIED for decision in decisions):
            return False
        try:
            validate_evidence(
                self.terms_reference,
                self.terms_sha256,
                label="provider terms evidence",
            )
        except ValueError:
            return False
        return True

    def canonical_value(self) -> dict[str, object]:
        return {
            "storage": self.storage.value,
            "cache": self.cache.value,
            "display": self.display.value,
            "redistribution": self.redistribution.value,
            "retention_days": self.retention_days,
            "terms_reference": self.terms_reference,
            "terms_sha256": self.terms_sha256,
        }

    @property
    def data_policy_hash(self) -> str:
        canonical = json.dumps(
            self.canonical_value(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class AdapterRelease:
    provider: str
    adapter_release_id: str
    release_hash: str
    interface_contract_version: str
    expected_capture_method: ModelCaptureMethod
    capabilities: ProviderCapabilities
    data_policy: ProviderDataPolicy
    state: ReleaseState
    capability_evidence_reference: str | None = None
    capability_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        _require_release_hash(self.release_hash, label="adapter release")
        if not self.provider.strip() or not self.adapter_release_id.strip():
            raise ModelRouteError("adapter release identity cannot be empty")
        if not self.interface_contract_version.strip():
            raise ModelRouteError("adapter interface contract version cannot be empty")
        object.__setattr__(
            self,
            "expected_capture_method",
            ModelCaptureMethod(self.expected_capture_method),
        )
        if self.capabilities.provider != self.provider:
            raise ModelRouteError("adapter capability provider does not match its release")
        if self.state is ReleaseState.APPROVED:
            if self.capabilities.verification is not CapabilityVerification.VERIFIED:
                raise ProviderPolicyViolation(
                    f"adapter release {self.adapter_release_id} has unverified capabilities"
                )
            try:
                validate_evidence(
                    self.capability_evidence_reference,
                    self.capability_evidence_sha256,
                    label="adapter capability evidence",
                )
            except ValueError as exc:
                raise ProviderPolicyViolation(str(exc)) from exc
            if not self.data_policy.verified:
                raise ProviderPolicyViolation(
                    f"adapter release {self.adapter_release_id} has unresolved data terms"
                )

    @property
    def data_policy_hash(self) -> str:
        return self.data_policy.data_policy_hash


@dataclass(frozen=True)
class ModelRelease:
    provider: str
    adapter_release_id: str
    model_release_id: str
    release_hash: str
    configured_model: str
    state: ReleaseState
    reported_model_policy: ReportedModelPolicy = ReportedModelPolicy.RECORD_ONLY
    allowed_reported_models: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_release_hash(self.release_hash, label="model release")
        if not self.provider.strip() or not self.adapter_release_id.strip():
            raise ModelRouteError("model release provider and adapter identity cannot be empty")
        if not self.model_release_id.strip():
            raise ModelRouteError("model release identity cannot be empty")
        if not self.configured_model.strip():
            raise ModelRouteError("model release configured_model cannot be empty")
        if (
            self.reported_model_policy is ReportedModelPolicy.ALLOWLIST
            and not self.allowed_reported_models
        ):
            raise ModelRouteError("reported model allowlist cannot be empty")
        if any(not value.strip() for value in self.allowed_reported_models):
            raise ModelRouteError("reported model allowlist cannot contain empty identities")
        if len(self.allowed_reported_models) != len(set(self.allowed_reported_models)):
            raise ModelRouteError("reported model allowlist cannot contain duplicates")


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    adapter_release_id: str
    adapter_release_hash: str
    model_release_id: str
    model_release_hash: str

    def __post_init__(self) -> None:
        _require_release_hash(self.adapter_release_hash, label="routed adapter release")
        _require_release_hash(self.model_release_hash, label="routed model release")


class ModelReleaseRegistry:
    """Resolves one exact approved route; it never searches for alternatives."""

    def __init__(
        self,
        *,
        adapter_releases: tuple[AdapterRelease, ...],
        model_releases: tuple[ModelRelease, ...],
    ) -> None:
        self._adapters: dict[tuple[str, str], AdapterRelease] = {}
        self._models: dict[tuple[str, str, str], ModelRelease] = {}
        for adapter_release in adapter_releases:
            adapter_key = (adapter_release.provider, adapter_release.adapter_release_id)
            if adapter_key in self._adapters:
                raise ModelRouteError(f"duplicate adapter release: {adapter_key}")
            self._adapters[adapter_key] = adapter_release
        for model_release in model_releases:
            model_key = (
                model_release.provider,
                model_release.adapter_release_id,
                model_release.model_release_id,
            )
            if model_key in self._models:
                raise ModelRouteError(f"duplicate model release: {model_key}")
            adapter_key = (model_release.provider, model_release.adapter_release_id)
            if adapter_key not in self._adapters:
                raise ModelRouteError(
                    f"model release {model_release.model_release_id} references an unknown adapter release"
                )
            self._models[model_key] = model_release

    def resolve(self, route: ModelRoute) -> tuple[AdapterRelease, ModelRelease]:
        adapter_key = (route.provider, route.adapter_release_id)
        model_key = (route.provider, route.adapter_release_id, route.model_release_id)
        try:
            adapter = self._adapters[adapter_key]
        except KeyError as exc:
            raise ModelRouteError(
                f"adapter release is not registered: {route.provider}/{route.adapter_release_id}"
            ) from exc
        try:
            model = self._models[model_key]
        except KeyError as exc:
            raise ModelRouteError(
                "model release is not registered: "
                f"{route.provider}/{route.adapter_release_id}/{route.model_release_id}"
            ) from exc
        if adapter.state is not ReleaseState.APPROVED:
            raise ModelRouteError(f"adapter release is not approved: {adapter.adapter_release_id}")
        if model.state is not ReleaseState.APPROVED:
            raise ModelRouteError(f"model release is not approved: {model.model_release_id}")
        if adapter.release_hash != route.adapter_release_hash:
            raise ModelRouteError(
                f"adapter release hash does not match the frozen route: {adapter.adapter_release_id}"
            )
        if model.release_hash != route.model_release_hash:
            raise ModelRouteError(
                f"model release hash does not match the frozen route: {model.model_release_id}"
            )
        return adapter, model


def draft_provider_adapter_releases() -> tuple[AdapterRelease, ...]:
    """Return fail-closed templates without claiming live provider verification.

    A deployment must replace capability and terms placeholders with reviewed evidence,
    assign a new release hash, and mark that release approved before routing any call.
    """

    return tuple(_draft_adapter_release(provider) for provider in KNOWN_MODEL_PROVIDERS)


def _draft_adapter_release(provider: str) -> AdapterRelease:
    release_id = f"{provider}-adapter-contract-v1"
    contract = {
        "provider": provider,
        "adapter_release_id": release_id,
        "interface_contract_version": "geo-model-gateway-v1",
        "expected_capture_method": _expected_capture_method(provider).value,
        "verification": "unverified",
    }
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    return AdapterRelease(
        provider=provider,
        adapter_release_id=release_id,
        release_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        interface_contract_version="geo-model-gateway-v1",
        expected_capture_method=_expected_capture_method(provider),
        capabilities=ProviderCapabilities(
            provider=provider,
            external_training_allowed=False,
            structured_output=False,
            data_retention_days=None,
            policy_reference="unverified:deployment-must-supply-provider-policy",
            verification=CapabilityVerification.UNVERIFIED,
        ),
        data_policy=ProviderDataPolicy(
            storage=DataUseDecision.UNVERIFIED,
            cache=DataUseDecision.UNVERIFIED,
            display=DataUseDecision.UNVERIFIED,
            redistribution=DataUseDecision.UNVERIFIED,
            retention_days=None,
            terms_reference="",
        ),
        state=ReleaseState.DRAFT,
    )


def _expected_capture_method(provider: str) -> ModelCaptureMethod:
    if provider == "microsoft":
        return ModelCaptureMethod.PROXY_GROUNDED_API
    return ModelCaptureMethod.PROVIDER_API


def _require_release_hash(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ModelRouteError(f"{label} hash must be a lowercase SHA-256 value")
