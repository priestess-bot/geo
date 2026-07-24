"""Errors shared by recommendation evidence and lifecycle rules."""

SOURCE_STALE_PROBLEM_CODE = "recommendation_source_stale"


class RecommendationRuleViolation(ValueError):
    """A recommendation command violates a deterministic domain invariant."""


class RecommendationConflict(RuntimeError):
    """A recommendation command conflicts with current persisted state."""


class RecommendationSourceStale(RecommendationConflict):
    """A downstream action no longer has the approved source snapshot."""

    problem_code = SOURCE_STALE_PROBLEM_CODE


class RecommendationEvidenceTampered(RecommendationRuleViolation):
    """A supplied evidence graph hash does not match its canonical content."""
