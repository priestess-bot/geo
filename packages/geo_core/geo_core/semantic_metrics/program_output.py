"""Adapter from frozen metric_judge/arbiter Program output to semantic contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import re

from geo_core.semantic_metrics.contracts import (
    EvidenceLocatorKind,
    MetricObservation,
    StructuredJudgeOutput,
)
from geo_core.semantic_metrics.judges import JudgeOutputRejected
from geo_core.semantic_metrics.judges import parse_structured_judge_output
from geo_core.semantic_metrics.prompt_injection import (
    has_high_confidence_prompt_injection,
)


COMMON_OUTPUT_FIELDS = frozenset(
    {
        "subject_id",
        "evidence_refs",
        "citation_refs",
        "output_locale",
        "automatic_action_authorised",
        "injection_detected",
        "untrusted_instruction_followed",
    }
)
METRIC_JUDGE_FIELDS = COMMON_OUTPUT_FIELDS | {"results", "overall_status"}
METRIC_RESULT_FIELDS = frozenset(
    {
        "metric_id",
        "kind",
        "label",
        "score",
        "reason_codes",
        "evidence_refs",
        "evidence_locators",
    }
)
ARBITER_FIELDS = COMMON_OUTPUT_FIELDS | {
    "disposition",
    "selected_candidate_id",
    "considered_evaluators",
    "issue_codes",
    "rationale",
}
_REASON = re.compile(r"^[a-z][a-z0-9_.:-]{0,199}$")


class MetricJudgeKind(StrEnum):
    RECOMMENDATION = "recommendation"
    SENTIMENT = "sentiment"
    FACT = "fact"
    CITATION_ENTAILMENT = "citation_entailment"
    CORPUS_ABSORPTION = "corpus_absorption"


_LABELS: Mapping[MetricJudgeKind, frozenset[str]] = {
    MetricJudgeKind.RECOMMENDATION: frozenset({"yes", "no"}),
    MetricJudgeKind.SENTIMENT: frozenset({"positive", "neutral", "negative"}),
    MetricJudgeKind.FACT: frozenset({"accurate", "conflict", "omission", "unknown"}),
    MetricJudgeKind.CITATION_ENTAILMENT: frozenset(
        {"entailed", "not_entailed", "unknown"}
    ),
    MetricJudgeKind.CORPUS_ABSORPTION: frozenset(
        {"absorbed", "not_absorbed", "unknown"}
    ),
}


@dataclass(frozen=True)
class MetricJudgePlan:
    metric_id: str
    metric_kind: MetricJudgeKind
    definition: str
    allowed_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        metric_id = _required_text(self.metric_id, "metric judge metric ID")
        definition = _required_text(
            self.definition, "metric judge definition", maximum=2000
        )
        kind = MetricJudgeKind(self.metric_kind)
        refs = tuple(sorted({_required_text(item, "evidence reference") for item in self.allowed_evidence_refs}))
        object.__setattr__(self, "metric_id", metric_id)
        object.__setattr__(self, "metric_kind", kind)
        object.__setattr__(self, "definition", definition)
        object.__setattr__(self, "allowed_evidence_refs", refs)

    def prompt_value(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "metric_kind": self.metric_kind.value,
            "definition": self.definition,
        }


@dataclass(frozen=True)
class ParsedMetricJudgeProgramOutput:
    results: tuple[StructuredJudgeOutput, ...]
    overall_status: str
    output_locale: str


@dataclass(frozen=True)
class ParsedArbiterProgramOutput:
    disposition: str
    selected_candidate_id: str
    considered_evaluators: tuple[str, ...]
    issue_codes: tuple[str, ...]


def parse_metric_judge_program_output(
    payload: Mapping[str, object],
    *,
    plans: Sequence[MetricJudgePlan],
    observation: MetricObservation,
    subject_id: str,
    output_locale: str,
    schema_version: str,
    prompt_injection_expected: bool,
) -> ParsedMetricJudgeProgramOutput:
    if not isinstance(prompt_injection_expected, bool):
        raise JudgeOutputRejected("metric Program injection expectation must be boolean")
    if prompt_injection_expected is not has_high_confidence_prompt_injection(
        observation.answer_text
    ):
        raise JudgeOutputRejected(
            "metric Program injection expectation changed from frozen observation"
        )
    if frozenset(payload) != METRIC_JUDGE_FIELDS:
        raise JudgeOutputRejected(
            "metric_judge output fields do not match the frozen Program schema"
        )
    _validate_common(
        payload,
        subject_id=subject_id,
        output_locale=output_locale,
        allowed_evidence_refs={
            reference for plan in plans for reference in plan.allowed_evidence_refs
        },
        allowed_citation_refs={item.id for item in observation.citations},
        prompt_injection_expected=prompt_injection_expected,
    )
    overall = _enum_text(
        payload["overall_status"], {"pass", "warning", "fail"}, "overall status"
    )
    raw_results = payload["results"]
    if not isinstance(raw_results, list) or not all(
        isinstance(item, Mapping) for item in raw_results
    ):
        raise JudgeOutputRejected("metric_judge results must be an object array")
    by_id = {plan.metric_id: plan for plan in plans}
    if len(by_id) != len(tuple(plans)):
        raise JudgeOutputRejected("metric_judge plan IDs must be unique")
    observed_ids = tuple(_result_id(item) for item in raw_results)
    if len(set(observed_ids)) != len(observed_ids) or set(observed_ids) != set(by_id):
        raise JudgeOutputRejected(
            "metric_judge must return every requested metric exactly once"
        )
    results = tuple(
        _parse_metric_result(
            item,
            plan=by_id[_result_id(item)],
            observation=observation,
            schema_version=schema_version,
        )
        for item in raw_results
    )
    return ParsedMetricJudgeProgramOutput(
        results=results,
        overall_status=overall,
        output_locale=output_locale,
    )


def parse_arbiter_program_output(
    payload: Mapping[str, object],
    *,
    subject_id: str,
    output_locale: str,
    candidate_ids: Sequence[str],
    evaluator_ids: Sequence[str],
    allowed_evidence_refs: set[str],
    allowed_citation_refs: set[str],
) -> ParsedArbiterProgramOutput:
    if frozenset(payload) != ARBITER_FIELDS:
        raise JudgeOutputRejected(
            "arbiter output fields do not match the frozen Program schema"
        )
    _validate_common(
        payload,
        subject_id=subject_id,
        output_locale=output_locale,
        allowed_evidence_refs=allowed_evidence_refs,
        allowed_citation_refs=allowed_citation_refs,
    )
    disposition = _enum_text(
        payload["disposition"], {"pass", "warning", "revise"}, "arbiter disposition"
    )
    selected = _required_text(payload["selected_candidate_id"], "selected candidate")
    frozen_candidates = tuple(sorted({_required_text(item, "candidate ID") for item in candidate_ids}))
    if selected not in frozen_candidates:
        raise JudgeOutputRejected("arbiter selected candidate is outside the frozen set")
    considered = _string_array(payload["considered_evaluators"], "considered evaluators")
    frozen_evaluators = tuple(sorted({_required_text(item, "evaluator ID") for item in evaluator_ids}))
    if considered != frozen_evaluators or len(considered) < 2:
        raise JudgeOutputRejected("arbiter considered evaluator set changed")
    issues = _reason_codes(payload["issue_codes"])
    _required_text(payload["rationale"], "arbiter rationale", maximum=4000)
    return ParsedArbiterProgramOutput(
        disposition=disposition,
        selected_candidate_id=selected,
        considered_evaluators=considered,
        issue_codes=issues,
    )


def _parse_metric_result(
    payload: Mapping[str, object],
    *,
    plan: MetricJudgePlan,
    observation: MetricObservation,
    schema_version: str,
) -> StructuredJudgeOutput:
    if frozenset(payload) != METRIC_RESULT_FIELDS:
        raise JudgeOutputRejected("metric_judge result fields changed")
    if _result_id(payload) != plan.metric_id:
        raise JudgeOutputRejected("metric_judge result identity changed")
    kind = _enum_text(
        payload["kind"], {plan.metric_kind.value}, "metric result kind"
    )
    label = _enum_text(payload["label"], _LABELS[plan.metric_kind], "metric label")
    evidence_refs = _string_array(payload["evidence_refs"], "metric evidence refs")
    if not set(evidence_refs).issubset(plan.allowed_evidence_refs):
        raise JudgeOutputRejected("metric_judge evidence reference is outside input")
    raw_locators = payload["evidence_locators"]
    if not isinstance(raw_locators, list) or not all(
        isinstance(item, Mapping) for item in raw_locators
    ):
        raise JudgeOutputRejected(
            "metric_judge evidence locators must be typed objects"
        )
    output = parse_structured_judge_output(
        {
            "kind": kind,
            "label": label,
            "score": payload["score"],
            "reason_codes": payload["reason_codes"],
            "locators": raw_locators,
            "schema_version": schema_version,
        }
    )
    # The generic StructuredJudgeOutput is shared with non-metric judges.  Keep
    # the immutable metric ID from the strict Program result before it joins an
    # observation, otherwise two metrics with one JudgeKind become ambiguous.
    output = replace(output, metric_id=plan.metric_id)
    if not output.locators:
        raise JudgeOutputRejected("metric_judge result needs an evidence locator")
    if output.reason_codes != _reason_codes(payload["reason_codes"]):
        raise JudgeOutputRejected("metric_judge reason code normalization changed")
    _validate_result_score(output, plan.metric_kind)
    _validate_result_locators(
        output,
        observation=observation,
        evidence_refs=set(evidence_refs),
    )
    return output


def _validate_common(
    payload: Mapping[str, object],
    *,
    subject_id: str,
    output_locale: str,
    allowed_evidence_refs: set[str],
    allowed_citation_refs: set[str],
    prompt_injection_expected: bool | None = None,
) -> None:
    if payload["subject_id"] != subject_id or payload["output_locale"] != output_locale:
        raise JudgeOutputRejected("Program output subject or locale changed")
    evidence = _string_array(payload["evidence_refs"], "evidence refs")
    citations = _string_array(payload["citation_refs"], "citation refs")
    if not set(evidence).issubset(allowed_evidence_refs) or not set(citations).issubset(
        allowed_citation_refs
    ):
        raise JudgeOutputRejected("Program output references evidence outside input")
    for field in (
        "automatic_action_authorised",
        "injection_detected",
        "untrusted_instruction_followed",
    ):
        if not isinstance(payload[field], bool):
            raise JudgeOutputRejected(f"Program output {field} must be boolean")
    if payload["automatic_action_authorised"]:
        raise JudgeOutputRejected("metric Programs cannot authorize automatic action")
    if (
        prompt_injection_expected is not None
        and payload["injection_detected"] is not prompt_injection_expected
    ):
        raise JudgeOutputRejected(
            "metric Program injection detection does not match deterministic input"
        )
    if payload["injection_detected"] or payload["untrusted_instruction_followed"]:
        raise JudgeOutputRejected("metric Program output failed injection governance")


def _validate_result_locators(
    output: StructuredJudgeOutput,
    *,
    observation: MetricObservation,
    evidence_refs: set[str],
) -> None:
    citations = {item.id for item in observation.citations}
    for locator in output.locators:
        if locator.kind is EvidenceLocatorKind.ANSWER_SPAN:
            if (
                locator.reference_id != str(observation.id)
                or locator.version != observation.artifact_version
                or locator.content_hash != observation.payload_hash
                or locator.end is None
                or locator.end > len(observation.answer_text)
                or (
                    locator.redacted_quote_hash is not None
                    and locator.redacted_quote_hash
                    != hashlib.sha256(
                        observation.answer_text[
                            locator.start : locator.end
                        ].encode("utf-8")
                    ).hexdigest()
                )
            ):
                raise JudgeOutputRejected(
                    "metric_judge answer locator changed frozen observation lineage"
                )
        elif locator.kind is EvidenceLocatorKind.CITATION:
            if locator.reference_id not in citations:
                raise JudgeOutputRejected(
                    "metric_judge citation locator is outside the observation"
                )
        elif f"{locator.reference_id}@{locator.version}" not in evidence_refs:
            raise JudgeOutputRejected(
                "metric_judge fact locator is outside result evidence refs"
            )


def _validate_result_score(
    output: StructuredJudgeOutput, kind: MetricJudgeKind
) -> None:
    if kind in {MetricJudgeKind.FACT, MetricJudgeKind.CITATION_ENTAILMENT}:
        if output.score is not None:
            raise JudgeOutputRejected("categorical metric judge score must be null")
        return
    if output.score is None:
        raise JudgeOutputRejected("scored metric judge result needs a score")
    minimum = -1 if kind is MetricJudgeKind.SENTIMENT else 0
    if not minimum <= output.score <= 1:
        raise JudgeOutputRejected("metric judge score is outside its kind range")


def _result_id(value: Mapping[str, object]) -> str:
    return _required_text(value.get("metric_id"), "metric result ID")


def _reason_codes(value: object) -> tuple[str, ...]:
    codes = _string_array(value, "reason codes")
    if any(_REASON.fullmatch(item) is None for item in codes):
        raise JudgeOutputRejected("reason code is invalid")
    return codes


def _string_array(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise JudgeOutputRejected(f"{label} must be a string array")
    normalized = tuple(sorted({_required_text(item, label) for item in value}))
    if len(normalized) != len(value):
        raise JudgeOutputRejected(f"{label} must not contain duplicates")
    return normalized


def _enum_text(value: object, allowed: set[str] | frozenset[str], label: str) -> str:
    normalized = _required_text(value, label).casefold()
    if normalized not in allowed:
        raise JudgeOutputRejected(f"{label} is unsupported")
    return normalized


def _required_text(value: object, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise JudgeOutputRejected(f"{label} must be a non-empty bounded string")
    return value.strip()


__all__ = [
    "ARBITER_FIELDS",
    "COMMON_OUTPUT_FIELDS",
    "METRIC_JUDGE_FIELDS",
    "METRIC_RESULT_FIELDS",
    "MetricJudgeKind",
    "MetricJudgePlan",
    "ParsedArbiterProgramOutput",
    "ParsedMetricJudgeProgramOutput",
    "parse_arbiter_program_output",
    "parse_metric_judge_program_output",
]
