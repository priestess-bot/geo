"""Strict PostgreSQL read projection for Recommendation generation Jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.recommendations.generation_contracts import (
    GenerationExecution,
    GenerationJobStatus,
    RecommendationGenerationConflict,
    RecommendationGenerationJob,
    RecommendationGenerationResult,
)
from geo_core.recommendations.postgres.rows import (
    generation_result_from_row,
    generation_spec_record_from_row,
)


class PostgresRecommendationGenerationReads:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connect = connection_factory

    def get(self, *, project_id: UUID, job_id: UUID) -> GenerationExecution:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            job = self.get_in_connection(
                connection,
                project_id=project_id,
                job_id=job_id,
            )
            result = self.result_in_connection(
                connection,
                project_id=project_id,
                job_id=job_id,
            )
            connection.rollback()
            return GenerationExecution(job, result)
        except psycopg.Error as error:
            connection.rollback()
            raise RecommendationGenerationConflict(
                "PostgreSQL could not read the Recommendation generation Job"
            ) from error
        finally:
            connection.close()

    def get_in_connection(
        self,
        connection: Any,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> RecommendationGenerationJob:
        row = connection.execute(
            """SELECT spec.job_id, spec.project_id, spec.api_version,
                      spec.spec_payload, spec.spec_payload_hash, spec.input_hash,
                      spec.idempotency_key_hash, spec.valid_until, spec.created_by,
                      spec.created_at, job.status AS job_status,
                      job.lease_token, job.lease_expires_at, job.fencing_generation,
                      job.cancel_requested_at, job.error_code,
                      (SELECT count(*) FROM recommendation_model_call_lineage AS call
                       WHERE call.project_id = spec.project_id
                         AND call.parent_job_id = spec.job_id
                         AND call.status = 'succeeded'
                         AND (call.model_attempt_id IS NOT NULL
                              OR call.dify_attempt_id IS NOT NULL)) AS consumed_model_calls
               FROM recommendation_generation_specs AS spec
               JOIN durable_jobs AS job
                 ON job.id = spec.job_id AND job.project_id = spec.project_id
               WHERE spec.project_id = %s AND spec.job_id = %s""",
            (project_id, job_id),
        ).fetchone()
        if row is None:
            raise RecommendationGenerationConflict(
                "Recommendation generation Job does not exist in this Project"
            )
        record = generation_spec_record_from_row(row)
        status = _public_status(str(row["job_status"]))
        return RecommendationGenerationJob(
            id=record.job_id,
            spec=record.spec,
            input_hash=record.spec.input_hash,
            idempotency_key_hash=record.idempotency_key_hash,
            status=status,
            version=record.api_version,
            consumed_model_calls=int(row["consumed_model_calls"]),
            lease_id=(
                row["lease_token"] if status is GenerationJobStatus.RUNNING else None
            ),
            lease_expires_at=(
                row["lease_expires_at"]
                if status is GenerationJobStatus.RUNNING
                else None
            ),
            fencing_token=(
                int(row["fencing_generation"])
                if status is GenerationJobStatus.RUNNING
                else 0
            ),
            cancel_requested=row["cancel_requested_at"] is not None,
            error_code=row["error_code"],
        )

    def result_in_connection(
        self,
        connection: Any,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> RecommendationGenerationResult | None:
        row = connection.execute(
            """SELECT project_id, job_id, recommendation_id,
                      result_payload, result_hash
               FROM recommendation_generation_results
               WHERE project_id = %s AND job_id = %s""",
            (project_id, job_id),
        ).fetchone()
        return generation_result_from_row(row) if row is not None else None


def _public_status(status: str) -> GenerationJobStatus:
    if status in {"queued", "retry_wait"}:
        return GenerationJobStatus.QUEUED
    if status in {"running", "finalizing"}:
        return GenerationJobStatus.RUNNING
    if status == "succeeded":
        return GenerationJobStatus.SUCCEEDED
    if status == "cancelled":
        return GenerationJobStatus.CANCELLED
    if status in {"failed", "dead_lettered"}:
        return GenerationJobStatus.FAILED
    raise RecommendationGenerationConflict(
        "Recommendation generation Job has an unsupported durable status"
    )


__all__ = ["PostgresRecommendationGenerationReads"]
