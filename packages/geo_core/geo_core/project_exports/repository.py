"""PostgreSQL durable-job and immutable-artifact repository for F027."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
import hashlib
import json
from typing import Any, cast
from uuid import UUID

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.project_exports.contracts import ExportAudience, ProjectExportScope
from geo_core.project_exports.errors import ProjectExportRuleViolation
from geo_core.project_exports.job_models import (
    ProjectExportArtifact,
    ProjectExportClaim,
)
from geo_core.project_scope import set_project_scope


class PostgresProjectExportRepository:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        job_store: PostgresDurableJobStore | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._job_store = job_store or PostgresDurableJobStore(connection_factory)

    def enqueue(
        self,
        *,
        scope: ProjectExportScope,
        audience: ExportAudience,
        requested_by: UUID,
        idempotency_key: str,
    ) -> ProjectExportArtifact:
        input_hash = _input_hash(scope, audience)
        connection = self._open(scope.project_id)
        try:
            if scope.campaign_id is not None:
                row = connection.execute(
                    """SELECT id FROM geo_campaigns
                       WHERE project_id = %s AND id = %s""",
                    (scope.project_id, scope.campaign_id),
                ).fetchone()
                if row is None:
                    raise ProjectExportRuleViolation(
                        "campaign scope does not belong to the requested project"
                    )
            inserted = _one(
                connection.execute(
                    """INSERT INTO durable_jobs
                         (project_id, campaign_id, kind, input_hash,
                          idempotency_key, max_attempts)
                       VALUES (%s, %s, 'project.export', %s, %s, 3)
                       ON CONFLICT
                         (project_id, kind, idempotency_key, replay_nonce)
                       DO NOTHING
                       RETURNING id""",
                    (
                        scope.project_id,
                        scope.campaign_id,
                        input_hash,
                        idempotency_key,
                    ),
                )
            )
            if inserted is None:
                existing = _one(
                    connection.execute(
                        """SELECT id, input_hash FROM durable_jobs
                           WHERE project_id = %s AND kind = 'project.export'
                             AND idempotency_key = %s AND replay_nonce = 0""",
                        (scope.project_id, idempotency_key),
                    )
                )
                if existing is None or existing["input_hash"] != input_hash:
                    raise ProjectExportRuleViolation(
                        "project export idempotency key conflicts with another scope"
                    )
                job_id = cast(UUID, existing["id"])
            else:
                job_id = cast(UUID, inserted["id"])
                connection.execute(
                    """INSERT INTO project_export_specs
                         (job_id, project_id, campaign_id, audience,
                          requested_by, input_hash)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        job_id,
                        scope.project_id,
                        scope.campaign_id,
                        audience.value,
                        requested_by,
                        input_hash,
                    ),
                )
                connection.execute(
                    """INSERT INTO broker_outbox
                         (project_id, job_id, topic, payload, idempotency_key)
                       VALUES (%s, %s, 'project.export', %s::jsonb, %s)
                       ON CONFLICT (project_id, idempotency_key) DO NOTHING""",
                    (
                        scope.project_id,
                        job_id,
                        json.dumps(
                            {
                                "job_id": str(job_id),
                                "project_id": str(scope.project_id),
                            }
                        ),
                        f"wake:project.export:{idempotency_key}",
                    ),
                )
            result = self._get(connection, scope.project_id, job_id, audience)
            connection.commit()
            if result is None:
                raise RuntimeError("project export job was not readable after enqueue")
            return result
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list(
        self, *, project_id: UUID, audience: ExportAudience
    ) -> tuple[ProjectExportArtifact, ...]:
        connection = self._open(project_id)
        try:
            rows = connection.execute(
                _VIEW_SQL
                + " WHERE spec.project_id = %s AND spec.audience = %s"
                + " ORDER BY job.created_at DESC, job.id DESC",
                (project_id, audience.value),
            ).fetchall()
            connection.rollback()
            return tuple(_artifact(row, audience) for row in rows)
        finally:
            connection.close()

    def get(
        self, *, project_id: UUID, job_id: UUID, audience: ExportAudience
    ) -> ProjectExportArtifact | None:
        connection = self._open(project_id)
        try:
            result = self._get(connection, project_id, job_id, audience)
            connection.rollback()
            return result
        finally:
            connection.close()

    def load_claim(self, lease: WorkerLease) -> ProjectExportClaim:
        connection = self._open(lease.project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT spec.job_id, spec.project_id, spec.campaign_id,
                              spec.audience, spec.requested_by, job.created_at
                       FROM project_export_specs spec
                       JOIN durable_jobs job
                         ON job.id = spec.job_id AND job.project_id = spec.project_id
                       WHERE spec.project_id = %s AND spec.job_id = %s""",
                    (lease.project_id, lease.job_id),
                )
            )
            connection.rollback()
            if row is None:
                raise ProjectExportRuleViolation("project export job spec is missing")
            return ProjectExportClaim(
                job_id=cast(UUID, row["job_id"]),
                scope=ProjectExportScope(
                    cast(UUID, row["project_id"]),
                    cast(UUID | None, row["campaign_id"]),
                ),
                audience=ExportAudience(str(row["audience"])),
                requested_by=cast(UUID, row["requested_by"]),
                generated_at=cast(datetime, row["created_at"]),
            )
        finally:
            connection.close()

    def finalize(
        self,
        lease: WorkerLease,
        claim: ProjectExportClaim,
        *,
        artifact_uri: str,
        storage_key: str,
        content_hash: str,
        manifest_hash: str,
        byte_count: int,
        file_count: int,
    ) -> Mapping[str, object]:
        details = {
            "artifact_uri": artifact_uri,
            "manifest_hash": manifest_hash,
            "content_hash": content_hash,
            "byte_count": byte_count,
            "file_count": file_count,
        }
        with self._job_store.fenced_transaction(lease) as connection:
            connection.execute(
                """INSERT INTO project_export_artifacts
                     (job_id, project_id, campaign_id, audience, storage_key,
                      artifact_uri, content_hash, manifest_hash, byte_count,
                      file_count, finalized_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           clock_timestamp())
                   ON CONFLICT (job_id, project_id) DO NOTHING""",
                (
                    lease.job_id,
                    lease.project_id,
                    claim.scope.campaign_id,
                    claim.audience.value,
                    storage_key,
                    artifact_uri,
                    content_hash,
                    manifest_hash,
                    byte_count,
                    file_count,
                ),
            )
            persisted = _one(
                connection.execute(
                    """SELECT artifact_uri, storage_key, content_hash,
                              manifest_hash, byte_count, file_count
                       FROM project_export_artifacts
                       WHERE job_id = %s AND project_id = %s""",
                    (lease.job_id, lease.project_id),
                )
            )
            expected = {
                "artifact_uri": artifact_uri,
                "storage_key": storage_key,
                "content_hash": content_hash,
                "manifest_hash": manifest_hash,
                "byte_count": byte_count,
                "file_count": file_count,
            }
            if persisted is None or any(
                persisted[name] != value for name, value in expected.items()
            ):
                raise ProjectExportRuleViolation(
                    "stored project export artifact conflicts with rendered bytes"
                )
            self._job_store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"project-export:{lease.job_id}",
                details=details,
            )
        return details

    def _open(self, project_id: UUID) -> Any:
        connection = self._connection_factory()
        set_project_scope(connection, project_id)
        return connection

    @staticmethod
    def _get(
        connection: Any,
        project_id: UUID,
        job_id: UUID,
        audience: ExportAudience,
    ) -> ProjectExportArtifact | None:
        row = _one(
            connection.execute(
                _VIEW_SQL
                + " WHERE spec.project_id = %s AND spec.job_id = %s"
                + " AND spec.audience = %s",
                (project_id, job_id, audience.value),
            )
        )
        return _artifact(row, audience) if row else None


_VIEW_SQL = """
SELECT job.id AS job_id, spec.project_id, spec.campaign_id, spec.audience,
       job.status, artifact.artifact_uri, artifact.storage_key,
       artifact.content_hash, artifact.manifest_hash, artifact.byte_count,
       artifact.file_count, job.created_at, artifact.finalized_at,
       job.error_code
FROM project_export_specs spec
JOIN durable_jobs job
  ON job.id = spec.job_id AND job.project_id = spec.project_id
LEFT JOIN project_export_artifacts artifact
  ON artifact.job_id = spec.job_id AND artifact.project_id = spec.project_id
"""


def _input_hash(scope: ProjectExportScope, audience: ExportAudience) -> str:
    payload = json.dumps(
        {
            "schema_version": "project-export-request-v1",
            "audience": audience.value,
            "project_id": str(scope.project_id),
            "campaign_id": str(scope.campaign_id) if scope.campaign_id else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _artifact(row: Any, audience: ExportAudience) -> ProjectExportArtifact:
    value = dict(row) if isinstance(row, Mapping) else row
    return ProjectExportArtifact(
        job_id=cast(UUID, value["job_id"]),
        project_id=cast(UUID, value["project_id"]),
        campaign_id=cast(UUID | None, value["campaign_id"]),
        audience=audience,
        status=cast(Any, value["status"]),
        artifact_uri=cast(str | None, value["artifact_uri"]),
        storage_key=cast(str | None, value["storage_key"]),
        content_hash=cast(str | None, value["content_hash"]),
        manifest_hash=cast(str | None, value["manifest_hash"]),
        byte_count=cast(int | None, value["byte_count"]),
        file_count=cast(int | None, value["file_count"]),
        created_at=cast(datetime, value["created_at"]),
        finalized_at=cast(datetime | None, value["finalized_at"]),
        error_code=cast(str | None, value["error_code"]),
    )


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((item.name for item in cursor.description), row, strict=True))
