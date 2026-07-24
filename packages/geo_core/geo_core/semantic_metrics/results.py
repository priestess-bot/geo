"""Frozen per-metric result records with auditable denominator and lineage."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import re

from geo_core.semantic_metrics.contracts import (
    EvidenceLocator,
    MetricKey,
    MetricStatus,
    MetricValueKind,
    SemanticMetricRuleViolation,
    canonical_hash,
    decimal_value,
)


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,199}$")


@dataclass(frozen=True)
class MetricInterval:
    method: str
    confidence_level: Decimal | None
    low: Decimal
    high: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", _key(self.method, "metric interval method"))
        _finite(self.low, "metric interval lower bound")
        _finite(self.high, "metric interval upper bound")
        if self.low > self.high:
            raise SemanticMetricRuleViolation("metric interval is reversed")
        if self.confidence_level is not None and not (
            Decimal(0) < self.confidence_level < Decimal(1)
        ):
            raise SemanticMetricRuleViolation("metric confidence level must be in (0, 1)")

    def canonical_value(self) -> dict[str, object]:
        return {
            "method": self.method,
            "confidence_level": decimal_value(self.confidence_level),
            "low": decimal_value(self.low),
            "high": decimal_value(self.high),
        }


@dataclass(frozen=True)
class SemanticMetricResult:
    metric_key: MetricKey
    metric_version: str
    value_kind: MetricValueKind
    input_set_hash: str
    stratum: tuple[tuple[str, str], ...]
    stratum_hash: str
    numerator: Decimal
    denominator: int
    estimate: Decimal
    interval: MetricInterval
    valid_input_count: int
    invalid_input_count: int
    missing_input_count: int
    status: MetricStatus
    judge_version: str | None
    judge_version_hash: str | None
    rule_versions: tuple[tuple[str, str], ...]
    rule_versions_hash: str
    evidence_locators: tuple[EvidenceLocator, ...] = ()
    breakdown: tuple[tuple[str, Decimal], ...] = ()
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_key", MetricKey(self.metric_key))
        object.__setattr__(self, "metric_version", _key(self.metric_version, "metric version"))
        object.__setattr__(self, "value_kind", MetricValueKind(self.value_kind))
        object.__setattr__(self, "status", MetricStatus(self.status))
        for value, label in (
            (self.numerator, "metric numerator"),
            (self.estimate, "metric estimate"),
        ):
            _finite(value, label)
        counts = (self.valid_input_count, self.invalid_input_count, self.missing_input_count)
        if self.denominator < 0 or min(counts) < 0:
            raise SemanticMetricRuleViolation("metric counts must be non-negative")
        if sum(counts) != self.denominator:
            raise SemanticMetricRuleViolation(
                "metric counts do not preserve the frozen denominator"
            )
        stratum = tuple(
            sorted((_key(key, "metric stratum key"), value.strip()) for key, value in self.stratum)
        )
        if (
            not stratum
            or any(not value for _, value in stratum)
            or len({key for key, _ in stratum}) != len(stratum)
            or canonical_hash(dict(stratum)) != self.stratum_hash
        ):
            raise SemanticMetricRuleViolation("metric stratum dimensions are inconsistent")
        for digest, label in (
            (self.input_set_hash, "metric input set hash"),
            (self.stratum_hash, "metric stratum hash"),
            (self.rule_versions_hash, "metric rule versions hash"),
        ):
            if not SHA256_PATTERN.fullmatch(digest):
                raise SemanticMetricRuleViolation(f"{label} must be SHA-256")
        if self.judge_version_hash is not None and not SHA256_PATTERN.fullmatch(
            self.judge_version_hash
        ):
            raise SemanticMetricRuleViolation("metric judge version hash must be SHA-256")
        judge_version = (
            _key(self.judge_version, "metric judge version")
            if self.judge_version is not None
            else None
        )
        if (judge_version is None) != (self.judge_version_hash is None):
            raise SemanticMetricRuleViolation("metric judge version lineage is incomplete")
        rule_versions = tuple(
            sorted(
                (_key(key, "metric rule key"), _key(version, "metric rule version"))
                for key, version in self.rule_versions
            )
        )
        if (
            not rule_versions
            or len({key for key, _ in rule_versions}) != len(rule_versions)
            or canonical_hash(dict(rule_versions)) != self.rule_versions_hash
        ):
            raise SemanticMetricRuleViolation("metric rule versions must be non-empty and unique")
        locators = tuple(sorted(set(self.evidence_locators), key=_locator_sort_key))
        breakdown = tuple(
            sorted((_key(key, "metric breakdown key"), value) for key, value in self.breakdown)
        )
        for _, value in breakdown:
            _finite(value, "metric breakdown value")
        object.__setattr__(self, "evidence_locators", locators)
        object.__setattr__(self, "breakdown", breakdown)
        object.__setattr__(self, "stratum", stratum)
        object.__setattr__(self, "judge_version", judge_version)
        object.__setattr__(self, "rule_versions", rule_versions)
        object.__setattr__(self, "result_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "metric_key": self.metric_key.value,
            "metric_version": self.metric_version,
            "value_kind": self.value_kind.value,
            "input_set_hash": self.input_set_hash,
            "stratum": dict(self.stratum),
            "stratum_hash": self.stratum_hash,
            "numerator": decimal_value(self.numerator),
            "denominator": self.denominator,
            "estimate": decimal_value(self.estimate),
            "interval": self.interval.canonical_value(),
            "valid_input_count": self.valid_input_count,
            "invalid_input_count": self.invalid_input_count,
            "missing_input_count": self.missing_input_count,
            "status": self.status.value,
            "judge_version": self.judge_version,
            "judge_version_hash": self.judge_version_hash,
            "rule_versions": dict(self.rule_versions),
            "rule_versions_hash": self.rule_versions_hash,
            "evidence_locators": [item.canonical_value() for item in self.evidence_locators],
            "breakdown": {key: decimal_value(value) for key, value in self.breakdown},
        }


def _locator_sort_key(locator: EvidenceLocator) -> tuple[object, ...]:
    return (
        locator.kind.value,
        locator.reference_id,
        locator.version or "",
        locator.content_hash or "",
        locator.start if locator.start is not None else -1,
        locator.end if locator.end is not None else -1,
        locator.redacted_quote_hash or "",
    )


def _key(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if not KEY_PATTERN.fullmatch(normalized):
        raise SemanticMetricRuleViolation(f"{label} is invalid")
    return normalized


def _finite(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise SemanticMetricRuleViolation(f"{label} must be a finite Decimal")
