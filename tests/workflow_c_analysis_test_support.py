from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from geo_core.semantic_metrics import (
    DeterministicRuleVersions,
    FrozenMetricSuite,
    JudgeVersion,
    MetricDefinition,
    MetricKey,
    MetricValueKind,
    SubjectInventory,
)
from geo_core.workflow_c_analysis_admission import MetricProtocolDefinition


PROMPT_RELEASE_ID = UUID("71000000-0000-4000-8000-000000000002")
FACT_SNAPSHOT_ID = UUID("71000000-0000-4000-8000-000000000003")
CORPUS_VERSION_ID = UUID("71000000-0000-4000-8000-000000000004")


def metric_protocol_definition_fixture() -> MetricProtocolDefinition:
    prompt_hash = "8" * 64
    suite = FrozenMetricSuite(
        definitions=(
            MetricDefinition(
                key=MetricKey.BRAND_MENTION,
                version="semantic-metric-v1",
                value_kind=MetricValueKind.BINARY_RATE,
            ),
        ),
        judge_version=JudgeVersion(
            key="metric-judge",
            version="metric-judge-v1",
            prompt_release_id=PROMPT_RELEASE_ID,
            prompt_release_hash=prompt_hash,
            model_identity="review-provider/model-v1",
            schema_version="metric-judge-output-v1",
        ),
        rule_versions=DeterministicRuleVersions(
            subject="subject-rule-v1",
            url="url-rule-v1",
            citation_order="citation-order-v1",
            denominator="planned-denominator-v1",
            mention="mention-rule-v1",
        ),
        minimum_valid_completion=Decimal("0.80"),
    )
    return MetricProtocolDefinition(
        metric_suite=suite,
        subjects=SubjectInventory(
            primary_subject_key="advinsys",
            brand_aliases=("Advinsys",),
            product_aliases=("Advinsys Suite",),
            competitors=(("competitor", ("Competitor",)),),
        ),
        approved_facts=(),
        verified_urls=("https://example.com",),
        approved_corpus_version="corpus-v1",
        approved_corpus_hash="9" * 64,
        baseline_question_scores=(),
        question_clusters=(("question-1", "purchase"),),
        fact_snapshot_id=FACT_SNAPSHOT_ID,
        fact_snapshot_hash="a" * 64,
        prompt_release_id=PROMPT_RELEASE_ID,
        prompt_release_hash=prompt_hash,
        corpus_version_id=CORPUS_VERSION_ID,
        corpus_version_hash="9" * 64,
    )


__all__ = ["metric_protocol_definition_fixture"]
