"""Stable placement application and domain errors."""


class PlacementRuleViolation(ValueError):
    """A placement command violates an explicit business invariant."""


class PlacementContractMigrationRequired(PlacementRuleViolation):
    """A frozen legacy input cannot be executed without an operator rebuild."""

    def __init__(self, message: str, *, error_code: str, operator_action: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.operator_action = operator_action


class ConcurrencyConflict(RuntimeError):
    """The caller edited a stale immutable version."""


class PlacementConflict(RuntimeError):
    """The command conflicts with the aggregate's current state."""


class PlacementNotFound(RuntimeError):
    """A project-scoped placement resource does not exist."""


class CampaignContextMismatch(PlacementRuleViolation):
    """Explicit descendant identifiers do not share one Campaign lineage."""
