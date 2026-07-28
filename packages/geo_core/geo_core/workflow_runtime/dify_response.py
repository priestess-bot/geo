"""Strict Dify response parsing and lineage extraction."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import re
from typing import Mapping
from uuid import UUID

from .contracts import WorkflowExecutionResult, WorkflowRuntimeRelease, canonical_json_hash
from .errors import (
    RetryableWorkflowExecutionError,
    WorkflowConfigurationError,
    WorkflowContractError,
    WorkflowExecutionError,
)


def parse_result(
    body: Mapping[str, object],
    *,
    release: WorkflowRuntimeRelease,
    expected_workflow_id: str,
    attempt_id: UUID,
) -> WorkflowExecutionResult:
    data = body.get("data")
    if not isinstance(data, Mapping):
        raise WorkflowContractError("Dify response has no workflow data")
    status = str(data.get("status", ""))
    if status != "succeeded":
        message = str(data.get("error") or data.get("message") or status or "unknown failure")
        retryable = any(token in message.lower() for token in ("timeout", "rate", "temporar"))
        error_type = RetryableWorkflowExecutionError if retryable else WorkflowExecutionError
        raise error_type(
            f"Dify workflow ended as {status or 'failed'}: {message[:500]}",
            code="dify_workflow_failed",
        )
    reported_workflow = _optional_text(data.get("workflow_id"))
    if reported_workflow is None:
        raise WorkflowConfigurationError(
            "Dify succeeded without reporting the exact published workflow identity",
            code="dify_workflow_identity_missing",
        )
    if reported_workflow != expected_workflow_id:
        raise WorkflowConfigurationError(
            "Dify response came from a different workflow release",
            code="dify_workflow_identity_mismatch",
        )
    run_id = str(body.get("workflow_run_id") or data.get("id") or "").strip()
    if not run_id:
        raise WorkflowContractError("Dify response omitted workflow_run_id")
    outputs = data.get("outputs")
    if not isinstance(outputs, Mapping):
        raise WorkflowContractError("Dify workflow outputs are missing")
    output = _output_object(outputs)
    usage = data.get("usage") if isinstance(data.get("usage"), Mapping) else {}
    return WorkflowExecutionResult(
        output=output,
        attempt_id=attempt_id,
        runtime_release_id=release.id,
        runtime_release_hash=release.release_hash,
        dify_task_id=_optional_text(body.get("task_id")),
        dify_run_id=run_id,
        configured_model=release.configured_model,
        provider_reported_model=_optional_text(usage.get("model") if usage else None),
        prompt_tokens=_optional_int(
            usage.get("prompt_tokens") if usage else data.get("prompt_tokens")
        ),
        completion_tokens=_optional_int(
            usage.get("completion_tokens") if usage else data.get("completion_tokens")
        ),
        total_steps=_optional_int(data.get("total_steps")),
        elapsed_seconds=_optional_decimal(data.get("elapsed_time")),
        response_hash=canonical_json_hash(output),
    )


def response_lineage(body: Mapping[str, object]) -> Mapping[str, str | None]:
    data = body.get("data")
    data_mapping = data if isinstance(data, Mapping) else {}
    return {
        "dify_task_id": _optional_text(body.get("task_id")),
        "dify_run_id": _optional_text(body.get("workflow_run_id") or data_mapping.get("id")),
        "reported_workflow_id": _optional_text(data_mapping.get("workflow_id")),
    }


def _output_object(outputs: Mapping[str, object]) -> Mapping[str, object]:
    for key in ("result", "output", "geo_result"):
        if key in outputs:
            return _coerce_json_object(outputs[key])
    if len(outputs) == 1:
        return _coerce_json_object(next(iter(outputs.values())))
    if outputs and all(isinstance(key, str) for key in outputs):
        return dict(outputs)
    raise WorkflowContractError(
        "Dify must return an object in result, output or geo_result",
        code="dify_output_missing",
    )


def _coerce_json_object(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.I)
        if fenced:
            text = fenced.group(1)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RetryableWorkflowExecutionError(
                "Dify model returned malformed JSON; retry the same GEO Job",
                code="dify_output_not_json",
            ) from exc
        if isinstance(parsed, Mapping):
            return dict(parsed)
    raise WorkflowContractError(
        "Dify result is not a JSON object", code="dify_output_shape_invalid"
    )


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except (InvalidOperation, ValueError):
        return None
