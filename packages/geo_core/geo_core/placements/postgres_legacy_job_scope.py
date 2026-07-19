"""Fail-closed recognition of project-scoped legacy Prompt Simulation jobs."""

from __future__ import annotations

from typing import Any
from uuid import UUID


def is_exact_legacy_simulation_job(db: Any, *, project_id: UUID, job_id: UUID) -> bool:
    row = db.execute(
        """SELECT CASE job.kind
                     WHEN 'prompt_simulation.generate' THEN EXISTS (
                       SELECT 1 WHERE geo_is_exact_legacy_simulation_generation_job(
                         job.id, job.project_id
                       )
                     )
                     WHEN 'artifact.finalize' THEN
                       geo_is_exact_legacy_simulation_artifact_job(job.id, job.project_id)
                     ELSE false
                   END
           FROM durable_jobs AS job
           WHERE job.id = %s AND job.project_id = %s AND job.campaign_id IS NULL""",
        (job_id, project_id),
    ).fetchone()
    return bool(row and row[0])
