"""Worst-question, cluster and cross-query negative-gain aggregation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from geo_core.semantic_metrics.contracts import (
    BaselineQuestionScore,
    PlannedMetricSlot,
    SemanticMetricRuleViolation,
)


SIX_PLACES = Decimal("0.000001")


@dataclass(frozen=True, order=True)
class QuestionPerformance:
    question_id: str
    question_cluster: str
    score: Decimal
    planned_slot_count: int

    def __post_init__(self) -> None:
        _ratio(self.score, "question performance score")
        if self.planned_slot_count < 1:
            raise SemanticMetricRuleViolation("question performance requires planned slots")


@dataclass(frozen=True, order=True)
class ClusterPerformance:
    question_cluster: str
    score: Decimal
    planned_slot_count: int

    def __post_init__(self) -> None:
        _ratio(self.score, "cluster performance score")
        if self.planned_slot_count < 1:
            raise SemanticMetricRuleViolation("cluster performance requires planned slots")


@dataclass(frozen=True)
class NegativeGainSummary:
    compared_question_count: int
    affected_question_count: int
    mean_negative_gain: Decimal
    range_low: Decimal
    range_high: Decimal
    worst_question_id: str | None
    worst_question_delta: Decimal | None

    def __post_init__(self) -> None:
        if not 0 <= self.affected_question_count <= self.compared_question_count:
            raise SemanticMetricRuleViolation("negative-gain question counts are inconsistent")
        for value in (self.mean_negative_gain, self.range_low, self.range_high):
            if not value.is_finite() or not Decimal(-1) <= value <= Decimal(0):
                raise SemanticMetricRuleViolation("negative-gain values must be in [-1, 0]")
        if self.range_low > self.range_high:
            raise SemanticMetricRuleViolation("negative-gain interval is reversed")
        if (self.affected_question_count == 0) != (self.worst_question_id is None):
            raise SemanticMetricRuleViolation("negative-gain worst question is inconsistent")
        if self.worst_question_delta is not None and not (
            Decimal(-1) <= self.worst_question_delta < Decimal(0)
        ):
            raise SemanticMetricRuleViolation("worst question delta must be negative")


@dataclass(frozen=True)
class PerformanceSummary:
    questions: tuple[QuestionPerformance, ...]
    clusters: tuple[ClusterPerformance, ...]
    worst_question_id: str
    worst_question_score: Decimal
    worst_cluster: str
    worst_cluster_score: Decimal
    negative_gain: NegativeGainSummary | None


def aggregate_performance(
    *,
    planned_slots: Sequence[PlannedMetricSlot],
    slot_scores: Mapping[str, Decimal],
    baseline_scores: Sequence[BaselineQuestionScore] = (),
) -> PerformanceSummary:
    expected_ids = {item.slot_id for item in planned_slots}
    if set(slot_scores) != expected_ids:
        raise SemanticMetricRuleViolation("performance scores must preserve every planned slot")
    for score in slot_scores.values():
        _ratio(score, "slot performance score")
    question_values: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    cluster_values: dict[str, list[Decimal]] = defaultdict(list)
    for slot in planned_slots:
        score = slot_scores[slot.slot_id]
        question_values[(slot.question_id, slot.question_cluster)].append(score)
        cluster_values[slot.question_cluster].append(score)
    questions = tuple(
        sorted(
            QuestionPerformance(
                question_id=question_id,
                question_cluster=cluster,
                score=_mean(values),
                planned_slot_count=len(values),
            )
            for (question_id, cluster), values in question_values.items()
        )
    )
    clusters = tuple(
        sorted(
            ClusterPerformance(
                question_cluster=cluster,
                score=_mean(values),
                planned_slot_count=len(values),
            )
            for cluster, values in cluster_values.items()
        )
    )
    worst_question = min(questions, key=lambda item: (item.score, item.question_id))
    worst_cluster = min(clusters, key=lambda item: (item.score, item.question_cluster))
    negative_gain = compare_question_scores(questions, baseline_scores) if baseline_scores else None
    return PerformanceSummary(
        questions=questions,
        clusters=clusters,
        worst_question_id=worst_question.question_id,
        worst_question_score=worst_question.score,
        worst_cluster=worst_cluster.question_cluster,
        worst_cluster_score=worst_cluster.score,
        negative_gain=negative_gain,
    )


def compare_question_scores(
    current: Sequence[QuestionPerformance],
    baseline: Sequence[BaselineQuestionScore],
) -> NegativeGainSummary:
    current_by_id = {item.question_id: item.score for item in current}
    baseline_by_id = {item.question_id: item.score for item in baseline}
    shared = tuple(sorted(set(current_by_id).intersection(baseline_by_id)))
    deltas = tuple(
        (question_id, _quantize(current_by_id[question_id] - baseline_by_id[question_id]))
        for question_id in shared
    )
    negative = tuple((question_id, delta) for question_id, delta in deltas if delta < 0)
    if not negative:
        return NegativeGainSummary(
            compared_question_count=len(shared),
            affected_question_count=0,
            mean_negative_gain=Decimal(0),
            range_low=Decimal(0),
            range_high=Decimal(0),
            worst_question_id=None,
            worst_question_delta=None,
        )
    worst_question_id, worst_delta = min(negative, key=lambda item: (item[1], item[0]))
    values = [item[1] for item in negative]
    return NegativeGainSummary(
        compared_question_count=len(shared),
        affected_question_count=len(negative),
        mean_negative_gain=_mean(values),
        range_low=min(values),
        range_high=max(values),
        worst_question_id=worst_question_id,
        worst_question_delta=worst_delta,
    )


def _mean(values: Sequence[Decimal]) -> Decimal:
    return _quantize(sum(values, Decimal(0)) / Decimal(len(values)))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)


def _ratio(value: Decimal, label: str) -> None:
    if not value.is_finite() or not Decimal(0) <= value <= Decimal(1):
        raise SemanticMetricRuleViolation(f"{label} must be in [0, 1]")
