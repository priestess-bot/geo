"""Frozen contracts for reproducible statistical comparisons."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import re


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,199}$")


class StatisticalRuleViolation(ValueError):
    """A statistical input or frozen method contract is invalid."""


class ComparisonConclusion(StrEnum):
    WIN = "win"
    EQUIVALENT = "equivalent"
    LOSS = "loss"
    INCONCLUSIVE = "inconclusive"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, order=True)
class StatisticalStratum:
    provider: str
    reported_model: str
    capture_method: str
    locale: str
    region: str
    source_composition_hash: str
    sampling_source_stratum_hash: str
    question_cluster: str
    stratum_hash: str = field(init=False, compare=False)

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "reported_model",
            "capture_method",
            "locale",
            "region",
            "question_cluster",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), f"stratum {name}"))
        if not SHA256_PATTERN.fullmatch(
            self.source_composition_hash
        ) or not SHA256_PATTERN.fullmatch(self.sampling_source_stratum_hash):
            raise StatisticalRuleViolation("source lineage hashes must be SHA-256")
        object.__setattr__(self, "stratum_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "reported_model": self.reported_model,
            "capture_method": self.capture_method,
            "locale": self.locale,
            "region": self.region,
            "source_composition_hash": self.source_composition_hash,
            "sampling_source_stratum_hash": self.sampling_source_stratum_hash,
            "question_cluster": self.question_cluster,
        }


@dataclass(frozen=True)
class FrozenComparisonProtocol:
    protocol_hash: str
    question_set_hash: str
    baseline_version: str
    candidate_version: str
    metric_key: str
    metric_method_version: str
    comparison_id: str
    family: str
    stratum: StatisticalStratum
    alpha: Decimal
    delta: Decimal
    target_power: Decimal
    precision: Decimal
    min_pairs: int
    power_plan_hash: str
    a_priori_design_power: Decimal
    power_method_version: str = "a-priori-design-power-v1"
    minimum_completion_ratio: Decimal = Decimal("0.80")
    bootstrap_iterations: int = 10_000
    bootstrap_method: str = "paired-bootstrap-percentile-v1"
    correction_method: str = "holm-v1"
    simultaneous_interval_method: str = "paired-bootstrap-percentile-bonferroni-family-v1"
    frozen_hash: str = field(init=False)
    seed_hex: str = field(init=False)

    def __post_init__(self) -> None:
        for digest, label in (
            (self.protocol_hash, "protocol hash"),
            (self.question_set_hash, "QuestionSet hash"),
            (self.power_plan_hash, "power plan hash"),
        ):
            if not SHA256_PATTERN.fullmatch(digest):
                raise StatisticalRuleViolation(f"{label} must be SHA-256")
        for name in (
            "baseline_version",
            "candidate_version",
            "metric_key",
            "metric_method_version",
            "comparison_id",
            "family",
            "bootstrap_method",
            "correction_method",
            "simultaneous_interval_method",
            "power_method_version",
        ):
            object.__setattr__(self, name, _key(getattr(self, name), name))
        for value, label in (
            (self.alpha, "alpha"),
            (self.delta, "delta"),
            (self.target_power, "target power"),
            (self.precision, "precision"),
            (self.minimum_completion_ratio, "minimum completion ratio"),
            (self.a_priori_design_power, "a-priori design power"),
        ):
            _finite(value, label)
        if not Decimal(0) < self.alpha < Decimal(1):
            raise StatisticalRuleViolation("alpha must be in (0, 1)")
        if self.delta < 0 or self.precision <= 0:
            raise StatisticalRuleViolation("delta must be non-negative and precision positive")
        if not Decimal("0.80") <= self.target_power <= Decimal(1):
            raise StatisticalRuleViolation("target power must be in [0.80, 1]")
        if not Decimal(0) <= self.a_priori_design_power <= Decimal(1):
            raise StatisticalRuleViolation("a-priori design power must be in [0, 1]")
        if not Decimal(0) < self.minimum_completion_ratio <= Decimal(1):
            raise StatisticalRuleViolation("minimum completion ratio must be in (0, 1]")
        if self.min_pairs < 1 or self.bootstrap_iterations < 100:
            raise StatisticalRuleViolation("min pairs and bootstrap iterations are too small")
        seed_hex = canonical_hash(
            {
                "protocol_hash": self.protocol_hash,
                "question_set_hash": self.question_set_hash,
                "baseline_version": self.baseline_version,
                "candidate_version": self.candidate_version,
                "metric_method_version": self.metric_method_version,
                "comparison_id": self.comparison_id,
            }
        )
        object.__setattr__(self, "seed_hex", seed_hex)
        object.__setattr__(self, "frozen_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "protocol_hash": self.protocol_hash,
            "question_set_hash": self.question_set_hash,
            "baseline_version": self.baseline_version,
            "candidate_version": self.candidate_version,
            "metric_key": self.metric_key,
            "metric_method_version": self.metric_method_version,
            "comparison_id": self.comparison_id,
            "family": self.family,
            "stratum": self.stratum.canonical_value(),
            "alpha": decimal_value(self.alpha),
            "delta": decimal_value(self.delta),
            "target_power": decimal_value(self.target_power),
            "precision": decimal_value(self.precision),
            "min_pairs": self.min_pairs,
            "power_plan_hash": self.power_plan_hash,
            "a_priori_design_power": decimal_value(self.a_priori_design_power),
            "power_method_version": self.power_method_version,
            "minimum_completion_ratio": decimal_value(self.minimum_completion_ratio),
            "bootstrap_iterations": self.bootstrap_iterations,
            "bootstrap_method": self.bootstrap_method,
            "correction_method": self.correction_method,
            "simultaneous_interval_method": self.simultaneous_interval_method,
            "seed_hex": self.seed_hex,
        }


@dataclass(frozen=True, order=True)
class PairedObservation:
    pair_id: str
    question_id: str
    question_cluster: str
    stratum_hash: str
    sampling_source_stratum_hash: str
    capture_method: str
    baseline: Decimal
    candidate: Decimal

    def __post_init__(self) -> None:
        for name in ("pair_id", "question_id", "question_cluster", "capture_method"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not SHA256_PATTERN.fullmatch(
            self.stratum_hash
        ) or not SHA256_PATTERN.fullmatch(self.sampling_source_stratum_hash):
            raise StatisticalRuleViolation("pair stratum lineage must be SHA-256")
        _finite(self.baseline, "paired baseline value")
        _finite(self.candidate, "paired candidate value")

    @property
    def delta(self) -> Decimal:
        return self.candidate - self.baseline

    def canonical_value(self) -> dict[str, object]:
        return {
            "pair_id": self.pair_id,
            "question_id": self.question_id,
            "question_cluster": self.question_cluster,
            "stratum_hash": self.stratum_hash,
            "sampling_source_stratum_hash": self.sampling_source_stratum_hash,
            "capture_method": self.capture_method,
            "baseline": decimal_value(self.baseline),
            "candidate": decimal_value(self.candidate),
        }


@dataclass(frozen=True)
class ComparisonInput:
    protocol: FrozenComparisonProtocol
    sampling_source_stratum_hash: str
    planned_pair_count: int
    pairs: tuple[PairedObservation, ...]
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        pairs = tuple(sorted(self.pairs))
        if (
            not SHA256_PATTERN.fullmatch(self.sampling_source_stratum_hash)
            or self.sampling_source_stratum_hash
            != self.protocol.stratum.sampling_source_stratum_hash
        ):
            raise StatisticalRuleViolation(
                "ComparisonInput must freeze the complete Sampling SourceStratum hash"
            )
        if len({item.pair_id for item in pairs}) != len(pairs):
            raise StatisticalRuleViolation("paired observation ids must be unique")
        if self.planned_pair_count < 1 or len(pairs) > self.planned_pair_count:
            raise StatisticalRuleViolation("planned and valid pair counts are inconsistent")
        for item in pairs:
            if (
                item.stratum_hash != self.protocol.stratum.stratum_hash
                or item.sampling_source_stratum_hash != self.sampling_source_stratum_hash
                or item.capture_method != self.protocol.stratum.capture_method
                or item.question_cluster != self.protocol.stratum.question_cluster
            ):
                raise StatisticalRuleViolation(
                    "paired observations cannot mix frozen strata or capture methods"
                )
        object.__setattr__(self, "pairs", pairs)
        object.__setattr__(
            self,
            "input_hash",
            canonical_hash(
                {
                    "protocol_frozen_hash": self.protocol.frozen_hash,
                    "planned_pair_count": self.planned_pair_count,
                    "sampling_source_stratum_hash": self.sampling_source_stratum_hash,
                    "pairs": [item.canonical_value() for item in pairs],
                }
            ),
        )


@dataclass(frozen=True)
class StatisticalInterval:
    method: str
    alpha: Decimal
    low: Decimal
    high: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", _key(self.method, "interval method"))
        _finite(self.alpha, "interval alpha")
        _finite(self.low, "interval lower bound")
        _finite(self.high, "interval upper bound")
        if not Decimal(0) < self.alpha < Decimal(1) or self.low > self.high:
            raise StatisticalRuleViolation("statistical interval is invalid")

    @property
    def half_width(self) -> Decimal:
        return (self.high - self.low) / Decimal(2)

    def canonical_value(self) -> dict[str, object]:
        return {
            "method": self.method,
            "alpha": decimal_value(self.alpha),
            "low": decimal_value(self.low),
            "high": decimal_value(self.high),
        }


@dataclass(frozen=True)
class BootstrapEstimate:
    point_estimate: Decimal
    interval: StatisticalInterval
    two_sided_p_value: Decimal
    seed_hex: str
    iterations: int
    distribution_hash: str

    def __post_init__(self) -> None:
        _finite(self.point_estimate, "bootstrap point estimate")
        _finite(self.two_sided_p_value, "bootstrap p-value")
        if not Decimal(0) <= self.two_sided_p_value <= Decimal(1):
            raise StatisticalRuleViolation("bootstrap p-value must be in [0, 1]")
        if not SHA256_PATTERN.fullmatch(self.seed_hex) or not SHA256_PATTERN.fullmatch(
            self.distribution_hash
        ):
            raise StatisticalRuleViolation("bootstrap hashes must be SHA-256")
        if self.iterations < 100:
            raise StatisticalRuleViolation("bootstrap result iteration count is too small")


@dataclass(frozen=True)
class HolmAdjustment:
    comparison_id: str
    rank: int
    raw_p_value: Decimal
    adjusted_p_value: Decimal
    local_alpha: Decimal
    rejected: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "comparison_id", _key(self.comparison_id, "comparison id"))
        for value, label in (
            (self.raw_p_value, "raw p-value"),
            (self.adjusted_p_value, "adjusted p-value"),
            (self.local_alpha, "Holm local alpha"),
        ):
            _finite(value, label)
        if (
            self.rank < 1
            or not Decimal(0) <= self.raw_p_value <= Decimal(1)
            or not Decimal(0) <= self.adjusted_p_value <= Decimal(1)
            or not Decimal(0) < self.local_alpha < Decimal(1)
        ):
            raise StatisticalRuleViolation("Holm adjustment is invalid")


@dataclass(frozen=True)
class ComparisonResult:
    comparison_id: str
    family: str
    protocol_frozen_hash: str
    input_hash: str
    stratum_hash: str
    valid_pair_count: int
    planned_pair_count: int
    completion_ratio: Decimal
    point_estimate: Decimal
    raw_interval: StatisticalInterval
    adjusted_interval: StatisticalInterval
    raw_p_value: Decimal
    adjusted_p_value: Decimal
    holm_rank: int
    local_alpha: Decimal
    a_priori_design_power: Decimal
    power_plan_hash: str
    power_method_version: str
    conclusion: ComparisonConclusion
    seed_hex: str
    bootstrap_iterations: int
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "comparison_id", _key(self.comparison_id, "comparison id"))
        object.__setattr__(self, "family", _key(self.family, "comparison family"))
        object.__setattr__(self, "conclusion", ComparisonConclusion(self.conclusion))
        if not 0 <= self.valid_pair_count <= self.planned_pair_count or self.planned_pair_count < 1:
            raise StatisticalRuleViolation("comparison result pair counts are inconsistent")
        for value, label in (
            (self.completion_ratio, "completion ratio"),
            (self.point_estimate, "comparison point estimate"),
            (self.raw_p_value, "raw p-value"),
            (self.adjusted_p_value, "adjusted p-value"),
            (self.local_alpha, "local alpha"),
        ):
            _finite(value, label)
        if (
            not Decimal(0) <= self.completion_ratio <= Decimal(1)
            or not Decimal(0) <= self.raw_p_value <= Decimal(1)
            or not Decimal(0) <= self.adjusted_p_value <= Decimal(1)
            or not Decimal(0) < self.local_alpha < Decimal(1)
            or self.holm_rank < 1
            or self.bootstrap_iterations < 100
        ):
            raise StatisticalRuleViolation("comparison result statistical fields are invalid")
        _finite(self.a_priori_design_power, "comparison a-priori design power")
        if not Decimal(0) <= self.a_priori_design_power <= Decimal(1):
            raise StatisticalRuleViolation("comparison a-priori design power must be in [0, 1]")
        object.__setattr__(
            self,
            "power_method_version",
            _key(self.power_method_version, "power method version"),
        )
        for digest in (
            self.protocol_frozen_hash,
            self.input_hash,
            self.stratum_hash,
            self.seed_hex,
            self.power_plan_hash,
        ):
            if not SHA256_PATTERN.fullmatch(digest):
                raise StatisticalRuleViolation("comparison result lineage hash is invalid")
        object.__setattr__(self, "result_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "comparison_id": self.comparison_id,
            "family": self.family,
            "protocol_frozen_hash": self.protocol_frozen_hash,
            "input_hash": self.input_hash,
            "stratum_hash": self.stratum_hash,
            "valid_pair_count": self.valid_pair_count,
            "planned_pair_count": self.planned_pair_count,
            "completion_ratio": decimal_value(self.completion_ratio),
            "point_estimate": decimal_value(self.point_estimate),
            "raw_interval": self.raw_interval.canonical_value(),
            "adjusted_interval": self.adjusted_interval.canonical_value(),
            "raw_p_value": decimal_value(self.raw_p_value),
            "adjusted_p_value": decimal_value(self.adjusted_p_value),
            "holm_rank": self.holm_rank,
            "local_alpha": decimal_value(self.local_alpha),
            "a_priori_design_power": decimal_value(self.a_priori_design_power),
            "power_plan_hash": self.power_plan_hash,
            "power_method_version": self.power_method_version,
            "conclusion": self.conclusion.value,
            "seed_hex": self.seed_hex,
            "bootstrap_iterations": self.bootstrap_iterations,
        }


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def decimal_value(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _finite(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise StatisticalRuleViolation(f"{label} must be a finite Decimal")


def _key(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if not KEY_PATTERN.fullmatch(normalized):
        raise StatisticalRuleViolation(f"{label} is invalid")
    return normalized


def _text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise StatisticalRuleViolation(f"{label} is required and bounded")
    return normalized
