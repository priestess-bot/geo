"""Strict structured-output parsing and evidence-locator validation for metric judges."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import math

from geo_core.semantic_metrics.contracts import (
    EvidenceLocator,
    EvidenceLocatorKind,
    JudgeKind,
    JudgeVersion,
    MetricInputSet,
    MetricObservation,
    SemanticMetricRuleViolation,
    StructuredJudgeOutput,
)


OUTPUT_FIELDS = frozenset({"kind", "label", "score", "reason_codes", "locators", "schema_version"})
LOCATOR_FIELDS = frozenset(
    {
        "kind",
        "reference_id",
        "version",
        "content_hash",
        "start",
        "end",
        "redacted_quote_hash",
    }
)


class JudgeOutputRejected(SemanticMetricRuleViolation):
    """A model response does not satisfy the frozen structured-output schema."""


class JudgementValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class ValidatedJudgement:
    output: StructuredJudgeOutput
    status: JudgementValidationStatus
    invalid_reasons: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.status is JudgementValidationStatus.VALID


def parse_structured_judge_output(payload: Mapping[str, object]) -> StructuredJudgeOutput:
    """Parse exactly the frozen JSON shape; unknown or free-text fields are rejected."""

    if frozenset(payload) != OUTPUT_FIELDS:
        raise JudgeOutputRejected("judge output fields do not match the frozen schema")
    raw_reasons = payload["reason_codes"]
    raw_locators = payload["locators"]
    if not isinstance(raw_reasons, list) or not all(isinstance(item, str) for item in raw_reasons):
        raise JudgeOutputRejected("judge reason_codes must be a JSON string array")
    if not isinstance(raw_locators, list) or not all(
        isinstance(item, Mapping) for item in raw_locators
    ):
        raise JudgeOutputRejected("judge locators must be a JSON object array")
    kind = _string(payload["kind"], "judge kind")
    label = _string(payload["label"], "judge label")
    schema_version = _string(payload["schema_version"], "judge schema version")
    score = _decimal_or_none(payload["score"])
    locators = tuple(_parse_locator(item) for item in raw_locators)
    try:
        return StructuredJudgeOutput(
            kind=JudgeKind(kind),
            label=label,
            score=score,
            reason_codes=tuple(raw_reasons),
            locators=locators,
            schema_version=schema_version,
        )
    except (ValueError, TypeError) as error:
        raise JudgeOutputRejected("judge output violates the frozen schema") from error


def validate_judgement(
    output: StructuredJudgeOutput,
    *,
    observation: MetricObservation,
    input_set: MetricInputSet,
    judge_version: JudgeVersion,
) -> ValidatedJudgement:
    reasons: set[str] = set()
    if output.schema_version != judge_version.schema_version:
        reasons.add("schema_version_mismatch")
    if not output.locators:
        reasons.add("missing_evidence_locator")
    for locator in output.locators:
        reasons.update(_locator_errors(locator, observation=observation, input_set=input_set))
    locator_kinds = {item.kind for item in output.locators}
    _validate_kind_contract(output, locator_kinds, reasons)
    invalid_reasons = tuple(sorted(reasons))
    return ValidatedJudgement(
        output=output,
        status=(
            JudgementValidationStatus.INVALID
            if invalid_reasons
            else JudgementValidationStatus.VALID
        ),
        invalid_reasons=invalid_reasons,
    )


def locator_reference_ids(
    output: StructuredJudgeOutput, kind: EvidenceLocatorKind
) -> frozenset[str]:
    return frozenset(item.reference_id for item in output.locators if item.kind is kind)


def _parse_locator(payload: Mapping[str, object]) -> EvidenceLocator:
    if frozenset(payload) != LOCATOR_FIELDS:
        raise JudgeOutputRejected("judge locator fields do not match the frozen schema")
    version = payload["version"]
    content_hash = payload["content_hash"]
    redacted_quote_hash = payload["redacted_quote_hash"]
    start = payload["start"]
    end = payload["end"]
    if version is not None and not isinstance(version, str):
        raise JudgeOutputRejected("judge locator version must be a string or null")
    if content_hash is not None and not isinstance(content_hash, str):
        raise JudgeOutputRejected("judge locator content_hash must be a string or null")
    if redacted_quote_hash is not None and not isinstance(redacted_quote_hash, str):
        raise JudgeOutputRejected(
            "judge locator redacted_quote_hash must be a string or null"
        )
    if start is not None and (not isinstance(start, int) or isinstance(start, bool)):
        raise JudgeOutputRejected("judge locator start must be an integer or null")
    if end is not None and (not isinstance(end, int) or isinstance(end, bool)):
        raise JudgeOutputRejected("judge locator end must be an integer or null")
    try:
        return EvidenceLocator(
            kind=EvidenceLocatorKind(_string(payload["kind"], "locator kind")),
            reference_id=_string(payload["reference_id"], "locator reference"),
            version=version,
            content_hash=content_hash,
            start=start,
            end=end,
            redacted_quote_hash=redacted_quote_hash,
        )
    except (ValueError, TypeError) as error:
        raise JudgeOutputRejected("judge locator violates the frozen schema") from error


def _locator_errors(
    locator: EvidenceLocator,
    *,
    observation: MetricObservation,
    input_set: MetricInputSet,
) -> set[str]:
    if locator.kind is EvidenceLocatorKind.ANSWER_SPAN:
        if locator.reference_id != str(observation.id):
            return {"answer_span_wrong_observation"}
        if locator.version != observation.artifact_version:
            return {"answer_span_artifact_version_mismatch"}
        if locator.content_hash != observation.payload_hash:
            return {"answer_span_content_hash_mismatch"}
        assert locator.start is not None and locator.end is not None
        if locator.end > len(observation.answer_text):
            return {"answer_span_out_of_range"}
        if locator.redacted_quote_hash is not None and (
            _sha256(observation.answer_text[locator.start : locator.end])
            != locator.redacted_quote_hash
        ):
            return {"answer_span_redacted_quote_hash_mismatch"}
        return set()
    if locator.kind is EvidenceLocatorKind.CITATION:
        return (
            set()
            if locator.reference_id in {item.id for item in observation.citations}
            else {"citation_locator_not_in_observation"}
        )
    approved = {(item.id, item.version) for item in input_set.approved_facts}
    return (
        set()
        if (locator.reference_id, locator.version) in approved
        else {"fact_locator_not_approved"}
    )


def _validate_kind_contract(
    output: StructuredJudgeOutput,
    locator_kinds: set[EvidenceLocatorKind],
    reasons: set[str],
) -> None:
    label = output.label
    score = output.score
    if output.kind is JudgeKind.RECOMMENDATION:
        _label(label, {"yes", "no"}, reasons)
        _score(score, Decimal(0), Decimal(1), reasons)
        _locator_kind(EvidenceLocatorKind.ANSWER_SPAN, locator_kinds, reasons)
    elif output.kind is JudgeKind.SENTIMENT:
        _label(label, {"positive", "neutral", "negative"}, reasons)
        _score(score, Decimal(-1), Decimal(1), reasons)
        _locator_kind(EvidenceLocatorKind.ANSWER_SPAN, locator_kinds, reasons)
        if label == "negative" and not output.reason_codes:
            reasons.add("negative_sentiment_missing_reason")
    elif output.kind is JudgeKind.FACT:
        _label(label, {"accurate", "conflict", "omission", "unknown"}, reasons)
        if score is not None:
            reasons.add("fact_judgement_score_forbidden")
        _locator_kind(EvidenceLocatorKind.FACT, locator_kinds, reasons)
        if label in {"accurate", "conflict"}:
            _locator_kind(EvidenceLocatorKind.ANSWER_SPAN, locator_kinds, reasons)
    elif output.kind is JudgeKind.CITATION_ENTAILMENT:
        _label(label, {"entailed", "not_entailed", "unknown"}, reasons)
        if score is not None:
            reasons.add("citation_judgement_score_forbidden")
        _locator_kind(EvidenceLocatorKind.CITATION, locator_kinds, reasons)
    else:
        _label(label, {"absorbed", "not_absorbed", "unknown"}, reasons)
        _score(score, Decimal(0), Decimal(1), reasons)
        if not locator_kinds.intersection(
            {EvidenceLocatorKind.ANSWER_SPAN, EvidenceLocatorKind.FACT}
        ):
            reasons.add("corpus_absorption_missing_answer_or_fact_locator")


def _label(label: str, allowed: set[str], reasons: set[str]) -> None:
    if label not in allowed:
        reasons.add("unsupported_judgement_label")


def _score(
    score: Decimal | None,
    minimum: Decimal,
    maximum: Decimal,
    reasons: set[str],
) -> None:
    if score is None:
        reasons.add("missing_judgement_score")
    elif not minimum <= score <= maximum:
        reasons.add("judgement_score_out_of_range")


def _locator_kind(
    required: EvidenceLocatorKind,
    actual: set[EvidenceLocatorKind],
    reasons: set[str],
) -> None:
    if required not in actual:
        reasons.add(f"missing_{required.value}_locator")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JudgeOutputRejected(f"{label} must be a non-empty string")
    return value.strip()


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise JudgeOutputRejected("judge score must be numeric or null")
    if isinstance(value, float) and not math.isfinite(value):
        raise JudgeOutputRejected("judge score must be finite")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise JudgeOutputRejected("judge score must be numeric") from error
    if not result.is_finite():
        raise JudgeOutputRejected("judge score must be finite")
    return result


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
