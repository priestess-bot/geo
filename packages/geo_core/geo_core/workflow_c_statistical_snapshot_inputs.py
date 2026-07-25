"""Frozen snapshot loading and validation for Workflow C statistics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from geo_core.sampling import SamplingSourceStratum, sampling_source_stratum_from_value
from geo_core.semantic_metrics._validation import canonical_hash as semantic_hash
from geo_core.workflow_c_analysis_admission import WorkflowCAnalysisAdmissionError
from geo_core.workflow_c_statistical_protocols import (
    ComparisonPlanDefinition,
    DriftProtocolDefinition,
    StatisticalProtocolKind,
    parse_statistical_protocol_definition,
)


_HASH_CHARACTERS = frozenset("0123456789abcdef")


class PostgresWorkflowCStatisticalAdmissionError(WorkflowCAnalysisAdmissionError):
    """A governed statistical Job could not be reconstructed safely."""


@dataclass(frozen=True)
class _QuestionPerformance:
    question_id: str
    question_cluster: str
    score: Decimal
    planned_slot_count: int


@dataclass(frozen=True)
class _MetricSnapshot:
    snapshot_hash: str
    input_set_hash: str
    metric_suite_hash: str
    source_stratum_hash: str
    capture_method: str
    evidence_status: str
    sampling_suite_hash: str
    question_set_hash: str
    source: SamplingSourceStratum
    questions: tuple[_QuestionPerformance, ...]


@dataclass(frozen=True)
class _ApprovedProtocol:
    id: UUID
    definition_hash: str
    definition: ComparisonPlanDefinition | DriftProtocolDefinition


def _load_protocol(
    connection: Any,
    *,
    project_id: UUID,
    protocol_id: UUID,
    expected_kind: StatisticalProtocolKind,
) -> _ApprovedProtocol:
    row = connection.execute(
        """SELECT id, protocol_kind AS kind, status, definition_hash, definition
             FROM workflow_c_statistical_protocol_versions
            WHERE project_id = %s AND id = %s""",
        (project_id, protocol_id),
    ).fetchone()
    if row is None:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "approved statistical protocol does not exist"
        )
    value = _mapping(row, "statistical protocol row")
    if value.get("status") != "approved" or value.get("kind") != expected_kind.value:
        raise PostgresWorkflowCStatisticalAdmissionError(
            f"an approved {expected_kind.value} is required"
        )
    definition = parse_statistical_protocol_definition(
        _mapping(value.get("definition"), "statistical protocol definition")
    )
    definition_hash = _hash(value.get("definition_hash"), "statistical protocol hash")
    if definition.kind is not expected_kind or definition.definition_hash != definition_hash:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "statistical protocol definition lineage is corrupt"
        )
    return _ApprovedProtocol(
        id=_uuid(value.get("id"), "statistical protocol id"),
        definition_hash=definition_hash,
        definition=definition,
    )


def _load_snapshots(
    connection: Any,
    *,
    project_id: UUID,
    source_hash: str,
    target_hash: str,
) -> tuple[_MetricSnapshot, _MetricSnapshot]:
    rows = connection.execute(
        """SELECT metric.snapshot_hash, metric.input_set_hash,
                  metric.metric_suite_hash, metric.source_stratum_hash,
                  metric.capture_method, metric.evidence_status, metric.payload,
                  run.suite_hash AS sampling_suite_hash,
                  suite.source_stratum_hash AS suite_source_stratum_hash,
                  suite.capture_method AS suite_capture_method,
                  suite.payload AS sampling_suite_payload
             FROM workflow_c_semantic_metric_snapshots AS metric
             JOIN workflow_c_sampling_runs AS run
               ON run.project_id = metric.project_id AND run.id = metric.run_id
             JOIN workflow_c_sampling_suites AS suite
               ON suite.project_id = run.project_id AND suite.id = run.suite_id
            WHERE metric.project_id = %s AND metric.snapshot_hash = ANY(%s)
            ORDER BY metric.snapshot_hash""",
        (project_id, [source_hash, target_hash]),
    ).fetchall()
    by_hash = {
        snapshot.snapshot_hash: snapshot
        for snapshot in (_snapshot(_mapping(row, "metric snapshot row")) for row in rows)
    }
    if set(by_hash) != {source_hash, target_hash}:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "both immutable semantic metric snapshots are required"
        )
    return by_hash[source_hash], by_hash[target_hash]


def _snapshot(row: Mapping[str, object]) -> _MetricSnapshot:
    snapshot_hash = _hash(row.get("snapshot_hash"), "metric snapshot hash")
    input_set_hash = _hash(row.get("input_set_hash"), "metric input set hash")
    metric_suite_hash = _hash(row.get("metric_suite_hash"), "metric suite hash")
    source_stratum_hash = _hash(
        row.get("source_stratum_hash"), "metric source stratum hash"
    )
    capture_method = _text(row.get("capture_method"), "metric capture method")
    evidence_status = _text(row.get("evidence_status"), "metric evidence status")
    if evidence_status not in {"complete", "insufficient_evidence"}:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "metric snapshot evidence status is invalid"
        )
    sampling_suite_hash = _hash(
        row.get("sampling_suite_hash"), "sampling suite hash"
    )
    payload = _mapping(row.get("payload"), "metric snapshot payload")
    _exact_keys(
        payload,
        {
            "input_set_hash",
            "suite_hash",
            "stratum_hash",
            "results",
            "performance",
            "computed_at",
        },
        "metric snapshot payload",
    )
    result_value = dict(payload)
    result_value.pop("computed_at")
    if semantic_hash(result_value) != snapshot_hash:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "metric snapshot payload hash is corrupt"
        )
    if payload.get("input_set_hash") != input_set_hash or (
        payload.get("suite_hash") != metric_suite_hash
    ):
        raise PostgresWorkflowCStatisticalAdmissionError(
            "metric snapshot header differs from its payload"
        )
    suite_payload = _mapping(row.get("sampling_suite_payload"), "sampling suite payload")
    _exact_keys(
        suite_payload,
        {"schema_version", "suite", "frozen_by", "frozen_at"},
        "sampling suite payload",
    )
    if suite_payload.get("schema_version") != 1:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "sampling suite payload schema is invalid"
        )
    suite = _mapping(suite_payload.get("suite"), "sampling suite definition")
    source = sampling_source_stratum_from_value(suite.get("source_stratum"))
    if source.stratum_hash != source_stratum_hash or (
        row.get("suite_source_stratum_hash") != source_stratum_hash
    ):
        raise PostgresWorkflowCStatisticalAdmissionError(
            "sampling SourceStratum lineage differs from metric snapshot"
        )
    if source.capture_method.value != capture_method or (
        row.get("suite_capture_method") != capture_method
    ):
        raise PostgresWorkflowCStatisticalAdmissionError(
            "sampling capture method differs from metric snapshot"
        )
    question_set_hash = _hash(suite.get("question_set_hash"), "QuestionSet hash")
    suite_question_ids = _suite_question_ids(suite)
    questions = _performance_questions(payload)
    if {item.question_id for item in questions} != suite_question_ids:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "metric performance question inventory differs from its Sampling Suite"
        )
    _validate_semantic_stratum(
        payload,
        source=source,
        sampling_suite_hash=sampling_suite_hash,
        source_stratum_hash=source_stratum_hash,
        capture_method=capture_method,
    )
    return _MetricSnapshot(
        snapshot_hash=snapshot_hash,
        input_set_hash=input_set_hash,
        metric_suite_hash=metric_suite_hash,
        source_stratum_hash=source_stratum_hash,
        capture_method=capture_method,
        evidence_status=evidence_status,
        sampling_suite_hash=sampling_suite_hash,
        question_set_hash=question_set_hash,
        source=source,
        questions=questions,
    )


def _performance_questions(
    snapshot_payload: Mapping[str, object],
) -> tuple[_QuestionPerformance, ...]:
    performance = _mapping(snapshot_payload.get("performance"), "metric performance")
    _exact_keys(
        performance,
        {
            "questions",
            "clusters",
            "worst_question_id",
            "worst_question_score",
            "worst_cluster",
            "worst_cluster_score",
            "negative_gain",
        },
        "metric performance",
    )
    values = _array(performance.get("questions"), "metric performance questions")
    if not values:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "metric performance questions are required"
        )
    questions: list[_QuestionPerformance] = []
    for raw in values:
        value = _mapping(raw, "metric performance question")
        _exact_keys(
            value,
            {"question_id", "question_cluster", "score", "planned_slot_count"},
            "metric performance question",
        )
        planned = _integer(value.get("planned_slot_count"), "planned slot count")
        if planned < 1:
            raise PostgresWorkflowCStatisticalAdmissionError(
                "metric planned slot count must be positive"
            )
        questions.append(
            _QuestionPerformance(
                question_id=_text(value.get("question_id"), "metric question id"),
                question_cluster=_text(
                    value.get("question_cluster"), "metric question cluster"
                ),
                score=_decimal(value.get("score"), "metric question score"),
                planned_slot_count=planned,
            )
        )
    result = tuple(sorted(questions, key=lambda item: item.question_id))
    if len({item.question_id for item in result}) != len(result):
        raise PostgresWorkflowCStatisticalAdmissionError(
            "metric performance question ids must be unique"
        )
    return result
def _validate_semantic_stratum(
    snapshot_payload: Mapping[str, object],
    *,
    source: SamplingSourceStratum,
    sampling_suite_hash: str,
    source_stratum_hash: str,
    capture_method: str,
) -> None:
    result_values = _array(snapshot_payload.get("results"), "semantic metric results")
    if not result_values:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "semantic metric results are required"
        )
    expected = {
        "provider": source.platform,
        "reported_model": source.reported_model,
        "capture_method": capture_method,
        "locale": source.locale,
        "region": source.region,
        "source_composition_hash": sampling_suite_hash,
        "sampling_source_stratum_hash": source_stratum_hash,
        "question_cluster": "all",
    }
    expected_hash = semantic_hash(expected)
    if snapshot_payload.get("stratum_hash") != expected_hash:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "semantic metric root stratum lineage is corrupt"
        )
    for raw in result_values:
        result = _mapping(raw, "semantic metric result")
        if result.get("stratum") != expected or result.get("stratum_hash") != expected_hash:
            raise PostgresWorkflowCStatisticalAdmissionError(
                "semantic metric result stratum lineage is corrupt"
            )


def _suite_question_ids(suite: Mapping[str, object]) -> set[str]:
    values = _array(suite.get("questions"), "sampling suite questions")
    ids = {
        _text(
            _mapping(item, "sampling suite question").get("question_id"),
            "sampling suite question id",
        )
        for item in values
    }
    if not ids or len(ids) != len(values):
        raise PostgresWorkflowCStatisticalAdmissionError(
            "sampling suite questions must be non-empty and unique"
        )
    return ids


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} is malformed")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} must be an array")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} fields are invalid")


def _text(value: object, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum:
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} is invalid")
    return result


def _hash(value: object, label: str) -> str:
    result = _text(value, label, maximum=64)
    if len(result) != 64 or any(character not in _HASH_CHARACTERS for character in result):
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} must be SHA-256")
    return result


def _uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} is invalid") from error


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} is invalid") from error
    return result


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} is invalid") from error
    if not result.is_finite():
        raise PostgresWorkflowCStatisticalAdmissionError(f"{label} is invalid")
    return result
