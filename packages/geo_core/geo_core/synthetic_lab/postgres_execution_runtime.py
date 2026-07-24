"""PostgreSQL-backed runtime checks for Synthetic execution workers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from geo_core.project_scope import set_project_scope
from geo_core.prompts.application import PromptProgramApplication
from geo_core.prompts.postgres_repository import PsycopgPromptProgramRepository
from geo_core.synthetic_lab.domain import StyleProfileStatus, StyleProfileVersion
from geo_core.synthetic_lab.ports import RuntimeInputSnapshot, SyntheticLabStaleInput
from geo_core.synthetic_lab.postgres_rows import aggregate_from_row


class PostgresSyntheticRuntimeInputPort:
    """Re-read the exact Fact, Profile, and frozen Prompt before each checkpoint."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def current(self, frozen: RuntimeInputSnapshot) -> RuntimeInputSnapshot:
        connection = self._connection_factory()
        try:
            set_project_scope(connection, frozen.project_id)
            facts = connection.execute(
                """SELECT id, pack_hash FROM evidence_pack_attempts
                   WHERE project_id = %s AND id = %s AND status = 'ready'
                     AND pack_hash IS NOT NULL""",
                (frozen.project_id, frozen.fact_snapshot_id),
            ).fetchone()
            profile_row = connection.execute(
                """SELECT * FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = 'style_profile' AND resource_id = %s
                   ORDER BY version DESC LIMIT 1""",
                (frozen.project_id, frozen.profile_version_id),
            ).fetchone()
            prompt = connection.execute(
                """SELECT state.id FROM prompt_program_release_states AS state
                   JOIN prompt_program_releases AS release
                     ON release.id = state.release_id
                    AND release.project_id = state.project_id
                   WHERE state.project_id = %s AND state.release_id = %s
                     AND state.release_hash = %s AND state.status = 'frozen'
                     AND release.release_hash = %s""",
                (
                    frozen.project_id,
                    frozen.prompt_release_id,
                    frozen.prompt_release_hash,
                    frozen.prompt_release_hash,
                ),
            ).fetchone()
            profile = self._profile(profile_row)
            return RuntimeInputSnapshot(
                project_id=frozen.project_id,
                fact_snapshot_id=frozen.fact_snapshot_id,
                fact_snapshot_hash=(
                    facts["pack_hash"] if facts is not None else frozen.fact_snapshot_hash
                ),
                profile_version_id=frozen.profile_version_id,
                profile_hash=(
                    profile.profile_hash if profile is not None else frozen.profile_hash
                ),
                prompt_release_id=frozen.prompt_release_id,
                prompt_release_hash=frozen.prompt_release_hash,
                facts_current_approved=facts is not None,
                profile_frozen=(
                    profile is not None
                    and profile.status is StyleProfileStatus.FROZEN
                    and profile.profile_hash == frozen.profile_hash
                ),
                prompt_frozen=prompt is not None,
            )
        finally:
            connection.rollback()
            connection.close()

    @staticmethod
    def _profile(row: object) -> StyleProfileVersion | None:
        if row is None:
            return None
        try:
            aggregate = aggregate_from_row(cast(Mapping[str, Any], row))
        except Exception as error:
            raise SyntheticLabStaleInput("stored Style Profile runtime is invalid") from error
        return aggregate.payload if isinstance(aggregate.payload, StyleProfileVersion) else None


class PostgresRuntimePromptApplication:
    """Short-lived project-scoped Prompt Program reader for a worker checkpoint."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def resolve_runtime_binding(self, *, project_id, purpose: str):
        connection = self._connection_factory()
        try:
            set_project_scope(connection, project_id)
            repository = PsycopgPromptProgramRepository(connection)
            return PromptProgramApplication(repository).resolve_runtime_binding(
                project_id=project_id,
                purpose=purpose,
            )
        finally:
            connection.rollback()
            connection.close()


__all__ = [
    "PostgresRuntimePromptApplication",
    "PostgresSyntheticRuntimeInputPort",
]
