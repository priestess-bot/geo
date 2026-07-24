"""Append-only PostgreSQL persistence for Prompt Program commands."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.prompts.ports import (
    PromptCommandOperation,
    PromptCommandRecord,
    PromptProgramIdempotencyConflict,
    PromptProgramPersistenceError,
    PromptProgramVersionConflict,
    StoredPromptCommand,
)
from geo_core.prompts.postgres_read import PromptProgramReadMixin
from geo_core.prompts.postgres_read_models import state_from_row
from geo_core.prompts.postgres_serialization import plain_json, serialize_result
from geo_core.prompts.postgres_worker_transition import (
    store_worker_test_transition as _store_worker_test_transition,
)
from geo_core.prompts.program import (
    ProgramBinding,
    ProgramReleaseDiff,
    ProgramReleaseState,
    ProgramReleaseStatus,
    ProgramTestEvidence,
    PromptProgram,
    PromptProgramRelease,
    PromptProgramRuleViolation,
)


class PsycopgPromptProgramRepository(PromptProgramReadMixin):
    """Append-only persistence with project scope, idempotency and CAS."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

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
            raise PromptProgramRuleViolation(
                "Prompt Program Release belongs to another Program"
            )
        if (
            state.release_id != release.id
            or state.release_hash != release.release_hash
            or state.version != 1
            or state.previous_state_id is not None
            or state.status is not ProgramReleaseStatus.DRAFT
        ):
            raise PromptProgramRuleViolation(
                "initial Prompt Program state does not match its Release"
            )

        replay = self._begin_command(command)
        if replay is not None:
            return replay
        try:
            self._execute(
                """INSERT INTO prompt_programs
                     (id, project_id, program_kind, purpose, owner_id)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    program.id,
                    project_id,
                    program.program_kind.value,
                    program.purpose,
                    program.owner_id,
                ),
            )
            self._insert_release(release)
            self._insert_state(project_id=project_id, state=state)
            self._insert_command(command)
        except psycopg.errors.UniqueViolation as error:
            raise PromptProgramVersionConflict(
                "Prompt Program identity or version already exists"
            ) from error
        except psycopg.Error as error:
            raise self._database_error("create Prompt Program", error) from error
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
        if project_id != release.project_id or project_id != command.project_id:
            raise PromptProgramRuleViolation(
                "Prompt Program transition project does not match"
            )
        if state.release_id != release.id or state.release_hash != release.release_hash:
            raise PromptProgramRuleViolation(
                "Prompt Program transition does not match its Release"
            )

        replay = self._begin_command(command)
        if replay is not None:
            return replay
        self._lock_release(project_id=project_id, release=release)
        current = self._current_state_for_update(
            project_id=project_id, release_id=release.id
        )
        if current is None or current.version != expected_version:
            raise PromptProgramVersionConflict(
                "Prompt Program Release state changed after it was read"
            )
        if state.version != expected_version + 1 or state.previous_state_id != current.id:
            raise PromptProgramRuleViolation("Prompt Program transition is not linear")
        if command.operation is PromptCommandOperation.TEST:
            if test_evidence is None or state.status is not ProgramReleaseStatus.TESTED:
                raise PromptProgramRuleViolation(
                    "test transitions require frozen test evidence"
                )
            self._validate_test_evidence(
                project_id=project_id,
                release=release,
                state=state,
                evidence=test_evidence,
            )
        elif test_evidence is not None:
            raise PromptProgramRuleViolation(
                "only test transitions can persist new test evidence"
            )
        if state.status is ProgramReleaseStatus.APPROVED:
            admitted = self.get_test_evidence(
                project_id=project_id, tested_state_id=current.id
            )
            if (
                admitted is None
                or current.evidence_ref != admitted.state_evidence_ref
                or admitted.release_hash != release.release_hash
            ):
                raise PromptProgramRuleViolation(
                    "Prompt Program approval requires intact test evidence"
                )
        try:
            self._insert_state(project_id=project_id, state=state)
            if test_evidence is not None:
                self._insert_test_evidence(test_evidence)
            self._insert_command(command)
        except psycopg.errors.UniqueViolation as error:
            raise PromptProgramVersionConflict(
                "Prompt Program Release state changed concurrently"
            ) from error
        except psycopg.Error as error:
            raise self._database_error("transition Prompt Program Release", error) from error
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
        _store_worker_test_transition(
            self,
            project_id=project_id,
            release=release,
            state=state,
            expected_version=expected_version,
            test_evidence=test_evidence,
        )

    def store_created_release(
        self,
        *,
        project_id: UUID,
        release: PromptProgramRelease,
        state: ProgramReleaseState,
        expected_version: int,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        if command.operation is not PromptCommandOperation.CREATE_RELEASE:
            raise PromptProgramRuleViolation(
                "Prompt Program Release create command type does not match"
            )
        if project_id != release.project_id or project_id != command.project_id:
            raise PromptProgramRuleViolation(
                "Prompt Program Release create project does not match"
            )
        if (
            release.version != expected_version + 1
            or state.release_id != release.id
            or state.release_hash != release.release_hash
            or state.version != 1
            or state.previous_state_id is not None
            or state.status is not ProgramReleaseStatus.DRAFT
        ):
            raise PromptProgramRuleViolation(
                "new Prompt Program Release is not the next draft version"
            )

        replay = self._begin_command(command)
        if replay is not None:
            return replay
        self._advisory_lock(
            f"prompt-program-release:{project_id}:{release.program_id}"
        )
        program = self.get_program(
            project_id=project_id, program_id=release.program_id
        )
        if (
            program is None
            or program.program_kind != release.program_kind
            or program.purpose != release.purpose
            or program.owner_id != release.owner_id
        ):
            raise PromptProgramRuleViolation(
                "new Prompt Program Release does not match its Program"
            )
        latest = self._optional(
            """SELECT version FROM prompt_program_releases
               WHERE project_id = %s AND program_id = %s
               ORDER BY version DESC LIMIT 1""",
            (project_id, release.program_id),
        )
        current_version = int(latest["version"]) if latest is not None else 0
        if current_version != expected_version:
            raise PromptProgramVersionConflict(
                "Prompt Program Release series changed after it was read"
            )
        try:
            self._insert_release(release)
            self._insert_state(project_id=project_id, state=state)
            self._insert_command(command)
        except psycopg.errors.UniqueViolation as error:
            raise PromptProgramVersionConflict(
                "Prompt Program Release version changed concurrently"
            ) from error
        except psycopg.Error as error:
            raise self._database_error("create Prompt Program Release", error) from error
        return StoredPromptCommand(command, replayed=False)

    def store_binding(
        self,
        *,
        project_id: UUID,
        binding: ProgramBinding,
        expected_version: int,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        if binding.project_id != project_id or command.project_id != project_id:
            raise PromptProgramRuleViolation("Prompt Program binding project does not match")
        replay = self._begin_command(command)
        if replay is not None:
            return replay
        self._advisory_lock(f"prompt-binding:{project_id}:{binding.purpose}")
        current = self.get_current_binding(project_id=project_id, purpose=binding.purpose)
        current_version = current.binding_version if current is not None else 0
        if current_version != expected_version:
            raise PromptProgramVersionConflict(
                "Prompt Program binding changed after it was read"
            )
        if binding.binding_version != expected_version + 1:
            raise PromptProgramRuleViolation("Prompt Program binding history is not linear")
        if binding.previous_binding_id != (current.id if current is not None else None):
            raise PromptProgramRuleViolation(
                "Prompt Program binding predecessor does not match"
            )
        try:
            self._execute(
                """INSERT INTO prompt_program_bindings
                     (id, project_id, purpose, program_kind, program_id,
                      release_id, release_version, release_hash, frozen_state_id,
                      binding_version, previous_binding_id, bound_by, bound_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    binding.id,
                    project_id,
                    binding.purpose,
                    binding.program_kind.value,
                    binding.program_id,
                    binding.release_id,
                    binding.release_version,
                    binding.release_hash,
                    binding.frozen_state_id,
                    binding.binding_version,
                    binding.previous_binding_id,
                    binding.bound_by,
                    binding.bound_at,
                ),
            )
            self._insert_command(command)
        except psycopg.errors.UniqueViolation as error:
            raise PromptProgramVersionConflict(
                "Prompt Program binding changed concurrently"
            ) from error
        except psycopg.Error as error:
            raise self._database_error("bind Prompt Program Release", error) from error
        return StoredPromptCommand(command, replayed=False)

    def store_diff(
        self,
        *,
        project_id: UUID,
        candidate_release_id: UUID,
        expected_version: int,
        command: PromptCommandRecord,
    ) -> StoredPromptCommand:
        if (
            command.project_id != project_id
            or command.operation is not PromptCommandOperation.DIFF
            or not isinstance(command.result, ProgramReleaseDiff)
            or command.result.candidate_release_id != candidate_release_id
        ):
            raise PromptProgramRuleViolation(
                "Prompt Program diff command scope does not match"
            )
        replay = self._begin_command(command)
        if replay is not None:
            return replay
        self._advisory_lock(
            f"prompt-release:{project_id}:{candidate_release_id}"
        )
        current = self._current_state_for_update(
            project_id=project_id, release_id=candidate_release_id
        )
        if current is None or current.version != expected_version:
            raise PromptProgramVersionConflict(
                "Prompt Program Release state changed after it was read"
            )
        candidate = self.get_release(
            project_id=project_id, release_id=candidate_release_id
        )
        baseline = self.get_release(
            project_id=project_id,
            release_id=command.result.base_release_id,
        )
        if (
            candidate is None
            or baseline is None
            or candidate.program_id != baseline.program_id
            or candidate.release_hash != command.result.candidate_release_hash
            or baseline.release_hash != command.result.base_release_hash
        ):
            raise PromptProgramRuleViolation(
                "Prompt Program diff result lineage does not match"
            )
        try:
            self._insert_command(command)
        except psycopg.errors.UniqueViolation as error:
            raise PromptProgramIdempotencyConflict(
                "Prompt Program diff idempotency key changed concurrently"
            ) from error
        except psycopg.Error as error:
            raise self._database_error("store Prompt Program diff", error) from error
        return StoredPromptCommand(command, replayed=False)

    def _begin_command(self, command: PromptCommandRecord) -> StoredPromptCommand | None:
        self._advisory_lock(
            f"prompt-command:{command.project_id}:{command.idempotency_key_hash}"
        )
        existing = self.get_command(
            project_id=command.project_id,
            idempotency_key_hash=command.idempotency_key_hash,
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

    def _insert_release(self, release: PromptProgramRelease) -> None:
        self._execute(
            """INSERT INTO prompt_program_releases
                 (id, project_id, program_id, program_kind, purpose, version,
                  owner_id, system_template, user_template,
                  variable_schema_version, variable_schema,
                  input_schema_version, input_schema,
                  output_schema_version, output_schema, output_schema_hash,
                  application_output_schema_version, application_output_schema,
                  application_output_schema_hash,
                  model_policy_version, model_policy, model_policy_hash,
                  test_set_id, test_set_version, test_set_hash, compiler_version,
                  system_template_hash, user_template_hash, release_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s)""",
            (
                release.id,
                release.project_id,
                release.program_id,
                release.program_kind.value,
                release.purpose,
                release.version,
                release.owner_id,
                release.system_template,
                release.user_template,
                release.schemas.variable_schema_version,
                Jsonb(plain_json(release.schemas.variable_schema)),
                release.schemas.input_schema_version,
                Jsonb(plain_json(release.schemas.input_schema)),
                release.schemas.output_schema_version,
                Jsonb(plain_json(release.schemas.output_schema)),
                release.schemas.output_schema_hash,
                release.schemas.application_output_schema_version,
                Jsonb(plain_json(release.schemas.application_output_schema)),
                release.schemas.application_output_schema_hash,
                release.model_policy.version,
                Jsonb(plain_json(release.model_policy.policy)),
                release.model_policy.policy_hash,
                release.test_set_id,
                release.test_set_version,
                release.test_set_hash,
                release.compiler_version,
                release.system_template_hash,
                release.user_template_hash,
                release.release_hash,
            ),
        )

    def _insert_state(self, *, project_id: UUID, state: ProgramReleaseState) -> None:
        self._execute(
            """INSERT INTO prompt_program_release_states
                 (id, project_id, release_id, release_hash, version,
                  previous_state_id, status, acted_by, acted_at, evidence_ref)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                state.id,
                project_id,
                state.release_id,
                state.release_hash,
                state.version,
                state.previous_state_id,
                state.status.value,
                state.acted_by,
                state.acted_at,
                state.evidence_ref,
            ),
        )

    def _insert_test_evidence(self, evidence: ProgramTestEvidence) -> None:
        self._execute(
            """INSERT INTO prompt_program_test_evidence
                 (id, project_id, release_id, release_hash, tested_state_id,
                  test_set_id, test_set_version, output_artifact_ref, output_hash,
                  tested_by, tested_at, evidence_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                evidence.id,
                evidence.project_id,
                evidence.release_id,
                evidence.release_hash,
                evidence.tested_state_id,
                evidence.test_set_id,
                evidence.test_set_version,
                evidence.output_artifact_ref,
                evidence.output_hash,
                evidence.tested_by,
                evidence.tested_at,
                evidence.evidence_hash,
            ),
        )

    def _insert_command(self, command: PromptCommandRecord) -> None:
        result_kind, payload = serialize_result(command.result)
        self._execute(
            """INSERT INTO prompt_program_command_receipts
                 (project_id, idempotency_key_hash, operation, request_hash,
                  result_kind, result_payload)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                command.project_id,
                command.idempotency_key_hash,
                command.operation.value,
                command.request_hash,
                result_kind,
                Jsonb(payload),
            ),
        )

    def _current_state_for_update(
        self, *, project_id: UUID, release_id: UUID
    ) -> ProgramReleaseState | None:
        row = self._optional(
            """SELECT id, release_id, release_hash, version, previous_state_id,
                      status, acted_by, acted_at, evidence_ref
               FROM prompt_program_release_states
               WHERE project_id = %s AND release_id = %s
               ORDER BY version DESC
               LIMIT 1""",
            (project_id, release_id),
        )
        return state_from_row(row) if row is not None else None

    def _lock_release(
        self, *, project_id: UUID, release: PromptProgramRelease
    ) -> None:
        self._advisory_lock(f"prompt-release:{project_id}:{release.id}")
        row = self._optional(
            """SELECT release_hash FROM prompt_program_releases
               WHERE project_id = %s AND id = %s""",
            (project_id, release.id),
        )
        if row is None:
            raise PromptProgramVersionConflict("Prompt Program Release is not current")
        if str(row["release_hash"]) != release.release_hash:
            raise PromptProgramPersistenceError(
                "Prompt Program Release content changed in storage"
            )

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
            raise PromptProgramRuleViolation(
                "Prompt Program test evidence lineage does not match"
            )

    def _advisory_lock(self, key: str) -> None:
        self._execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))

    def _execute(self, query: str, parameters: tuple[object, ...] = ()) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(query, parameters)

    def _optional(
        self, query: str, parameters: tuple[object, ...]
    ) -> Mapping[str, Any] | None:
        try:
            with self._connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, parameters)
                return cast(Mapping[str, Any] | None, cursor.fetchone())
        except psycopg.Error as error:
            raise self._database_error("read Prompt Program state", error) from error

    def _many(
        self, query: str, parameters: tuple[object, ...]
    ) -> tuple[Mapping[str, Any], ...]:
        try:
            with self._connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, parameters)
                return tuple(cast(list[Mapping[str, Any]], cursor.fetchall()))
        except psycopg.Error as error:
            raise self._database_error("list Prompt Program state", error) from error

    @staticmethod
    def _database_error(
        operation: str, error: psycopg.Error
    ) -> PromptProgramPersistenceError:
        del error
        return PromptProgramPersistenceError(f"PostgreSQL could not {operation}")


__all__ = ["PsycopgPromptProgramRepository"]
