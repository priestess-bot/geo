"""Frozen optional Metric model-program decoder for semantic parent Jobs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any
from uuid import UUID

from geo_core.workflow_c_analysis_common import (
    array_value,
    hash_value,
    integer_value,
    object_value,
    optional_text_value,
    text_value,
    uuid_value,
)
from geo_core.workflow_c_job_specs import WorkflowCJobSpec, WorkflowCJobSpecError
from geo_core.workflow_c_metric_judge_worker_contracts import ModelRequestTask
from geo_core.workflow_c_metric_parent_admission import (
    MetricArbiterEvaluatorAdmission,
    MetricJudgeEvaluatorAdmission,
    WorkflowCMetricParentAdmissionError,
)


@dataclass(frozen=True)
class MetricModelProgramAdmission:
    """All frozen model/Purpose lineages needed by a durable Metric parent."""

    admitted_by: UUID
    admitted_at: datetime
    judges: tuple[MetricJudgeEvaluatorAdmission, ...]
    arbiter: MetricArbiterEvaluatorAdmission

    def __post_init__(self) -> None:
        if not self.judges or len({item.evaluator_id for item in self.judges}) != len(self.judges):
            raise WorkflowCJobSpecError("metric model program needs distinct judges")
        if self.admitted_by.int == 0 or self.admitted_at.tzinfo is None:
            raise WorkflowCJobSpecError("metric model program admission is invalid")


def metric_model_program_admission(
    spec: WorkflowCJobSpec,
) -> MetricModelProgramAdmission | None:
    """Return the optional frozen model program without weakening legacy specs."""

    payload = object_value(spec.payload, "semantic metrics Worker payload")
    value = object_value(payload.get("semantic_metrics"), "semantic metrics Worker input")
    program = value.get("metric_model_program")
    if program is None:
        return None
    source = object_value(program, "metric model program")
    _only_keys(source, {"admitted_by", "admitted_at", "judges", "arbiter"}, "metric model program")
    admitted_at = _datetime(source.get("admitted_at"), "metric model program admission time")
    judges = tuple(
        _judge_evaluator(object_value(item, "metric judge evaluator"))
        for item in array_value(source.get("judges"), "metric model judges")
    )
    if len(judges) < 2:
        raise WorkflowCJobSpecError("metric model program needs at least two judges")
    try:
        return MetricModelProgramAdmission(
            admitted_by=uuid_value(source.get("admitted_by"), "metric admission actor"),
            admitted_at=admitted_at,
            judges=judges,
            arbiter=_arbiter_evaluator(
                object_value(source.get("arbiter"), "metric arbiter evaluator")
            ),
        )
    except WorkflowCMetricParentAdmissionError as error:
        raise WorkflowCJobSpecError("metric model program lineage is invalid") from error


def _judge_evaluator(value: Mapping[str, object]) -> MetricJudgeEvaluatorAdmission:
    try:
        return MetricJudgeEvaluatorAdmission(**_evaluator_values(value))
    except WorkflowCMetricParentAdmissionError as error:
        raise WorkflowCJobSpecError("metric judge evaluator lineage is invalid") from error


def _arbiter_evaluator(value: Mapping[str, object]) -> MetricArbiterEvaluatorAdmission:
    try:
        return MetricArbiterEvaluatorAdmission(**_evaluator_values(value))
    except WorkflowCMetricParentAdmissionError as error:
        raise WorkflowCJobSpecError("metric arbiter evaluator lineage is invalid") from error


def _evaluator_values(value: Mapping[str, object]) -> dict[str, Any]:
    _only_keys(
        value,
        {
            "evaluator_id",
            "runtime_selection_id",
            "runtime_manifest_id",
            "runtime_manifest_hash",
            "runtime_option_id",
            "runtime_option_hash",
            "prompt_binding_id",
            "prompt_binding_version",
            "prompt_frozen_state_id",
            "prompt_state_version",
            "prompt_release_id",
            "prompt_release_version",
            "prompt_release_hash",
            "prompt_purpose",
            "prompt_bundle_hash",
            "request",
        },
        "metric evaluator",
    )
    return {
        "evaluator_id": text_value(value.get("evaluator_id"), "metric evaluator ID"),
        "runtime_selection_id": uuid_value(
            value.get("runtime_selection_id"), "metric runtime selection"
        ),
        "runtime_manifest_id": uuid_value(
            value.get("runtime_manifest_id"), "metric runtime manifest"
        ),
        "runtime_manifest_hash": hash_value(
            value.get("runtime_manifest_hash"), "metric runtime manifest hash"
        ),
        "runtime_option_id": uuid_value(value.get("runtime_option_id"), "metric runtime option"),
        "runtime_option_hash": hash_value(
            value.get("runtime_option_hash"), "metric runtime option hash"
        ),
        "prompt_binding_id": uuid_value(value.get("prompt_binding_id"), "metric Prompt binding"),
        "prompt_binding_version": _positive(
            value.get("prompt_binding_version"), "metric Prompt binding version"
        ),
        "prompt_frozen_state_id": uuid_value(
            value.get("prompt_frozen_state_id"), "metric Prompt state"
        ),
        "prompt_state_version": _positive(
            value.get("prompt_state_version"), "metric Prompt state version"
        ),
        "prompt_release_id": uuid_value(value.get("prompt_release_id"), "metric Prompt Release"),
        "prompt_release_version": _positive(
            value.get("prompt_release_version"), "metric Prompt Release version"
        ),
        "prompt_release_hash": hash_value(
            value.get("prompt_release_hash"), "metric Prompt Release hash"
        ),
        "prompt_purpose": text_value(value.get("prompt_purpose"), "metric Prompt purpose"),
        "prompt_bundle_hash": hash_value(
            value.get("prompt_bundle_hash"), "metric Prompt bundle hash"
        ),
        "request": _request(object_value(value.get("request"), "metric model request")),
    }


def _request(value: Mapping[str, object]) -> ModelRequestTask:
    _only_keys(
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
    messages = tuple(
        _message(object_value(item, "metric model message"))
        for item in array_value(value.get("messages"), "metric model messages")
    )
    if not messages:
        raise WorkflowCJobSpecError("metric model request needs messages")
    seed = value.get("seed")
    if seed is not None:
        seed = integer_value(seed, "metric model seed")
    deadline = value.get("deadline_at")
    return ModelRequestTask(
        messages=messages,
        configured_model=text_value(value.get("configured_model"), "metric configured model"),
        temperature=_temperature(value.get("temperature")),
        max_output_tokens=_positive(value.get("max_output_tokens"), "metric max output tokens"),
        output_schema=dict(object_value(value.get("output_schema"), "metric output schema")),
        application_output_schema=dict(
            object_value(value.get("application_output_schema"), "metric application output schema")
        ),
        seed=seed,
        tool_mode=optional_text_value(value.get("tool_mode"), "metric tool mode"),
        search_mode=optional_text_value(value.get("search_mode"), "metric search mode"),
        deadline_at=None if deadline is None else _datetime(deadline, "metric model deadline"),
    )


def _message(value: Mapping[str, object]) -> dict[str, str]:
    _only_keys(value, {"role", "content"}, "metric model message")
    return {
        "role": text_value(value.get("role"), "metric model message role"),
        "content": text_value(value.get("content"), "metric model message content"),
    }


def _positive(value: object, label: str) -> int:
    parsed = integer_value(value, label)
    if parsed < 1:
        raise WorkflowCJobSpecError(f"{label} must be positive")
    return parsed


def _temperature(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise WorkflowCJobSpecError("metric temperature must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 <= parsed <= 2:
        raise WorkflowCJobSpecError("metric temperature must be in [0, 2]")
    return parsed


def _datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise WorkflowCJobSpecError(f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise WorkflowCJobSpecError(f"{label} must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WorkflowCJobSpecError(f"{label} must have a timezone")
    return parsed


def _only_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise WorkflowCJobSpecError(f"{label} has an unexpected schema")


__all__ = ["MetricModelProgramAdmission", "metric_model_program_admission"]
