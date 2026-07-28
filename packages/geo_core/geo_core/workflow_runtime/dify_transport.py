"""HTTP error classification and endpoint validation for Dify execution."""

from __future__ import annotations

from typing import Mapping
from urllib.parse import urlsplit

import httpx

from .errors import (
    RetryableWorkflowExecutionError,
    UnknownWorkflowOutcomeError,
    WorkflowAuthenticationError,
    WorkflowConfigurationError,
    WorkflowContractError,
    WorkflowExecutionError,
)


def classified_error(error: Exception) -> WorkflowExecutionError:
    if isinstance(error, WorkflowExecutionError):
        return error
    return WorkflowExecutionError(
        "Dify execution failed unexpectedly; inspect the workflow attempt",
        code=type(error).__name__,
    )


def http_error(status: int, detail: str) -> WorkflowExecutionError:
    error: WorkflowExecutionError
    if status in {401, 403}:
        error = WorkflowAuthenticationError(
            "Dify rejected the configured API key", code="dify_auth_rejected"
        )
    elif status == 429:
        error = RetryableWorkflowExecutionError(
            f"Dify returned HTTP {status}: {detail}", code="dify_http_retryable"
        )
    elif status >= 500:
        error = UnknownWorkflowOutcomeError(
            f"Dify returned HTTP {status} after receiving a non-idempotent workflow request. "
            "Do not retry automatically; reconcile Dify history before deciding whether to "
            f"retry. Provider detail: {detail}",
            code="dify_unknown_outcome",
        )
    elif status == 404:
        error = WorkflowConfigurationError(
            "Dify workflow endpoint or app was not found", code="dify_workflow_not_found"
        )
    else:
        error = WorkflowContractError(
            f"Dify rejected the workflow input with HTTP {status}: {detail}",
            code="dify_request_rejected",
        )
    error.http_status = status
    return error


def safe_error_detail(response: httpx.Response) -> str:
    try:
        value = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(value, Mapping):
        return str(value.get("message") or value.get("code") or "request failed")[:500]
    return "request failed"


def validated_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise WorkflowConfigurationError(
            "GEO_DIFY_API_URL must be one HTTP(S) origin without credentials or a path"
        )
    return normalized
