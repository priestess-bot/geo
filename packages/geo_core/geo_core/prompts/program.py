"""Compatibility facade for the split Prompt Program domain contracts."""

from geo_core.prompts.program_contracts import (
    AUXILIARY_PROGRAM_KINDS,
    CORE_FIRST_PHASE_PROGRAM_KINDS,
    FIRST_PHASE_PROGRAM_KINDS,
    ModelPolicySnapshot,
    ProgramKind,
    ProgramReleaseCommand,
    ProgramReleaseStatus,
    ProgramSchemaContract,
    PromptProgramRuleViolation,
)
from geo_core.prompts.program_lifecycle import (
    assert_binding_scope,
    bind_frozen_release,
    create_initial_release_state,
    transition_release_state,
)
from geo_core.prompts.program_models import (
    CompiledProgramPrompt,
    ProgramBinding,
    ProgramReleaseDiff,
    ProgramReleaseState,
    ProgramTestEvidence,
    PromptProgram,
    PromptProgramRelease,
)
from geo_core.prompts.program_rendering import (
    compare_candidate_to_approved,
    render_program_release,
)


__all__ = [
    "AUXILIARY_PROGRAM_KINDS",
    "CompiledProgramPrompt",
    "CORE_FIRST_PHASE_PROGRAM_KINDS",
    "FIRST_PHASE_PROGRAM_KINDS",
    "ModelPolicySnapshot",
    "ProgramBinding",
    "ProgramKind",
    "ProgramReleaseCommand",
    "ProgramReleaseDiff",
    "ProgramReleaseState",
    "ProgramReleaseStatus",
    "ProgramSchemaContract",
    "ProgramTestEvidence",
    "PromptProgram",
    "PromptProgramRelease",
    "PromptProgramRuleViolation",
    "assert_binding_scope",
    "bind_frozen_release",
    "compare_candidate_to_approved",
    "create_initial_release_state",
    "render_program_release",
    "transition_release_state",
]
