"""PostgreSQL persistence for the editable Prompt workspace."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from geo_core.prompts.application_models import PromptProgramNotFound
from geo_core.prompts.ports import PromptProgramVersionConflict
from geo_core.prompts.workspace import (
    PromptTestRunSummary,
    PromptWorkingDraft,
    draft_hash,
)


class PromptWorkspacePersistenceMixin:
    def _optional(
        self, query: str, parameters: tuple[object, ...]
    ) -> Mapping[str, Any] | None:
        raise NotImplementedError

    def _many(
        self, query: str, parameters: tuple[object, ...]
    ) -> tuple[Mapping[str, Any], ...]:
        raise NotImplementedError

    def _execute(self, query: str, parameters: tuple[object, ...] = ()) -> None:
        raise NotImplementedError

    def _advisory_lock(self, key: str) -> None:
        raise NotImplementedError

    def get_working_draft(
        self, *, project_id: UUID, program_id: UUID
    ) -> PromptWorkingDraft | None:
        row = self._optional(
            """SELECT project_id, program_id, display_name, system_template,
                      user_template, revision, draft_hash, base_release_id,
                      candidate_release_id, updated_by, updated_at
               FROM prompt_program_working_drafts
               WHERE project_id = %s AND program_id = %s""",
            (project_id, program_id),
        )
        return _draft_from_row(row) if row is not None else None

    def save_working_draft(
        self,
        *,
        project_id: UUID,
        program_id: UUID,
        display_name: str,
        system_template: str,
        user_template: str,
        expected_revision: int,
        updated_by: UUID,
        updated_at: datetime,
    ) -> PromptWorkingDraft:
        name = display_name.strip()
        system = system_template.strip()
        user = user_template.strip()
        if not name or not system or not user:
            raise ValueError("Prompt name, System Prompt and User Prompt are required")
        if len(name) > 120 or len(system) > 100_000 or len(user) > 100_000:
            raise ValueError("Prompt draft exceeds its text budget")
        self._advisory_lock(f"prompt-draft:{project_id}:{program_id}")
        current = self.get_working_draft(project_id=project_id, program_id=program_id)
        if current is None:
            raise PromptProgramNotFound("The Prompt working draft does not exist.")
        if current.revision != expected_revision:
            raise PromptProgramVersionConflict(
                "Prompt working draft changed after it was read"
            )
        next_hash = draft_hash(
            display_name=name,
            system_template=system,
            user_template=user,
        )
        if next_hash == current.draft_hash:
            return current
        self._execute(
            """UPDATE prompt_program_working_drafts
               SET display_name = %s,
                   system_template = %s,
                   user_template = %s,
                   revision = revision + 1,
                   draft_hash = %s,
                   candidate_release_id = NULL,
                   updated_by = %s,
                   updated_at = %s
               WHERE project_id = %s AND program_id = %s AND revision = %s""",
            (
                name,
                system,
                user,
                next_hash,
                updated_by,
                updated_at,
                project_id,
                program_id,
                expected_revision,
            ),
        )
        saved = self.get_working_draft(project_id=project_id, program_id=program_id)
        if saved is None or saved.revision != expected_revision + 1:
            raise PromptProgramVersionConflict("Prompt draft save was not applied")
        return saved

    def set_working_draft_candidate(
        self,
        *,
        project_id: UUID,
        program_id: UUID,
        expected_revision: int,
        candidate_release_id: UUID,
        updated_by: UUID,
        updated_at: datetime,
    ) -> PromptWorkingDraft:
        self._advisory_lock(f"prompt-draft:{project_id}:{program_id}")
        current = self.get_working_draft(project_id=project_id, program_id=program_id)
        if current is None or current.revision != expected_revision:
            raise PromptProgramVersionConflict("Prompt working draft changed before testing")
        self._execute(
            """UPDATE prompt_program_working_drafts
               SET candidate_release_id = %s, updated_by = %s, updated_at = %s
               WHERE project_id = %s AND program_id = %s AND revision = %s""",
            (
                candidate_release_id,
                updated_by,
                updated_at,
                project_id,
                program_id,
                expected_revision,
            ),
        )
        saved = self.get_working_draft(project_id=project_id, program_id=program_id)
        if saved is None or saved.candidate_release_id != candidate_release_id:
            raise PromptProgramVersionConflict("Prompt test candidate was not recorded")
        return saved

    def mark_working_draft_published(
        self,
        *,
        project_id: UUID,
        program_id: UUID,
        expected_revision: int,
        release_id: UUID,
        updated_by: UUID,
        updated_at: datetime,
    ) -> PromptWorkingDraft:
        self._advisory_lock(f"prompt-draft:{project_id}:{program_id}")
        current = self.get_working_draft(project_id=project_id, program_id=program_id)
        if (
            current is None
            or current.revision != expected_revision
            or current.candidate_release_id != release_id
        ):
            raise PromptProgramVersionConflict("Prompt draft changed before publishing")
        self._execute(
            """UPDATE prompt_program_working_drafts
               SET base_release_id = %s, candidate_release_id = NULL,
                   updated_by = %s, updated_at = %s
               WHERE project_id = %s AND program_id = %s AND revision = %s""",
            (
                release_id,
                updated_by,
                updated_at,
                project_id,
                program_id,
                expected_revision,
            ),
        )
        saved = self.get_working_draft(project_id=project_id, program_id=program_id)
        if saved is None or saved.base_release_id != release_id:
            raise PromptProgramVersionConflict("Published Prompt draft was not advanced")
        return saved

    def list_prompt_test_runs(
        self,
        *,
        project_id: UUID,
        program_id: UUID,
        limit: int = 20,
    ) -> tuple[PromptTestRunSummary, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("Prompt test run limit is out of range")
        rows = self._many(
            """SELECT task.job_id, task.project_id, task.program_id,
                      task.release_id, task.release_version,
                      job.status, task.requested_at, job.completed_at,
                      job.result_ref, job.error_code,
                      terminal.details AS terminal_details
               FROM prompt_program_test_run_tasks AS task
               JOIN durable_jobs AS job
                 ON job.id = task.job_id AND job.project_id = task.project_id
               LEFT JOIN LATERAL (
                   SELECT event.details
                   FROM durable_job_events AS event
                   WHERE event.project_id = task.project_id
                     AND event.job_id = task.job_id
                     AND event.event_type IN (
                         'job_succeeded', 'job_failed', 'job_dead_lettered'
                     )
                   ORDER BY event.created_at DESC
                   LIMIT 1
               ) AS terminal ON true
               WHERE task.project_id = %s AND task.program_id = %s
               ORDER BY task.requested_at DESC, task.job_id DESC
               LIMIT %s""",
            (project_id, program_id, limit),
        )
        return tuple(_test_run_from_row(row) for row in rows)


def _draft_from_row(row: Mapping[str, object]) -> PromptWorkingDraft:
    return PromptWorkingDraft(
        project_id=cast(UUID, row["project_id"]),
        program_id=cast(UUID, row["program_id"]),
        display_name=str(row["display_name"]),
        system_template=str(row["system_template"]),
        user_template=str(row["user_template"]),
        revision=int(cast(int, row["revision"])),
        draft_hash=str(row["draft_hash"]),
        base_release_id=cast(UUID, row["base_release_id"]),
        candidate_release_id=cast(UUID | None, row["candidate_release_id"]),
        updated_by=cast(UUID, row["updated_by"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def _test_run_from_row(row: Mapping[str, object]) -> PromptTestRunSummary:
    details = row.get("terminal_details")
    terminal = details if isinstance(details, Mapping) else {}
    passed = terminal.get("passed")
    score = terminal.get("score")
    return PromptTestRunSummary(
        job_id=cast(UUID, row["job_id"]),
        project_id=cast(UUID, row["project_id"]),
        program_id=cast(UUID, row["program_id"]),
        release_id=cast(UUID, row["release_id"]),
        release_version=int(cast(int, row["release_version"])),
        status=str(row["status"]),
        requested_at=cast(datetime, row["requested_at"]),
        finished_at=cast(datetime | None, row.get("completed_at")),
        passed=passed if isinstance(passed, bool) else None,
        score=score if isinstance(score, int) and not isinstance(score, bool) else None,
        result_ref=str(row["result_ref"]) if row.get("result_ref") else None,
        error_code=str(row["error_code"]) if row.get("error_code") else None,
    )


__all__ = ["PromptWorkspacePersistenceMixin"]
