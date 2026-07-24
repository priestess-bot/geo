"""Pure Prompt Program state transitions and frozen binding rules."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from geo_core.prompts.program_contracts import (
    ProgramKind,
    ProgramReleaseCommand,
    ProgramReleaseStatus,
    PromptProgramRuleViolation,
    _normalize_purpose,
)
from geo_core.prompts.program_models import (
    ProgramBinding,
    ProgramReleaseState,
    PromptProgramRelease,
    _assert_state_matches_release,
)


_RELEASE_TRANSITIONS: Mapping[
    ProgramReleaseStatus, Mapping[ProgramReleaseCommand, ProgramReleaseStatus]
] = MappingProxyType(
    {
        ProgramReleaseStatus.DRAFT: MappingProxyType(
            {ProgramReleaseCommand.RECORD_TEST: ProgramReleaseStatus.TESTED}
        ),
        ProgramReleaseStatus.TESTED: MappingProxyType(
            {ProgramReleaseCommand.APPROVE: ProgramReleaseStatus.APPROVED}
        ),
        ProgramReleaseStatus.APPROVED: MappingProxyType(
            {ProgramReleaseCommand.FREEZE: ProgramReleaseStatus.FROZEN}
        ),
        ProgramReleaseStatus.FROZEN: MappingProxyType({}),
    }
)


def create_initial_release_state(
    *,
    id: UUID,
    release: PromptProgramRelease,
    actor_id: UUID,
    acted_at: datetime,
) -> ProgramReleaseState:
    return ProgramReleaseState(
        id=id,
        release_id=release.id,
        release_hash=release.release_hash,
        version=1,
        previous_state_id=None,
        status=ProgramReleaseStatus.DRAFT,
        acted_by=actor_id,
        acted_at=acted_at,
    )


def transition_release_state(
    *,
    id: UUID,
    release: PromptProgramRelease,
    current: ProgramReleaseState,
    command: ProgramReleaseCommand | str,
    actor_id: UUID,
    acted_at: datetime,
    evidence_ref: str,
) -> ProgramReleaseState:
    _assert_state_matches_release(state=current, release=release)
    try:
        parsed_command = ProgramReleaseCommand(command)
    except ValueError as exc:
        raise PromptProgramRuleViolation(f"unknown Prompt Program command: {command}") from exc
    target = _RELEASE_TRANSITIONS[current.status].get(parsed_command)
    if target is None:
        raise PromptProgramRuleViolation(
            f"command {parsed_command.value!r} is not allowed from {current.status.value!r}"
        )
    if id == current.id:
        raise PromptProgramRuleViolation("a Prompt Program transition requires a new state ID")
    return ProgramReleaseState(
        id=id,
        release_id=release.id,
        release_hash=release.release_hash,
        version=current.version + 1,
        previous_state_id=current.id,
        status=target,
        acted_by=actor_id,
        acted_at=acted_at,
        evidence_ref=evidence_ref,
    )


def bind_frozen_release(
    *,
    id: UUID,
    project_id: UUID,
    purpose: str,
    release: PromptProgramRelease,
    state: ProgramReleaseState,
    binding_version: int,
    previous_binding_id: UUID | None,
    actor_id: UUID,
    bound_at: datetime,
) -> ProgramBinding:
    """Bind only an exact frozen Release within its owning project and purpose."""

    _assert_state_matches_release(state=state, release=release)
    normalized_purpose = _normalize_purpose(purpose)
    if project_id != release.project_id:
        raise PromptProgramRuleViolation("a Prompt Program cannot be bound across projects")
    if normalized_purpose != release.purpose:
        raise PromptProgramRuleViolation("a Prompt Program cannot be bound to another purpose")
    if state.status != ProgramReleaseStatus.FROZEN:
        raise PromptProgramRuleViolation("only a frozen Prompt Program Release can be bound")
    return ProgramBinding(
        id=id,
        project_id=project_id,
        purpose=normalized_purpose,
        program_kind=release.program_kind,
        program_id=release.program_id,
        release_id=release.id,
        release_version=release.version,
        release_hash=release.release_hash,
        frozen_state_id=state.id,
        binding_version=binding_version,
        previous_binding_id=previous_binding_id,
        bound_by=actor_id,
        bound_at=bound_at,
    )


def assert_binding_scope(
    *, binding: ProgramBinding, project_id: UUID, purpose: str, kind: ProgramKind
) -> None:
    """Fail closed before runtime uses a binding from another project or purpose."""

    if binding.project_id != project_id:
        raise PromptProgramRuleViolation("Prompt Program binding belongs to another project")
    if binding.purpose != _normalize_purpose(purpose):
        raise PromptProgramRuleViolation("Prompt Program binding belongs to another purpose")
    if binding.program_kind != ProgramKind(kind):
        raise PromptProgramRuleViolation("Prompt Program binding kind does not match")
