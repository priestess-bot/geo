"""Transactional binding for one-time Dify unknown-outcome resubmissions."""

from __future__ import annotations

from typing import Any
from uuid import UUID


class DifyRecoveryBindingError(RuntimeError):
    """A verified unknown-outcome recovery could not be bound safely."""

    code = "dify_recovery_invalid"


class DifyRecoveryRequiredError(DifyRecoveryBindingError):
    """An unresolved matching request requires explicit operator recovery."""

    code = "dify_recovery_required"


def bind_dify_resubmission(
    connection: Any,
    *,
    project_id: UUID,
    new_parent_job_id: UUID,
    actor_id: UUID,
    recovery_of_attempt_id: UUID | None,
    token: str | None,
) -> UUID | None:
    """Bind a new parent to verified old-attempt evidence in its enqueue transaction."""
    connection.execute(
        "SELECT set_config('geo.identity_id', %s, true)",
        (str(actor_id),),
    )
    try:
        row = connection.execute(
            "SELECT geo_bind_dify_resubmission(%s, %s, %s, %s, %s) AS old_attempt_id",
            (project_id, new_parent_job_id, actor_id, recovery_of_attempt_id, token),
        ).fetchone()
    except Exception as error:
        sqlstate = getattr(error, "sqlstate", None)
        diagnostics = getattr(error, "diag", None)
        primary = str(getattr(diagnostics, "message_primary", "") or "").strip()
        if sqlstate in {"22023", "23514", "40001", "42501"} and primary:
            if "requires recovery_of_attempt_id" in primary:
                raise DifyRecoveryRequiredError(
                    f"{primary}. Verify the old Dify run, issue a one-time token, then "
                    "retry this new parent with both recovery fields."
                ) from error
            raise DifyRecoveryBindingError(
                f"{primary}. Do not retry the old parent; verify the attempt/token and "
                "submit a newly queued parent with the same frozen business input."
            ) from error
        raise
    if row is None:
        raise RuntimeError("Dify reconciliation binding returned no result")
    value = row.get("old_attempt_id") if hasattr(row, "get") else row[0]
    return value if isinstance(value, UUID) else UUID(str(value)) if value else None


__all__ = [
    "DifyRecoveryBindingError",
    "DifyRecoveryRequiredError",
    "bind_dify_resubmission",
]
