"""Strong provenance contract for monitoring observations and official reports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from geo_core.monitoring.source_registry import (
    CAPTURE_SURFACE_KIND,
    PUBLIC_OBSERVATION_CAPTURE_METHODS as PUBLIC_OBSERVATION_CAPTURE_METHODS,
    SURFACE_DEFINITIONS,
    CaptureMethod,
    ObservationPlatform,
    ObservationSurface,
    SurfaceKind,
)


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
S3_URI_PATTERN = re.compile(r"^s3://[^/]+/.+$")
LEGACY_SOURCE_STRATUM_CONTRACT_VERSION = "geo-observation-source-v2"
SOURCE_CONTRACT_VERSION = "geo-observation-source-v3"


class ModelIdentityState(StrEnum):
    DISCLOSED = "disclosed"
    NOT_DISCLOSED = "not_disclosed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ModelIdentity:
    state: ModelIdentityState
    value: str | None = None

    def __post_init__(self) -> None:
        state = ModelIdentityState(self.state)
        value = self.value.strip() if self.value else None
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "value", value)
        if state == ModelIdentityState.DISCLOSED and not value:
            raise ValueError("a disclosed model identity requires a value")
        if state != ModelIdentityState.DISCLOSED and value is not None:
            raise ValueError("an unavailable model identity cannot carry a value")


class ObservationDevice(StrEnum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"
    API = "api"
    INTERNAL_WORKER = "internal_worker"
    REPORT = "report"


class ClientKind(StrEnum):
    BROWSER = "browser"
    NATIVE_APP = "native_app"
    API = "api"
    INTERNAL_WORKER = "internal_worker"
    REPORT_IMPORT = "report_import"


class SearchMode(StrEnum):
    DISABLED = "disabled"
    LIVE_WEB = "live_web"
    GROUNDED_WEB = "grounded_web"
    AUTOMATIC = "automatic"
    NOT_APPLICABLE = "not_applicable"


class RawEvidenceKind(StrEnum):
    ANSWER = "answer"
    INLINE_RESPONSE = "inline_response"
    ARTIFACT = "artifact"
    LEGACY_UNKNOWN = "legacy_unknown"


@dataclass(frozen=True)
class RawEvidence:
    kind: RawEvidenceKind
    answer: str | None = None
    inline_response: Mapping[str, object] | None = None
    artifact_uri: str | None = None
    artifact_hash: str | None = None
    artifact_verified: bool = False

    def __post_init__(self) -> None:
        kind = RawEvidenceKind(self.kind)
        answer = self.answer.strip() if self.answer else None
        inline = dict(self.inline_response) if self.inline_response is not None else None
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "answer", answer)
        object.__setattr__(
            self, "inline_response", MappingProxyType(inline) if inline is not None else None
        )
        if (self.artifact_uri is None) != (self.artifact_hash is None):
            raise ValueError("artifact URI and hash must be supplied together")
        if self.artifact_uri and not S3_URI_PATTERN.fullmatch(self.artifact_uri):
            raise ValueError("raw artifact must use an s3:// URI")
        if self.artifact_hash and not SHA256_PATTERN.fullmatch(self.artifact_hash):
            raise ValueError("raw artifact hash must be lowercase SHA-256")
        populated = sum(
            (
                answer is not None,
                bool(inline),
                self.artifact_uri is not None,
            )
        )
        if kind == RawEvidenceKind.LEGACY_UNKNOWN:
            return
        if populated != 1:
            raise ValueError("raw evidence must contain exactly one evidence representation")
        expected = {
            RawEvidenceKind.ANSWER: answer is not None,
            RawEvidenceKind.INLINE_RESPONSE: bool(inline),
            RawEvidenceKind.ARTIFACT: self.artifact_uri is not None,
        }
        if not expected.get(kind, False):
            raise ValueError("raw evidence kind does not match its payload")

    @property
    def eligible(self) -> bool:
        return self.kind != RawEvidenceKind.LEGACY_UNKNOWN and (
            self.kind != RawEvidenceKind.ARTIFACT or self.artifact_verified
        )


@dataclass(frozen=True)
class ObservationRunParameters:
    engine: str | None
    locale: str | None
    region: str | None
    language: str | None
    device: ObservationDevice | None
    client_kind: ClientKind | None
    search_enabled: bool | None
    search_mode: SearchMode | None
    prompt_text: str | None
    follow_up_prompts: tuple[str, ...] = ()
    adapter_name: str | None = None
    adapter_version: str | None = None
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "engine",
            "locale",
            "region",
            "language",
            "prompt_text",
            "adapter_name",
            "adapter_version",
            "provider_request_id",
        ):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if value and value.strip() else None)
        prompts = tuple(value.strip() for value in self.follow_up_prompts if value.strip())
        object.__setattr__(self, "follow_up_prompts", prompts)
        if self.device is not None:
            object.__setattr__(self, "device", ObservationDevice(self.device))
        if self.client_kind is not None:
            object.__setattr__(self, "client_kind", ClientKind(self.client_kind))
        if self.search_mode is not None:
            object.__setattr__(self, "search_mode", SearchMode(self.search_mode))


@dataclass(frozen=True)
class SourceStratumKey:
    capture_method: CaptureMethod
    platform: ObservationPlatform
    surface: ObservationSurface
    surface_kind: SurfaceKind
    engine: str
    configured_model: ModelIdentity
    reported_model: ModelIdentity
    locale: str
    region: str
    language: str
    device: ObservationDevice
    client_kind: ClientKind
    search_enabled: bool
    search_mode: SearchMode
    platform_detail: str | None = None
    surface_detail: str | None = None
    source_contract_version: str = SOURCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "capture_method", CaptureMethod(self.capture_method))
        object.__setattr__(self, "platform", ObservationPlatform(self.platform))
        object.__setattr__(self, "surface", ObservationSurface(self.surface))
        object.__setattr__(self, "surface_kind", SurfaceKind(self.surface_kind))
        object.__setattr__(self, "device", ObservationDevice(self.device))
        object.__setattr__(self, "client_kind", ClientKind(self.client_kind))
        object.__setattr__(self, "search_mode", SearchMode(self.search_mode))
        for name in ("engine", "locale", "region", "language"):
            value = getattr(self, name).strip()
            if not _ascii_nonempty(value):
                raise ValueError(f"source stratum {name} must be non-empty ASCII")
            object.__setattr__(self, name, value)
        for name in ("platform_detail", "surface_detail"):
            value = getattr(self, name)
            normalized = value.strip() if value and value.strip() else None
            if normalized is not None and not _ascii_nonempty(normalized):
                raise ValueError(f"source stratum {name} must be non-empty ASCII")
            object.__setattr__(self, name, normalized)
        if self.source_contract_version not in {
            LEGACY_SOURCE_STRATUM_CONTRACT_VERSION,
            SOURCE_CONTRACT_VERSION,
        }:
            raise ValueError("unsupported source stratum contract version")
        if self.source_contract_version == LEGACY_SOURCE_STRATUM_CONTRACT_VERSION:
            if self.platform_detail is not None or self.surface_detail is not None:
                raise ValueError("legacy source strata cannot carry detail fields")
            return
        if (self.platform == ObservationPlatform.OTHER) != (
            self.platform_detail is not None
        ):
            raise ValueError("platform detail is required exactly for OTHER")
        if (self.surface == ObservationSurface.OTHER) != (
            self.surface_detail is not None
        ):
            raise ValueError("surface detail is required exactly for OTHER")

    def canonical_value(self) -> dict[str, object]:
        value: dict[str, object] = {
            "capture_method": self.capture_method.value,
            "platform": self.platform.value,
            "surface": self.surface.value,
            "surface_kind": self.surface_kind.value,
            "engine": self.engine,
            "configured_model": {
                "state": self.configured_model.state.value,
                "value": self.configured_model.value,
            },
            "reported_model": {
                "state": self.reported_model.state.value,
                "value": self.reported_model.value,
            },
            "locale": self.locale,
            "region": self.region,
            "language": self.language,
            "device": self.device.value,
            "client_kind": self.client_kind.value,
            "search_enabled": self.search_enabled,
            "search_mode": self.search_mode.value,
        }
        if self.source_contract_version == SOURCE_CONTRACT_VERSION:
            value["platform_detail"] = self.platform_detail
            value["surface_detail"] = self.surface_detail
        return value

    def canonical_hash(self) -> str:
        return _canonical_hash(self.canonical_value())


@dataclass(frozen=True)
class ObservationSource:
    capture_method: CaptureMethod
    platform: ObservationPlatform
    surface: ObservationSurface
    surface_kind: SurfaceKind
    platform_detail: str | None
    surface_detail: str | None
    configured_model: ModelIdentity
    reported_model: ModelIdentity
    run: ObservationRunParameters
    raw_evidence: RawEvidence
    citations_captured: bool
    source_contract_version: str = SOURCE_CONTRACT_VERSION
    source_job_id: UUID | None = None
    model_call_log_id: UUID | None = None
    test_only: bool = False
    publication_eligible: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "capture_method", CaptureMethod(self.capture_method))
        object.__setattr__(self, "platform", ObservationPlatform(self.platform))
        object.__setattr__(self, "surface", ObservationSurface(self.surface))
        object.__setattr__(self, "surface_kind", SurfaceKind(self.surface_kind))
        for name in ("platform_detail", "surface_detail"):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if value and value.strip() else None)

    @classmethod
    def legacy_unknown(
        cls,
        *,
        raw_evidence: RawEvidence,
        configured_model: str,
        reported_model: str | None,
    ) -> "ObservationSource":
        configured = ModelIdentity(ModelIdentityState.DISCLOSED, configured_model)
        reported = (
            ModelIdentity(ModelIdentityState.DISCLOSED, reported_model)
            if reported_model
            else ModelIdentity(ModelIdentityState.NOT_DISCLOSED)
        )
        return cls(
            capture_method=CaptureMethod.UNKNOWN,
            platform=ObservationPlatform.OTHER,
            surface=ObservationSurface.OTHER,
            surface_kind=SurfaceKind.OTHER,
            platform_detail="legacy_unclassified",
            surface_detail="legacy_unclassified",
            configured_model=configured,
            reported_model=reported,
            run=ObservationRunParameters(
                engine=None,
                locale=None,
                region=None,
                language=None,
                device=None,
                client_kind=None,
                search_enabled=None,
                search_mode=None,
                prompt_text=None,
            ),
            raw_evidence=raw_evidence,
            citations_captured=False,
            source_contract_version="legacy-v1",
            publication_eligible=False,
        )

    def hard_violations(self) -> tuple[str, ...]:
        reasons: set[str] = set()
        expected_kind = CAPTURE_SURFACE_KIND[self.capture_method]
        definition = SURFACE_DEFINITIONS[self.surface]
        actual_kind = (
            self.surface_kind if self.surface == ObservationSurface.OTHER else definition.kind
        )
        if actual_kind != expected_kind:
            reasons.add("capture_surface_kind_mismatch")
        if self.surface != ObservationSurface.OTHER and self.surface_kind != definition.kind:
            reasons.add("surface_kind_mismatch")
        if definition.platform is not None and self.platform != definition.platform:
            reasons.add("platform_surface_mismatch")
        if self.platform == ObservationPlatform.OTHER and not self.platform_detail:
            reasons.add("missing_platform_detail")
        elif self.platform != ObservationPlatform.OTHER and self.platform_detail:
            reasons.add("unexpected_platform_detail")
        if self.platform_detail and not _ascii_nonempty(self.platform_detail):
            reasons.add("non_ascii_platform_detail")
        if self.surface == ObservationSurface.OTHER and not self.surface_detail:
            reasons.add("missing_surface_detail")
        elif self.surface != ObservationSurface.OTHER and self.surface_detail:
            reasons.add("unexpected_surface_detail")
        if self.surface_detail and not _ascii_nonempty(self.surface_detail):
            reasons.add("non_ascii_surface_detail")
        if self.capture_method == CaptureMethod.SYNTHETIC:
            if (
                self.source_job_id is None
                or self.model_call_log_id is None
                or not self.test_only
                or self.publication_eligible
            ):
                reasons.add("invalid_synthetic_lineage")
        elif self.capture_method == CaptureMethod.UNKNOWN:
            if self.test_only or self.publication_eligible:
                reasons.add("invalid_legacy_publication_flags")
        elif self.test_only or not self.publication_eligible:
            reasons.add("invalid_publication_flags")
        return tuple(sorted(reasons))

    def canonical_value(self) -> dict[str, object]:
        run = self.run
        evidence = self.raw_evidence
        return {
            "source_contract_version": self.source_contract_version,
            "capture_method": self.capture_method.value,
            "platform": self.platform.value,
            "platform_detail": self.platform_detail,
            "surface": self.surface.value,
            "surface_kind": self.surface_kind.value,
            "surface_detail": self.surface_detail,
            "configured_model": {
                "state": self.configured_model.state.value,
                "value": self.configured_model.value,
            },
            "reported_model": {
                "state": self.reported_model.state.value,
                "value": self.reported_model.value,
            },
            "run": {
                "engine": run.engine,
                "locale": run.locale,
                "region": run.region,
                "language": run.language,
                "device": run.device.value if run.device else None,
                "client_kind": run.client_kind.value if run.client_kind else None,
                "search_enabled": run.search_enabled,
                "search_mode": run.search_mode.value if run.search_mode else None,
                "prompt_text": run.prompt_text,
                "follow_up_prompts": list(run.follow_up_prompts),
                "adapter_name": run.adapter_name,
                "adapter_version": run.adapter_version,
                "provider_request_id": run.provider_request_id,
            },
            "raw_evidence": {
                "kind": evidence.kind.value,
                "answer": evidence.answer,
                "inline_response": (
                    dict(evidence.inline_response) if evidence.inline_response is not None else None
                ),
                "artifact_uri": evidence.artifact_uri,
                "artifact_hash": evidence.artifact_hash,
                "artifact_verified": evidence.artifact_verified,
            },
            "citations_captured": self.citations_captured,
            "source_job_id": str(self.source_job_id) if self.source_job_id else None,
            "model_call_log_id": (str(self.model_call_log_id) if self.model_call_log_id else None),
            "test_only": self.test_only,
            "publication_eligible": self.publication_eligible,
        }

    def source_identity_hash(self) -> str:
        return self.stratum_key().canonical_hash()

    def eligibility_reasons(self, *, result_succeeded: bool) -> tuple[str, ...]:
        reasons = set(self.hard_violations())
        if self.capture_method == CaptureMethod.UNKNOWN:
            return ("legacy_unknown_capture_method",)
        if self.capture_method == CaptureMethod.SYNTHETIC:
            reasons.add("synthetic_test_only")
        if not result_succeeded:
            reasons.add("capture_failed")
        if not self.raw_evidence.eligible:
            reasons.add("missing_or_unverified_raw_evidence")
        if not self.citations_captured and self.capture_method not in {
            CaptureMethod.OFFICIAL_REPORT_IMPORT,
            CaptureMethod.UNKNOWN,
        }:
            reasons.add("citation_capture_not_confirmed")
        run = self.run
        for name in ("engine", "locale", "region", "language"):
            if not getattr(run, name):
                reasons.add(f"missing_{name}")
        if run.device is None:
            reasons.add("missing_device")
        if run.client_kind is None:
            reasons.add("missing_client_kind")
        if run.search_enabled is None:
            reasons.add("missing_search_enabled")
        if run.search_mode is None:
            reasons.add("missing_search_mode")
        elif run.search_enabled is False and run.search_mode not in {
            SearchMode.DISABLED,
            SearchMode.NOT_APPLICABLE,
        }:
            reasons.add("search_mode_mismatch")
        elif run.search_enabled is True and run.search_mode in {
            SearchMode.DISABLED,
            SearchMode.NOT_APPLICABLE,
        }:
            reasons.add("search_mode_mismatch")

        if self.capture_method == CaptureMethod.OFFICIAL_REPORT_IMPORT:
            if self.raw_evidence.kind != RawEvidenceKind.ARTIFACT:
                reasons.add("official_report_requires_artifact")
            if self.configured_model.state != ModelIdentityState.NOT_APPLICABLE:
                reasons.add("official_report_model_must_be_not_applicable")
            if self.reported_model.state != ModelIdentityState.NOT_APPLICABLE:
                reasons.add("official_report_model_must_be_not_applicable")
        else:
            if not run.prompt_text:
                reasons.add("missing_prompt_text")
            if self.configured_model.state == ModelIdentityState.NOT_APPLICABLE:
                reasons.add("configured_model_not_recorded")

        if self.capture_method in {
            CaptureMethod.PROVIDER_API,
            CaptureMethod.PROXY_GROUNDED_API,
            CaptureMethod.SYNTHETIC,
        }:
            if self.configured_model.state != ModelIdentityState.DISCLOSED:
                reasons.add("configured_model_not_disclosed")
            if not run.adapter_name:
                reasons.add("missing_adapter_name")
            if not run.adapter_version:
                reasons.add("missing_adapter_version")
        if (
            self.capture_method
            in {
                CaptureMethod.PROVIDER_API,
                CaptureMethod.PROXY_GROUNDED_API,
            }
            and not run.provider_request_id
        ):
            reasons.add("missing_provider_request_id")
        if self.capture_method == CaptureMethod.PROXY_GROUNDED_API and not run.search_enabled:
            reasons.add("grounded_proxy_requires_search")
        return tuple(sorted(reasons))

    def stratum_key(self) -> SourceStratumKey:
        run = self.run
        missing: list[str] = []
        for name in ("engine", "locale", "region", "language"):
            if not getattr(run, name):
                missing.append(f"missing_{name}")
        if run.device is None:
            missing.append("missing_device")
        if run.client_kind is None:
            missing.append("missing_client_kind")
        if run.search_enabled is None:
            missing.append("missing_search_enabled")
        if run.search_mode is None:
            missing.append("missing_search_mode")
        if missing:
            raise ValueError(
                "an ineligible observation has no metric stratum: " + ", ".join(missing)
            )
        assert run.engine is not None
        assert run.locale is not None
        assert run.region is not None
        assert run.language is not None
        assert run.device is not None
        assert run.client_kind is not None
        assert run.search_enabled is not None
        assert run.search_mode is not None
        return SourceStratumKey(
            capture_method=self.capture_method,
            platform=self.platform,
            surface=self.surface,
            surface_kind=self.surface_kind,
            engine=run.engine,
            configured_model=self.configured_model,
            reported_model=self.reported_model,
            locale=run.locale,
            region=run.region,
            language=run.language,
            device=run.device,
            client_kind=run.client_kind,
            search_enabled=run.search_enabled,
            search_mode=run.search_mode,
            platform_detail=(
                self.platform_detail
                if self.source_contract_version == SOURCE_CONTRACT_VERSION
                else None
            ),
            surface_detail=(
                self.surface_detail
                if self.source_contract_version == SOURCE_CONTRACT_VERSION
                else None
            ),
            source_contract_version=self.source_contract_version,
        )


def _canonical_hash(value: object) -> str:
    serialized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _ascii_nonempty(value: str) -> bool:
    return bool(value.strip()) and value.isascii()
