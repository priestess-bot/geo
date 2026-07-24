"""Project-scoped Prompt Program reads and immutable row reconstruction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from geo_core.prompts.application import (
    BoundPromptProgram,
    CreatedPromptProgram,
    CreatedPromptRelease,
    TestedPromptProgram,
    TransitionedPromptProgram,
)
from geo_core.prompts.ports import (
    PromptCommandOperation,
    PromptBindingPageRead,
    PromptCommandRecord,
    PromptProgramPersistenceError,
    PromptProgramPageRead,
    PromptReleasePageRead,
    PromptReleaseRead,
)
from geo_core.prompts.postgres_serialization import payload_uuid
from geo_core.prompts.postgres_read_models import (
    binding_from_row,
    payload_sha256,
    program_from_row,
    release_from_row,
    state_from_row,
    test_evidence_from_row,
)
from geo_core.prompts.program import (
    ProgramBinding,
    ProgramKind,
    ProgramReleaseState,
    ProgramReleaseDiff,
    ProgramTestEvidence,
    PromptProgram,
    PromptProgramRelease,
    PromptProgramRuleViolation,
)


class PromptProgramReadMixin:
    """Read side shared by the concrete Psycopg repository."""

    def _optional(
        self, query: str, parameters: tuple[object, ...]
    ) -> Mapping[str, Any] | None:
        raise NotImplementedError

    def _many(
        self, query: str, parameters: tuple[object, ...]
    ) -> tuple[Mapping[str, Any], ...]:
        raise NotImplementedError

    def get_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> PromptCommandRecord | None:
        row = self._optional(
            """SELECT project_id, idempotency_key_hash, operation, request_hash,
                      result_kind, result_payload
               FROM prompt_program_command_receipts
               WHERE project_id = %s AND idempotency_key_hash = %s""",
            (project_id, idempotency_key_hash),
        )
        if row is None:
            return None
        try:
            operation = PromptCommandOperation(str(row["operation"]))
            result = self._load_result(
                project_id=project_id,
                result_kind=str(row["result_kind"]),
                payload=cast(Mapping[str, object], row["result_payload"]),
            )
            return PromptCommandRecord(
                project_id=cast(UUID, row["project_id"]),
                idempotency_key_hash=str(row["idempotency_key_hash"]),
                operation=operation,
                request_hash=str(row["request_hash"]),
                result=result,
            )
        except (KeyError, TypeError, ValueError, PromptProgramRuleViolation) as error:
            raise PromptProgramPersistenceError(
                "stored Prompt Program command receipt is invalid"
            ) from error

    def get_program(
        self, *, project_id: UUID, program_id: UUID
    ) -> PromptProgram | None:
        row = self._optional(
            """SELECT id, project_id, program_kind, purpose, owner_id
               FROM prompt_programs WHERE project_id = %s AND id = %s""",
            (project_id, program_id),
        )
        return program_from_row(row) if row is not None else None

    def list_programs(
        self, *, project_id: UUID, limit: int, offset: int
    ) -> PromptProgramPageRead:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("Prompt Program pagination is out of range")
        count_row = self._optional(
            "SELECT count(*) AS total FROM prompt_programs WHERE project_id = %s",
            (project_id,),
        )
        rows = self._many(
            """SELECT id, project_id, program_kind, purpose, owner_id
               FROM prompt_programs
               WHERE project_id = %s
               ORDER BY created_at DESC, id
               LIMIT %s OFFSET %s""",
            (project_id, limit, offset),
        )
        total = int(count_row["total"]) if count_row is not None else 0
        return PromptProgramPageRead(
            tuple(program_from_row(row) for row in rows), total
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
        count_row = self._optional(
            """SELECT count(*) AS total FROM prompt_program_releases
               WHERE project_id = %s AND program_id = %s""",
            (project_id, program_id),
        )
        rows = self._many(
            """SELECT id, project_id, program_id, program_kind, purpose, version,
                      owner_id, system_template, user_template,
                      variable_schema_version, variable_schema,
                      input_schema_version, input_schema,
                      output_schema_version, output_schema, output_schema_hash,
                      application_output_schema_version, application_output_schema,
                      application_output_schema_hash,
                      model_policy_version, model_policy, model_policy_hash,
                      test_set_id, test_set_version, test_set_hash, compiler_version,
                      system_template_hash, user_template_hash, release_hash
               FROM prompt_program_releases
               WHERE project_id = %s AND program_id = %s
               ORDER BY version DESC, id
               LIMIT %s OFFSET %s""",
            (project_id, program_id, limit, offset),
        )
        releases = tuple(release_from_row(row) for row in rows)
        state_rows = (
            self._many(
                """SELECT DISTINCT ON (release_id)
                          id, release_id, release_hash, version, previous_state_id,
                          status, acted_by, acted_at, evidence_ref
                   FROM prompt_program_release_states
                   WHERE project_id = %s AND release_id = ANY(%s)
                   ORDER BY release_id, version DESC""",
                (project_id, [release.id for release in releases]),
            )
            if releases
            else ()
        )
        states = {
            cast(UUID, row["release_id"]): state_from_row(row)
            for row in state_rows
        }
        try:
            items = tuple(
                PromptReleaseRead(release, states[release.id]) for release in releases
            )
            total = int(count_row["total"]) if count_row is not None else 0
        except KeyError as error:
            raise PromptProgramPersistenceError(
                "Prompt Program Release history is incomplete"
            ) from error
        return PromptReleasePageRead(items, total)

    def get_release(
        self, *, project_id: UUID, release_id: UUID
    ) -> PromptProgramRelease | None:
        row = self._release_row(project_id=project_id, release_id=release_id)
        return release_from_row(row) if row is not None else None

    def get_current_release_state(
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

    def get_test_evidence(
        self, *, project_id: UUID, tested_state_id: UUID
    ) -> ProgramTestEvidence | None:
        row = self._test_evidence_row(
            project_id=project_id, tested_state_id=tested_state_id
        )
        return test_evidence_from_row(row) if row is not None else None

    def get_latest_passed_test_evidence(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        release_hash: str,
        test_set_id: UUID,
        test_set_version: int,
    ) -> ProgramTestEvidence | None:
        row = self._optional(
            """SELECT id, project_id, release_id, release_hash, tested_state_id,
                      test_set_id, test_set_version, output_artifact_ref, output_hash,
                      tested_by, tested_at, evidence_hash
               FROM prompt_program_test_evidence
               WHERE project_id = %s AND release_id = %s AND release_hash = %s
                 AND test_set_id = %s AND test_set_version = %s
               ORDER BY tested_at DESC, id DESC
               LIMIT 1""",
            (
                project_id,
                release_id,
                release_hash,
                test_set_id,
                test_set_version,
            ),
        )
        return test_evidence_from_row(row) if row is not None else None

    def get_current_binding(
        self, *, project_id: UUID, purpose: str
    ) -> ProgramBinding | None:
        row = self._optional(
            """SELECT id, project_id, purpose, program_kind, program_id,
                      release_id, release_version, release_hash, frozen_state_id,
                      binding_version, previous_binding_id, bound_by, bound_at
               FROM prompt_program_bindings
               WHERE project_id = %s AND purpose = %s
               ORDER BY binding_version DESC
               LIMIT 1""",
            (project_id, purpose.strip()),
        )
        return binding_from_row(row) if row is not None else None

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
        kind = program_kind.value if program_kind is not None else None
        count = self._optional(
            """WITH latest AS (
                   SELECT DISTINCT ON (binding.purpose) binding.program_kind
                   FROM prompt_program_bindings AS binding
                   JOIN prompt_program_release_states AS state
                     ON state.id = binding.frozen_state_id
                    AND state.project_id = binding.project_id
                    AND state.release_id = binding.release_id
                    AND state.status = 'frozen'
                   WHERE binding.project_id = %s
                   ORDER BY binding.purpose, binding.binding_version DESC
               ) SELECT count(*) AS total FROM latest
                 WHERE (%s IS NULL OR program_kind = %s)""",
            (project_id, kind, kind),
        )
        rows = self._many(
            """WITH latest AS (
                   SELECT DISTINCT ON (binding.purpose)
                          binding.id, binding.project_id, binding.purpose,
                          binding.program_kind, binding.program_id, binding.release_id,
                          binding.release_version, binding.release_hash,
                          binding.frozen_state_id, binding.binding_version,
                          binding.previous_binding_id, binding.bound_by, binding.bound_at
                   FROM prompt_program_bindings AS binding
                   JOIN prompt_program_release_states AS state
                     ON state.id = binding.frozen_state_id
                    AND state.project_id = binding.project_id
                    AND state.release_id = binding.release_id
                    AND state.status = 'frozen'
                   WHERE binding.project_id = %s
                   ORDER BY binding.purpose, binding.binding_version DESC
               ) SELECT * FROM latest
                 WHERE (%s IS NULL OR program_kind = %s)
                 ORDER BY bound_at DESC, id
                 LIMIT %s OFFSET %s""",
            (project_id, kind, kind, limit, offset),
        )
        return PromptBindingPageRead(
            tuple(binding_from_row(row) for row in rows),
            int(count["total"]) if count is not None else 0,
        )

    def _load_result(
        self,
        *,
        project_id: UUID,
        result_kind: str,
        payload: Mapping[str, object],
    ) -> object:
        if result_kind == "diffed":
            return self._load_diff_result(project_id=project_id, payload=payload)
        release = self._required_release(
            project_id=project_id,
            release_id=payload_uuid(payload, "release_id"),
        )
        state = self._required_state(
            project_id=project_id,
            state_id=payload_uuid(payload, "state_id"),
        )
        if result_kind == "created":
            program = self._required_program(
                project_id=project_id,
                program_id=payload_uuid(payload, "program_id"),
            )
            return CreatedPromptProgram(program, release, state)
        if result_kind == "created_release":
            return CreatedPromptRelease(release, state)
        if result_kind == "tested":
            tested_evidence = self._required_test_evidence(
                project_id=project_id,
                evidence_id=payload_uuid(payload, "evidence_id"),
            )
            return TestedPromptProgram(release, state, tested_evidence)
        if result_kind == "transitioned":
            raw_evidence_id = payload.get("evidence_id")
            admitted_evidence = (
                self._required_test_evidence(
                    project_id=project_id,
                    evidence_id=UUID(str(raw_evidence_id)),
                )
                if raw_evidence_id is not None
                else None
            )
            return TransitionedPromptProgram(release, state, admitted_evidence)
        if result_kind == "bound":
            binding = self._required_binding(
                project_id=project_id,
                binding_id=payload_uuid(payload, "binding_id"),
            )
            return BoundPromptProgram(release, state, binding)
        raise PromptProgramPersistenceError(
            "stored Prompt Program result kind is unsupported"
        )

    def _load_diff_result(
        self, *, project_id: UUID, payload: Mapping[str, object]
    ) -> ProgramReleaseDiff:
        base = self._required_release(
            project_id=project_id,
            release_id=payload_uuid(payload, "base_release_id"),
        )
        candidate = self._required_release(
            project_id=project_id,
            release_id=payload_uuid(payload, "candidate_release_id"),
        )
        raw_fields = payload.get("changed_fields")
        if not isinstance(raw_fields, list) or any(
            not isinstance(field, str) for field in raw_fields
        ):
            raise PromptProgramPersistenceError(
                "stored Prompt Program diff fields are invalid"
            )
        result = ProgramReleaseDiff(
            base_release_id=base.id,
            base_release_hash=payload_sha256(payload, "base_release_hash"),
            candidate_release_id=candidate.id,
            candidate_release_hash=payload_sha256(
                payload, "candidate_release_hash"
            ),
            changed_fields=tuple(raw_fields),
            fixed_input_hash=payload_sha256(payload, "fixed_input_hash"),
            base_system_hash=payload_sha256(payload, "base_system_hash"),
            candidate_system_hash=payload_sha256(
                payload, "candidate_system_hash"
            ),
            base_user_hash=payload_sha256(payload, "base_user_hash"),
            candidate_user_hash=payload_sha256(payload, "candidate_user_hash"),
        )
        if (
            result.base_release_hash != base.release_hash
            or result.candidate_release_hash != candidate.release_hash
            or base.project_id != candidate.project_id
            or base.program_id != candidate.program_id
        ):
            raise PromptProgramPersistenceError(
                "stored Prompt Program diff lineage is invalid"
            )
        return result

    def _required_program(self, *, project_id: UUID, program_id: UUID) -> PromptProgram:
        program = self.get_program(project_id=project_id, program_id=program_id)
        if program is None:
            raise PromptProgramPersistenceError(
                "Prompt Program command references a missing Program"
            )
        return program

    def _required_release(
        self, *, project_id: UUID, release_id: UUID
    ) -> PromptProgramRelease:
        release = self.get_release(project_id=project_id, release_id=release_id)
        if release is None:
            raise PromptProgramPersistenceError(
                "Prompt Program command references a missing Release"
            )
        return release

    def _required_state(
        self, *, project_id: UUID, state_id: UUID
    ) -> ProgramReleaseState:
        row = self._optional(
            """SELECT id, release_id, release_hash, version, previous_state_id,
                      status, acted_by, acted_at, evidence_ref
               FROM prompt_program_release_states
               WHERE project_id = %s AND id = %s""",
            (project_id, state_id),
        )
        if row is None:
            raise PromptProgramPersistenceError(
                "Prompt Program command references a missing state"
            )
        return state_from_row(row)

    def _required_test_evidence(
        self, *, project_id: UUID, evidence_id: UUID
    ) -> ProgramTestEvidence:
        row = self._optional(
            """SELECT id, project_id, release_id, release_hash, tested_state_id,
                      test_set_id, test_set_version, output_artifact_ref, output_hash,
                      tested_by, tested_at, evidence_hash
               FROM prompt_program_test_evidence
               WHERE project_id = %s AND id = %s""",
            (project_id, evidence_id),
        )
        if row is None:
            raise PromptProgramPersistenceError(
                "Prompt Program command references missing test evidence"
            )
        return test_evidence_from_row(row)

    def _required_binding(
        self, *, project_id: UUID, binding_id: UUID
    ) -> ProgramBinding:
        row = self._optional(
            """SELECT id, project_id, purpose, program_kind, program_id,
                      release_id, release_version, release_hash, frozen_state_id,
                      binding_version, previous_binding_id, bound_by, bound_at
               FROM prompt_program_bindings
               WHERE project_id = %s AND id = %s""",
            (project_id, binding_id),
        )
        if row is None:
            raise PromptProgramPersistenceError(
                "Prompt Program command references a missing binding"
            )
        return binding_from_row(row)

    def _release_row(
        self, *, project_id: UUID, release_id: UUID
    ) -> Mapping[str, Any] | None:
        return self._optional(
            """SELECT id, project_id, program_id, program_kind, purpose, version,
                      owner_id, system_template, user_template,
                      variable_schema_version, variable_schema,
                      input_schema_version, input_schema,
                      output_schema_version, output_schema, output_schema_hash,
                      application_output_schema_version, application_output_schema,
                      application_output_schema_hash,
                      model_policy_version, model_policy, model_policy_hash,
                      test_set_id, test_set_version, test_set_hash, compiler_version,
                      system_template_hash, user_template_hash, release_hash
               FROM prompt_program_releases
               WHERE project_id = %s AND id = %s""",
            (project_id, release_id),
        )

    def _test_evidence_row(
        self, *, project_id: UUID, tested_state_id: UUID
    ) -> Mapping[str, Any] | None:
        return self._optional(
            """SELECT id, project_id, release_id, release_hash, tested_state_id,
                      test_set_id, test_set_version, output_artifact_ref, output_hash,
                      tested_by, tested_at, evidence_hash
               FROM prompt_program_test_evidence
               WHERE project_id = %s AND tested_state_id = %s""",
            (project_id, tested_state_id),
        )
