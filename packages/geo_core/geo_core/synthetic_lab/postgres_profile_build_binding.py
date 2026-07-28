"""PostgreSQL repository for immutable Style Profile build selections."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg

from geo_core.synthetic_lab.ports import (
    SyntheticLabPersistenceError,
    SyntheticLabVersionConflict,
)
from geo_core.synthetic_lab.profile_build_binding import StyleProfileBuildBinding


class PostgresStyleProfileBuildBindingRepository:
    def __init__(self, connection: Any, project_id: UUID) -> None:
        self._connection, self._project_id = connection, project_id

    def get(
        self, *, project_id: UUID, profile_version_id: UUID
    ) -> StyleProfileBuildBinding | None:
        self._require_scope(project_id)
        row = self._connection.execute(
            """SELECT project_id, profile_version_id, profile_hash,
                      execution_job_id, execution_result_id, result_hash,
                      result_payload_hash, artifact_hash, bound_by
               FROM synthetic_lab_style_profile_build_bindings
               WHERE project_id = %s AND profile_version_id = %s
                 AND verification_status = 'verified'
                 AND rebuild_required = false""",
            (project_id, profile_version_id),
        ).fetchone()
        return StyleProfileBuildBinding(**dict(row)) if row is not None else None

    def stage(self, binding: StyleProfileBuildBinding) -> None:
        self._require_scope(binding.project_id)
        existing = self.get(
            project_id=binding.project_id,
            profile_version_id=binding.profile_version_id,
        )
        if existing is not None:
            if existing != binding:
                raise SyntheticLabVersionConflict(
                    "Style Profile version is already bound to another build result"
                )
            return
        try:
            self._connection.execute(
                """INSERT INTO synthetic_lab_style_profile_build_bindings(
                       project_id, profile_version_id, profile_hash,
                       execution_job_id, execution_result_id, result_hash,
                       result_payload_hash, artifact_hash, bound_by
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    binding.project_id,
                    binding.profile_version_id,
                    binding.profile_hash,
                    binding.execution_job_id,
                    binding.execution_result_id,
                    binding.result_hash,
                    binding.result_payload_hash,
                    binding.artifact_hash,
                    binding.bound_by,
                ),
            )
        except psycopg.Error as error:
            if error.sqlstate in {"23505", "40001"}:
                raise SyntheticLabVersionConflict(
                    "Style Profile build result binding lost a concurrent race"
                ) from error
            raise SyntheticLabPersistenceError(
                "PostgreSQL rejected the Style Profile build result binding"
            ) from error

    def _require_scope(self, project_id: UUID) -> None:
        if project_id != self._project_id:
            raise SyntheticLabPersistenceError(
                "Style Profile build binding belongs to another Project"
            )


__all__ = ["PostgresStyleProfileBuildBindingRepository"]
