"""Immutable release evidence required by governed Provider Sampling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping
from urllib.parse import urlparse
from uuid import UUID

from geo_core.model_gateway import AdapterRelease, ModelRelease
from geo_core.sampling.contracts import CaptureMethod
from geo_core.sampling.provider_sources import require_canonical_provider_source


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_SOURCE_COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class ProviderSamplingReleaseError(ValueError):
    """A release snapshot cannot support the state it claims."""


class ProviderSamplingReleaseState(StrEnum):
    DRAFT = "draft"
    FIXTURE_READY = "fixture_ready"
    LIVE_CANDIDATE = "live_candidate"
    APPROVED = "approved"
    DEFERRED_PENDING_AUTHORIZATION = "deferred_pending_authorization"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class ProviderReportedModelPolicy(StrEnum):
    RECORD_ONLY = "record_only"
    REQUIRE_PRESENT = "require_present"
    EXACT = "exact"
    ALLOWLIST = "allowlist"


@dataclass(frozen=True)
class ProviderSamplingRelease:
    """Reviewable Provider contract; runtime secrets are deliberately absent."""

    release_id: str
    gateway_provider: str
    platform: str
    surface: str
    capture_method: CaptureMethod
    adapter_release_id: str
    adapter_release_hash: str
    model_release_id: str
    model_release_hash: str
    configured_model: str
    reported_model_policy: ProviderReportedModelPolicy
    allowed_reported_models: tuple[str, ...]
    search_mode: str
    native_search_verified: bool
    request_contract_hash: str
    result_contract_hash: str
    error_contract_hash: str
    citation_contract_hash: str
    location_contract_hash: str
    fixture_corpus_hash: str
    contract_test_result_hash: str
    dependency_lock_hash: str
    data_policy_hash: str
    raw_storage_decision: str
    raw_display_decision: str
    raw_retention_days: int | None
    documentation_references: tuple[str, ...]
    owner: str
    source_commit: str
    state: ProviderSamplingReleaseState
    live_canary_run_id: UUID | None = None
    live_canary_manifest_hash: str | None = None
    published_by: str | None = None
    published_at: datetime | None = None
    status_reason_code: str | None = None
    release_hash: str = field(init=False)
    record_hash: str = field(init=False)

    def __post_init__(self) -> None:
        method = CaptureMethod(self.capture_method)
        state = ProviderSamplingReleaseState(self.state)
        policy = ProviderReportedModelPolicy(self.reported_model_policy)
        object.__setattr__(self, "capture_method", method)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "reported_model_policy", policy)
        require_canonical_provider_source(
            gateway_provider=self.gateway_provider,
            platform=self.platform,
            surface=self.surface,
            capture_method=method,
        )
        for value, label in (
            (self.release_id, "release"),
            (self.adapter_release_id, "adapter release"),
            (self.model_release_id, "model release"),
            (self.configured_model, "configured model"),
            (self.search_mode, "search mode"),
            (self.owner, "owner"),
        ):
            if _IDENTITY.fullmatch(value) is None:
                raise ProviderSamplingReleaseError(f"{label} identity is invalid")
        if _SOURCE_COMMIT.fullmatch(self.source_commit) is None:
            raise ProviderSamplingReleaseError("source commit must be a full Git object ID")
        for value, label in (
            (self.adapter_release_hash, "adapter release"),
            (self.model_release_hash, "model release"),
            (self.request_contract_hash, "request contract"),
            (self.result_contract_hash, "result contract"),
            (self.error_contract_hash, "error contract"),
            (self.citation_contract_hash, "citation contract"),
            (self.location_contract_hash, "location contract"),
            (self.fixture_corpus_hash, "fixture corpus"),
            (self.contract_test_result_hash, "contract test result"),
            (self.dependency_lock_hash, "dependency lock"),
            (self.data_policy_hash, "data policy"),
        ):
            _require_hash(value, label)
        models = tuple(self.allowed_reported_models)
        if len(models) != len(set(models)) or any(
            _IDENTITY.fullmatch(value) is None for value in models
        ):
            raise ProviderSamplingReleaseError("reported model allowlist is invalid")
        object.__setattr__(self, "allowed_reported_models", models)
        if policy in {
            ProviderReportedModelPolicy.EXACT,
            ProviderReportedModelPolicy.ALLOWLIST,
        } and not models:
            raise ProviderSamplingReleaseError("reported model policy requires an allowlist")
        if policy is ProviderReportedModelPolicy.EXACT and len(models) != 1:
            raise ProviderSamplingReleaseError("exact reported model policy requires one value")
        if self.raw_storage_decision not in {"allowed", "prohibited"}:
            raise ProviderSamplingReleaseError("raw storage decision is invalid")
        if self.raw_display_decision not in {"allowed", "prohibited"}:
            raise ProviderSamplingReleaseError("raw display decision is invalid")
        if self.raw_storage_decision == "prohibited":
            if self.raw_display_decision != "prohibited" or self.raw_retention_days not in {
                None,
                0,
            }:
                raise ProviderSamplingReleaseError(
                    "prohibited raw storage requires prohibited display and zero retention"
                )
        elif self.raw_retention_days is None or not 1 <= self.raw_retention_days <= 3650:
            raise ProviderSamplingReleaseError(
                "allowed raw storage requires a bounded retention of 1 to 3650 days"
            )
        references = tuple(self.documentation_references)
        if (
            not references
            or len(references) != len(set(references))
            or any(not _public_reference(value) for value in references)
        ):
            raise ProviderSamplingReleaseError(
                "release documentation must use credential-free HTTPS references"
            )
        object.__setattr__(self, "documentation_references", references)
        if self.gateway_provider == "kimi" and not self.native_search_verified:
            if self.search_mode != "disabled":
                raise ProviderSamplingReleaseError(
                    "Kimi without verified native Search must freeze search_mode=disabled"
                )
        elif self.gateway_provider != "kimi" and not self.native_search_verified:
            raise ProviderSamplingReleaseError(
                "grounded Provider releases must verify their search capability"
            )
        self._validate_lifecycle()
        object.__setattr__(
            self, "release_hash", _canonical_hash(self.definition_value())
        )
        object.__setattr__(self, "record_hash", _canonical_hash(self.record_value()))

    def _validate_lifecycle(self) -> None:
        live_pair = self.live_canary_run_id is not None or self.live_canary_manifest_hash is not None
        if live_pair:
            if self.live_canary_run_id is None or self.live_canary_manifest_hash is None:
                raise ProviderSamplingReleaseError("live canary identity and hash must be paired")
            if self.live_canary_run_id.int == 0:
                raise ProviderSamplingReleaseError("live canary Run ID cannot be zero")
            _require_hash(self.live_canary_manifest_hash, "live canary manifest")
        publication_pair = self.published_by is not None or self.published_at is not None
        if publication_pair:
            if self.published_by is None or self.published_at is None:
                raise ProviderSamplingReleaseError("publisher identity and time must be paired")
            _require_aware(self.published_at, "release publication time")
        live_states = {
            ProviderSamplingReleaseState.LIVE_CANDIDATE,
            ProviderSamplingReleaseState.APPROVED,
            ProviderSamplingReleaseState.DEPRECATED,
            ProviderSamplingReleaseState.RETIRED,
            ProviderSamplingReleaseState.SUSPENDED,
            ProviderSamplingReleaseState.REVOKED,
        }
        if self.state in live_states and not live_pair:
            raise ProviderSamplingReleaseError("release state requires a real live canary")
        published_states = live_states.difference(
            {ProviderSamplingReleaseState.LIVE_CANDIDATE}
        )
        if self.state in published_states and not publication_pair:
            raise ProviderSamplingReleaseError("release state requires publisher evidence")
        terminal_states = {
            ProviderSamplingReleaseState.DEPRECATED,
            ProviderSamplingReleaseState.RETIRED,
            ProviderSamplingReleaseState.SUSPENDED,
            ProviderSamplingReleaseState.REVOKED,
        }
        if self.state in terminal_states:
            if self.status_reason_code is None or not self.status_reason_code.strip():
                raise ProviderSamplingReleaseError("terminal release state needs a reason code")
        elif self.status_reason_code is not None:
            raise ProviderSamplingReleaseError("active release cannot carry a terminal reason")

    def definition_value(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "release_id": self.release_id,
            "gateway_provider": self.gateway_provider,
            "platform": self.platform,
            "surface": self.surface,
            "capture_method": self.capture_method.value,
            "adapter_release_id": self.adapter_release_id,
            "adapter_release_hash": self.adapter_release_hash,
            "model_release_id": self.model_release_id,
            "model_release_hash": self.model_release_hash,
            "configured_model": self.configured_model,
            "reported_model_policy": self.reported_model_policy.value,
            "allowed_reported_models": list(self.allowed_reported_models),
            "search_mode": self.search_mode,
            "native_search_verified": self.native_search_verified,
            "request_contract_hash": self.request_contract_hash,
            "result_contract_hash": self.result_contract_hash,
            "error_contract_hash": self.error_contract_hash,
            "citation_contract_hash": self.citation_contract_hash,
            "location_contract_hash": self.location_contract_hash,
            "fixture_corpus_hash": self.fixture_corpus_hash,
            "contract_test_result_hash": self.contract_test_result_hash,
            "dependency_lock_hash": self.dependency_lock_hash,
            "data_policy_hash": self.data_policy_hash,
            "raw_storage_decision": self.raw_storage_decision,
            "raw_display_decision": self.raw_display_decision,
            "raw_retention_days": self.raw_retention_days,
            "documentation_references": list(self.documentation_references),
            "owner": self.owner,
            "source_commit": self.source_commit,
        }

    def record_value(self) -> dict[str, object]:
        return {
            **self.definition_value(),
            "state": self.state.value,
            "live_canary_run_id": (
                str(self.live_canary_run_id) if self.live_canary_run_id else None
            ),
            "live_canary_manifest_hash": self.live_canary_manifest_hash,
            "published_by": self.published_by,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "status_reason_code": self.status_reason_code,
        }

    def value(self) -> dict[str, object]:
        return {
            **self.record_value(),
            "release_hash": self.release_hash,
            "record_hash": self.record_hash,
        }

    def validate_gateway_releases(
        self, adapter: AdapterRelease, model: ModelRelease
    ) -> None:
        if (
            adapter.provider != self.gateway_provider
            or adapter.adapter_release_id != self.adapter_release_id
            or adapter.release_hash != self.adapter_release_hash
            or adapter.expected_capture_method.value != self.capture_method.value
            or adapter.data_policy_hash != self.data_policy_hash
        ):
            raise ProviderSamplingReleaseError(
                "Model Gateway Adapter Release differs from Provider Sampling release"
            )
        if (
            model.provider != self.gateway_provider
            or model.adapter_release_id != self.adapter_release_id
            or model.model_release_id != self.model_release_id
            or model.release_hash != self.model_release_hash
            or model.configured_model != self.configured_model
        ):
            raise ProviderSamplingReleaseError(
                "Model Gateway Model Release differs from Provider Sampling release"
            )

    def accepts_reported_model(self, value: str | None) -> bool:
        if self.reported_model_policy is ProviderReportedModelPolicy.RECORD_ONLY:
            return True
        if value is None or not value.strip():
            return False
        if self.reported_model_policy is ProviderReportedModelPolicy.REQUIRE_PRESENT:
            return True
        return value in self.allowed_reported_models


def provider_sampling_release_from_value(
    value: Mapping[str, object],
) -> ProviderSamplingRelease:
    """Decode a strict release snapshot and verify both canonical hashes."""

    definition_fields = {
        "schema_version",
        "release_id",
        "gateway_provider",
        "platform",
        "surface",
        "capture_method",
        "adapter_release_id",
        "adapter_release_hash",
        "model_release_id",
        "model_release_hash",
        "configured_model",
        "reported_model_policy",
        "allowed_reported_models",
        "search_mode",
        "native_search_verified",
        "request_contract_hash",
        "result_contract_hash",
        "error_contract_hash",
        "citation_contract_hash",
        "location_contract_hash",
        "fixture_corpus_hash",
        "contract_test_result_hash",
        "dependency_lock_hash",
        "data_policy_hash",
        "raw_storage_decision",
        "raw_display_decision",
        "raw_retention_days",
        "documentation_references",
        "owner",
        "source_commit",
    }
    lifecycle_fields = {
        "state",
        "live_canary_run_id",
        "live_canary_manifest_hash",
        "published_by",
        "published_at",
        "status_reason_code",
        "release_hash",
        "record_hash",
    }
    if set(value) != definition_fields | lifecycle_fields:
        raise ProviderSamplingReleaseError("Provider release fields are not allowlisted")
    if value.get("schema_version") != 1:
        raise ProviderSamplingReleaseError("Provider release schema version is unsupported")
    release = ProviderSamplingRelease(
        release_id=_string(value, "release_id"),
        gateway_provider=_string(value, "gateway_provider"),
        platform=_string(value, "platform"),
        surface=_string(value, "surface"),
        capture_method=CaptureMethod(_string(value, "capture_method")),
        adapter_release_id=_string(value, "adapter_release_id"),
        adapter_release_hash=_string(value, "adapter_release_hash"),
        model_release_id=_string(value, "model_release_id"),
        model_release_hash=_string(value, "model_release_hash"),
        configured_model=_string(value, "configured_model"),
        reported_model_policy=ProviderReportedModelPolicy(
            _string(value, "reported_model_policy")
        ),
        allowed_reported_models=_string_tuple(
            value.get("allowed_reported_models"), "reported models"
        ),
        search_mode=_string(value, "search_mode"),
        native_search_verified=_boolean(value, "native_search_verified"),
        request_contract_hash=_string(value, "request_contract_hash"),
        result_contract_hash=_string(value, "result_contract_hash"),
        error_contract_hash=_string(value, "error_contract_hash"),
        citation_contract_hash=_string(value, "citation_contract_hash"),
        location_contract_hash=_string(value, "location_contract_hash"),
        fixture_corpus_hash=_string(value, "fixture_corpus_hash"),
        contract_test_result_hash=_string(value, "contract_test_result_hash"),
        dependency_lock_hash=_string(value, "dependency_lock_hash"),
        data_policy_hash=_string(value, "data_policy_hash"),
        raw_storage_decision=_string(value, "raw_storage_decision"),
        raw_display_decision=_string(value, "raw_display_decision"),
        raw_retention_days=_optional_integer(value, "raw_retention_days"),
        documentation_references=_string_tuple(
            value.get("documentation_references"), "documentation"
        ),
        owner=_string(value, "owner"),
        source_commit=_string(value, "source_commit"),
        state=ProviderSamplingReleaseState(_string(value, "state")),
        live_canary_run_id=_optional_uuid(value, "live_canary_run_id"),
        live_canary_manifest_hash=_optional_string(value, "live_canary_manifest_hash"),
        published_by=_optional_string(value, "published_by"),
        published_at=_optional_datetime(value, "published_at"),
        status_reason_code=_optional_string(value, "status_reason_code"),
    )
    if value.get("release_hash") != release.release_hash:
        raise ProviderSamplingReleaseError("Provider release hash does not match")
    if value.get("record_hash") != release.record_hash:
        raise ProviderSamplingReleaseError("Provider release record hash does not match")
    return release


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ProviderSamplingReleaseError(f"Provider release {key} must be text")
    return item


def _optional_string(value: Mapping[str, object], key: str) -> str | None:
    return None if value.get(key) is None else _string(value, key)


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProviderSamplingReleaseError(f"Provider release {label} must be a text list")
    return tuple(value)


def _boolean(value: Mapping[str, object], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ProviderSamplingReleaseError(f"Provider release {key} must be boolean")
    return item


def _optional_integer(value: Mapping[str, object], key: str) -> int | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, int) or isinstance(item, bool):
        raise ProviderSamplingReleaseError(f"Provider release {key} must be integer")
    return item


def _optional_uuid(value: Mapping[str, object], key: str) -> UUID | None:
    item = value.get(key)
    if item is None:
        return None
    try:
        return UUID(str(item))
    except (TypeError, ValueError) as error:
        raise ProviderSamplingReleaseError(f"Provider release {key} must be UUID") from error


def _optional_datetime(value: Mapping[str, object], key: str) -> datetime | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ProviderSamplingReleaseError(f"Provider release {key} must be ISO datetime")
    try:
        return datetime.fromisoformat(item)
    except ValueError as error:
        raise ProviderSamplingReleaseError(
            f"Provider release {key} must be ISO datetime"
        ) from error


def _require_hash(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ProviderSamplingReleaseError(f"{label} hash must be lowercase SHA-256")


def _public_reference(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderSamplingReleaseError(f"{label} must include a timezone")


__all__ = [
    "ProviderReportedModelPolicy",
    "ProviderSamplingRelease",
    "ProviderSamplingReleaseError",
    "ProviderSamplingReleaseState",
    "provider_sampling_release_from_value",
]
