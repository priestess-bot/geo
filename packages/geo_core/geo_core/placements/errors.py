"""Stable placement application and domain errors."""


class PlacementRuleViolation(ValueError):
    """A placement command violates an explicit business invariant."""


class ConcurrencyConflict(RuntimeError):
    """The caller edited a stale immutable version."""


class PlacementConflict(RuntimeError):
    """The command conflicts with the aggregate's current state."""


class PlacementNotFound(RuntimeError):
    """A project-scoped placement resource does not exist."""


class CampaignContextMismatch(PlacementRuleViolation):
    """Explicit descendant identifiers do not share one Campaign lineage."""
