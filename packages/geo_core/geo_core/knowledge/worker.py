"""Durable Worker handler for knowledge preprocessing runs."""

from __future__ import annotations

from datetime import timedelta
import hashlib
import json
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.knowledge.domain import (
    KnowledgeProcessingError,
    KnowledgeSourceRevisionRequired,
    ProcessingInput,
    ProcessingResult,
)
from geo_core.knowledge.locking import lock_source_aggregate
from geo_core.knowledge.processing import process_source
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy


class KnowledgeProcessHandler:
    def __init__(
        self,
        store: PostgresDurableJobStore,
        *,
        lease_for: timedelta,
        rag_policy: KnowledgeRagEnqueuePolicy | None = None,
    ) -> None:
        self._store = store
        self._rag_policy = rag_policy
        self._lease_for = lease_for

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            claim = self._load(lease)
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                result = process_source(claim)
                heartbeat.raise_if_stopped()
            return self._finalize(lease, claim, result)
        except (JobCancellationRequested, LostJobLease):
            raise
        except KnowledgeProcessingError as exc:
            return self._fail(lease, exc, retry=exc.retryable)
        except Exception as exc:
            return self._fail(lease, exc, retry=_is_retryable_database_error(exc))

    def reconcile_terminal(self, *, job_id: UUID, project_id: UUID) -> None:
        connection = self._store.open_project(project_id)
        try:
            row = _one(
                connection.execute(
                    """SELECT job.status AS job_status, run.id AS pipeline_run_id,
                              run.source_id, source.logical_source_id
                       FROM durable_jobs job
                       JOIN knowledge_job_specs spec
                         ON spec.job_id = job.id AND spec.project_id = job.project_id
                       JOIN knowledge_pipeline_runs run
                         ON run.id = spec.pipeline_run_id AND run.project_id = spec.project_id
                       JOIN knowledge_sources source
                         ON source.id = run.source_id AND source.project_id = run.project_id
                       WHERE job.id = %s AND job.project_id = %s""",
                    (job_id, project_id),
                )
            )
            if row is None or row["job_status"] not in {"cancelled", "dead_lettered"}:
                connection.rollback()
                return
            lock_source_aggregate(connection, row["logical_source_id"] or row["source_id"])
            cancelled = row["job_status"] == "cancelled"
            run_status = "cancelled" if cancelled else "failed"
            error_code = "job_cancelled" if cancelled else "attempt_budget_exhausted"
            detail = (
                "knowledge processing was cancelled"
                if cancelled
                else "worker lease attempts were exhausted"
            )
            connection.execute(
                """UPDATE knowledge_pipeline_runs
                   SET status = %s, error_code = %s, error_detail = %s,
                       completed_at = clock_timestamp(), updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s
                     AND status IN ('queued', 'running')""",
                (run_status, error_code, detail, row["pipeline_run_id"], project_id),
            )
            connection.execute(
                """UPDATE knowledge_pipeline_stages
                   SET status = CASE
                         WHEN %s OR status = 'pending' THEN 'skipped'
                         ELSE 'failed'
                       END,
                       error_detail = %s,
                       completed_at = clock_timestamp()
                   WHERE pipeline_run_id = %s AND project_id = %s
                     AND status IN ('pending', 'running')""",
                (cancelled, detail, row["pipeline_run_id"], project_id),
            )
            connection.execute(
                """UPDATE knowledge_sources
                   SET status = 'failed', error_code = %s, error_detail = %s,
                       updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s
                     AND status IN ('queued', 'processing')""",
                (error_code, detail, row["source_id"], project_id),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _load(self, lease: WorkerLease) -> ProcessingInput:
        with self._store.fenced_transaction(lease) as connection:
            row = _one(
                connection.execute(
                    """SELECT source.id AS source_id, run.id AS pipeline_run_id,
                              source.project_id, source.logical_source_id,
                              source.source_kind, source.title,
                              source.source_url, source.filename, source.media_type,
                              source.raw_content,
                              source.content_hash AS expected_content_hash,
                              spec.requested_by
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
            lock_source_aggregate(connection, row["logical_source_id"] or row["source_id"])
            source = _one(
                connection.execute(
                    """SELECT status FROM knowledge_sources
                       WHERE id = %s AND project_id = %s FOR UPDATE""",
                    (row["source_id"], lease.project_id),
                )
            )
            if source is None:
                raise KnowledgeProcessingError("Knowledge source disappeared before processing")
            if source["status"] == "archived":
                raise JobCancellationRequested("Knowledge source was archived before processing")
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
            return ProcessingInput(**row)

    def _finalize(
        self, lease: WorkerLease, claim: ProcessingInput, result: ProcessingResult
    ) -> Mapping[str, object]:
        content_hash = hashlib.sha256(result.raw_content).hexdigest()
        if claim.expected_content_hash and claim.expected_content_hash != content_hash:
            raise KnowledgeSourceRevisionRequired(
                "source content changed; create an immutable Knowledge source revision"
            )
        with self._store.fenced_transaction(lease) as connection:
            lock_source_aggregate(connection, claim.logical_source_id or claim.source_id)
            source = _one(
                connection.execute(
                    """SELECT status FROM knowledge_sources
                       WHERE id = %s AND project_id = %s FOR UPDATE""",
                    (claim.source_id, lease.project_id),
                )
            )
            if source is None:
                raise KnowledgeProcessingError("Knowledge source disappeared during processing")
            if source["status"] == "archived":
                raise JobCancellationRequested("Knowledge source was archived during processing")
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
                         (project_id, pipeline_run_id, source_id, document_id, chunk_id,
                          statement, statement_hash, extractor_release, lifecycle_status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s,
                               'legacy-sentence-v1', %s)
                       ON CONFLICT (pipeline_run_id, statement_hash)
                         WHERE rag_revision_id IS NULL
                       DO NOTHING""",
                    (
                        lease.project_id,
                        claim.pipeline_run_id,
                        claim.source_id,
                        document_id,
                        chunk_ids[fact.chunk_index],
                        fact.statement,
                        fact.statement_hash,
                        "superseded" if self._rag_policy is not None else "active",
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
                        chunk_ids[finding.chunk_index] if finding.chunk_index is not None else None,
                        finding.finding_code,
                        finding.severity,
                        finding.message,
                        json.dumps(dict(finding.details)),
                    ),
                )
            if self._rag_policy is None:
                self._supersede_previous_run_content(connection, lease=lease, claim=claim)
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
                       source_url = CASE WHEN content_hash IS NULL
                         THEN COALESCE(%s, source_url) ELSE source_url END,
                       content_hash = %s,
                       error_code = NULL, error_detail = NULL, updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (
                    result.raw_content,
                    result.resolved_url,
                    content_hash,
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
            rag_job_id = self._enqueue_rag(
                connection,
                lease=lease,
                claim=claim,
                document_id=document_id,
                cleaned_text_hash=result.cleaned_text_hash,
                chunks=result.chunks,
            )
            if rag_job_id is not None:
                details["rag_job_id"] = str(rag_job_id)
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"knowledge-run:{claim.pipeline_run_id}",
                details=details,
            )
        return {"status": "succeeded", "job_id": str(lease.job_id), **details}

    @staticmethod
    def _supersede_previous_run_content(
        connection: Any, *, lease: WorkerLease, claim: ProcessingInput
    ) -> None:
        connection.execute(
            """UPDATE knowledge_fact_candidates fact
                   SET lifecycle_status = 'superseded', updated_at = clock_timestamp()
                 WHERE fact.project_id = %s AND fact.source_id = %s
                   AND fact.pipeline_run_id <> %s AND fact.lifecycle_status = 'active'
                   AND EXISTS (
                     SELECT 1 FROM knowledge_pipeline_runs previous
                     WHERE previous.id = fact.pipeline_run_id
                       AND previous.project_id = fact.project_id
                       AND previous.source_id = fact.source_id
                       AND previous.status = 'succeeded'
                   )""",
            (lease.project_id, claim.source_id, claim.pipeline_run_id),
        )
        connection.execute(
            """UPDATE knowledge_chunks chunk
                   SET status = 'disabled', updated_at = clock_timestamp()
                 WHERE chunk.project_id = %s AND chunk.source_id = %s
                   AND chunk.pipeline_run_id <> %s AND chunk.status = 'active'
                   AND EXISTS (
                     SELECT 1 FROM knowledge_pipeline_runs previous
                     WHERE previous.id = chunk.pipeline_run_id
                       AND previous.project_id = chunk.project_id
                       AND previous.source_id = chunk.source_id
                       AND previous.status = 'succeeded'
                   )""",
            (lease.project_id, claim.source_id, claim.pipeline_run_id),
        )

    def _enqueue_rag(
        self,
        connection: Any,
        *,
        lease: WorkerLease,
        claim: ProcessingInput,
        document_id: Any,
        cleaned_text_hash: str,
        chunks: tuple[Any, ...],
    ) -> Any | None:
        policy = self._rag_policy
        if policy is None:
            return None
        if claim.requested_by is None:
            raise KnowledgeProcessingError("Knowledge RAG enqueue requires its requesting identity")
        input_hash = hashlib.sha256(
            json.dumps(
                {
                    "pipeline_run_id": str(claim.pipeline_run_id),
                    "source_id": str(claim.source_id),
                    "document_id": str(document_id),
                    "cleaned_text_hash": cleaned_text_hash,
                    "chunk_hashes": [item.text_hash for item in chunks],
                    "adapter_release": policy.adapter_release,
                    "selection_manifest_hash": policy.selection_manifest_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        job_id = uuid5(
            NAMESPACE_URL,
            f"geo-knowledge-rag-job:{claim.pipeline_run_id}:{policy.adapter_release}",
        )
        idempotency_key = f"knowledge-rag:{claim.pipeline_run_id}:{policy.adapter_release}"
        connection.execute(
            """INSERT INTO durable_jobs
                 (id, project_id, kind, input_hash, idempotency_key,
                  parent_job_id, max_attempts)
               VALUES (%s, %s, 'knowledge.rag.extract', %s, %s, %s, %s)""",
            (
                job_id,
                lease.project_id,
                input_hash,
                idempotency_key,
                lease.job_id,
                policy.maximum_attempts,
            ),
        )
        connection.execute(
            """INSERT INTO knowledge_rag_job_specs
                 (job_id, project_id, pipeline_run_id, source_id, document_id,
                  configured_model, model_call_budget, adapter_release,
                  selection_manifest_hash, requested_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                job_id,
                lease.project_id,
                claim.pipeline_run_id,
                claim.source_id,
                document_id,
                policy.configured_model,
                len(chunks) * policy.model_calls_per_chunk * policy.maximum_attempts,
                policy.adapter_release,
                policy.selection_manifest_hash,
                claim.requested_by,
            ),
        )
        connection.execute(
            """INSERT INTO broker_outbox
                 (project_id, job_id, topic, payload, idempotency_key)
               VALUES (%s, %s, 'knowledge.rag.extract', %s::jsonb, %s)""",
            (
                lease.project_id,
                job_id,
                json.dumps({"job_id": str(job_id), "project_id": str(lease.project_id)}),
                f"wake:{idempotency_key}",
            ),
        )
        return job_id

    def _fail(self, lease: WorkerLease, error: Exception, *, retry: bool) -> Mapping[str, object]:
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
                status = (
                    "queued" if retry and lease.attempt_count < lease.max_attempts else "failed"
                )
                connection.execute(
                    """UPDATE knowledge_pipeline_runs SET status = %s, error_code = %s,
                           error_detail = %s, completed_at = CASE WHEN %s = 'failed'
                             THEN clock_timestamp() ELSE NULL END,
                           updated_at = clock_timestamp()
                       WHERE id = %s AND project_id = %s
                         AND status IN ('queued', 'running')""",
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
                       WHERE id = %s AND project_id = %s
                         AND status IN ('queued', 'processing', 'ready', 'failed')""",
                    (
                        (
                            "ready"
                            if isinstance(error, KnowledgeSourceRevisionRequired)
                            else "processing"
                            if status == "queued"
                            else "failed"
                        ),
                        type(error).__name__,
                        detail,
                        spec["source_id"],
                        lease.project_id,
                    ),
                )
                if status == "queued":
                    connection.execute(
                        """UPDATE knowledge_pipeline_stages
                           SET status = 'pending', error_detail = %s,
                               started_at = NULL, completed_at = NULL
                           WHERE pipeline_run_id = %s AND project_id = %s
                             AND status = 'running'""",
                        (detail, spec["pipeline_run_id"], lease.project_id),
                    )
                else:
                    connection.execute(
                        """UPDATE knowledge_pipeline_stages
                           SET status = CASE WHEN status = 'running'
                                             THEN 'failed' ELSE 'skipped' END,
                               error_detail = %s, completed_at = clock_timestamp()
                           WHERE pipeline_run_id = %s AND project_id = %s
                             AND status IN ('pending', 'running')""",
                        (detail, spec["pipeline_run_id"], lease.project_id),
                    )
            if retry:
                job_status = self._store.fail_with_retry_in_transaction(
                    connection,
                    lease,
                    error_code=type(error).__name__,
                    details={"message": detail},
                    retry_delay=timedelta(seconds=30),
                )
            else:
                self._store.fail_in_transaction(
                    connection,
                    lease,
                    error_code=type(error).__name__,
                    details={"message": detail},
                )
                job_status = "failed"
            return {"status": job_status, "job_id": str(lease.job_id)}


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((column.name for column in cursor.description), row, strict=True))


def _is_retryable_database_error(error: Exception) -> bool:
    return getattr(error, "sqlstate", None) in {"40001", "40P01"}
