"""The first frozen semantic metric inventory."""

from __future__ import annotations

from decimal import Decimal

from geo_core.semantic_metrics.contracts import (
    DeterministicRuleVersions,
    FrozenMetricSuite,
    JudgeKind,
    JudgeVersion,
    MetricDefinition,
    MetricKey,
    MetricValueKind,
)


SEMANTIC_METRIC_VERSION = "semantic-metric-v1"


FIRST_METRIC_DEFINITIONS = (
    MetricDefinition(MetricKey.BRAND_MENTION, SEMANTIC_METRIC_VERSION, MetricValueKind.BINARY_RATE),
    MetricDefinition(
        MetricKey.PRODUCT_MENTION, SEMANTIC_METRIC_VERSION, MetricValueKind.BINARY_RATE
    ),
    MetricDefinition(
        MetricKey.RECOMMENDATION,
        SEMANTIC_METRIC_VERSION,
        MetricValueKind.BINARY_RATE,
        JudgeKind.RECOMMENDATION,
    ),
    MetricDefinition(
        MetricKey.RECOMMENDATION_STRENGTH,
        SEMANTIC_METRIC_VERSION,
        MetricValueKind.MEAN_SCORE,
        JudgeKind.RECOMMENDATION,
    ),
    MetricDefinition(
        MetricKey.COMPETITOR_MENTION, SEMANTIC_METRIC_VERSION, MetricValueKind.BINARY_RATE
    ),
    MetricDefinition(
        MetricKey.COMPETITOR_RELATIVE_POSITION,
        SEMANTIC_METRIC_VERSION,
        MetricValueKind.SIGNED_SCORE,
    ),
    MetricDefinition(
        MetricKey.SENTIMENT,
        SEMANTIC_METRIC_VERSION,
        MetricValueKind.SIGNED_SCORE,
        JudgeKind.SENTIMENT,
    ),
    MetricDefinition(
        MetricKey.FACT_ACCURACY,
        SEMANTIC_METRIC_VERSION,
        MetricValueKind.BINARY_RATE,
        JudgeKind.FACT,
    ),
    MetricDefinition(
        MetricKey.EXPLICIT_CONFLICT,
        SEMANTIC_METRIC_VERSION,
        MetricValueKind.BINARY_RATE,
        JudgeKind.FACT,
    ),
    MetricDefinition(MetricKey.SUBJECT_MIXUP, SEMANTIC_METRIC_VERSION, MetricValueKind.BINARY_RATE),
    MetricDefinition(
        MetricKey.KEY_FACT_OMISSION,
        SEMANTIC_METRIC_VERSION,
        MetricValueKind.BINARY_RATE,
        JudgeKind.FACT,
    ),
    MetricDefinition(
        MetricKey.CITATION_ENTAILMENT,
        SEMANTIC_METRIC_VERSION,
        MetricValueKind.BINARY_RATE,
        JudgeKind.CITATION_ENTAILMENT,
    ),
    MetricDefinition(
        MetricKey.CITATION_POSITION, SEMANTIC_METRIC_VERSION, MetricValueKind.MEAN_SCORE
    ),
    MetricDefinition(
        MetricKey.CITATION_ORDER, SEMANTIC_METRIC_VERSION, MetricValueKind.BINARY_RATE
    ),
    MetricDefinition(
        MetricKey.VERIFIED_URL_HIT, SEMANTIC_METRIC_VERSION, MetricValueKind.BINARY_RATE
    ),
    MetricDefinition(
        MetricKey.SOURCE_DOMAIN_DIVERSITY, SEMANTIC_METRIC_VERSION, MetricValueKind.COUNT
    ),
    MetricDefinition(
        MetricKey.SOURCE_TYPE_DIVERSITY, SEMANTIC_METRIC_VERSION, MetricValueKind.COUNT
    ),
    MetricDefinition(
        MetricKey.APPROVED_CORPUS_ABSORPTION,
        SEMANTIC_METRIC_VERSION,
        MetricValueKind.MEAN_SCORE,
        JudgeKind.CORPUS_ABSORPTION,
    ),
)


def first_metric_suite(
    *,
    judge_version: JudgeVersion,
    rule_versions: DeterministicRuleVersions,
    minimum_valid_completion: Decimal = Decimal("0.80"),
) -> FrozenMetricSuite:
    return FrozenMetricSuite(
        definitions=FIRST_METRIC_DEFINITIONS,
        judge_version=judge_version,
        rule_versions=rule_versions,
        minimum_valid_completion=minimum_valid_completion,
    )
