"""Canonical semantic metric snapshot and performance projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from geo_core.semantic_metrics.aggregation import PerformanceSummary
from geo_core.semantic_metrics.contracts import (
    FrozenMetricSuite,
    MetricInputSet,
    SemanticMetricRuleViolation,
    canonical_hash,
    decimal_value,
)
from geo_core.semantic_metrics.results import SemanticMetricResult


@dataclass(frozen=True)
class SemanticMetricSnapshot:
    input_set_hash: str
    suite_hash: str
    stratum_hash: str
    results: tuple[SemanticMetricResult, ...]
    performance: PerformanceSummary
    computed_at: datetime
    snapshot_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.computed_at.tzinfo is None or self.computed_at.utcoffset() is None:
            raise SemanticMetricRuleViolation("semantic metric computation time must be aware")
        results = tuple(sorted(self.results, key=lambda item: item.metric_key.value))
        if not results or len({item.metric_key for item in results}) != len(results):
            raise SemanticMetricRuleViolation("semantic metric snapshot results must be unique")
        if any(
            item.input_set_hash != self.input_set_hash or item.stratum_hash != self.stratum_hash
            for item in results
        ):
            raise SemanticMetricRuleViolation("semantic metric result lineage is inconsistent")
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "snapshot_hash", canonical_hash(self.result_value()))

    @classmethod
    def create(
        cls,
        *,
        input_set: MetricInputSet,
        suite: FrozenMetricSuite,
        results: tuple[SemanticMetricResult, ...],
        performance: PerformanceSummary,
        computed_at: datetime,
    ) -> SemanticMetricSnapshot:
        if {item.metric_key for item in results} != {item.key for item in suite.definitions}:
            raise SemanticMetricRuleViolation("snapshot does not contain every frozen metric")
        return cls(
            input_set_hash=input_set.input_set_hash,
            suite_hash=suite.suite_hash,
            stratum_hash=input_set.stratum.stratum_hash,
            results=results,
            performance=performance,
            computed_at=computed_at,
        )

    def canonical_value(self) -> dict[str, object]:
        return {**self.result_value(), "computed_at": self.computed_at.isoformat()}

    def result_value(self) -> dict[str, object]:
        negative = self.performance.negative_gain
        return {
            "input_set_hash": self.input_set_hash,
            "suite_hash": self.suite_hash,
            "stratum_hash": self.stratum_hash,
            "results": [item.canonical_value() for item in self.results],
            "performance": {
                "questions": [
                    {
                        "question_id": item.question_id,
                        "question_cluster": item.question_cluster,
                        "score": decimal_value(item.score),
                        "planned_slot_count": item.planned_slot_count,
                    }
                    for item in self.performance.questions
                ],
                "clusters": [
                    {
                        "question_cluster": item.question_cluster,
                        "score": decimal_value(item.score),
                        "planned_slot_count": item.planned_slot_count,
                    }
                    for item in self.performance.clusters
                ],
                "worst_question_id": self.performance.worst_question_id,
                "worst_question_score": decimal_value(self.performance.worst_question_score),
                "worst_cluster": self.performance.worst_cluster,
                "worst_cluster_score": decimal_value(self.performance.worst_cluster_score),
                "negative_gain": (
                    {
                        "compared_question_count": negative.compared_question_count,
                        "affected_question_count": negative.affected_question_count,
                        "mean_negative_gain": decimal_value(negative.mean_negative_gain),
                        "range_low": decimal_value(negative.range_low),
                        "range_high": decimal_value(negative.range_high),
                        "worst_question_id": negative.worst_question_id,
                        "worst_question_delta": decimal_value(negative.worst_question_delta),
                    }
                    if negative is not None
                    else None
                ),
            },
        }
