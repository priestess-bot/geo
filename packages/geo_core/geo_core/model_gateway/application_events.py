"""Terminal event and sanitized lineage construction for model calls."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import re
from uuid import UUID

from geo_core.model_gateway.contracts import ModelGatewayError, ModelGatewayResult
from geo_core.model_gateway.ports import (
    ModelCallAttempt,
    ModelCallFailureClass,
    ModelCallLineage,
    ModelCallTerminalEvent,
    ModelCallTerminalStatus,
    canonical_json_hash,
    hash_secret_identifier,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def empty_lineage(attempt: ModelCallAttempt) -> ModelCallLineage:
    return ModelCallLineage(
        search_mode=attempt.spec.search_mode,
        capture_method=attempt.spec.capture_method,
        citation_count=0,
        citation_lineage_hash=canonical_json_hash(()),
        search_event_count=0,
        search_lineage_hash=canonical_json_hash(()),
        usage_details_hash=canonical_json_hash({}),
        raw_artifact_reference_hash=None,
        raw_artifact_policy_hash=attempt.spec.raw_artifact_policy_hash,
        raw_artifact_storage_decision=attempt.spec.raw_artifact_storage_decision,
        raw_artifact_cache_decision=attempt.spec.raw_artifact_cache_decision,
        raw_artifact_display_decision=attempt.spec.raw_artifact_display_decision,
        raw_artifact_redistribution_decision=(
            attempt.spec.raw_artifact_redistribution_decision
        ),
        raw_artifact_retention_days=attempt.spec.raw_artifact_retention_days,
        usage_purpose=attempt.spec.purpose,
        usage_audience=attempt.spec.usage_audience,
        effective_location=None,
    )


def result_lineage(result: ModelGatewayResult) -> ModelCallLineage:
    if (
        result.raw_artifact_policy_hash is None
        or result.raw_artifact_storage_decision is None
        or result.raw_artifact_cache_decision is None
        or result.raw_artifact_display_decision is None
        or result.raw_artifact_redistribution_decision is None
        or result.usage_purpose is None
        or result.usage_audience is None
    ):
        raise ValueError("model result has no frozen raw-artifact policy lineage")
    return ModelCallLineage(
        search_mode=result.search_mode,
        capture_method=result.capture_method,
        citation_count=len(result.citations),
        citation_lineage_hash=canonical_json_hash(result.citations),
        search_event_count=len(result.tool_events),
        search_lineage_hash=canonical_json_hash(result.tool_events),
        usage_details_hash=canonical_json_hash(result.usage_details or {}),
        raw_artifact_reference_hash=(
            hash_secret_identifier(result.raw_artifact_reference)
            if result.raw_artifact_reference is not None
            else None
        ),
        raw_artifact_policy_hash=result.raw_artifact_policy_hash,
        raw_artifact_storage_decision=result.raw_artifact_storage_decision,
        raw_artifact_cache_decision=result.raw_artifact_cache_decision,
        raw_artifact_display_decision=result.raw_artifact_display_decision,
        raw_artifact_redistribution_decision=(
            result.raw_artifact_redistribution_decision
        ),
        raw_artifact_retention_days=result.raw_artifact_retention_days,
        usage_purpose=result.usage_purpose,
        usage_audience=result.usage_audience,
        effective_location=result.effective_location,
    )


def success_event(
    *,
    event_id: UUID,
    occurred_at: datetime,
    attempt: ModelCallAttempt,
    result: ModelGatewayResult,
    paid_calls: int = 1,
) -> ModelCallTerminalEvent:
    if (
        result.requested_location != attempt.spec.requested_location
        or (attempt.spec.requested_location is None)
        != (result.effective_location is None)
    ):
        raise ValueError(
            "model result location differs from the reserved request lineage"
        )
    return ModelCallTerminalEvent(
        id=event_id,
        project_id=attempt.spec.project_id,
        job_id=attempt.spec.job_id,
        attempt_id=attempt.spec.id,
        status=ModelCallTerminalStatus.SUCCEEDED,
        occurred_at=occurred_at,
        paid_call_count=paid_calls,
        gateway_call_log_id=result.call_log_id,
        configured_model=result.configured_model,
        provider_reported_model=result.provider_reported_model,
        provider_request_id=result.provider_request_id,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=result.cost_usd,
        finish_reason=result.finish_reason,
        input_hash=attempt.spec.input_hash,
        output_hash=canonical_json_hash(result.output),
        response_hash=result.response_hash,
        lineage=result_lineage(result),
    )


def failure_event(
    *,
    event_id: UUID,
    occurred_at: datetime,
    attempt: ModelCallAttempt,
    error: ModelGatewayError,
    paid_calls: int,
    classification: ModelCallFailureClass,
    result: ModelGatewayResult | None = None,
) -> ModelCallTerminalEvent:
    output_hash = _safe_json_hash(result.output) if result is not None else None
    response_hash = _safe_hash(result.response_hash) if result is not None else None
    lineage = (
        _safe_result_lineage(result, attempt)
        if result is not None
        else empty_lineage(attempt)
    )
    return ModelCallTerminalEvent(
        id=event_id,
        project_id=attempt.spec.project_id,
        job_id=attempt.spec.job_id,
        attempt_id=attempt.spec.id,
        status=ModelCallTerminalStatus.FAILED,
        occurred_at=occurred_at,
        paid_call_count=paid_calls,
        gateway_call_log_id=result.call_log_id if result is not None else None,
        configured_model=attempt.spec.configured_model,
        provider_reported_model=result.provider_reported_model if result is not None else None,
        provider_request_id=result.provider_request_id if result is not None else None,
        prompt_tokens=result.prompt_tokens if result is not None else None,
        completion_tokens=result.completion_tokens if result is not None else None,
        cost_usd=result.cost_usd if result is not None else None,
        finish_reason=result.finish_reason if result is not None else None,
        input_hash=attempt.spec.input_hash,
        output_hash=output_hash,
        response_hash=response_hash,
        lineage=lineage,
        error_classification=classification,
        error_code=error.code,
        error_retryable=error.retryable,
    )


def _safe_result_lineage(
    result: ModelGatewayResult, attempt: ModelCallAttempt
) -> ModelCallLineage:
    try:
        return replace(result_lineage(result), effective_location=None)
    except ValueError:
        return empty_lineage(attempt)


def _safe_json_hash(value: object) -> str | None:
    try:
        return canonical_json_hash(value)
    except ValueError:
        return None


def _safe_hash(value: str | None) -> str | None:
    return value if value is not None and _SHA256.fullmatch(value) else None


__all__ = ["empty_lineage", "failure_event", "result_lineage", "success_event"]
