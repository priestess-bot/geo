"""Cross-question negative gain and worst-question/cluster summaries."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from geo_core.statistical_methods.contracts import (
    StatisticalRuleViolation,
    canonical_hash,
    decimal_value,
)


TWELVE_PLACES = Decimal("0.000000000001")


@dataclass(frozen=True, order=True)
class QuestionEffect:
    question_id: str
    question_cluster: str
    effect: Decimal
    interval_low: Decimal
    interval_high: Decimal

    def __post_init__(self) -> None:
        if not self.question_id.strip() or not self.question_cluster.strip():
            raise StatisticalRuleViolation("question effect identity is required")
        for value in (self.effect, self.interval_low, self.interval_high):
            if not value.is_finite():
                raise StatisticalRuleViolation("question effect values must be finite")
        if self.interval_low > self.interval_high:
            raise StatisticalRuleViolation("question effect interval is reversed")


@dataclass(frozen=True, order=True)
class ClusterEffect:
    question_cluster: str
    question_count: int
    mean_effect: Decimal


@dataclass(frozen=True)
class NegativeGainReport:
    question_count: int
    affected_question_count: int
    average_effect: Decimal
    mean_negative_gain: Decimal
    negative_range_low: Decimal
    negative_range_high: Decimal
    worst_question_id: str | None
    worst_question_effect: Decimal | None
    clusters: tuple[ClusterEffect, ...]
    worst_cluster: str
    worst_cluster_effect: Decimal
    method_version: str = "negative-gain-v1"
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.question_count < 1 or not 0 <= self.affected_question_count <= self.question_count:
            raise StatisticalRuleViolation("negative-gain counts are inconsistent")
        if not self.clusters:
            raise StatisticalRuleViolation("negative-gain report requires cluster results")
        if (self.affected_question_count == 0) != (self.worst_question_id is None):
            raise StatisticalRuleViolation("negative-gain worst question is inconsistent")
        object.__setattr__(self, "result_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "question_count": self.question_count,
            "affected_question_count": self.affected_question_count,
            "average_effect": decimal_value(self.average_effect),
            "mean_negative_gain": decimal_value(self.mean_negative_gain),
            "negative_range_low": decimal_value(self.negative_range_low),
            "negative_range_high": decimal_value(self.negative_range_high),
            "worst_question_id": self.worst_question_id,
            "worst_question_effect": decimal_value(self.worst_question_effect),
            "clusters": [
                {
                    "question_cluster": item.question_cluster,
                    "question_count": item.question_count,
                    "mean_effect": decimal_value(item.mean_effect),
                }
                for item in self.clusters
            ],
            "worst_cluster": self.worst_cluster,
            "worst_cluster_effect": decimal_value(self.worst_cluster_effect),
            "method_version": self.method_version,
        }


def summarize_negative_gain(
    effects: Sequence[QuestionEffect],
) -> NegativeGainReport:
    ordered = tuple(sorted(effects))
    if not ordered or len({item.question_id for item in ordered}) != len(ordered):
        raise StatisticalRuleViolation("question effects must be non-empty and unique")
    negative = tuple(item for item in ordered if item.effect < 0)
    cluster_values: dict[str, list[Decimal]] = defaultdict(list)
    for item in ordered:
        cluster_values[item.question_cluster].append(item.effect)
    clusters = tuple(
        sorted(
            ClusterEffect(cluster, len(values), _mean(values))
            for cluster, values in cluster_values.items()
        )
    )
    worst_cluster = min(clusters, key=lambda item: (item.mean_effect, item.question_cluster))
    if negative:
        worst_question = min(negative, key=lambda item: (item.effect, item.question_id))
        mean_negative = _mean([item.effect for item in negative])
        interval_low = min(item.interval_low for item in negative)
        interval_high = max(item.interval_high for item in negative)
        worst_id: str | None = worst_question.question_id
        worst_effect: Decimal | None = worst_question.effect
    else:
        mean_negative = interval_low = interval_high = Decimal(0)
        worst_id = None
        worst_effect = None
    return NegativeGainReport(
        question_count=len(ordered),
        affected_question_count=len(negative),
        average_effect=_mean([item.effect for item in ordered]),
        mean_negative_gain=mean_negative,
        negative_range_low=_quantize(interval_low),
        negative_range_high=_quantize(interval_high),
        worst_question_id=worst_id,
        worst_question_effect=worst_effect,
        clusters=clusters,
        worst_cluster=worst_cluster.question_cluster,
        worst_cluster_effect=worst_cluster.mean_effect,
    )


def _mean(values: Sequence[Decimal]) -> Decimal:
    return _quantize(sum(values, Decimal(0)) / Decimal(len(values)))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWELVE_PLACES, rounding=ROUND_HALF_UP)
