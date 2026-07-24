"""Strict immutable payload decoder for Workflow C semantic metric jobs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from geo_core.semantic_metrics import (
    ApprovedFactReference,
    BaselineQuestionScore,
    CitationInput,
    DeterministicRuleVersions,
    EvidenceLocator,
    EvidenceLocatorKind,
    FrozenMetricSuite,
    JudgeKind,
    JudgeVersion,
    MetricDefinition,
    MetricInputSet,
    MetricKey,
    MetricObservation,
    MetricValueKind,
    PlannedMetricSlot,
    SemanticStratum,
    StructuredJudgeOutput,
    SubjectAssertion,
    SubjectInventory,
)
from geo_core.workflow_c_analysis_common import (
    array_value,
    boolean_value,
    decimal_value,
    hash_value,
    integer_value,
    object_value,
    only_keys,
    optional_integer_value,
    optional_text_value,
    ratio_decimal_value,
    text_value,
    uuid_value,
)
from geo_core.workflow_c_job_specs import WorkflowCJobSpec, WorkflowCJobSpecError


@dataclass(frozen=True)
class SemanticMetricMetadata:
    run_id: UUID
    source_stratum_hash: str
    capture_method: str
    warning_ratio: Decimal
    test_only: bool
    synthetic: bool


def semantic_inputs(
    spec: WorkflowCJobSpec,
) -> tuple[SemanticMetricMetadata, MetricInputSet, FrozenMetricSuite]:
    payload = object_value(spec.payload, "semantic metrics Worker payload")
    value = object_value(payload.get("semantic_metrics"), "semantic metrics Worker input")
    expected_keys = {
        "run_id",
        "source_stratum_hash",
        "capture_method",
        "warning_ratio",
        "test_only",
        "synthetic",
        "input_set",
        "suite",
    }
    # A frozen model program opts a parent into the durable Judge/Arbiter
    # state machine. Legacy semantic Jobs retain their exact existing shape.
    if set(value) not in (expected_keys, expected_keys | {"metric_model_program"}):
        raise WorkflowCJobSpecError("semantic metrics Worker input has an unexpected schema")
    metadata = SemanticMetricMetadata(
        run_id=uuid_value(value.get("run_id"), "sampling run id"),
        source_stratum_hash=hash_value(value.get("source_stratum_hash"), "source stratum hash"),
        capture_method=capture_method(value.get("capture_method")),
        warning_ratio=ratio_decimal_value(value.get("warning_ratio"), "warning ratio"),
        test_only=boolean_value(value.get("test_only"), "test only"),
        synthetic=boolean_value(value.get("synthetic"), "synthetic"),
    )
    return (
        metadata,
        metric_input_set(object_value(value.get("input_set"), "metric input set")),
        metric_suite(object_value(value.get("suite"), "metric suite")),
    )


def metric_input_set(value: Mapping[str, object]) -> MetricInputSet:
    only_keys(
        value,
        {
            "stratum",
            "planned_slots",
            "observations",
            "subjects",
            "approved_facts",
            "verified_urls",
            "approved_corpus_version",
            "approved_corpus_hash",
            "baseline_question_scores",
        },
        "metric input set",
    )
    return MetricInputSet(
        stratum=semantic_stratum(object_value(value.get("stratum"), "semantic stratum")),
        planned_slots=tuple(
            planned_slot(object_value(item, "planned metric slot"))
            for item in array_value(value.get("planned_slots"), "planned metric slots")
        ),
        observations=tuple(
            metric_observation(object_value(item, "metric observation"))
            for item in array_value(value.get("observations"), "metric observations")
        ),
        subjects=subject_inventory(object_value(value.get("subjects"), "subject inventory")),
        approved_facts=tuple(
            approved_fact(object_value(item, "approved Fact"))
            for item in array_value(value.get("approved_facts"), "approved Facts")
        ),
        verified_urls=tuple(
            text_value(item, "verified URL")
            for item in array_value(value.get("verified_urls"), "verified URLs")
        ),
        approved_corpus_version=text_value(
            value.get("approved_corpus_version"), "approved corpus version"
        ),
        approved_corpus_hash=hash_value(value.get("approved_corpus_hash"), "approved corpus hash"),
        baseline_question_scores=tuple(
            baseline_question_score(object_value(item, "baseline question score"))
            for item in array_value(
                value.get("baseline_question_scores"), "baseline question scores"
            )
        ),
    )


def semantic_stratum(value: Mapping[str, object]) -> SemanticStratum:
    if not value:
        raise WorkflowCJobSpecError("semantic stratum must be a non-empty string object")
    dimensions: list[tuple[str, str]] = []
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise WorkflowCJobSpecError("semantic stratum must be a non-empty string object")
        dimensions.append((key, item))
    return SemanticStratum(tuple(dimensions))


def planned_slot(value: Mapping[str, object]) -> PlannedMetricSlot:
    only_keys(value, {"slot_id", "question_id", "question_cluster"}, "planned metric slot")
    return PlannedMetricSlot(
        slot_id=text_value(value.get("slot_id"), "metric slot id"),
        question_id=text_value(value.get("question_id"), "metric question id"),
        question_cluster=text_value(value.get("question_cluster"), "metric question cluster"),
    )


def metric_observation(value: Mapping[str, object]) -> MetricObservation:
    only_keys(
        value,
        {
            "id",
            "slot_id",
            "payload_hash",
            "question_id",
            "question_cluster",
            "answer_text",
            "artifact_version",
            "citations",
            "subject_assertions",
            "judge_outputs",
        },
        "metric observation",
    )
    return MetricObservation(
        id=uuid_value(value.get("id"), "metric observation id"),
        slot_id=text_value(value.get("slot_id"), "metric observation slot id"),
        payload_hash=hash_value(value.get("payload_hash"), "metric observation payload hash"),
        question_id=text_value(value.get("question_id"), "metric observation question id"),
        question_cluster=text_value(value.get("question_cluster"), "metric observation cluster"),
        answer_text=text_value(value.get("answer_text"), "metric observation answer"),
        artifact_version=text_value(
            value.get("artifact_version"), "metric observation artifact version"
        ),
        citations=tuple(
            citation(object_value(item, "metric citation"))
            for item in array_value(value.get("citations"), "metric citations")
        ),
        subject_assertions=tuple(
            subject_assertion(object_value(item, "subject assertion"))
            for item in array_value(value.get("subject_assertions"), "subject assertions")
        ),
        judge_outputs=tuple(
            judge_output(object_value(item, "judge output"))
            for item in array_value(value.get("judge_outputs"), "judge outputs")
        ),
    )


def citation(value: Mapping[str, object]) -> CitationInput:
    only_keys(value, {"id", "ordinal", "url", "visible_title", "source_type"}, "metric citation")
    return CitationInput(
        id=text_value(value.get("id"), "citation id"),
        ordinal=integer_value(value.get("ordinal"), "citation ordinal"),
        url=text_value(value.get("url"), "citation URL"),
        visible_title=text_value(value.get("visible_title"), "citation title"),
        source_type=text_value(value.get("source_type"), "citation source type"),
    )


def subject_assertion(value: Mapping[str, object]) -> SubjectAssertion:
    only_keys(value, {"claimed_subject_key", "catalog_subject_key", "locator"}, "subject assertion")
    return SubjectAssertion(
        claimed_subject_key=text_value(value.get("claimed_subject_key"), "claimed subject"),
        catalog_subject_key=text_value(value.get("catalog_subject_key"), "catalog subject"),
        locator=evidence_locator(object_value(value.get("locator"), "subject assertion locator")),
    )


def judge_output(value: Mapping[str, object]) -> StructuredJudgeOutput:
    only_keys(
        value,
        {"kind", "label", "score", "reason_codes", "locators", "schema_version", "metric_id"},
        "judge output",
    )
    return StructuredJudgeOutput(
        kind=JudgeKind(text_value(value.get("kind"), "judge output kind")),
        label=text_value(value.get("label"), "judge output label"),
        score=(
            None
            if value.get("score") is None
            else decimal_value(value.get("score"), "judge output score")
        ),
        reason_codes=tuple(
            text_value(item, "judge output reason")
            for item in array_value(value.get("reason_codes"), "judge output reasons")
        ),
        locators=tuple(
            evidence_locator(object_value(item, "judge output locator"))
            for item in array_value(value.get("locators"), "judge output locators")
        ),
        schema_version=text_value(value.get("schema_version"), "judge output schema version"),
        metric_id=(
            text_value(value.get("metric_id"), "judge output metric id")
            if value.get("metric_id") is not None
            else None
        ),
    )


def evidence_locator(value: Mapping[str, object]) -> EvidenceLocator:
    only_keys(
        value,
        {"kind", "reference_id", "version", "content_hash", "start", "end", "redacted_quote_hash"},
        "evidence locator",
    )
    return EvidenceLocator(
        kind=EvidenceLocatorKind(text_value(value.get("kind"), "locator kind")),
        reference_id=text_value(value.get("reference_id"), "locator reference"),
        version=optional_text_value(value.get("version"), "locator version"),
        content_hash=(
            hash_value(value.get("content_hash"), "locator content hash")
            if value.get("content_hash") is not None
            else None
        ),
        start=optional_integer_value(value.get("start"), "locator start"),
        end=optional_integer_value(value.get("end"), "locator end"),
        redacted_quote_hash=(
            hash_value(value.get("redacted_quote_hash"), "locator redacted quote hash")
            if value.get("redacted_quote_hash") is not None
            else None
        ),
    )


def subject_inventory(value: Mapping[str, object]) -> SubjectInventory:
    only_keys(
        value,
        {"primary_subject_key", "brand_aliases", "product_aliases", "competitors"},
        "subject inventory",
    )
    competitors: list[tuple[str, tuple[str, ...]]] = []
    for item in array_value(value.get("competitors"), "competitors"):
        if not isinstance(item, list) or len(item) != 2:
            raise WorkflowCJobSpecError("competitor input must have a key and alias array")
        competitors.append(
            (
                text_value(item[0], "competitor key"),
                tuple(
                    text_value(alias, "competitor alias")
                    for alias in array_value(item[1], "competitor aliases")
                ),
            )
        )
    return SubjectInventory(
        primary_subject_key=text_value(value.get("primary_subject_key"), "primary subject key"),
        brand_aliases=tuple(
            text_value(item, "brand alias")
            for item in array_value(value.get("brand_aliases"), "brand aliases")
        ),
        product_aliases=tuple(
            text_value(item, "product alias")
            for item in array_value(value.get("product_aliases"), "product aliases")
        ),
        competitors=tuple(competitors),
    )


def approved_fact(value: Mapping[str, object]) -> ApprovedFactReference:
    only_keys(value, {"id", "version", "subject_key", "sha256"}, "approved Fact")
    return ApprovedFactReference(
        id=text_value(value.get("id"), "Fact id"),
        version=text_value(value.get("version"), "Fact version"),
        subject_key=text_value(value.get("subject_key"), "Fact subject key"),
        sha256=hash_value(value.get("sha256"), "Fact hash"),
    )


def baseline_question_score(value: Mapping[str, object]) -> BaselineQuestionScore:
    only_keys(value, {"question_id", "score", "snapshot_hash"}, "baseline question score")
    return BaselineQuestionScore(
        question_id=text_value(value.get("question_id"), "baseline question id"),
        score=ratio_decimal_value(value.get("score"), "baseline question score"),
        snapshot_hash=hash_value(value.get("snapshot_hash"), "baseline snapshot hash"),
    )


def metric_suite(value: Mapping[str, object]) -> FrozenMetricSuite:
    only_keys(
        value,
        {"definitions", "judge_version", "rule_versions", "minimum_valid_completion"},
        "metric suite",
    )
    return FrozenMetricSuite(
        definitions=tuple(
            metric_definition(object_value(item, "metric definition"))
            for item in array_value(value.get("definitions"), "metric definitions")
        ),
        judge_version=judge_version(object_value(value.get("judge_version"), "judge version")),
        rule_versions=rule_versions(object_value(value.get("rule_versions"), "rule versions")),
        minimum_valid_completion=ratio_decimal_value(
            value.get("minimum_valid_completion"), "minimum valid completion"
        ),
    )


def metric_definition(value: Mapping[str, object]) -> MetricDefinition:
    only_keys(value, {"key", "version", "value_kind", "judge_kind"}, "metric definition")
    raw_judge = value.get("judge_kind")
    return MetricDefinition(
        key=MetricKey(text_value(value.get("key"), "metric key")),
        version=text_value(value.get("version"), "metric version"),
        value_kind=MetricValueKind(text_value(value.get("value_kind"), "metric value kind")),
        judge_kind=(
            JudgeKind(text_value(raw_judge, "metric judge kind")) if raw_judge is not None else None
        ),
    )


def judge_version(value: Mapping[str, object]) -> JudgeVersion:
    only_keys(
        value,
        {
            "key",
            "version",
            "prompt_release_id",
            "prompt_release_hash",
            "model_identity",
            "schema_version",
        },
        "judge version",
    )
    return JudgeVersion(
        key=text_value(value.get("key"), "judge version key"),
        version=text_value(value.get("version"), "judge version"),
        prompt_release_id=uuid_value(value.get("prompt_release_id"), "judge Prompt Release id"),
        prompt_release_hash=hash_value(
            value.get("prompt_release_hash"), "judge Prompt Release hash"
        ),
        model_identity=text_value(value.get("model_identity"), "judge model identity"),
        schema_version=text_value(value.get("schema_version"), "judge schema version"),
    )


def rule_versions(value: Mapping[str, object]) -> DeterministicRuleVersions:
    only_keys(
        value, {"subject", "url", "citation_order", "denominator", "mention"}, "rule versions"
    )
    return DeterministicRuleVersions(
        subject=text_value(value.get("subject"), "subject rule version"),
        url=text_value(value.get("url"), "URL rule version"),
        citation_order=text_value(value.get("citation_order"), "citation order rule version"),
        denominator=text_value(value.get("denominator"), "denominator rule version"),
        mention=text_value(value.get("mention"), "mention rule version"),
    )


def capture_method(value: object) -> str:
    method = text_value(value, "capture method")
    if method not in {"provider_api", "proxy_grounded_api", "manual_ui", "automated_ui"}:
        raise WorkflowCJobSpecError("semantic metrics capture method is invalid")
    return method


__all__ = ["SemanticMetricMetadata", "semantic_inputs"]
