from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from geo_core.semantic_metrics import (
    EvidenceLocator,
    EvidenceLocatorKind,
    FrozenMetricSuite,
    JudgeKind,
    JudgeOutputRejected,
    JudgeVersion,
    MetricInputSet,
    MetricKey,
    MetricStatus,
    SemanticMetricRuleViolation,
    StructuredJudgeOutput,
    compute_semantic_metric_snapshot,
    parse_structured_judge_output,
    validate_judgement,
)

from tests.unit.semantic_metrics.support import NOW, OBSERVATION_IDS


def test_input_set_hash_is_order_independent_but_stratum_sensitive(
    metric_input_set: MetricInputSet,
) -> None:
    reordered = replace(
        metric_input_set,
        planned_slots=tuple(reversed(metric_input_set.planned_slots)),
        observations=tuple(reversed(metric_input_set.observations)),
        verified_urls=tuple(reversed(metric_input_set.verified_urls)),
    )

    assert reordered.input_set_hash == metric_input_set.input_set_hash
    changed_stratum = replace(
        metric_input_set.stratum,
        dimensions=(("capture_method", "fixture"), ("locale", "en-US"), ("region", "US")),
    )
    assert replace(metric_input_set, stratum=changed_stratum).input_set_hash != metric_input_set.input_set_hash


def test_planned_slot_denominator_cannot_be_rewritten_by_missing_observations(
    metric_input_set: MetricInputSet,
    metric_suite: FrozenMetricSuite,
) -> None:
    reduced = replace(metric_input_set, observations=metric_input_set.observations[:3])
    snapshot = compute_semantic_metric_snapshot(
        input_set=reduced,
        suite=metric_suite,
        computed_at=NOW,
    )
    product = next(item for item in snapshot.results if item.metric_key is MetricKey.PRODUCT_MENTION)

    assert product.denominator == 5
    assert product.valid_input_count == 3
    assert product.missing_input_count == 2
    assert product.status is MetricStatus.INSUFFICIENT_EVIDENCE


def test_structured_parser_rejects_unknown_free_text_fields() -> None:
    payload = _payload()
    payload["rationale"] = "unbounded model prose"

    with pytest.raises(JudgeOutputRejected, match="fields"):
        parse_structured_judge_output(payload)


def test_structured_parser_accepts_only_the_frozen_shape() -> None:
    output = parse_structured_judge_output(_payload())

    assert output.kind is JudgeKind.RECOMMENDATION
    assert output.label == "yes"
    assert output.score == Decimal("0.8")
    assert output.schema_version == "metric-judge-output-v2"
    assert len(output.output_hash) == 64


def test_missing_or_unresolvable_locator_marks_judgement_invalid(
    metric_input_set: MetricInputSet,
    judge_version: JudgeVersion,
) -> None:
    observation = metric_input_set.observations[0]
    missing = StructuredJudgeOutput(
        JudgeKind.RECOMMENDATION,
        "yes",
        Decimal("0.8"),
        (),
        (),
        "metric-judge-output-v2",
    )
    wrong_span = StructuredJudgeOutput(
        JudgeKind.RECOMMENDATION,
        "yes",
        Decimal("0.8"),
        (),
        (
            EvidenceLocator(
                EvidenceLocatorKind.ANSWER_SPAN,
                str(observation.id),
                version=observation.artifact_version,
                content_hash="f" * 64,
                start=0,
                end=4,
            ),
        ),
        "metric-judge-output-v2",
    )

    missing_result = validate_judgement(
        missing,
        observation=observation,
        input_set=metric_input_set,
        judge_version=judge_version,
    )
    wrong_result = validate_judgement(
        wrong_span,
        observation=observation,
        input_set=metric_input_set,
        judge_version=judge_version,
    )

    assert missing_result.valid is False
    assert "missing_evidence_locator" in missing_result.invalid_reasons
    assert wrong_result.valid is False
    assert "answer_span_content_hash_mismatch" in wrong_result.invalid_reasons


def test_unapproved_fact_and_wrong_schema_are_invalid(
    metric_input_set: MetricInputSet,
    judge_version: JudgeVersion,
) -> None:
    observation = metric_input_set.observations[0]
    output = StructuredJudgeOutput(
        JudgeKind.FACT,
        "omission",
        None,
        (),
        (EvidenceLocator(EvidenceLocatorKind.FACT, "fact:unknown", version="v9"),),
        "old-schema-v1",
    )

    result = validate_judgement(
        output,
        observation=observation,
        input_set=metric_input_set,
        judge_version=judge_version,
    )

    assert result.valid is False
    assert result.invalid_reasons == (
        "fact_locator_not_approved",
        "schema_version_mismatch",
    )


def test_model_schema_has_no_subject_url_order_or_denominator_judgements() -> None:
    assert {item.value for item in JudgeKind} == {
        "recommendation",
        "sentiment",
        "fact",
        "citation_entailment",
        "corpus_absorption",
    }
    payload = _payload()
    payload["kind"] = "subject_mixup"
    with pytest.raises(JudgeOutputRejected):
        parse_structured_judge_output(payload)


def test_invalid_judge_output_is_counted_not_silently_dropped(
    metric_input_set: MetricInputSet,
    metric_suite: FrozenMetricSuite,
) -> None:
    observation = metric_input_set.observations[0]
    invalid = StructuredJudgeOutput(
        JudgeKind.RECOMMENDATION,
        "yes",
        Decimal("0.8"),
        (),
        (),
        "metric-judge-output-v2",
    )
    changed_outputs = tuple(
        invalid if item.kind is JudgeKind.RECOMMENDATION else item
        for item in observation.judge_outputs
    )
    changed_observation = replace(observation, judge_outputs=changed_outputs)
    changed_input = replace(
        metric_input_set,
        observations=(changed_observation, *metric_input_set.observations[1:]),
    )
    snapshot = compute_semantic_metric_snapshot(
        input_set=changed_input,
        suite=metric_suite,
        computed_at=NOW,
    )
    recommendation = next(
        item for item in snapshot.results if item.metric_key is MetricKey.RECOMMENDATION
    )

    assert recommendation.denominator == 5
    assert recommendation.valid_input_count == 3
    assert recommendation.invalid_input_count == 1
    assert recommendation.missing_input_count == 1
    assert recommendation.status is MetricStatus.INSUFFICIENT_EVIDENCE


def test_duplicate_slot_or_cross_slot_observation_is_rejected(
    metric_input_set: MetricInputSet,
) -> None:
    duplicated = replace(
        metric_input_set.observations[1],
        id=OBSERVATION_IDS[0],
        slot_id=metric_input_set.observations[0].slot_id,
    )
    with pytest.raises(SemanticMetricRuleViolation, match="one observation"):
        replace(metric_input_set, observations=(metric_input_set.observations[0], duplicated))


def _payload() -> dict[str, object]:
    return {
        "kind": "recommendation",
        "label": "yes",
        "score": 0.8,
        "reason_codes": [],
        "locators": [
            {
                "kind": "answer_span",
                "reference_id": str(OBSERVATION_IDS[0]),
                "version": "observation-artifact-v1",
                "content_hash": "1" * 64,
                "start": 0,
                "end": 11,
                "redacted_quote_hash": None,
            }
        ],
        "schema_version": "metric-judge-output-v2",
    }
