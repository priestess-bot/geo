"""Deterministic computation over a frozen semantic metric input set."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from geo_core.semantic_metrics.aggregation import aggregate_performance
from geo_core.semantic_metrics.contracts import (
    CitationInput,
    EvidenceLocator,
    EvidenceLocatorKind,
    FrozenMetricSuite,
    JudgeKind,
    MetricDefinition,
    MetricInputSet,
    MetricKey,
    MetricObservation,
    MetricStatus,
    MetricValueKind,
    SemanticMetricRuleViolation,
    StructuredJudgeOutput,
)
from geo_core.semantic_metrics.judges import (
    locator_reference_ids,
    validate_judgement,
)
from geo_core.semantic_metrics.prompt_injection import (
    has_high_confidence_prompt_injection,
)
from geo_core.semantic_metrics.results import MetricInterval, SemanticMetricResult
from geo_core.semantic_metrics.rules import (
    brand_mentions,
    citation_order_valid,
    citation_position_score,
    competitor_mentions,
    competitor_relative_position,
    product_mentions,
    source_domain_diversity,
    source_type_diversity,
    subject_mixups,
    verified_url_hit,
)
from geo_core.semantic_metrics.snapshot import SemanticMetricSnapshot


SIX_PLACES = Decimal("0.000001")
WILSON_Z = Decimal("1.959963984540054")


@dataclass(frozen=True)
class _Values:
    values: tuple[Decimal, ...]
    denominator: int
    invalid: int
    missing: int
    locators: tuple[EvidenceLocator, ...] = ()
    breakdown: tuple[tuple[str, Decimal], ...] = ()
    numerator_override: Decimal | None = None

    @property
    def valid(self) -> int:
        return len(self.values)


def compute_semantic_metric_snapshot(
    *,
    input_set: MetricInputSet,
    suite: FrozenMetricSuite,
    computed_at: datetime,
) -> SemanticMetricSnapshot:
    injected = tuple(
        str(observation.id)
        for observation in input_set.observations
        if has_high_confidence_prompt_injection(observation.answer_text)
    )
    if injected:
        raise SemanticMetricRuleViolation(
            "semantic metric snapshot cannot aggregate prompt-injection observations: "
            + ", ".join(injected)
        )
    results = tuple(
        _compute_result(definition, input_set=input_set, suite=suite)
        for definition in suite.definitions
    )
    performance = aggregate_performance(
        planned_slots=input_set.planned_slots,
        slot_scores=_performance_slot_scores(input_set, suite),
        baseline_scores=input_set.baseline_question_scores,
    )
    return SemanticMetricSnapshot.create(
        input_set=input_set,
        suite=suite,
        results=results,
        performance=performance,
        computed_at=computed_at,
    )


def _compute_result(
    definition: MetricDefinition,
    *,
    input_set: MetricInputSet,
    suite: FrozenMetricSuite,
) -> SemanticMetricResult:
    values = _metric_values(definition.key, input_set=input_set, suite=suite)
    numerator = (
        values.numerator_override
        if values.numerator_override is not None
        else sum(values.values, Decimal(0))
    )
    estimate = (
        numerator
        if definition.value_kind is MetricValueKind.COUNT
        else _ratio(numerator, values.denominator)
    )
    status = (
        MetricStatus.COMPLETE
        if values.denominator > 0
        and Decimal(values.valid) >= suite.minimum_valid_completion * Decimal(values.denominator)
        else MetricStatus.INSUFFICIENT_EVIDENCE
    )
    return SemanticMetricResult(
        metric_key=definition.key,
        metric_version=definition.version,
        value_kind=definition.value_kind,
        input_set_hash=input_set.input_set_hash,
        stratum=input_set.stratum.dimensions,
        stratum_hash=input_set.stratum.stratum_hash,
        numerator=_quantize(numerator),
        denominator=values.denominator,
        estimate=_quantize(estimate),
        interval=_interval(
            definition.value_kind,
            numerator=numerator,
            denominator=values.denominator,
            estimate=estimate,
            observed=values.values,
        ),
        valid_input_count=values.valid,
        invalid_input_count=values.invalid,
        missing_input_count=values.missing,
        status=status,
        judge_version=(suite.judge_version.version if definition.judge_kind is not None else None),
        judge_version_hash=(
            suite.judge_version.version_hash if definition.judge_kind is not None else None
        ),
        rule_versions=(
            ("subject", suite.rule_versions.subject),
            ("url", suite.rule_versions.url),
            ("citation_order", suite.rule_versions.citation_order),
            ("denominator", suite.rule_versions.denominator),
            ("mention", suite.rule_versions.mention),
        ),
        rule_versions_hash=suite.rule_versions.versions_hash,
        evidence_locators=values.locators,
        breakdown=values.breakdown,
    )


def _metric_values(
    key: MetricKey, *, input_set: MetricInputSet, suite: FrozenMetricSuite
) -> _Values:
    if key is MetricKey.BRAND_MENTION:
        return _observation_rule_values(
            input_set, lambda item: brand_mentions(item, input_set.subjects)
        )
    if key is MetricKey.PRODUCT_MENTION:
        return _observation_rule_values(
            input_set, lambda item: product_mentions(item, input_set.subjects)
        )
    if key is MetricKey.COMPETITOR_MENTION:
        return _observation_rule_values(
            input_set, lambda item: competitor_mentions(item, input_set.subjects)
        )
    if key is MetricKey.COMPETITOR_RELATIVE_POSITION:
        return _observation_score_values(
            input_set, lambda item: competitor_relative_position(item, input_set.subjects)
        )
    if key is MetricKey.SUBJECT_MIXUP:
        return _subject_mixup_values(input_set)
    if key is MetricKey.RECOMMENDATION:
        return _single_judge_values(
            input_set,
            suite,
            JudgeKind.RECOMMENDATION,
            _recommendation_value,
            metric_id=MetricKey.RECOMMENDATION.value,
        )
    if key is MetricKey.RECOMMENDATION_STRENGTH:
        return _single_judge_values(
            input_set,
            suite,
            JudgeKind.RECOMMENDATION,
            _score_value,
            metric_id=MetricKey.RECOMMENDATION.value,
        )
    if key is MetricKey.SENTIMENT:
        return _sentiment_values(input_set, suite)
    if key is MetricKey.FACT_ACCURACY:
        return _fact_values(input_set, suite, target_label="accurate")
    if key is MetricKey.EXPLICIT_CONFLICT:
        return _fact_values(input_set, suite, target_label="conflict")
    if key is MetricKey.KEY_FACT_OMISSION:
        return _fact_values(input_set, suite, target_label="omission")
    if key is MetricKey.CITATION_ENTAILMENT:
        return _citation_entailment_values(input_set, suite)
    if key is MetricKey.CITATION_POSITION:
        return _citation_values(input_set, lambda item: citation_position_score(item))
    if key is MetricKey.CITATION_ORDER:
        return _citation_order_values(input_set)
    if key is MetricKey.VERIFIED_URL_HIT:
        return _citation_values(
            input_set,
            lambda item: Decimal(int(verified_url_hit(item, input_set.verified_urls))),
        )
    citations = tuple(
        item for observation in input_set.observations for item in observation.citations
    )
    if key is MetricKey.SOURCE_DOMAIN_DIVERSITY:
        return _diversity_values(citations, source_domain_diversity(citations), "unique_domains")
    if key is MetricKey.SOURCE_TYPE_DIVERSITY:
        return _diversity_values(citations, source_type_diversity(citations), "unique_source_types")
    return _single_judge_values(
        input_set,
        suite,
        JudgeKind.CORPUS_ABSORPTION,
        _score_value,
        metric_id=MetricKey.APPROVED_CORPUS_ABSORPTION.value,
    )


def _observation_rule_values(
    input_set: MetricInputSet,
    matches: Callable[[MetricObservation], tuple[object, ...]],
) -> _Values:
    observations = {item.slot_id: item for item in input_set.observations}
    values: list[Decimal] = []
    locators: list[EvidenceLocator] = []
    for slot in input_set.planned_slots:
        observation = observations.get(slot.slot_id)
        if observation is None:
            continue
        found = matches(observation)
        values.append(Decimal(int(bool(found))))
        locators.extend(item.locator for item in found)  # type: ignore[attr-defined]
    return _Values(
        values=tuple(values),
        denominator=len(input_set.planned_slots),
        invalid=0,
        missing=len(input_set.planned_slots) - len(values),
        locators=tuple(locators),
    )


def _observation_score_values(
    input_set: MetricInputSet, score: Callable[[MetricObservation], Decimal]
) -> _Values:
    values = tuple(score(item) for item in input_set.observations)
    return _Values(
        values=values,
        denominator=len(input_set.planned_slots),
        invalid=0,
        missing=len(input_set.planned_slots) - len(values),
    )


def _subject_mixup_values(input_set: MetricInputSet) -> _Values:
    values: list[Decimal] = []
    locators: list[EvidenceLocator] = []
    for observation in input_set.observations:
        mixups = subject_mixups(observation)
        values.append(Decimal(int(bool(mixups))))
        locators.extend(item.locator for item in mixups)
    return _Values(
        values=tuple(values),
        denominator=len(input_set.planned_slots),
        invalid=0,
        missing=len(input_set.planned_slots) - len(values),
        locators=tuple(locators),
    )


def _single_judge_values(
    input_set: MetricInputSet,
    suite: FrozenMetricSuite,
    kind: JudgeKind,
    value: Callable[[StructuredJudgeOutput], Decimal],
    *,
    metric_id: str | None = None,
) -> _Values:
    observations = {item.slot_id: item for item in input_set.observations}
    values: list[Decimal] = []
    locators: list[EvidenceLocator] = []
    invalid = 0
    missing = 0
    for slot in input_set.planned_slots:
        observation = observations.get(slot.slot_id)
        if observation is None:
            missing += 1
            continue
        outputs = tuple(item for item in observation.judge_outputs if item.kind is kind)
        if metric_id is not None:
            exact = tuple(item for item in outputs if item.metric_id == metric_id)
            # Pre-migration manually adjudicated fixtures did not carry a
            # Program metric_id. They are usable only when there is exactly one
            # legacy output of the requested JudgeKind.
            legacy = tuple(item for item in outputs if item.metric_id is None)
            outputs = exact if exact else legacy
        if not outputs:
            missing += 1
            continue
        if len(outputs) != 1:
            invalid += 1
            continue
        validation = validate_judgement(
            outputs[0],
            observation=observation,
            input_set=input_set,
            judge_version=suite.judge_version,
        )
        if not validation.valid:
            invalid += 1
            continue
        values.append(value(outputs[0]))
        locators.extend(outputs[0].locators)
    return _Values(tuple(values), len(input_set.planned_slots), invalid, missing, tuple(locators))


def _sentiment_values(input_set: MetricInputSet, suite: FrozenMetricSuite) -> _Values:
    base = _single_judge_values(
        input_set,
        suite,
        JudgeKind.SENTIMENT,
        _score_value,
        metric_id=MetricKey.SENTIMENT.value,
    )
    reasons: Counter[str] = Counter()
    for observation in input_set.observations:
        outputs = tuple(
            item
            for item in observation.judge_outputs
            if item.kind is JudgeKind.SENTIMENT
            and (item.metric_id in {None, MetricKey.SENTIMENT.value})
        )
        if len(outputs) == 1:
            validation = validate_judgement(
                outputs[0],
                observation=observation,
                input_set=input_set,
                judge_version=suite.judge_version,
            )
            if validation.valid and outputs[0].label == "negative":
                reasons.update(outputs[0].reason_codes)
    return _Values(
        base.values,
        base.denominator,
        base.invalid,
        base.missing,
        base.locators,
        tuple((key, Decimal(count)) for key, count in sorted(reasons.items())),
    )


def _fact_values(
    input_set: MetricInputSet,
    suite: FrozenMetricSuite,
    *,
    target_label: str,
) -> _Values:
    observations = {item.slot_id: item for item in input_set.observations}
    denominator = len(input_set.planned_slots) * len(input_set.approved_facts)
    values: list[Decimal] = []
    locators: list[EvidenceLocator] = []
    invalid = 0
    missing = 0
    for slot in input_set.planned_slots:
        observation = observations.get(slot.slot_id)
        if observation is None:
            missing += len(input_set.approved_facts)
            continue
        outputs = tuple(item for item in observation.judge_outputs if item.kind is JudgeKind.FACT)
        used: set[str] = set()
        local_missing = 0
        for fact in input_set.approved_facts:
            matching = tuple(
                item
                for item in outputs
                if any(
                    locator.kind is EvidenceLocatorKind.FACT
                    and locator.reference_id == fact.id
                    and locator.version == fact.version
                    for locator in item.locators
                )
            )
            if not matching:
                local_missing += 1
                continue
            used.update(item.output_hash for item in matching)
            if len(matching) != 1:
                invalid += 1
                continue
            validation = validate_judgement(
                matching[0],
                observation=observation,
                input_set=input_set,
                judge_version=suite.judge_version,
            )
            if not validation.valid or matching[0].label == "unknown":
                invalid += 1
                continue
            values.append(Decimal(int(matching[0].label == target_label)))
            locators.extend(matching[0].locators)
        unassigned = sum(item.output_hash not in used for item in outputs)
        reassigned = min(unassigned, local_missing)
        invalid += reassigned
        missing += local_missing - reassigned
    return _Values(tuple(values), denominator, invalid, missing, tuple(locators))


def _citation_entailment_values(input_set: MetricInputSet, suite: FrozenMetricSuite) -> _Values:
    values: list[Decimal] = []
    locators: list[EvidenceLocator] = []
    invalid = 0
    missing = 0
    denominator = sum(len(item.citations) for item in input_set.observations)
    for observation in input_set.observations:
        outputs = tuple(
            item for item in observation.judge_outputs if item.kind is JudgeKind.CITATION_ENTAILMENT
        )
        used: set[str] = set()
        local_missing = 0
        for citation in observation.citations:
            matching = tuple(
                item
                for item in outputs
                if citation.id in locator_reference_ids(item, EvidenceLocatorKind.CITATION)
            )
            if not matching:
                local_missing += 1
                continue
            used.update(item.output_hash for item in matching)
            if len(matching) != 1:
                invalid += 1
                continue
            validation = validate_judgement(
                matching[0],
                observation=observation,
                input_set=input_set,
                judge_version=suite.judge_version,
            )
            if not validation.valid or matching[0].label == "unknown":
                invalid += 1
                continue
            values.append(Decimal(int(matching[0].label == "entailed")))
            locators.extend(matching[0].locators)
        unassigned = sum(item.output_hash not in used for item in outputs)
        reassigned = min(unassigned, local_missing)
        invalid += reassigned
        missing += local_missing - reassigned
    return _Values(tuple(values), denominator, invalid, missing, tuple(locators))


def _citation_values(
    input_set: MetricInputSet, value: Callable[[CitationInput], Decimal]
) -> _Values:
    citations = tuple(
        item for observation in input_set.observations for item in observation.citations
    )
    values = tuple(value(item) for item in citations)
    return _Values(values, len(citations), 0, 0)


def _citation_order_values(input_set: MetricInputSet) -> _Values:
    values = tuple(
        Decimal(int(citation_order_valid(item.citations)))
        for item in input_set.observations
        if item.citations
    )
    return _Values(
        values,
        len(input_set.planned_slots),
        0,
        len(input_set.planned_slots) - len(values),
    )


def _diversity_values(citations: tuple[CitationInput, ...], count: int, key: str) -> _Values:
    values = tuple(Decimal(1) for _ in citations)
    return _Values(
        values,
        len(citations),
        0,
        0,
        breakdown=((key, Decimal(count)),),
        numerator_override=Decimal(count),
    )


def _performance_slot_scores(
    input_set: MetricInputSet, suite: FrozenMetricSuite
) -> dict[str, Decimal]:
    observations = {item.slot_id: item for item in input_set.observations}
    scores: dict[str, Decimal] = {}
    for slot in input_set.planned_slots:
        observation = observations.get(slot.slot_id)
        if observation is None:
            scores[slot.slot_id] = Decimal(0)
            continue
        product_score = Decimal(int(bool(product_mentions(observation, input_set.subjects))))
        outputs = tuple(
            item for item in observation.judge_outputs if item.kind is JudgeKind.RECOMMENDATION
        )
        recommendation_score = Decimal(0)
        if (
            len(outputs) == 1
            and validate_judgement(
                outputs[0],
                observation=observation,
                input_set=input_set,
                judge_version=suite.judge_version,
            ).valid
        ):
            recommendation_score = Decimal(int(outputs[0].label == "yes"))
        scores[slot.slot_id] = (product_score + recommendation_score) / Decimal(2)
    return scores


def _recommendation_value(output: StructuredJudgeOutput) -> Decimal:
    return Decimal(int(output.label == "yes"))


def _score_value(output: StructuredJudgeOutput) -> Decimal:
    assert output.score is not None
    return output.score


def _interval(
    value_kind: MetricValueKind,
    *,
    numerator: Decimal,
    denominator: int,
    estimate: Decimal,
    observed: tuple[Decimal, ...],
) -> MetricInterval:
    if value_kind is MetricValueKind.BINARY_RATE:
        low, high = _wilson(int(numerator), denominator)
        return MetricInterval("wilson-95-v1", Decimal("0.95"), low, high)
    if value_kind is MetricValueKind.COUNT:
        exact = _quantize(numerator)
        return MetricInterval("exact-count-v1", None, exact, exact)
    if observed:
        low = min(*observed, estimate)
        high = max(*observed, estimate)
    elif value_kind is MetricValueKind.SIGNED_SCORE:
        low, high = Decimal(-1), Decimal(1)
    else:
        low, high = Decimal(0), Decimal(1)
    return MetricInterval("observed-range-v1", None, _quantize(low), _quantize(high))


def _wilson(numerator: int, denominator: int) -> tuple[Decimal, Decimal]:
    if denominator == 0:
        return Decimal(0), Decimal(1)
    n = Decimal(denominator)
    share = Decimal(numerator) / n
    z2 = WILSON_Z * WILSON_Z
    adjustment = Decimal(1) + z2 / n
    center = (share + z2 / (Decimal(2) * n)) / adjustment
    margin = (
        WILSON_Z
        * ((share * (Decimal(1) - share) / n + z2 / (Decimal(4) * n * n)).sqrt())
        / adjustment
    )
    return _quantize(max(Decimal(0), center - margin)), _quantize(min(Decimal(1), center + margin))


def _ratio(numerator: Decimal, denominator: int) -> Decimal:
    return Decimal(0) if denominator == 0 else numerator / Decimal(denominator)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)
