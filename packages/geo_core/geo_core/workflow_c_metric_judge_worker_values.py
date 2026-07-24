"""Strict value parsing shared by frozen Workflow C metric child contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.semantic_metrics import (
    CitationInput,
    MetricJudgeKind,
    MetricJudgePlan,
    MetricObservation,
)
from geo_core.workflow_c_metric_judge_worker_types import (
    MetricArbiterTask,
    MetricChild,
    MetricJudgeTask,
    MetricTask,
    ModelRequestTask,
    WorkflowCMetricJudgeWorkerContractError,
)


_SHA256_LENGTH = 64


def parse_task(value: Mapping[str, object], *, expected_role: str) -> MetricTask:
    exact_keys(
        value,
        {"schema_version", "role", "admitted_by", "admitted_at", "request", "evaluation"},
        "metric task",
    )
    if value.get("schema_version") != 1:
        raise WorkflowCMetricJudgeWorkerContractError("metric task schema version is invalid")
    role = text(value.get("role"), "metric task role")
    if role != expected_role:
        raise WorkflowCMetricJudgeWorkerContractError("metric task role changed")
    evaluation = object_value(value.get("evaluation"), "metric task evaluation")
    return MetricTask(
        role=role,
        admitted_by=uuid(value.get("admitted_by"), "metric task admitted-by identity"),
        admitted_at=aware_datetime(value.get("admitted_at"), "metric task admission time"),
        request=parse_model_request(object_value(value.get("request"), "metric model request")),
        judge=parse_judge_task(evaluation) if role == "metric_judge" else None,
        arbiter=parse_arbiter_task(evaluation) if role == "arbiter" else None,
    )


def parse_model_request(value: Mapping[str, object]) -> ModelRequestTask:
    exact_keys(
        value,
        {
            "messages",
            "configured_model",
            "temperature",
            "max_output_tokens",
            "output_schema",
            "application_output_schema",
            "seed",
            "tool_mode",
            "search_mode",
            "deadline_at",
        },
        "metric model request",
    )
    raw_messages = value.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise WorkflowCMetricJudgeWorkerContractError("metric model request messages are invalid")
    messages: list[dict[str, str]] = []
    for raw in raw_messages:
        message = object_value(raw, "metric model message")
        exact_keys(message, {"role", "content"}, "metric model message")
        messages.append(
            {
                "role": text(message.get("role"), "metric message role"),
                "content": text(message.get("content"), "metric message content"),
            }
        )
    temperature = value.get("temperature")
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
        raise WorkflowCMetricJudgeWorkerContractError("metric temperature is invalid")
    max_output_tokens = value.get("max_output_tokens")
    if (
        not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens < 1
    ):
        raise WorkflowCMetricJudgeWorkerContractError("metric max output tokens are invalid")
    seed = value.get("seed")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise WorkflowCMetricJudgeWorkerContractError("metric seed is invalid")
    return ModelRequestTask(
        messages=tuple(messages),
        configured_model=text(value.get("configured_model"), "metric configured model"),
        temperature=float(temperature),
        max_output_tokens=max_output_tokens,
        output_schema=object_value(value.get("output_schema"), "metric portable output schema"),
        application_output_schema=object_value(
            value.get("application_output_schema"), "metric application output schema"
        ),
        seed=seed,
        tool_mode=optional_text(value.get("tool_mode"), "metric tool mode"),
        search_mode=optional_text(value.get("search_mode"), "metric search mode"),
        deadline_at=optional_aware_datetime(value.get("deadline_at"), "metric deadline"),
    )


def parse_judge_task(value: Mapping[str, object]) -> MetricJudgeTask:
    exact_keys(
        value,
        {"subject_id", "output_locale", "schema_version", "observation", "plans"},
        "metric judge task evaluation",
    )
    raw_plans = value.get("plans")
    if not isinstance(raw_plans, list) or not raw_plans:
        raise WorkflowCMetricJudgeWorkerContractError("metric judge plans are invalid")
    plans: list[MetricJudgePlan] = []
    for raw in raw_plans:
        plan = object_value(raw, "metric judge plan")
        exact_keys(
            plan,
            {"metric_id", "metric_kind", "definition", "allowed_evidence_refs"},
            "metric judge plan",
        )
        plans.append(
            MetricJudgePlan(
                metric_id=text(plan.get("metric_id"), "metric judge metric ID"),
                metric_kind=MetricJudgeKind(
                    text(plan.get("metric_kind"), "metric judge kind")
                ),
                definition=text(plan.get("definition"), "metric judge definition"),
                allowed_evidence_refs=text_array(
                    plan.get("allowed_evidence_refs"), "metric judge evidence references"
                ),
            )
        )
    if len({plan.metric_id for plan in plans}) != len(plans):
        raise WorkflowCMetricJudgeWorkerContractError("metric judge plans duplicate a metric ID")
    return MetricJudgeTask(
        subject_id=text(value.get("subject_id"), "metric judge subject ID"),
        output_locale=text(value.get("output_locale"), "metric judge output locale"),
        schema_version=text(value.get("schema_version"), "metric judge schema version"),
        observation=parse_observation(
            object_value(value.get("observation"), "metric observation")
        ),
        plans=tuple(plans),
    )


def parse_arbiter_task(value: Mapping[str, object]) -> MetricArbiterTask:
    exact_keys(
        value,
        {
            "subject_id",
            "output_locale",
            "candidate_ids",
            "evaluator_ids",
            "allowed_evidence_refs",
            "allowed_citation_refs",
        },
        "metric arbiter task evaluation",
    )
    candidates = text_array(value.get("candidate_ids"), "metric arbiter candidate IDs")
    evaluators = text_array(value.get("evaluator_ids"), "metric arbiter evaluator IDs")
    if len(candidates) < 2 or len(candidates) != len(set(candidates)):
        raise WorkflowCMetricJudgeWorkerContractError("metric arbiter candidate set is invalid")
    if len(evaluators) < 2 or len(evaluators) != len(set(evaluators)):
        raise WorkflowCMetricJudgeWorkerContractError("metric arbiter evaluator set is invalid")
    for candidate in candidates:
        uuid(candidate, "metric arbiter candidate ID")
    return MetricArbiterTask(
        subject_id=text(value.get("subject_id"), "metric arbiter subject ID"),
        output_locale=text(value.get("output_locale"), "metric arbiter output locale"),
        candidate_ids=tuple(sorted(candidates)),
        evaluator_ids=tuple(sorted(evaluators)),
        allowed_evidence_refs=frozenset(
            text_array(value.get("allowed_evidence_refs"), "arbiter evidence references")
        ),
        allowed_citation_refs=frozenset(
            text_array(value.get("allowed_citation_refs"), "arbiter citation references")
        ),
    )


def parse_observation(value: Mapping[str, object]) -> MetricObservation:
    exact_keys(
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
        },
        "metric observation",
    )
    raw_citations = value.get("citations")
    if not isinstance(raw_citations, list):
        raise WorkflowCMetricJudgeWorkerContractError("metric observation citations are invalid")
    citations: list[CitationInput] = []
    for raw in raw_citations:
        item = object_value(raw, "metric citation")
        exact_keys(
            item,
            {"id", "ordinal", "url", "visible_title", "source_type"},
            "metric citation",
        )
        ordinal = item.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool):
            raise WorkflowCMetricJudgeWorkerContractError("metric citation ordinal is invalid")
        citations.append(
            CitationInput(
                id=text(item.get("id"), "metric citation ID"),
                ordinal=ordinal,
                url=text(item.get("url"), "metric citation URL"),
                visible_title=text(item.get("visible_title"), "metric citation title"),
                source_type=text(item.get("source_type"), "metric citation type"),
            )
        )
    return MetricObservation(
        id=uuid(value.get("id"), "metric observation ID"),
        slot_id=text(value.get("slot_id"), "metric observation slot ID"),
        payload_hash=hash_value(value.get("payload_hash"), "metric observation payload hash"),
        question_id=text(value.get("question_id"), "metric observation question ID"),
        question_cluster=text(
            value.get("question_cluster"), "metric observation question cluster"
        ),
        answer_text=text(value.get("answer_text"), "metric observation answer text"),
        artifact_version=text(
            value.get("artifact_version"), "metric observation artifact version"
        ),
        citations=tuple(citations),
    )


def assert_task_schema_hashes(request: ModelRequestTask, child: MetricChild) -> None:
    if (
        canonical_json_hash(request.output_schema) != child.portable_output_schema_hash
        or canonical_json_hash(request.application_output_schema)
        != child.application_output_schema_hash
    ):
        raise WorkflowCMetricJudgeWorkerContractError("metric task output schema lineage changed")


def candidate_hash(parsed: Any) -> str:
    return canonical_json_hash(
        {
            "results": [item.canonical_value() for item in parsed.results],
            "overall_status": parsed.overall_status,
            "output_locale": parsed.output_locale,
        }
    )


def arbiter_hash(parsed: Any) -> str:
    return canonical_json_hash(
        {
            "disposition": parsed.disposition,
            "selected_candidate_id": parsed.selected_candidate_id,
            "considered_evaluators": list(parsed.considered_evaluators),
            "issue_codes": list(parsed.issue_codes),
        }
    )


def row_mapping(row: object) -> Mapping[str, object] | None:
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    raise WorkflowCMetricJudgeWorkerContractError("metric Worker PostgreSQL row shape is invalid")


def object_value(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be an object")
    return value


def exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} has an unexpected schema")


def text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be text")
    return value.strip()


def optional_text(value: object, label: str) -> str | None:
    return None if value is None else text(value, label)


def text_array(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be an array")
    return tuple(text(item, label) for item in value)


def uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        result = value
    elif isinstance(value, str):
        try:
            result = UUID(value)
        except ValueError as error:
            raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be a UUID") from error
    else:
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be a UUID")
    if result.int == 0:
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} must not be zero")
    return result


def hash_value(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH or value != value.lower():
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be SHA-256")
    try:
        int(value, 16)
    except ValueError as error:
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be SHA-256") from error
    return value


def bytes_value(value: object, label: str, exact_length: int | None = None) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be bytes")
    result = bytes(value)
    if not result or (exact_length is not None and len(result) != exact_length):
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} has an invalid length")
    return result


def positive(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be positive")
    return value


def aware_datetime(value: object, label: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as error:
            raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be ISO-8601") from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCMetricJudgeWorkerContractError(f"{label} must be timezone-aware")
    return value


def optional_aware_datetime(value: object, label: str) -> datetime | None:
    return None if value is None else aware_datetime(value, label)


def wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = [
    "arbiter_hash",
    "assert_task_schema_hashes",
    "aware_datetime",
    "bytes_value",
    "candidate_hash",
    "exact_keys",
    "hash_value",
    "object_value",
    "optional_aware_datetime",
    "optional_text",
    "parse_arbiter_task",
    "parse_judge_task",
    "parse_model_request",
    "parse_observation",
    "parse_task",
    "positive",
    "row_mapping",
    "text",
    "text_array",
    "uuid",
    "wipe",
]
