"""Shared fail-closed errors for Prompt bootstrap application validation."""

from __future__ import annotations

from geo_core.prompts.bootstrap_contracts import PromptBootstrapRuleViolation


class PromptOutputRuleViolation(PromptBootstrapRuleViolation):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


__all__ = ["PromptOutputRuleViolation"]
