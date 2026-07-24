"""Worker-only Prompt test transition kept outside the command repository surface."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

import psycopg

from geo_core.prompts.ports import (
    PromptProgramPersistenceError,
    PromptProgramVersionConflict,
)
from geo_core.prompts.program import (
    ProgramReleaseState,
    ProgramReleaseStatus,
    ProgramTestEvidence,
    PromptProgramRelease,
    PromptProgramRuleViolation,
)


class PromptWorkerTransitionRepository(Protocol):
    def _lock_release(
        self, *, project_id: UUID, release: PromptProgramRelease
    ) -> None: ...

    def _current_state_for_update(
        self, *, project_id: UUID, release_id: UUID
    ) -> ProgramReleaseState | None: ...

    def _insert_state(
        self, *, project_id: UUID, state: ProgramReleaseState
    ) -> None: ...

    def _insert_test_evidence(self, evidence: ProgramTestEvidence) -> None: ...

    def _validate_test_evidence(
        self,
        *,
        project_id: UUID,
        release: PromptProgramRelease,
        state: ProgramReleaseState,
        evidence: ProgramTestEvidence,
    ) -> None: ...


def store_worker_test_transition(
    repository: PromptWorkerTransitionRepository,
    *,
    project_id: UUID,
    release: PromptProgramRelease,
    state: ProgramReleaseState,
    expected_version: int,
    test_evidence: ProgramTestEvidence,
) -> None:
    if project_id != release.project_id:
        raise PromptProgramRuleViolation(
            "Prompt Program Worker transition project does not match"
        )
    if (
        state.status is not ProgramReleaseStatus.TESTED
        or state.release_id != release.id
        or state.release_hash != release.release_hash
    ):
        raise PromptProgramRuleViolation(
            "Prompt Program Worker transition does not match its Release"
        )
    repository._lock_release(project_id=project_id, release=release)
    current = repository._current_state_for_update(
        project_id=project_id,
        release_id=release.id,
    )
    if current is None or current.version != expected_version:
        raise PromptProgramVersionConflict(
            "Prompt Program Release state changed after it was read"
        )
    if (
        current.status is not ProgramReleaseStatus.DRAFT
        or state.version != expected_version + 1
        or state.previous_state_id != current.id
    ):
        raise PromptProgramRuleViolation(
            "Prompt Program Worker test transition is not linear"
        )
    repository._validate_test_evidence(
        project_id=project_id,
        release=release,
        state=state,
        evidence=test_evidence,
    )
    try:
        repository._insert_state(project_id=project_id, state=state)
        repository._insert_test_evidence(test_evidence)
    except psycopg.errors.UniqueViolation as error:
        raise PromptProgramVersionConflict(
            "Prompt Program Worker test transition changed concurrently"
        ) from error
    except psycopg.Error as error:
        raise PromptProgramPersistenceError(
            "PostgreSQL could not store Prompt Program Worker test evidence"
        ) from error


__all__ = ["store_worker_test_transition"]
