from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from geo_core.semantic_metrics import (
    ApprovedFactReference,
    BaselineQuestionScore,
    CitationInput,
    DeterministicRuleVersions,
    EvidenceLocator,
    EvidenceLocatorKind,
    JudgeVersion,
    MetricInputSet,
    MetricObservation,
    PlannedMetricSlot,
    SemanticStratum,
    StructuredJudgeOutput,
    SubjectAssertion,
    SubjectInventory,
    first_metric_suite,
)

from tests.unit.semantic_metrics.support import OBSERVATION_IDS

@pytest.fixture
def judge_version() -> JudgeVersion:
    return JudgeVersion(
        key="metric-judge",
        version="metric-judge-v1",
        prompt_release_id=UUID("60000000-0000-0000-0000-000000000001"),
        prompt_release_hash="a" * 64,
        model_identity="review-provider/model-v1",
        schema_version="metric-judge-output-v2",
    )


@pytest.fixture
def rule_versions() -> DeterministicRuleVersions:
    return DeterministicRuleVersions(
        subject="subject-rule-v1",
        url="url-rule-v1",
        citation_order="citation-order-v1",
        denominator="planned-denominator-v1",
        mention="mention-rule-v1",
    )


@pytest.fixture
def metric_suite(judge_version: JudgeVersion, rule_versions: DeterministicRuleVersions):
    return first_metric_suite(judge_version=judge_version, rule_versions=rule_versions)


@pytest.fixture
def metric_input_set() -> MetricInputSet:
    facts = (
        ApprovedFactReference("fact:battery", "fact-v1", "advinsys", "b" * 64),
        ApprovedFactReference("fact:warranty", "fact-v1", "advinsys", "c" * 64),
    )
    slots = (
        PlannedMetricSlot("slot-1", "q1", "purchase"),
        PlannedMetricSlot("slot-2", "q1", "purchase"),
        PlannedMetricSlot("slot-3", "q1", "purchase"),
        PlannedMetricSlot("slot-4", "q2", "trust"),
        PlannedMetricSlot("slot-5", "q2", "trust"),
    )
    observations = (
        _observation_one(facts),
        _observation_two(facts),
        _observation_three(facts),
        _observation_four(facts),
    )
    return MetricInputSet(
        stratum=SemanticStratum(
            (("capture_method", "fixture"), ("locale", "en-AU"), ("region", "AU"))
        ),
        planned_slots=slots,
        observations=observations,
        subjects=SubjectInventory(
            primary_subject_key="advinsys",
            brand_aliases=("Advinsys",),
            product_aliases=("RoboClean X",),
            competitors=(("rivalco", ("RivalBot",)),),
        ),
        approved_facts=facts,
        verified_urls=(
            "https://example.com/product",
            "https://docs.example.com/roboclean",
        ),
        approved_corpus_version="corpus-v7",
        approved_corpus_hash="d" * 64,
        baseline_question_scores=(
            BaselineQuestionScore("q1", Decimal("0.90"), "e" * 64),
            BaselineQuestionScore("q2", Decimal("0.80"), "e" * 64),
        ),
    )


def _observation_one(facts: tuple[ApprovedFactReference, ...]) -> MetricObservation:
    answer = "RoboClean X by Advinsys is my top recommendation, ahead of RivalBot."
    observation_id = OBSERVATION_IDS[0]
    citations = (
        CitationInput(
            "citation-1",
            1,
            "HTTPS://EXAMPLE.COM/product#details",
            "Product details",
            "official",
        ),
        CitationInput(
            "citation-2",
            2,
            "https://review.example.org/best",
            "Independent review",
            "editorial",
        ),
    )
    return MetricObservation(
        id=observation_id,
        slot_id="slot-1",
        payload_hash="1" * 64,
        question_id="q1",
        question_cluster="purchase",
        answer_text=answer,
        citations=citations,
        subject_assertions=(_assertion(answer, observation_id, "RoboClean X", "advinsys"),),
        judge_outputs=(
            _scored("recommendation", "yes", "0.90", answer, observation_id, "recommendation"),
            _scored("sentiment", "positive", "0.70", answer, observation_id, "top"),
            _fact("accurate", facts[0], answer, observation_id, "RoboClean X"),
            _fact("accurate", facts[1], answer, observation_id, "Advinsys"),
            _citation("entailed", citations[0]),
            _citation("not_entailed", citations[1]),
            _scored("corpus_absorption", "absorbed", "0.80", answer, observation_id, "RoboClean X"),
        ),
    )


def _observation_two(facts: tuple[ApprovedFactReference, ...]) -> MetricObservation:
    answer = "RivalBot appears first, but RoboClean X is still recommended."
    observation_id = OBSERVATION_IDS[1]
    citations = (
        CitationInput(
            "citation-3",
            2,
            "https://rival.example/compare",
            "Comparison",
            "forum",
        ),
    )
    return MetricObservation(
        id=observation_id,
        slot_id="slot-2",
        payload_hash="2" * 64,
        question_id="q1",
        question_cluster="purchase",
        answer_text=answer,
        citations=citations,
        subject_assertions=(_assertion(answer, observation_id, "RivalBot", "advinsys", "rivalco"),),
        judge_outputs=(
            _scored("recommendation", "yes", "0.60", answer, observation_id, "recommended"),
            _scored("sentiment", "neutral", "0.10", answer, observation_id, "appears first"),
            _fact("conflict", facts[0], answer, observation_id, "RivalBot"),
            _fact("omission", facts[1], answer, observation_id),
            _citation("entailed", citations[0]),
            _scored("corpus_absorption", "absorbed", "0.40", answer, observation_id, "RoboClean X"),
        ),
    )


def _observation_three(facts: tuple[ApprovedFactReference, ...]) -> MetricObservation:
    answer = "Advinsys offers RoboClean X, though battery life is a concern."
    observation_id = OBSERVATION_IDS[2]
    citations = (
        CitationInput(
            "citation-4",
            1,
            "https://docs.example.com/roboclean",
            "RoboClean manual",
            "official",
        ),
    )
    return MetricObservation(
        id=observation_id,
        slot_id="slot-3",
        payload_hash="3" * 64,
        question_id="q1",
        question_cluster="purchase",
        answer_text=answer,
        citations=citations,
        judge_outputs=(
            _scored("recommendation", "no", "0.20", answer, observation_id, "concern"),
            _scored("sentiment", "negative", "-0.60", answer, observation_id, "battery life", ("battery_life",)),
            _fact("accurate", facts[0], answer, observation_id, "battery life"),
            _fact("conflict", facts[1], answer, observation_id, "concern"),
            _citation("entailed", citations[0]),
            _scored("corpus_absorption", "absorbed", "0.50", answer, observation_id, "RoboClean X"),
        ),
    )


def _observation_four(facts: tuple[ApprovedFactReference, ...]) -> MetricObservation:
    answer = "RivalBot is the only option discussed."
    observation_id = OBSERVATION_IDS[3]
    return MetricObservation(
        id=observation_id,
        slot_id="slot-4",
        payload_hash="4" * 64,
        question_id="q2",
        question_cluster="trust",
        answer_text=answer,
        judge_outputs=(
            _scored("recommendation", "no", "0.10", answer, observation_id, "RivalBot"),
            _scored("sentiment", "negative", "-0.40", answer, observation_id, "only option", ("missing_primary_product",)),
            _fact("omission", facts[0], answer, observation_id),
            _fact("omission", facts[1], answer, observation_id),
            _scored("corpus_absorption", "not_absorbed", "0.10", answer, observation_id, "RivalBot"),
        ),
    )


def _scored(
    kind: str,
    label: str,
    score: str,
    answer: str,
    observation_id: UUID,
    quote: str,
    reasons: tuple[str, ...] = (),
) -> StructuredJudgeOutput:
    return StructuredJudgeOutput(
        kind=kind,  # type: ignore[arg-type]
        label=label,
        score=Decimal(score),
        reason_codes=reasons,
        locators=(_span(answer, observation_id, quote),),
        schema_version="metric-judge-output-v2",
    )


def _fact(
    label: str,
    fact: ApprovedFactReference,
    answer: str,
    observation_id: UUID,
    quote: str | None = None,
) -> StructuredJudgeOutput:
    locators = [EvidenceLocator(EvidenceLocatorKind.FACT, fact.id, version=fact.version)]
    if quote is not None:
        locators.append(_span(answer, observation_id, quote))
    return StructuredJudgeOutput(
        kind="fact",  # type: ignore[arg-type]
        label=label,
        score=None,
        reason_codes=(),
        locators=tuple(locators),
        schema_version="metric-judge-output-v2",
    )


def _citation(label: str, citation: CitationInput) -> StructuredJudgeOutput:
    return StructuredJudgeOutput(
        kind="citation_entailment",  # type: ignore[arg-type]
        label=label,
        score=None,
        reason_codes=(),
        locators=(EvidenceLocator(EvidenceLocatorKind.CITATION, citation.id),),
        schema_version="metric-judge-output-v2",
    )


def _assertion(
    answer: str,
    observation_id: UUID,
    quote: str,
    claimed: str,
    catalog: str | None = None,
) -> SubjectAssertion:
    return SubjectAssertion(claimed, catalog or claimed, _span(answer, observation_id, quote))


def _span(answer: str, observation_id: UUID, quote: str) -> EvidenceLocator:
    start = answer.index(quote)
    return EvidenceLocator(
        EvidenceLocatorKind.ANSWER_SPAN,
        str(observation_id),
        version="observation-artifact-v1",
        content_hash=f"{OBSERVATION_IDS.index(observation_id) + 1}" * 64,
        start=start,
        end=start + len(quote),
    )
