"""Stable errors raised by the project export bounded context."""


class ProjectExportRuleViolation(ValueError):
    """An export input is unsafe, ambiguous, or outside the requested scope."""


class ProjectExportVerificationError(ValueError):
    """A bundle is corrupt, out of contract, or cannot reproduce its metrics."""
