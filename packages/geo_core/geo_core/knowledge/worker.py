"""Durable Worker handler for knowledge preprocessing runs."""

from __future__ import annotations

from datetime import timedelta
import hashlib
import json
from typing import Any, Mapping
from uuid import uuid4

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.knowledge.domain import (
    KnowledgeProcessingError,
    ProcessingInput,
    ProcessingResult,
)
from geo_core.knowledge.processing import process_source


class KnowledgeProcessHandler:
    def __init__(self, store: PostgresDurableJobStore) -> None:
        self._store = store

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            claim = self._load(lease)
            result = process_source(claim)
            return self._finalize(lease, claim, result)
        except KnowledgeProcessingError as exc:
            return self._fail(lease, exc, retry=exc.retryable)
        except Exception as exc:
            return self._fail(lease, exc, retry=False)

    def _load(self, lease: WorkerLease) -> ProcessingInput:
        connection = self._store.open_project(lease.project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT source.id AS source_id, run.id AS pipeline_run_id,
                              source.project_id, source.source_kind, source.title,
                              source.source_url, source.filename, source.media_type,
                              source.raw_content
                       FROM knowledge_job_specs spec
                       JOIN knowledge_pipeline_runs run
                         ON run.id = spec.pipeline_run_id AND run.project_id = spec.project_id
                       JOIN knowledge_sources source
                         ON source.id = run.source_id AND source.project_id = run.project_id
                       WHERE spec.job_id = %s AND spec.project_id = %s""",
                    (lease.job_id, lease.project_id),
                )
            )
            if row is None:
                raise KnowledgeProcessingError("knowledge job specification is missing")
            connection.execute(
                """UPDATE knowledge_pipeline_runs
                   SET status = 'running', started_at = COALESCE(started_at, clock_timestamp()),
                       error_code = NULL, error_detail = NULL, updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (row["pipeline_run_id"], lease.project_id),
            )
            connection.execute(
                """UPDATE knowledge_sources SET status = 'processing', error_code = NULL,
                       error_detail = NULL, updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (row["source_id"], lease.project_id),
            )
            connection.execute(
                """UPDATE knowledge_pipeline_stages
                   SET status = 'running', started_at = clock_timestamp()
                   WHERE pipeline_run_id = %s AND project_id = %s AND stage_key = 'ingest'""",
                (row["pipeline_run_id"], lease.project_id),
            )
            connection.commit()
            return ProcessingInput(**row)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _finalize(
        self, lease: WorkerLease, claim: ProcessingInput, result: ProcessingResult
    ) -> Mapping[str, object]:
        with self._store.fenced_transaction(lease) as connection:
            document_id = uuid4()
            connection.execute(
                """INSERT INTO knowledge_documents
                     (id, project_id, pipeline_run_id, source_id, parser_version,
                      raw_text, cleaned_text, raw_text_hash, cleaned_text_hash, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)""",
                (
                    document_id,
                    lease.project_id,
                    claim.pipeline_run_id,
                    claim.source_id,
                    result.parser_version,
                    result.raw_text,
                    result.cleaned_text,
                    result.raw_text_hash,
                    result.cleaned_text_hash,
                    json.dumps({"resolved_url": result.resolved_url}, ensure_ascii=False),
                ),
            )
            chunk_ids: list[Any] = []
            for index, chunk in enumerate(result.chunks):
                chunk_id = uuid4()
                chunk_ids.append(chunk_id)
                connection.execute(
                    """INSERT INTO knowledge_chunks
                         (id, project_id, pipeline_run_id, source_id, document_id,
                          chunk_index, text, text_hash, char_count, quality_flags)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        chunk_id,
                        lease.project_id,
                        claim.pipeline_run_id,
                        claim.source_id,
                        document_id,
                        index,
                        chunk.text,
                        chunk.text_hash,
                        chunk.char_count,
                        list(chunk.quality_flags),
                    ),
                )
            for fact in result.facts:
                connection.execute(
                    """INSERT INTO knowledge_fact_candidates
                         (project_id, pipeline_run_id, source_id, chunk_id,
                          statement, statement_hash)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (pipeline_run_id, statement_hash) DO NOTHING""",
                    (
                        lease.project_id,
                        claim.pipeline_run_id,
                        claim.source_id,
                        chunk_ids[fact.chunk_index],
                        fact.statement,
                        fact.statement_hash,
                    ),
                )
            for finding in result.findings:
                connection.execute(
                    """INSERT INTO knowledge_quality_findings
                         (project_id, pipeline_run_id, source_id, chunk_id,
                          finding_code, severity, message, details)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)""",
                    (
                        lease.project_id,
                        claim.pipeline_run_id,
                        claim.source_id,
                        chunk_ids[finding.chunk_index]
                        if finding.chunk_index is not None
                        else None,
                        finding.finding_code,
                        finding.severity,
                        finding.message,
                        json.dumps(dict(finding.details)),
                    ),
                )
            metrics = {
                "ingest": {"content_bytes": len(result.raw_content)},
                "parse": {"raw_char_count": len(result.raw_text)},
                "clean": {"cleaned_char_count": len(result.cleaned_text)},
                "chunk": {"chunk_count": len(result.chunks)},
                "fact_extract": {"fact_candidate_count": len(result.facts)},
                "quality": {"finding_count": len(result.findings)},
            }
            for stage, values in metrics.items():
                connection.execute(
                    """UPDATE knowledge_pipeline_stages
                       SET status = 'succeeded', metrics = %s::jsonb,
                           started_at = COALESCE(started_at, clock_timestamp()),
                           completed_at = clock_timestamp(), error_detail = NULL
                       WHERE pipeline_run_id = %s AND project_id = %s AND stage_key = %s""",
                    (json.dumps(values), claim.pipeline_run_id, lease.project_id, stage),
                )
            connection.execute(
                """UPDATE knowledge_sources SET status = 'ready', raw_content = %s,
                       source_url = COALESCE(%s, source_url), content_hash = %s,
                       error_code = NULL, error_detail = NULL, updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (
                    result.raw_content,
                    result.resolved_url,
                    hashlib.sha256(result.raw_content).hexdigest(),
                    claim.source_id,
                    lease.project_id,
                ),
            )
            connection.execute(
                """UPDATE knowledge_pipeline_runs SET status = 'succeeded',
                       completed_at = clock_timestamp(), error_code = NULL,
                       error_detail = NULL, updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (claim.pipeline_run_id, lease.project_id),
            )
            details = {
                "pipeline_run_id": str(claim.pipeline_run_id),
                "source_id": str(claim.source_id),
                "chunk_count": len(result.chunks),
                "fact_candidate_count": len(result.facts),
                "quality_finding_count": len(result.findings),
            }
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"knowledge-run:{claim.pipeline_run_id}",
                details=details,
            )
        return {"status": "succeeded", "job_id": str(lease.job_id), **details}

    def _fail(
        self, lease: WorkerLease, error: Exception, *, retry: bool
    ) -> Mapping[str, object]:
        with self._store.fenced_transaction(lease) as connection:
            spec = _one(
                connection.execute(
                    """SELECT run.id AS pipeline_run_id, run.source_id
                       FROM knowledge_job_specs spec
                       JOIN knowledge_pipeline_runs run
                         ON run.id = spec.pipeline_run_id AND run.project_id = spec.project_id
                       WHERE spec.job_id = %s AND spec.project_id = %s""",
                    (lease.job_id, lease.project_id),
                )
            )
            detail = str(error)[:2000]
            if spec:
                status = "queued" if retry and lease.attempt_count < lease.max_attempts else "failed"
                connection.execute(
                    """UPDATE knowledge_pipeline_runs SET status = %s, error_code = %s,
                           error_detail = %s, completed_at = CASE WHEN %s = 'failed'
                             THEN clock_timestamp() ELSE NULL END,
                           updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s""",
                    (
                        status,
                        type(error).__name__,
                        detail,
                        status,
                        spec["pipeline_run_id"],
                        lease.project_id,
                    ),
                )
                connection.execute(
                    """UPDATE knowledge_sources SET status = %s, error_code = %s,
                           error_detail = %s, updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s""",
                    (
                        "queued" if status == "queued" else "failed",
                        type(error).__name__,
                        detail,
                        spec["source_id"],
                        lease.project_id,
                    ),
                )
                connection.execute(
                    """UPDATE knowledge_pipeline_stages
                       SET status = CASE WHEN status = 'running' THEN 'failed' ELSE status END,
                           error_detail = CASE WHEN status = 'running' THEN %s ELSE error_detail END,
                           completed_at = CASE WHEN status = 'running' THEN clock_timestamp()
                                               ELSE completed_at END
                       WHERE pipeline_run_id = %s AND project_id = %s""",
                    (detail, spec["pipeline_run_id"], lease.project_id),
                )
            if retry and lease.attempt_count < lease.max_attempts:
                # The store owns retry scheduling and clears the lease in its own transaction.
                pass
            else:
                self._store.fail_in_transaction(
                    connection,
                    lease,
                    error_code=type(error).__name__,
                    details={"message": detail},
                )
                return {"status": "failed", "job_id": str(lease.job_id)}
        status = self._store.fail(
            lease,
            error_code=type(error).__name__,
            details={"message": str(error)[:2000]},
            retry_delay=timedelta(seconds=30),
        )
        return {"status": status, "job_id": str(lease.job_id)}


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((column.name for column in cursor.description), row, strict=True))
