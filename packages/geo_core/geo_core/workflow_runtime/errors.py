"""Actionable failures for external workflow execution."""

from __future__ import annotations


class WorkflowExecutionError(RuntimeError):
    """A Dify workflow could not produce a usable business result."""

    classification = "provider"
    retryable = False

    def __init__(self, message: str, *, code: str = "workflow_execution_failed") -> None:
        super().__init__(message)
        self.code = code


class RetryableWorkflowExecutionError(WorkflowExecutionError):
    classification = "retryable"
    retryable = True


class WorkflowAuthenticationError(WorkflowExecutionError):
    classification = "authentication"


class WorkflowConfigurationError(WorkflowExecutionError):
    classification = "configuration"


class WorkflowContractError(WorkflowExecutionError):
    classification = "contract"
