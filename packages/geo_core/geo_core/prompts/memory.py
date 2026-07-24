"""Thread-safe in-memory Prompt Program repository for domain and application tests."""

from __future__ import annotations

from threading import RLock
from uuid import UUID

from geo_core.prompts.ports import (
    PromptCommandOperation,
    PromptCommandRecord,
    PromptBindingPageRead,
    PromptProgramIdempotencyConflict,
    PromptProgramPageRead,
    PromptReleasePageRead,
    PromptReleaseRead,
    PromptProgramVersionConflict,
    StoredPromptCommand,
)
from geo_core.prompts.program import (
    ProgramBinding,
    ProgramKind,
    ProgramReleaseDiff,
    ProgramReleaseState,
    ProgramReleaseStatus,
    ProgramTestEvidence,
    PromptProgram,
    PromptProgramRelease,
    PromptProgramRuleViolation,
)


class InMemoryPromptProgramRepository:
    """Atomic compare-and-swap semantics without pretending to be durable storage."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._programs: dict[tuple[UUID, UUID], PromptProgram] = {}
        self._releases: dict[tuple[UUID, UUID], PromptProgramRelease] = {}
        self._states: dict[tuple[UUID, UUID], ProgramReleaseState] = {}
        self._test_evidence: dict[tuple[UUID, UUID], ProgramTestEvidence] = {}
        self._bindings: dict[tuple[UUID, str], ProgramBinding] = {}
        self._commands: dict[tuple[UUID, str], PromptCommandRecord] = {}

    def get_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> PromptCommandRecord | None:
        with self._lock:
            return self._commands.get((project_id, idempotency_key_hash))

    def get_program(
        self, *, project_id: UUID, program_id: UUID
    ) -> PromptProgram | None:
        with self._lock:
            return self._programs.get((project_id, program_id))

    def list_programs(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> PromptProgramPageRead:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("Prompt Program pagination is out of range")
        with self._lock:
            programs = tuple(
                reversed(
                    [
                        program
                        for (scope, _), program in self._programs.items()
                        if scope == project_id
                    ]
                )
            )
            return PromptProgramPageRead(
                programs[offset : offset + limit], len(programs)
            )

    def list_releases(
        self,
        *,
        project_id: UUID,
        program_id: UUID,
        limit: int,
        offset: int,
    ) -> PromptReleasePageRead:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("Prompt Program Release pagination is out of range")
        with self._lock:
            releases = sorted(
                (
                    release
                    for (scope, _), release in self._releases.items()
                    if scope == project_id and release.program_id == program_id
                ),
                key=lambda release: (release.version, release.id),
                reverse=True,
            )
            page = releases[offset : offset + limit]
            return PromptReleasePageRead(
                tuple(
                    PromptReleaseRead(release, self._states[(project_id, release.id)])
                    for release in page
                ),
                len(releases),
            )

    def get_release(
        self, *, project_id: UUID, release_id: UUID
    ) -> PromptProgramRelease | None:
        with self._lock:
            return self._releases.get((project_id, release_id))

    def get_current_release_state(
        self, *, project_id: UUID, release_id: UUID
    ) -> ProgramReleaseState | None:
        with self._lock:
            return self._states.get((project_id, release_id))

    def get_test_evidence(
        self, *, project_id: UUID, tested_state_id: UUID
    ) -> ProgramTestEvidence | None:
        with self._lock:
            return self._test_evidence.get((project_id, tested_state_id))

    def get_latest_passed_test_evidence(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        release_hash: str,
        test_set_id: UUID,
        test_set_version: int,
    ) -> ProgramTestEvidence | None:
        with self._lock:
            matching = [
                evidence
                for (scope, _), evidence in self._test_evidence.items()
                if scope == project_id
                and evidence.release_id == release_id
                and evidence.release_hash == release_hash
                and evidence.test_set_id == test_set_id
                and evidence.test_set_version == test_set_version
            ]
            if not matching:
                return None
            return max(matching, key=lambda evidence: (evidence.tested_at, evidence.id))

    def get_current_binding(
        self, *, project_id: UUID, purpose: str
    ) -> ProgramBinding | None:
        with self._lock:
            return self._bindings.get((project_id, purpose))

    def list_current_bindings(
        self,
        *,
        project_id: UUID,
        program_kind: ProgramKind | None,
        limit: int,
        offset: int,
    ) -> PromptBindingPageRead:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("Prompt Program binding pagination is out of range")
        with self._lock:
            bindings = sorted(
                (
                    binding
                    for (scope, _), binding in self._bindings.items()
                    if scope == project_id
                    and (program_kind is None or binding.program_kind is program_kind)
                    and self._states[(project_id, binding.release_id)].id
                    == binding.frozen_state_id
                    and self._states[(project_id, binding.release_id)].status
                    is ProgramReleaseStatus.FROZEN
                ),
                key=lambda binding: (binding.bound_at, binding.id),
                reverse=True,
            )
            return PromptBindingPageRead(
                tuple(bindings[offset : offset + limit]),
                len(bindings),
            )

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
        with self._lock:
            if command.project_id != project_id:
                raise PromptProgramRuleViolation("Prompt Program command project does not match")
            replay = self._recover(command)
            if replay is not None:
                return replay
            if expected_version != 0:
                raise PromptProgramVersionConflict(
                    "new Prompt Programs require expected_version=0"
                )
            if not (
                project_id
                == program.project_id
                == release.project_id
                == command.project_id
            ):
                raise PromptProgramRuleViolation("Prompt Program create scope does not match")
            if release.program_id != program.id:
                raise PromptProgramRuleViolation("Prompt Program Release belongs to another Program")
            if state.release_id != release.id or state.release_hash != release.release_hash:
                raise PromptProgramRuleViolation("initial state does not belong to the Release")
            if state.version != 1 or state.previous_state_id is not None:
                raise PromptProgramRuleViolation("initial Prompt Program state must be version 1")
            if (project_id, program.id) in self._programs or (
                project_id,
                release.id,
            ) in self._releases:
                raise PromptProgramVersionConflict("Prompt Program identity already exists")

            self._programs[(project_id, program.id)] = program
            self._releases[(project_id, release.id)] = release
            self._states[(project_id, release.id)] = state
            self._commands[(project_id, command.idempotency_key_hash)] = command
            return StoredPromptCommand(command, replayed=False)

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
        with self._lock:
            if command.project_id != project_id:
                raise PromptProgramRuleViolation("Prompt Program command project does not match")
            replay = self._recover(command)
            if replay is not None:
                return replay
            current = self._states.get((project_id, release.id))
            if current is None or self._releases.get((project_id, release.id)) != release:
                raise PromptProgramVersionConflict("Prompt Program Release is not current")
            if current.version != expected_version:
                raise PromptProgramVersionConflict(
                    "Prompt Program Release state changed after it was read"
                )
            if state.version != expected_version + 1 or state.previous_state_id != current.id:
                raise PromptProgramRuleViolation("Prompt Program transition is not linear")
            if state.release_id != release.id or state.release_hash != release.release_hash:
                raise PromptProgramRuleViolation("Prompt Program transition scope does not match")
            if command.project_id != project_id or release.project_id != project_id:
                raise PromptProgramRuleViolation("Prompt Program transition project does not match")
            if command.operation == PromptCommandOperation.TEST:
                if test_evidence is None:
                    raise PromptProgramRuleViolation("test transitions require frozen evidence")
                self._validate_test_evidence(
                    project_id=project_id,
                    release=release,
                    state=state,
                    evidence=test_evidence,
                )
            elif test_evidence is not None:
                raise PromptProgramRuleViolation("only test transitions can persist test evidence")

            self._states[(project_id, release.id)] = state
            if test_evidence is not None:
                self._test_evidence[(project_id, state.id)] = test_evidence
            self._commands[(project_id, command.idempotency_key_hash)] = command
            return StoredPromptCommand(command, replayed=False)

    def store_worker_test_transition(
        self,
        *,
        project_id: UUID,
        release: PromptProgramRelease,
        state: ProgramReleaseState,
        expected_version: int,
        test_evidence: ProgramTestEvidence,
    ) -> None:
        with self._lock:
            current = self._states.get((project_id, release.id))
            if current is None or self._releases.get((project_id, release.id)) != release:
                raise PromptProgramVersionConflict("Prompt Program Release is not current")
            if current.version != expected_version:
                raise PromptProgramVersionConflict(
                    "Prompt Program Release state changed after it was read"
                )
            if (
                current.status is not ProgramReleaseStatus.DRAFT
                or state.status is not ProgramReleaseStatus.TESTED
                or state.version != expected_version + 1
                or state.previous_state_id != current.id
                or state.release_id != release.id
                or state.release_hash != release.release_hash
                or release.project_id != project_id
            ):
                raise PromptProgramRuleViolation(
                    "Prompt Program Worker test transition is inconsistent"
                )
            self._validate_test_evidence(
                project_id=project_id,
                release=release,
                state=state,
                evidence=test_evidence,
            )
            self._states[(project_id, release.id)] = state
            self._test_evidence[(project_id, state.id)] = test_evidence

    def store_created_release(
        self,
        *,
        project_id: UUID,
        release: PromptProgramRelease,
        state: ProgramReleaseState,
        expected_version: int,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        with self._lock:
            if command.project_id != project_id:
                raise PromptProgramRuleViolation("Prompt Program command project does not match")
            replay = self._recover(command)
            if replay is not None:
                return replay
            if command.operation != PromptCommandOperation.CREATE_RELEASE:
                raise PromptProgramRuleViolation("Prompt Program command is not create_release")
            program = self._programs.get((project_id, release.program_id))
            if program is None:
                raise PromptProgramVersionConflict("Prompt Program does not exist")
            releases = [
                item
                for (scope, _), item in self._releases.items()
                if scope == project_id and item.program_id == program.id
            ]
            latest_version = max((item.version for item in releases), default=0)
            if latest_version != expected_version:
                raise PromptProgramVersionConflict(
                    "Prompt Program latest Release changed after it was read"
                )
            if (
                release.project_id != project_id
                or release.version != expected_version + 1
                or release.program_kind != program.program_kind
                or release.purpose != program.purpose
                or release.owner_id != program.owner_id
            ):
                raise PromptProgramRuleViolation(
                    "Prompt Program Release identity or version is inconsistent"
                )
            if (
                state.release_id != release.id
                or state.release_hash != release.release_hash
                or state.version != 1
                or state.previous_state_id is not None
                or state.status != ProgramReleaseStatus.DRAFT
            ):
                raise PromptProgramRuleViolation(
                    "new Prompt Program Release requires an initial draft state"
                )
            if (project_id, release.id) in self._releases:
                raise PromptProgramVersionConflict("Prompt Program Release already exists")
            self._releases[(project_id, release.id)] = release
            self._states[(project_id, release.id)] = state
            self._commands[(project_id, command.idempotency_key_hash)] = command
            return StoredPromptCommand(command, replayed=False)

    def store_binding(
        self,
        *,
        project_id: UUID,
        binding: ProgramBinding,
        expected_version: int,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        with self._lock:
            if command.project_id != project_id:
                raise PromptProgramRuleViolation("Prompt Program command project does not match")
            replay = self._recover(command)
            if replay is not None:
                return replay
            current = self._bindings.get((project_id, binding.purpose))
            current_version = current.binding_version if current is not None else 0
            if current_version != expected_version:
                raise PromptProgramVersionConflict(
                    "Prompt Program binding changed after it was read"
                )
            if binding.binding_version != expected_version + 1:
                raise PromptProgramRuleViolation("Prompt Program binding version is not linear")
            expected_previous_id = current.id if current is not None else None
            if binding.previous_binding_id != expected_previous_id:
                raise PromptProgramRuleViolation("Prompt Program binding history is not linear")
            if binding.project_id != project_id or command.project_id != project_id:
                raise PromptProgramRuleViolation("Prompt Program binding project does not match")

            self._bindings[(project_id, binding.purpose)] = binding
            self._commands[(project_id, command.idempotency_key_hash)] = command
            return StoredPromptCommand(command, replayed=False)

    def store_diff(
        self,
        *,
        project_id: UUID,
        candidate_release_id: UUID,
        expected_version: int,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        with self._lock:
            if command.project_id != project_id:
                raise PromptProgramRuleViolation("Prompt Program command project does not match")
            replay = self._recover(command)
            if replay is not None:
                return replay
            state = self._states.get((project_id, candidate_release_id))
            if state is None or state.version != expected_version:
                raise PromptProgramVersionConflict(
                    "Prompt Program candidate state changed after it was read"
                )
            if (
                command.operation != PromptCommandOperation.DIFF
                or not isinstance(command.result, ProgramReleaseDiff)
                or command.result.candidate_release_id != candidate_release_id
            ):
                raise PromptProgramRuleViolation("Prompt Program diff receipt is inconsistent")
            self._commands[(project_id, command.idempotency_key_hash)] = command
            return StoredPromptCommand(command, replayed=False)

    def _recover(self, command: PromptCommandRecord) -> StoredPromptCommand | None:
        existing = self._commands.get(
            (command.project_id, command.idempotency_key_hash)
        )
        if existing is None:
            return None
        if (
            existing.operation != command.operation
            or existing.request_hash != command.request_hash
        ):
            raise PromptProgramIdempotencyConflict(
                "Prompt Program idempotency key was reused for another command"
            )
        return StoredPromptCommand(existing, replayed=True)

    @staticmethod
    def _validate_test_evidence(
        *,
        project_id: UUID,
        release: PromptProgramRelease,
        state: ProgramReleaseState,
        evidence: ProgramTestEvidence,
    ) -> None:
        if (
            evidence.project_id != project_id
            or evidence.release_id != release.id
            or evidence.release_hash != release.release_hash
            or evidence.tested_state_id != state.id
            or evidence.test_set_id != release.test_set_id
            or evidence.test_set_version != release.test_set_version
            or evidence.tested_by != state.acted_by
            or evidence.tested_at != state.acted_at
            or state.evidence_ref != evidence.state_evidence_ref
        ):
            raise PromptProgramRuleViolation("Prompt Program test evidence lineage does not match")
