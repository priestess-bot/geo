"""Typed, immutable evidence graph for explainable recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import ClassVar, Mapping
from uuid import UUID

from geo_core.recommendations.decision import (
    RecommendationDecision as RecommendationDecision,
)
from geo_core.recommendations.errors import RecommendationRuleViolation


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RecommendationInputKind(StrEnum):
    OBSERVATION = "observation"
    COMPARISON = "comparison"
    FACT = "fact"
    RULE_VERSION = "rule_version"
    PROMPT_RELEASE = "prompt_release"
    MODEL_CALL = "model_call"
    METHOD_VERSION = "method_version"
    CONTENT_VERSION = "content_version"
    QUESTION_VERSION = "question_version"
    SURFACE_RELEASE = "surface_release"
    ATTRIBUTION_AVAILABILITY = "attribution_availability"


class ObservationEvidenceClass(StrEnum):
    REAL_OBSERVATION = "real_observation"
    OFFICIAL_PROJECTION = "official_projection"
    SYNTHETIC = "synthetic"


class MetricComparisonConclusion(StrEnum):
    WIN = "win"
    EQUIVALENT = "equivalent"
    LOSS = "loss"
    INCONCLUSIVE = "inconclusive"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RecommendationRuleKind(StrEnum):
    THRESHOLD = "threshold"
    BASELINE_DELTA = "baseline_delta"
    NEGATIVE_QUESTION = "negative_question"
    COMPLETION_FRESHNESS = "completion_freshness"
    MODEL_DRIFT = "model_drift"
    SOURCE_DRIFT = "source_drift"
    CONNECTOR_FAILURE = "connector_failure"


class RecommendationRuleSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RecommendationRuleTriggerStatus(StrEnum):
    NOT_TRIGGERED = "not_triggered"
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    SUPPRESSED = "suppressed"
    RESOLVED = "resolved"


@dataclass(frozen=True, order=True)
class RecommendationInputVersion:
    kind: RecommendationInputKind
    resource_id: str
    version: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", RecommendationInputKind(self.kind))
        resource_id = self.resource_id.strip()
        version = self.version.strip()
        if not resource_id or not version:
            raise RecommendationRuleViolation("input resource identity and version are required")
        _require_hash(self.sha256, "input fingerprint")
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "version", version)

    @property
    def identity(self) -> tuple[str, str]:
        return (self.kind.value, self.resource_id)


@dataclass(frozen=True)
class RecommendationScope:
    project_id: UUID
    applicable_version: str
    campaign_id: UUID | None = None
    question_or_cluster_ref: str | None = None
    surface_ref: str | None = None
    content_asset_ref: str | None = None
    url_ref: str | None = None

    def __post_init__(self) -> None:
        version = self.applicable_version.strip()
        if not version:
            raise RecommendationRuleViolation("recommendation scope version is required")
        object.__setattr__(self, "applicable_version", version)
        for field_name in (
            "question_or_cluster_ref",
            "surface_ref",
            "content_asset_ref",
            "url_ref",
        ):
            object.__setattr__(self, field_name, _clean_optional(getattr(self, field_name)))

    def canonical_value(self) -> dict[str, object]:
        return {
            "project_id": str(self.project_id),
            "campaign_id": str(self.campaign_id) if self.campaign_id else None,
            "question_or_cluster_ref": self.question_or_cluster_ref,
            "surface_ref": self.surface_ref,
            "content_asset_ref": self.content_asset_ref,
            "url_ref": self.url_ref,
            "applicable_version": self.applicable_version,
        }


@dataclass(frozen=True, kw_only=True)
class VersionedEvidenceRef:
    project_id: UUID
    resource_id: str
    version: str
    sha256: str
    locator: Mapping[str, str]
    valid: bool = True

    ref_kind: ClassVar[str]
    input_kind: ClassVar[RecommendationInputKind]

    def __post_init__(self) -> None:
        resource_id = self.resource_id.strip()
        version = self.version.strip()
        if not resource_id or not version:
            raise RecommendationRuleViolation(
                f"{self.ref_kind} resource identity and version are required"
            )
        _require_hash(self.sha256, f"{self.ref_kind} hash")
        locator = _freeze_locator(self.locator, self.ref_kind)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "locator", locator)

    @property
    def identity(self) -> tuple[str, str]:
        return (self.ref_kind, self.resource_id)

    @property
    def current_and_valid(self) -> bool:
        return self.valid

    def input_versions(self) -> tuple[RecommendationInputVersion, ...]:
        return (
            RecommendationInputVersion(
                kind=self.input_kind,
                resource_id=self.resource_id,
                version=self.version,
                sha256=self.sha256,
            ),
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "kind": self.ref_kind,
            "project_id": str(self.project_id),
            "resource_id": self.resource_id,
            "version": self.version,
            "sha256": self.sha256,
            "locator": dict(self.locator),
            "valid": self.valid,
            **self.detail_value(),
        }

    def legacy_canonical_value(self) -> dict[str, object]:
        """Canonical value used by persisted v1 graphs and generation specs."""

        return {
            "kind": self.ref_kind,
            "project_id": str(self.project_id),
            "resource_id": self.resource_id,
            "version": self.version,
            "sha256": self.sha256,
            "locator": dict(self.locator),
            "valid": self.valid,
            **self.legacy_detail_value(),
        }

    def detail_value(self) -> dict[str, object]:
        return {}

    def legacy_detail_value(self) -> dict[str, object]:
        return self.detail_value()


@dataclass(frozen=True, kw_only=True)
class ObservationRef(VersionedEvidenceRef):
    capture_method: str
    evidence_class: ObservationEvidenceClass
    question_resource_id: str
    surface_resource_id: str
    eligible: bool

    ref_kind: ClassVar[str] = "observation"
    input_kind: ClassVar[RecommendationInputKind] = RecommendationInputKind.OBSERVATION

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "evidence_class", ObservationEvidenceClass(self.evidence_class))
        for field_name in ("capture_method", "question_resource_id", "surface_resource_id"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), f"observation {field_name}"),
            )

    @property
    def current_and_valid(self) -> bool:
        return self.valid and self.eligible

    @property
    def is_real(self) -> bool:
        return (
            self.current_and_valid
            and self.evidence_class == ObservationEvidenceClass.REAL_OBSERVATION
        )

    def detail_value(self) -> dict[str, object]:
        return {
            "capture_method": self.capture_method,
            "evidence_class": self.evidence_class.value,
            "question_resource_id": self.question_resource_id,
            "surface_resource_id": self.surface_resource_id,
            "eligible": self.eligible,
        }


@dataclass(frozen=True, kw_only=True)
class MetricComparisonRef(VersionedEvidenceRef):
    observation_resource_ids: tuple[str, ...]
    method_version: str
    method_sha256: str
    sufficient_evidence: bool
    conclusion: MetricComparisonConclusion | None = None

    ref_kind: ClassVar[str] = "metric_comparison"
    input_kind: ClassVar[RecommendationInputKind] = RecommendationInputKind.COMPARISON

    def __post_init__(self) -> None:
        super().__post_init__()
        observations = _normalise_ids(
            self.observation_resource_ids, "metric comparison observations"
        )
        method_version = _required_text(self.method_version, "metric method version")
        _require_hash(self.method_sha256, "metric method hash")
        conclusion = self.conclusion
        if conclusion is None:
            # Frozen jobs written before the conclusion field existed stay conservative.
            conclusion = (
                MetricComparisonConclusion.INCONCLUSIVE
                if self.sufficient_evidence
                else MetricComparisonConclusion.INSUFFICIENT_EVIDENCE
            )
        else:
            conclusion = MetricComparisonConclusion(conclusion)
        if self.sufficient_evidence is not (
            conclusion is not MetricComparisonConclusion.INSUFFICIENT_EVIDENCE
        ):
            raise RecommendationRuleViolation(
                "metric comparison sufficiency and conclusion are inconsistent"
            )
        object.__setattr__(self, "observation_resource_ids", observations)
        object.__setattr__(self, "method_version", method_version)
        object.__setattr__(self, "conclusion", conclusion)

    @property
    def current_and_valid(self) -> bool:
        return self.valid and self.sufficient_evidence

    def input_versions(self) -> tuple[RecommendationInputVersion, ...]:
        return (
            *super().input_versions(),
            RecommendationInputVersion(
                kind=RecommendationInputKind.METHOD_VERSION,
                resource_id=f"{self.resource_id}:method",
                version=self.method_version,
                sha256=self.method_sha256,
            ),
        )

    def detail_value(self) -> dict[str, object]:
        conclusion = self.conclusion
        if conclusion is None:  # Normalized in __post_init__; keeps the type invariant explicit.
            raise RecommendationRuleViolation("metric comparison conclusion is missing")
        return {
            "observation_resource_ids": list(self.observation_resource_ids),
            "method_version": self.method_version,
            "method_sha256": self.method_sha256,
            "sufficient_evidence": self.sufficient_evidence,
            "conclusion": conclusion.value,
        }

    def legacy_detail_value(self) -> dict[str, object]:
        return {
            "observation_resource_ids": list(self.observation_resource_ids),
            "method_version": self.method_version,
            "method_sha256": self.method_sha256,
            "sufficient_evidence": self.sufficient_evidence,
        }


@dataclass(frozen=True, kw_only=True)
class FactRef(VersionedEvidenceRef):
    approved: bool
    retired: bool

    ref_kind: ClassVar[str] = "fact"
    input_kind: ClassVar[RecommendationInputKind] = RecommendationInputKind.FACT

    @property
    def current_and_valid(self) -> bool:
        return self.valid and self.approved and not self.retired

    def detail_value(self) -> dict[str, object]:
        return {"approved": self.approved, "retired": self.retired}


@dataclass(frozen=True, kw_only=True)
class RuleRef(VersionedEvidenceRef):
    active: bool
    kind: RecommendationRuleKind = RecommendationRuleKind.THRESHOLD
    severity: RecommendationRuleSeverity = RecommendationRuleSeverity.INFO
    trigger_status: RecommendationRuleTriggerStatus = (
        RecommendationRuleTriggerStatus.NOT_TRIGGERED
    )

    ref_kind: ClassVar[str] = "rule"
    input_kind: ClassVar[RecommendationInputKind] = RecommendationInputKind.RULE_VERSION

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "kind", RecommendationRuleKind(self.kind))
        object.__setattr__(self, "severity", RecommendationRuleSeverity(self.severity))
        object.__setattr__(
            self,
            "trigger_status",
            RecommendationRuleTriggerStatus(self.trigger_status),
        )

    @property
    def current_and_valid(self) -> bool:
        return self.valid and self.active

    @property
    def triggered(self) -> bool:
        return self.current_and_valid and self.trigger_status in {
            RecommendationRuleTriggerStatus.OPEN,
            RecommendationRuleTriggerStatus.ACKNOWLEDGED,
        }

    def detail_value(self) -> dict[str, object]:
        return {
            "active": self.active,
            "rule_kind": self.kind.value,
            "severity": self.severity.value,
            "trigger_status": self.trigger_status.value,
        }

    def legacy_detail_value(self) -> dict[str, object]:
        return {"active": self.active}


@dataclass(frozen=True, kw_only=True)
class PromptReleaseRef(VersionedEvidenceRef):
    approved: bool
    frozen: bool

    ref_kind: ClassVar[str] = "prompt_release"
    input_kind: ClassVar[RecommendationInputKind] = RecommendationInputKind.PROMPT_RELEASE

    @property
    def current_and_valid(self) -> bool:
        return self.valid and self.approved and self.frozen

    def detail_value(self) -> dict[str, object]:
        return {"approved": self.approved, "frozen": self.frozen}


@dataclass(frozen=True, kw_only=True)
class ModelCallRef(VersionedEvidenceRef):
    prompt_release_resource_id: str
    model_identity: str
    succeeded: bool

    ref_kind: ClassVar[str] = "model_call"
    input_kind: ClassVar[RecommendationInputKind] = RecommendationInputKind.MODEL_CALL

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self,
            "prompt_release_resource_id",
            _required_text(self.prompt_release_resource_id, "model call Prompt Release"),
        )
        object.__setattr__(
            self, "model_identity", _required_text(self.model_identity, "model identity")
        )

    @property
    def current_and_valid(self) -> bool:
        return self.valid and self.succeeded

    def detail_value(self) -> dict[str, object]:
        return {
            "prompt_release_resource_id": self.prompt_release_resource_id,
            "model_identity": self.model_identity,
            "succeeded": self.succeeded,
        }


@dataclass(frozen=True, kw_only=True)
class ContentRef(VersionedEvidenceRef):
    current: bool

    ref_kind: ClassVar[str] = "content"
    input_kind: ClassVar[RecommendationInputKind] = RecommendationInputKind.CONTENT_VERSION

    @property
    def current_and_valid(self) -> bool:
        return self.valid and self.current

    def detail_value(self) -> dict[str, object]:
        return {"current": self.current}


@dataclass(frozen=True, kw_only=True)
class QuestionRef(VersionedEvidenceRef):
    active: bool

    ref_kind: ClassVar[str] = "question"
    input_kind: ClassVar[RecommendationInputKind] = RecommendationInputKind.QUESTION_VERSION

    @property
    def current_and_valid(self) -> bool:
        return self.valid and self.active

    def detail_value(self) -> dict[str, object]:
        return {"active": self.active}


@dataclass(frozen=True, kw_only=True)
class SurfaceRef(VersionedEvidenceRef):
    active: bool

    ref_kind: ClassVar[str] = "surface"
    input_kind: ClassVar[RecommendationInputKind] = RecommendationInputKind.SURFACE_RELEASE

    @property
    def current_and_valid(self) -> bool:
        return self.valid and self.active

    def detail_value(self) -> dict[str, object]:
        return {"active": self.active}


@dataclass(frozen=True, kw_only=True)
class AttributionRef(VersionedEvidenceRef):
    """An explicit availability boundary, never a synthetic attribution result."""

    available: bool
    reason: str

    ref_kind: ClassVar[str] = "attribution"
    input_kind: ClassVar[RecommendationInputKind] = (
        RecommendationInputKind.ATTRIBUTION_AVAILABILITY
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self, "reason", _required_text(self.reason, "attribution availability reason")
        )

    @property
    def current_and_valid(self) -> bool:
        return self.valid and self.available

    def detail_value(self) -> dict[str, object]:
        return {"available": self.available, "reason": self.reason}


EvidenceRef = (
    ObservationRef
    | MetricComparisonRef
    | FactRef
    | RuleRef
    | PromptReleaseRef
    | ModelCallRef
    | ContentRef
    | QuestionRef
    | SurfaceRef
    | AttributionRef
)


def _freeze_locator(locator: Mapping[str, str], label: str) -> Mapping[str, str]:
    if not locator:
        raise RecommendationRuleViolation(f"{label} locator is required")
    frozen: dict[str, str] = {}
    for raw_key, raw_value in locator.items():
        key = _required_text(raw_key, f"{label} locator key")
        value = _required_text(raw_value, f"{label} locator value")
        if key in frozen:
            raise RecommendationRuleViolation(f"{label} locator keys must be unique")
        frozen[key] = value
    return MappingProxyType(dict(sorted(frozen.items())))


def _normalise_ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    result = tuple(sorted({_required_text(value, label) for value in values}))
    if not result:
        raise RecommendationRuleViolation(f"{label} are required")
    return result


def _canonical_hash(value: object) -> str:
    serialized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _required_text(value: str, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise RecommendationRuleViolation(f"{label} is required")
    return clean


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def _require_hash(value: str, label: str) -> None:
    if not SHA256_PATTERN.fullmatch(value):
        raise RecommendationRuleViolation(f"{label} must be lowercase SHA-256")


from geo_core.recommendations.evidence_graph import (  # noqa: E402
    RecommendationEvidenceGraph as RecommendationEvidenceGraph,
    freeze_input_versions as freeze_input_versions,
    input_fingerprint as input_fingerprint,
)
