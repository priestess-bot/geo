"""Immutable Knowledge source revision and withdrawal workflows."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.access.models import AccessPrincipal
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeNotFound,
    KnowledgeValidationError,
    SourceInput,
)
from geo_core.knowledge.locking import lock_source_aggregate, source_logical_id
from geo_core.knowledge.rag_graph_lifecycle import archive_unreferenced_graph_rows


class KnowledgeRagSourceApplicationMixin:
    """Source lifecycle operations mixed into ``KnowledgeApplication``."""

    def create_source_revision(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        source_id: UUID,
        source: SourceInput,
        idempotency_key: str,
    ) -> Mapping[str, object]:
        _validate_source_revision(source)
        key = _idempotency_key(idempotency_key)
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            logical_source_id = source_logical_id(
                connection, project_id=project_id, source_id=source_id
            )
            if logical_source_id is None:
                raise KnowledgeNotFound("Knowledge source does not exist")
            lock_source_aggregate(connection, logical_source_id)
            new_source_id = uuid5(
                NAMESPACE_URL,
                f"geo-knowledge-source-revision:{project_id}:{logical_source_id}:{key}",
            )
            run_id = uuid5(NAMESPACE_URL, f"geo-knowledge-run:{new_source_id}:{key}")
            input_hash = _source_input_hash(project_id, source, key)
            existing = _one(
                connection.execute(
                    """SELECT run.input_hash
                       FROM knowledge_sources source
                       JOIN knowledge_pipeline_runs run
                         ON run.source_id = source.id AND run.project_id = source.project_id
                       WHERE source.id = %s AND source.project_id = %s AND run.id = %s""",
                    (new_source_id, project_id, run_id),
                )
            )
            if existing is not None:
                if existing["input_hash"] != input_hash:
                    raise KnowledgeConflict(
                        "source revision idempotency key was used for different content"
                    )
                return cast(
                    Mapping[str, object],
                    self._creation_result(connection, project_id, new_source_id, run_id),  # type: ignore[attr-defined]
                )
            previous = _one(
                connection.execute(
                    """SELECT id, logical_source_id, status, error_code
                       FROM knowledge_sources
                       WHERE id = %s AND project_id = %s FOR UPDATE""",
                    (source_id, project_id),
                )
            )
            if previous is None:
                raise KnowledgeNotFound("Knowledge source does not exist")
            revision_required = (
                previous["status"] == "failed"
                and previous["error_code"] == "KnowledgeSourceRevisionRequired"
            )
            if previous["status"] != "ready" and not revision_required:
                raise KnowledgeConflict("only a ready Knowledge source can create a revision")
            logical_source_id = previous["logical_source_id"] or previous["id"]
            successor = _one(
                connection.execute(
                    """SELECT id FROM knowledge_sources
                       WHERE supersedes_source_id = %s AND project_id = %s""",
                    (source_id, project_id),
                )
            )
            if successor is not None:
                raise KnowledgeConflict("Knowledge source already has a newer immutable revision")
            connection.execute(
                """INSERT INTO knowledge_sources
                     (id, project_id, logical_source_id, supersedes_source_id,
                      source_kind, title, source_url, filename, media_type,
                      raw_content, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    new_source_id,
                    project_id,
                    logical_source_id,
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
            self._create_pipeline_run(  # type: ignore[attr-defined]
                connection,
                principal=principal,
                project_id=project_id,
                source_id=new_source_id,
                run_id=run_id,
                input_hash=input_hash,
                idempotency_key=f"revision:{logical_source_id}:{key}",
            )
            return cast(
                Mapping[str, object],
                self._creation_result(connection, project_id, new_source_id, run_id),  # type: ignore[attr-defined]
            )

    def archive_source(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        source_id: UUID,
    ) -> Mapping[str, object]:
        with self._connection(  # type: ignore[attr-defined]
            principal, project_id, manage=True
        ) as connection:
            logical_source_id = source_logical_id(
                connection, project_id=project_id, source_id=source_id
            )
            if logical_source_id is None:
                raise KnowledgeNotFound("Knowledge source does not exist")
            _cancel_source_jobs(connection, project_id=project_id, source_id=source_id)
            lock_source_aggregate(connection, logical_source_id)
            _cancel_source_jobs(
                connection,
                project_id=project_id,
                source_id=source_id,
                statuses=("queued", "retry_wait"),
            )
            source = _one(
                connection.execute(
                    """SELECT id, logical_source_id, status FROM knowledge_sources
                       WHERE id = %s AND project_id = %s FOR UPDATE""",
                    (source_id, project_id),
                )
            )
            if source is None:
                raise KnowledgeNotFound("Knowledge source does not exist")
            if source["status"] == "archived":
                return {"outcome": "existing", **source}
            revision_rows = _many(
                connection.execute(
                    """UPDATE knowledge_rag_revisions
                       SET lifecycle_status = 'withdrawn', withdrawn_at = clock_timestamp()
                       WHERE project_id = %s AND source_id = %s
                         AND lifecycle_status = 'active' RETURNING id""",
                    (project_id, source_id),
                )
            )
            revision_ids = [value["id"] for value in revision_rows]
            if revision_ids:
                for table in (
                    "knowledge_fact_candidates",
                    "knowledge_entity_candidates",
                    "knowledge_relation_candidates",
                ):
                    connection.execute(
                        f"""UPDATE {table} SET lifecycle_status = 'withdrawn',
                                  updated_at = clock_timestamp()
                            WHERE project_id = %s AND rag_revision_id = ANY(%s)
                              AND lifecycle_status = 'active'""",  # nosec B608
                        (project_id, revision_ids),
                    )
                connection.execute(
                    """UPDATE knowledge_graph_entity_sources
                       SET lifecycle_status = 'withdrawn'
                       WHERE project_id = %s AND rag_revision_id = ANY(%s)""",
                    (project_id, revision_ids),
                )
                connection.execute(
                    """UPDATE knowledge_graph_relation_sources
                       SET lifecycle_status = 'withdrawn'
                       WHERE project_id = %s AND rag_revision_id = ANY(%s)""",
                    (project_id, revision_ids),
                )
                archive_unreferenced_graph_rows(connection, project_id)
            connection.execute(
                """UPDATE knowledge_fact_candidates
                   SET lifecycle_status = 'withdrawn', updated_at = clock_timestamp()
                   WHERE project_id = %s AND source_id = %s
                     AND lifecycle_status = 'active'""",
                (project_id, source_id),
            )
            connection.execute(
                """UPDATE knowledge_chunks SET status = 'disabled',
                          updated_at = clock_timestamp()
                   WHERE project_id = %s AND source_id = %s AND status = 'active'""",
                (project_id, source_id),
            )
            archived = _one(
                connection.execute(
                    """UPDATE knowledge_sources SET status = 'archived',
                              updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s
                       RETURNING id, project_id, logical_source_id, status, updated_at""",
                    (source_id, project_id),
                )
            )
            assert archived is not None
            return {
                "outcome": "archived",
                "withdrawn_revision_count": len(revision_ids),
                **archived,
            }


def _cancel_source_jobs(
    connection: Any,
    *,
    project_id: UUID,
    source_id: UUID,
    statuses: tuple[str, ...] = ("queued", "retry_wait", "running", "finalizing"),
) -> None:
    connection.execute(
        """UPDATE durable_jobs job SET cancel_requested_at = clock_timestamp(),
                  updated_at = clock_timestamp()
           FROM knowledge_rag_job_specs spec
           WHERE spec.job_id = job.id AND spec.project_id = job.project_id
             AND spec.source_id = %s AND spec.project_id = %s
             AND job.status = ANY(%s)""",
        (source_id, project_id, list(statuses)),
    )
    connection.execute(
        """UPDATE durable_jobs job SET cancel_requested_at = clock_timestamp(),
                  updated_at = clock_timestamp()
           FROM knowledge_job_specs spec
           JOIN knowledge_pipeline_runs run
             ON run.id = spec.pipeline_run_id AND run.project_id = spec.project_id
           WHERE spec.job_id = job.id AND spec.project_id = job.project_id
             AND run.source_id = %s AND spec.project_id = %s
             AND job.status = ANY(%s)""",
        (source_id, project_id, list(statuses)),
    )


def _validate_source_revision(source: SourceInput) -> None:
    if source.source_kind not in {"url", "file", "text"}:
        raise KnowledgeValidationError("source_kind must be url, file or text")
    if not source.title.strip() or len(source.title) > 300:
        raise KnowledgeValidationError(
            "source title is required and must be at most 300 characters"
        )
    if not source.media_type.strip():
        raise KnowledgeValidationError("source media type is required")
    if source.source_kind == "url" and not source.source_url:
        raise KnowledgeValidationError("URL source requires source_url")
    if source.source_kind != "url" and source.raw_content is None:
        raise KnowledgeValidationError("file and text sources require content")
    if source.raw_content is not None and len(source.raw_content) > 5 * 1024 * 1024:
        raise KnowledgeValidationError("source exceeds the 5 MB limit")


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 200:
        raise KnowledgeValidationError("Idempotency-Key must contain 1 to 200 characters")
    return normalized


def _source_input_hash(project_id: UUID, source: SourceInput, key: str) -> str:
    value = {
        "project_id": str(project_id),
        "source_kind": source.source_kind,
        "title": source.title,
        "source_url": source.source_url,
        "filename": source.filename,
        "media_type": source.media_type,
        "content_hash": hashlib.sha256(source.raw_content or b"").hexdigest(),
        "revision_key": key,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _one(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    return dict(value) if value is not None else None


def _many(cursor: Any) -> list[dict[str, Any]]:
    return [dict(value) for value in cursor.fetchall()]
