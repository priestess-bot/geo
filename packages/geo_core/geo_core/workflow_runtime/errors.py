"""Actionable failures for external workflow execution."""

from __future__ import annotations


class WorkflowExecutionError(RuntimeError):
    """A Dify workflow could not produce a usable business result."""

    classification = "provider"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str = "workflow_execution_failed",
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class RetryableWorkflowExecutionError(WorkflowExecutionError):
    classification = "retryable"
    retryable = True


class UnknownWorkflowOutcomeError(WorkflowExecutionError):
    """The provider may have accepted the request but its result is unknown."""

    classification = "unknown_outcome"


class WorkflowAuthenticationError(WorkflowExecutionError):
    classification = "authentication"


class WorkflowConfigurationError(WorkflowExecutionError):
    classification = "configuration"


class WorkflowContractError(WorkflowExecutionError):
    classification = "contract"
