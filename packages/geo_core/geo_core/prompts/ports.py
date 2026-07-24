"""Project-scoped persistence ports for Prompt Program application commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Protocol
from uuid import UUID

from geo_core.prompts.program import (
    ProgramBinding,
    ProgramKind,
    ProgramReleaseState,
    ProgramTestEvidence,
    PromptProgram,
    PromptProgramRelease,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PromptProgramPersistenceError(RuntimeError):
    """Base error for repository failures safe to map at an application boundary."""


class PromptProgramVersionConflict(PromptProgramPersistenceError):
    """The aggregate changed after the caller read its expected version."""


class PromptProgramIdempotencyConflict(PromptProgramPersistenceError):
    """An idempotency key was reused for a different immutable request."""


class PromptCommandOperation(StrEnum):
    CREATE = "create"
    CREATE_RELEASE = "create_release"
    TEST = "test"
    APPROVE = "approve"
    FREEZE = "freeze"
    BIND = "bind"
    DIFF = "diff"


@dataclass(frozen=True)
class PromptCommandRecord:
    project_id: UUID
    idempotency_key_hash: str
    operation: PromptCommandOperation
    request_hash: str
    result: object

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.idempotency_key_hash):
            raise ValueError("Prompt command idempotency key hash must be SHA-256")
        if not _SHA256.fullmatch(self.request_hash):
            raise ValueError("Prompt command request hash must be SHA-256")


@dataclass(frozen=True)
class StoredPromptCommand:
    record: PromptCommandRecord
    replayed: bool


@dataclass(frozen=True)
class PromptReleaseRead:
    release: PromptProgramRelease
    state: ProgramReleaseState


@dataclass(frozen=True)
class PromptReleasePageRead:
    items: tuple[PromptReleaseRead, ...]
    total: int


@dataclass(frozen=True)
class PromptProgramPageRead:
    items: tuple[PromptProgram, ...]
    total: int


@dataclass(frozen=True)
class PromptBindingPageRead:
    items: tuple[ProgramBinding, ...]
    total: int


class PromptProgramRepository(Protocol):
    """Atomic repository contract; every lookup and command is scoped by project."""

    def get_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> PromptCommandRecord | None: ...

    def get_program(
        self, *, project_id: UUID, program_id: UUID
    ) -> PromptProgram | None: ...

    def list_programs(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> PromptProgramPageRead: ...

    def list_releases(
        self,
        *,
        project_id: UUID,
        program_id: UUID,
        limit: int,
        offset: int,
    ) -> PromptReleasePageRead: ...

    def get_release(
        self, *, project_id: UUID, release_id: UUID
    ) -> PromptProgramRelease | None: ...

    def get_current_release_state(
        self, *, project_id: UUID, release_id: UUID
    ) -> ProgramReleaseState | None: ...

    def get_test_evidence(
        self, *, project_id: UUID, tested_state_id: UUID
    ) -> ProgramTestEvidence | None: ...

    def get_latest_passed_test_evidence(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        release_hash: str,
        test_set_id: UUID,
        test_set_version: int,
    ) -> ProgramTestEvidence | None: ...

    def get_current_binding(
        self, *, project_id: UUID, purpose: str
    ) -> ProgramBinding | None: ...

    def list_current_bindings(
        self,
        *,
        project_id: UUID,
        program_kind: ProgramKind | None,
        limit: int,
        offset: int,
    ) -> PromptBindingPageRead: ...

    def store_created_program(
        self,
        *,
        project_id: UUID,
        program: PromptProgram,
        release: PromptProgramRelease,
        state: ProgramReleaseState,
        expected_version: int,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        """Atomically persist a new Program/Release and its command receipt."""
        ...

    def store_created_release(
        self,
        *,
        project_id: UUID,
        release: PromptProgramRelease,
        state: ProgramReleaseState,
        expected_version: int,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        """Atomically append the next Release and its initial draft state."""
        ...

    def store_release_transition(
        self,
        *,
        project_id: UUID,
        release: PromptProgramRelease,
        state: ProgramReleaseState,
        expected_version: int,
        test_evidence: ProgramTestEvidence | None,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        """Atomically compare-and-swap state, evidence and command receipt."""
        ...

    def store_worker_test_transition(
        self,
        *,
        project_id: UUID,
        release: PromptProgramRelease,
        state: ProgramReleaseState,
        expected_version: int,
        test_evidence: ProgramTestEvidence,
    ) -> None:
        """Persist server-evaluated test evidence under the Worker's fence."""
        ...

    def store_binding(
        self,
        *,
        project_id: UUID,
        binding: ProgramBinding,
        expected_version: int,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        """Atomically compare-and-swap a project/purpose binding and receipt."""
        ...

    def store_diff(
        self,
        *,
        project_id: UUID,
        candidate_release_id: UUID,
        expected_version: int,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        """Persist an idempotent diff after checking candidate state CAS."""
        ...
