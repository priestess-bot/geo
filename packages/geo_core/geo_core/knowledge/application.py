"""Application service for project-scoped knowledge ingestion and review."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from geo_core.access.models import AccessPrincipal
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeForbidden,
    KnowledgeNotFound,
    KnowledgeValidationError,
    SourceInput,
)
from geo_core.knowledge.evidence import KnowledgeEvidenceApplicationMixin
from geo_core.knowledge.fact_review_application import KnowledgeFactReviewApplicationMixin
from geo_core.knowledge.locking import lock_source_aggregate, source_logical_id
from geo_core.knowledge.question_application import KnowledgeQuestionApplicationMixin
from geo_core.knowledge.question_set_application import KnowledgeQuestionSetApplicationMixin
from geo_core.knowledge.rag_application import KnowledgeRagApplicationMixin
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy
from geo_core.knowledge.source_application_support import (
    canonical_hash as _hash,
    idempotency_key as _idempotency_key,
    run_exists as _exists_run,
    validate_source as _validate_source,
)


_STAGES = ("ingest", "parse", "clean", "chunk", "fact_extract", "quality")
_MANAGE_ROLES = frozenset({"owner", "admin", "analyst"})


class KnowledgeApplication(
    KnowledgeQuestionSetApplicationMixin,
    KnowledgeQuestionApplicationMixin,
    KnowledgeRagApplicationMixin,
    KnowledgeFactReviewApplicationMixin,
    KnowledgeEvidenceApplicationMixin,
):
    def __init__(
        self,
        database_url: str,
        *,
        question_policy: KnowledgeRagEnqueuePolicy | None = None,
    ) -> None:
        if not database_url.strip():
            raise ValueError("knowledge database URL is required")
        self._database_url = database_url.strip()
        self._question_policy = question_policy

    def create_source(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        source: SourceInput,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        _validate_source(source)
        key = _idempotency_key(idempotency_key)
        source_id = uuid5(NAMESPACE_URL, f"geo-knowledge-source:{project_id}:{key}")
        run_id = uuid5(NAMESPACE_URL, f"geo-knowledge-run:{source_id}:{key}")
        input_hash = _hash(
            {
                "project_id": str(project_id),
                "source_kind": source.source_kind,
                "title": source.title,
                "source_url": source.source_url,
                "filename": source.filename,
                "media_type": source.media_type,
                "content_hash": hashlib.sha256(source.raw_content or b"").hexdigest(),
            }
        )
        with self._connection(principal, project_id, manage=True) as connection:
            lock_source_aggregate(connection, source_id)
            existing = _one(
                connection.execute(
                    """SELECT source.id, run.id AS pipeline_run_id, run.input_hash,
                              spec.job_id, job.status AS job_status
                       FROM knowledge_sources source
                       JOIN knowledge_pipeline_runs run
                         ON run.source_id = source.id AND run.project_id = source.project_id
                       JOIN knowledge_job_specs spec
                         ON spec.pipeline_run_id = run.id AND spec.project_id = run.project_id
                       JOIN durable_jobs job
                         ON job.id = spec.job_id AND job.project_id = spec.project_id
                       WHERE source.id = %s AND source.project_id = %s AND run.id = %s""",
                    (source_id, project_id, run_id),
                )
            )
            if existing:
                if existing["input_hash"] != input_hash:
                    raise KnowledgeConflict(
                        "idempotency key was already used for different source content"
                    )
                return self._creation_result(connection, project_id, source_id, run_id)
            connection.execute(
                """INSERT INTO knowledge_sources
                     (id, project_id, logical_source_id, source_kind, title, source_url, filename,
                      media_type, raw_content, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    source_id,
                    project_id,
                    source_id,
                    source.source_kind,
                    source.title.strip(),
                    source.source_url,
                    source.filename,
                    source.media_type.strip().lower(),
                    source.raw_content,
                    principal.identity_id,
                ),
            )
            self._create_pipeline_run(
                connection,
                principal=principal,
                project_id=project_id,
                source_id=source_id,
                run_id=run_id,
                input_hash=input_hash,
                idempotency_key=key,
            )
            return self._creation_result(connection, project_id, source_id, run_id)

    def reprocess_source(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        source_id: UUID,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        key = f"reprocess:{source_id}:{_idempotency_key(idempotency_key)}"
        run_id = uuid5(NAMESPACE_URL, f"geo-knowledge-run:{source_id}:{key}")
        with self._connection(principal, project_id, manage=True) as connection:
            logical_source_id = source_logical_id(
                connection, project_id=project_id, source_id=source_id
            )
            if logical_source_id is None:
                raise KnowledgeNotFound("knowledge source does not exist")
            lock_source_aggregate(connection, logical_source_id)
            if _exists_run(connection, run_id, project_id):
                return self._creation_result(connection, project_id, source_id, run_id)
            source = _one(
                connection.execute(
                    """SELECT source_kind, title, source_url, filename, media_type, raw_content,
                              content_hash, status,
                              EXISTS (
                                SELECT 1 FROM knowledge_sources successor
                                WHERE successor.supersedes_source_id = knowledge_sources.id
                                  AND successor.project_id = knowledge_sources.project_id
                              ) AS has_successor
                       FROM knowledge_sources WHERE id = %s AND project_id = %s""",
                    (source_id, project_id),
                )
            )
            if source is None:
                raise KnowledgeNotFound("knowledge source does not exist")
            if source["status"] == "archived":
                raise KnowledgeConflict("archived Knowledge sources cannot be reprocessed")
            if source["has_successor"]:
                raise KnowledgeConflict(
                    "only the latest Knowledge source revision can be reprocessed"
                )
            input_hash = _hash(
                {
                    "project_id": str(project_id),
                    "source_id": str(source_id),
                    "source_kind": source["source_kind"],
                    "source_url": source["source_url"],
                    "filename": source["filename"],
                    "media_type": source["media_type"],
                    "content_hash": source["content_hash"]
                    or hashlib.sha256(source["raw_content"] or b"").hexdigest(),
                    "reprocess_key": key,
                }
            )
            if source["status"] in {"queued", "processing"}:
                raise KnowledgeConflict("knowledge source already has an active processing run")
            self._create_pipeline_run(
                connection,
                principal=principal,
                project_id=project_id,
                source_id=source_id,
                run_id=run_id,
                input_hash=input_hash,
                idempotency_key=key,
            )
            connection.execute(
                """UPDATE knowledge_sources SET status = 'queued', error_code = NULL,
                          error_detail = NULL, updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (source_id, project_id),
            )
            return self._creation_result(connection, project_id, source_id, run_id)

    def _create_pipeline_run(
        self,
        connection: Any,
        *,
        principal: AccessPrincipal,
        project_id: UUID,
        source_id: UUID,
        run_id: UUID,
        input_hash: str,
        idempotency_key: str,
    ) -> None:
        connection.execute(
            """INSERT INTO knowledge_pipeline_runs
                 (id, project_id, source_id, input_hash, created_by)
               VALUES (%s, %s, %s, %s, %s)""",
            (run_id, project_id, source_id, input_hash, principal.identity_id),
        )
        for ordinal, stage in enumerate(_STAGES, 1):
            connection.execute(
                """INSERT INTO knowledge_pipeline_stages
                     (project_id, pipeline_run_id, stage_key, ordinal)
                   VALUES (%s, %s, %s, %s)""",
                (project_id, run_id, stage, ordinal),
            )
        job = _one(
            connection.execute(
                """INSERT INTO durable_jobs
                     (project_id, kind, input_hash, idempotency_key)
                   VALUES (%s, 'knowledge.process', %s, %s)
                   RETURNING id""",
                (project_id, input_hash, idempotency_key),
            )
        )
        assert job is not None
        connection.execute(
            """INSERT INTO knowledge_job_specs
                 (job_id, project_id, pipeline_run_id, requested_by)
               VALUES (%s, %s, %s, %s)""",
            (job["id"], project_id, run_id, principal.identity_id),
        )
        connection.execute(
            """INSERT INTO broker_outbox
                 (project_id, job_id, topic, payload, idempotency_key)
               VALUES (%s, %s, 'knowledge.process', %s::jsonb, %s)""",
            (
                project_id,
                job["id"],
                json.dumps({"job_id": str(job["id"]), "project_id": str(project_id)}),
                f"wake:knowledge.process:{idempotency_key}",
            ),
        )

    def list_sources(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        return self._list(
            principal,
            project_id,
            """SELECT id, project_id, logical_source_id, supersedes_source_id,
                      source_kind, title, source_url, filename, media_type,
                      status, content_hash, error_code, error_detail,
                      octet_length(raw_content) AS content_bytes, created_at, updated_at
               FROM knowledge_sources WHERE project_id = %s
               ORDER BY created_at DESC, id DESC""",
        )

    def list_runs(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        return self._list(
            principal,
            project_id,
            """SELECT run.id, run.project_id, run.source_id, source.title AS source_title,
                      run.status, run.input_hash, run.error_code, run.error_detail,
                      run.started_at, run.completed_at, run.created_at,
                      spec.job_id, job.status AS job_status
               FROM knowledge_pipeline_runs run
               JOIN knowledge_sources source
                 ON source.id = run.source_id AND source.project_id = run.project_id
               LEFT JOIN knowledge_job_specs spec
                 ON spec.pipeline_run_id = run.id AND spec.project_id = run.project_id
               LEFT JOIN durable_jobs job
                 ON job.id = spec.job_id AND job.project_id = spec.project_id
               WHERE run.project_id = %s ORDER BY run.created_at DESC, run.id DESC""",
        )

    def list_stages(
        self, principal: AccessPrincipal, *, project_id: UUID, run_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        with self._connection(principal, project_id) as connection:
            rows = _many(
                connection.execute(
                    """SELECT id, project_id, pipeline_run_id, stage_key, ordinal, status,
                              metrics, error_detail, started_at, completed_at
                       FROM knowledge_pipeline_stages
                       WHERE project_id = %s AND pipeline_run_id = %s ORDER BY ordinal""",
                    (project_id, run_id),
                )
            )
            if not rows and not _exists_run(connection, run_id, project_id):
                raise KnowledgeNotFound("knowledge pipeline run does not exist")
            return tuple(rows)

    def list_chunks(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        query: str = "",
        status: str = "",
    ) -> tuple[dict[str, Any], ...]:
        filters = ["chunk.project_id = %s"]
        values: list[object] = [project_id]
        if query.strip():
            filters.append("chunk.text ILIKE %s")
            values.append(f"%{query.strip()}%")
        if status.strip():
            filters.append("chunk.status = %s")
            values.append(status.strip())
        with self._connection(principal, project_id) as connection:
            return tuple(
                _many(
                    connection.execute(
                        f"""SELECT chunk.id, chunk.project_id, chunk.pipeline_run_id,
                                      chunk.source_id, source.title AS source_title,
                                      chunk.document_id, chunk.chunk_index, chunk.text,
                                      chunk.text_hash, chunk.char_count, chunk.status,
                                      chunk.quality_flags, chunk.created_at
                               FROM knowledge_chunks chunk
                               JOIN knowledge_sources source
                                 ON source.id = chunk.source_id
                                AND source.project_id = chunk.project_id
                               WHERE {' AND '.join(filters)}
                               ORDER BY chunk.created_at DESC, chunk.chunk_index
                               LIMIT 200""",  # nosec B608 - predicates are closed above.
                        values,
                    )
                )
            )

    def list_facts(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        return self._list(
            principal,
            project_id,
            """SELECT fact.id, fact.project_id, fact.pipeline_run_id, fact.source_id,
                      source.title AS source_title, fact.chunk_id, fact.statement,
                      fact.statement_hash, fact.status, fact.lifecycle_status,
                      fact.extractor_release, fact.reviewed_by,
                      fact.review_notes, fact.reviewed_at, fact.created_at
               FROM knowledge_fact_candidates fact
               JOIN knowledge_sources source
                 ON source.id = fact.source_id AND source.project_id = fact.project_id
               WHERE fact.project_id = %s AND fact.lifecycle_status = 'active'
               ORDER BY fact.created_at DESC LIMIT 200""",
        )

    def list_findings(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        return self._list(
            principal,
            project_id,
            """SELECT finding.id, finding.project_id, finding.pipeline_run_id,
                      finding.source_id, source.title AS source_title, finding.chunk_id,
                      finding.finding_code, finding.severity, finding.status,
                      finding.message, finding.details, finding.created_at
               FROM knowledge_quality_findings finding
               JOIN knowledge_sources source
                 ON source.id = finding.source_id AND source.project_id = finding.project_id
               WHERE finding.project_id = %s ORDER BY finding.created_at DESC LIMIT 200""",
        )

    def review_finding(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        finding_id: UUID,
        decision: str,
    ) -> Mapping[str, object]:
        if decision not in {"accepted", "resolved"}:
            raise KnowledgeValidationError("finding decision must be accepted or resolved")
        with self._connection(principal, project_id, manage=True) as connection:
            row = _one(
                connection.execute(
                    """UPDATE knowledge_quality_findings SET status = %s
                       WHERE id = %s AND project_id = %s AND status = 'open'
                       RETURNING id, project_id, finding_code, severity, status""",
                    (decision, finding_id, project_id),
                )
            )
            if row is None:
                raise KnowledgeNotFound("open knowledge quality finding does not exist")
            return row

    def dashboard(self, principal: AccessPrincipal, *, project_id: UUID) -> Mapping[str, object]:
        with self._connection(principal, project_id) as connection:
            row = _one(
                connection.execute(
                    """SELECT
                         (SELECT count(*) FROM knowledge_sources WHERE project_id = %s) AS sources,
                         (SELECT count(*) FROM knowledge_pipeline_runs
                           WHERE project_id = %s AND status = 'succeeded') AS succeeded_runs,
                         (SELECT count(*) FROM knowledge_pipeline_runs
                           WHERE project_id = %s AND status = 'failed') AS failed_runs,
                         (SELECT count(*) FROM knowledge_chunks
                           WHERE project_id = %s AND status = 'active') AS active_chunks,
                         (SELECT count(*) FROM knowledge_fact_candidates
                           WHERE project_id = %s AND status = 'pending_review'
                             AND lifecycle_status = 'active') AS pending_facts,
                         (SELECT count(*) FROM knowledge_quality_findings
                           WHERE project_id = %s AND status = 'open') AS open_findings""",
                    (project_id,) * 6,
                )
            )
            return row or {}

    def disable_chunk(
        self, principal: AccessPrincipal, *, project_id: UUID, chunk_id: UUID
    ) -> Mapping[str, object]:
        with self._connection(principal, project_id, manage=True) as connection:
            identity = _one(
                connection.execute(
                    """SELECT source.logical_source_id
                       FROM knowledge_chunks chunk
                       JOIN knowledge_sources source
                         ON source.id = chunk.source_id
                        AND source.project_id = chunk.project_id
                       WHERE chunk.id = %s AND chunk.project_id = %s""",
                    (chunk_id, project_id),
                )
            )
            if identity is None:
                raise KnowledgeNotFound("knowledge chunk does not exist")
            lock_source_aggregate(connection, identity["logical_source_id"])
            row = _one(
                connection.execute(
                    """UPDATE knowledge_chunks SET status = 'disabled',
                           updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s
                       RETURNING id, project_id, status, updated_at""",
                    (chunk_id, project_id),
                )
            )
            if row is None:
                raise KnowledgeNotFound("knowledge chunk does not exist")
            return row

    def source_content(
        self, principal: AccessPrincipal, *, project_id: UUID, source_id: UUID
    ) -> tuple[bytes, str, str]:
        with self._connection(principal, project_id) as connection:
            row = _one(
                connection.execute(
                    """SELECT raw_content, media_type, COALESCE(filename, title) AS filename
                       FROM knowledge_sources WHERE id = %s AND project_id = %s""",
                    (source_id, project_id),
                )
            )
            if row is None or row["raw_content"] is None:
                raise KnowledgeNotFound("knowledge source content is not available")
            return bytes(row["raw_content"]), row["media_type"], row["filename"]

    def _creation_result(
        self, connection: Any, project_id: UUID, source_id: UUID, run_id: UUID
    ) -> Mapping[str, object]:
        return {
            "source": _one(
                connection.execute(
                    """SELECT id, project_id, source_kind, title, source_url, filename,
                              media_type, status, created_at
                       FROM knowledge_sources WHERE id = %s AND project_id = %s""",
                    (source_id, project_id),
                )
            ),
            "pipeline_run": _one(
                connection.execute(
                    """SELECT id, project_id, source_id, status, input_hash, created_at
                       FROM knowledge_pipeline_runs WHERE id = %s AND project_id = %s""",
                    (run_id, project_id),
                )
            ),
            "job": _one(
                connection.execute(
                    """SELECT job.id, job.project_id, job.kind, job.status
                       FROM knowledge_job_specs spec JOIN durable_jobs job
                         ON job.id = spec.job_id AND job.project_id = spec.project_id
                       WHERE spec.pipeline_run_id = %s AND spec.project_id = %s""",
                    (run_id, project_id),
                )
            ),
        }

    def _list(
        self,
        principal: AccessPrincipal,
        project_id: UUID,
        statement: str,
    ) -> tuple[dict[str, Any], ...]:
        with self._connection(principal, project_id) as connection:
            return tuple(_many(connection.execute(statement, (project_id,))))

    def _connection(
        self, principal: AccessPrincipal, project_id: UUID, *, manage: bool = False
    ) -> _KnowledgeConnection:
        return _KnowledgeConnection(
            self._database_url, principal, project_id, require_manage=manage
        )


class _KnowledgeConnection:
    def __init__(
        self,
        database_url: str,
        principal: AccessPrincipal,
        project_id: UUID,
        *,
        require_manage: bool,
    ) -> None:
        self._database_url = database_url
        self._principal = principal
        self._project_id = project_id
        self._require_manage = require_manage
        self.connection: Any = None

    def __enter__(self) -> Any:
        self.connection = psycopg.connect(self._database_url, row_factory=dict_row)
        values = {
            "geo.actor_id": str(self._principal.identity_id),
            "geo.identity_id": str(self._principal.identity_id),
            "geo.tenant_id": str(self._principal.tenant_id),
            "geo.project_id": str(self._project_id),
            "geo.project_ids": json.dumps([str(self._project_id)]),
        }
        for name, value in values.items():
            self.connection.execute("SELECT set_config(%s, %s, true)", (name, value))
        membership = _one(
            self.connection.execute(
                """SELECT role FROM project_memberships
                   WHERE project_id = %s AND tenant_id = %s AND identity_id = %s
                     AND status = 'active'""",
                (self._project_id, self._principal.tenant_id, self._principal.identity_id),
            )
        )
        if membership is None or (self._require_manage and membership["role"] not in _MANAGE_ROLES):
            self.connection.rollback()
            self.connection.close()
            raise KnowledgeForbidden("current identity cannot access this knowledge workspace")
        return self.connection

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del traceback
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()


def _one(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    return dict(value) if value is not None else None


def _many(cursor: Any) -> list[dict[str, Any]]:
    return [dict(value) for value in cursor.fetchall()]
