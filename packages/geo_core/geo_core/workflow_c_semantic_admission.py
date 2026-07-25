"""Atomic producer for manifest-backed Workflow C semantic metric Jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from geo_core.project_scope import set_project_scope
from geo_core.semantic_metrics._validation import decimal_value
from geo_core.workflow_c_analysis_admission import (
    AnalysisArtifactKind,
    AnalysisInputManifest,
    AnalysisManifestItem,
    MetricProtocolDefinition,
    WorkflowCAnalysisAdmissionError,
    canonical_hash,
    manifest_id,
    metric_protocol_definition,
)
from geo_core.workflow_c_job_specs import WorkflowCEnqueuedJob


_KIND = "workflow_c.analysis.semantic_metrics"


class PostgresWorkflowCSemanticAdmissionError(WorkflowCAnalysisAdmissionError):
    """A semantic manifest or Job failed server-side admission."""


@dataclass(frozen=True)
class AdmittedSemanticAnalysis:
    manifest: AnalysisInputManifest
    job: WorkflowCEnqueuedJob


class PostgresWorkflowCSemanticAdmissionRepository:
    """Resolve, freeze and enqueue one completed Sampling Run atomically."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock

    def enqueue(
        self,
        *,
        project_id: UUID,
        sampling_run_id: UUID,
        metric_protocol_id: UUID,
        actor_id: str,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> AdmittedSemanticAnalysis:
        actor = _text(actor_id, "semantic analysis actor")
        key = _text(idempotency_key, "semantic analysis Idempotency-Key", maximum=200)
        frozen_at = self._clock()
        if frozen_at.tzinfo is None or frozen_at.utcoffset() is None:
            raise PostgresWorkflowCSemanticAdmissionError(
                "semantic analysis clock must be timezone-aware"
            )
        if max_attempts < 1:
            raise PostgresWorkflowCSemanticAdmissionError(
                "semantic analysis max attempts must be positive"
            )
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            protocol = _load_protocol(
                connection, project_id=project_id, protocol_id=metric_protocol_id
            )
            rows = _load_sampling_rows(
                connection, project_id=project_id, run_id=sampling_run_id
            )
            manifest = _manifest(
                project_id=project_id,
                idempotency_key=key,
                actor_id=actor,
                frozen_at=frozen_at,
                protocol_id=metric_protocol_id,
                protocol_hash=protocol.protocol_hash,
                definition=protocol.definition,
                rows=rows,
            )
            payload = manifest.job_payload()
            spec_hash = canonical_hash(payload)
            job_key = f"workflow-c:semantic:v2:{project_id}:{manifest.id}"
            row = connection.execute(
                """SELECT * FROM geo_enqueue_workflow_c_semantic_metric_job_v2(
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s
                   )""",
                (
                    project_id,
                    manifest.id,
                    manifest.manifest_hash,
                    manifest.sampling_run_id,
                    manifest.sampling_run_version,
                    manifest.sampling_suite_hash,
                    manifest.metric_protocol_id,
                    manifest.metric_protocol_hash,
                    manifest.baseline_snapshot_hash,
                    manifest.source_stratum_hash,
                    manifest.capture_method,
                    manifest.frozen_by,
                    manifest.frozen_at,
                    Jsonb(manifest.canonical_value()),
                    spec_hash,
                    Jsonb(payload),
                    job_key,
                    max_attempts,
                ),
            ).fetchone()
            if row is None:
                raise PostgresWorkflowCSemanticAdmissionError(
                    "semantic analysis admission returned no Job"
                )
            result = _admitted(_mapping(row), project_id=project_id, kind=_KIND)
            if (
                result.manifest_id != manifest.id
                or result.manifest_hash != manifest.manifest_hash
                or result.job.spec_hash != spec_hash
            ):
                raise PostgresWorkflowCSemanticAdmissionError(
                    "semantic analysis admission result changed"
                )
            connection.commit()
            return AdmittedSemanticAnalysis(manifest=manifest, job=result.job)
        except PostgresWorkflowCSemanticAdmissionError:
            connection.rollback()
            raise
        except psycopg.Error as error:
            connection.rollback()
            detail = getattr(error.diag, "message_primary", "") or ""
            if detail.startswith(("Semantic ", "Automated UI ")):
                raise PostgresWorkflowCSemanticAdmissionError(detail) from error
            raise PostgresWorkflowCSemanticAdmissionError(
                "PostgreSQL rejected semantic analysis admission"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


@dataclass(frozen=True)
class _Protocol:
    protocol_hash: str
    definition: MetricProtocolDefinition


@dataclass(frozen=True)
class _AdmissionResult:
    manifest_id: UUID
    manifest_hash: str
    job: WorkflowCEnqueuedJob


def _load_protocol(connection: Any, *, project_id: UUID, protocol_id: UUID) -> _Protocol:
    row = connection.execute(
        """SELECT status, protocol_hash, definition
             FROM workflow_c_metric_protocol_versions
            WHERE project_id = %s AND id = %s""",
        (project_id, protocol_id),
    ).fetchone()
    if row is None or row["status"] != "approved":
        raise PostgresWorkflowCSemanticAdmissionError(
            "an approved Metric Protocol is required"
        )
    definition = metric_protocol_definition(_mapping(row["definition"]))
    protocol_hash = _hash(row["protocol_hash"], "Metric Protocol hash")
    if definition.protocol_hash != protocol_hash:
        raise PostgresWorkflowCSemanticAdmissionError("Metric Protocol hash is corrupt")
    return _Protocol(protocol_hash=protocol_hash, definition=definition)


def _load_sampling_rows(
    connection: Any, *, project_id: UUID, run_id: UUID
) -> tuple[Mapping[str, object], ...]:
    rows = connection.execute(
        """SELECT run.id AS run_id, run.status AS run_status,
                  run.version AS run_version, run.suite_hash,
                  run.reserved_task_count, suite.source_stratum_hash,
                  suite.capture_method, suite.planned_task_count,
                  suite.payload AS suite_payload,
                  task.id AS task_id, task.task_key, task.question_id,
                  task.question_version, task.repetition, task.status AS task_status,
                  observation.id AS observation_id,
                  observation.observation_hash,
                  observation.status AS observation_status,
                  observation.evidence_json,
                  attempt.id AS attempt_id, attempt.status AS attempt_status,
                  attempt.durable_job_id AS source_job_id,
                  attempt.provider_attempt_id, attempt.output_hash,
                  attempt.actual_location_hash,
                  source_job.status AS source_job_status,
                  manual.artifact_manifest_id, manual.artifact_manifest_hash,
                  manual.artifact_content_hash, manual.status AS manual_status
             FROM workflow_c_sampling_runs AS run
             JOIN workflow_c_sampling_suites AS suite
               ON suite.project_id = run.project_id AND suite.id = run.suite_id
             JOIN workflow_c_sampling_tasks AS task
               ON task.project_id = run.project_id AND task.run_id = run.id
             LEFT JOIN workflow_c_sampling_observations AS observation
               ON observation.project_id = task.project_id
              AND observation.task_id = task.id
             LEFT JOIN workflow_c_sampling_attempts AS attempt
               ON attempt.project_id = observation.project_id
              AND attempt.id = observation.attempt_id
             LEFT JOIN durable_jobs AS source_job
               ON source_job.project_id = attempt.project_id
              AND source_job.id = attempt.durable_job_id
             LEFT JOIN workflow_c_sampling_manual_imports AS manual
               ON manual.project_id = attempt.project_id
              AND manual.attempt_id = attempt.id
            WHERE run.project_id = %s AND run.id = %s
            ORDER BY task.task_key""",
        (project_id, run_id),
    ).fetchall()
    values = tuple(_mapping(row) for row in rows)
    if not values:
        raise PostgresWorkflowCSemanticAdmissionError("Sampling Run does not exist")
    return values


def _manifest(
    *,
    project_id: UUID,
    idempotency_key: str,
    actor_id: str,
    frozen_at: datetime,
    protocol_id: UUID,
    protocol_hash: str,
    definition: MetricProtocolDefinition,
    rows: tuple[Mapping[str, object], ...],
) -> AnalysisInputManifest:
    first = rows[0]
    if (
        _text_value(first, "run_status") != "completed"
        or len(rows) != _integer(first, "reserved_task_count")
        or len(rows) != _integer(first, "planned_task_count")
    ):
        raise PostgresWorkflowCSemanticAdmissionError(
            "only a completed Sampling Run with its full denominator is admissible"
        )
    suite_payload = _mapping(first.get("suite_payload"))
    suite = _mapping(suite_payload.get("suite"))
    source = _mapping(suite.get("source_stratum"))
    capture_method = _text_value(first, "capture_method")
    if capture_method == "automated_ui":
        raise PostgresWorkflowCSemanticAdmissionError(
            "Automated UI analysis requires the excluded Board B admission"
        )
    source_hash = _hash(first.get("source_stratum_hash"), "SourceStratum hash")
    suite_hash = _hash(first.get("suite_hash"), "Sampling Suite hash")
    items = tuple(
        _manifest_item(
            ordinal=ordinal,
            row=row,
            definition=definition,
            capture_method=capture_method,
            run_id=_uuid(first.get("run_id"), "Sampling Run id"),
            suite_hash=suite_hash,
            source_hash=source_hash,
        )
        for ordinal, row in enumerate(rows, start=1)
    )
    baseline_hash = (
        canonical_hash(
            [
                {
                    "question_id": item.question_id,
                    "score": decimal_value(item.score),
                    "snapshot_hash": item.snapshot_hash,
                }
                for item in definition.baseline_question_scores
            ]
        )
        if definition.baseline_question_scores
        else None
    )
    stratum = (
        ("provider", _source_text(source, "platform")),
        ("reported_model", _source_text(source, "reported_model")),
        ("capture_method", capture_method),
        ("locale", _source_text(source, "locale")),
        ("region", _source_text(source, "region")),
        ("source_composition_hash", suite_hash),
        ("sampling_source_stratum_hash", source_hash),
        ("question_cluster", "all"),
    )
    return AnalysisInputManifest(
        id=manifest_id(project_id, idempotency_key),
        project_id=project_id,
        sampling_run_id=_uuid(first.get("run_id"), "Sampling Run id"),
        sampling_run_version=_integer(first, "run_version"),
        sampling_suite_hash=suite_hash,
        metric_protocol_id=protocol_id,
        metric_protocol_hash=protocol_hash,
        fact_snapshot_id=definition.fact_snapshot_id,
        fact_snapshot_hash=definition.fact_snapshot_hash,
        prompt_release_id=definition.prompt_release_id,
        prompt_release_hash=definition.prompt_release_hash,
        corpus_version_id=definition.corpus_version_id,
        corpus_version_hash=definition.corpus_version_hash,
        baseline_snapshot_hash=baseline_hash,
        source_stratum_hash=source_hash,
        capture_method=capture_method,
        stratum=stratum,
        items=items,
        frozen_by=actor_id,
        frozen_at=frozen_at,
    )


def _manifest_item(
    *,
    ordinal: int,
    row: Mapping[str, object],
    definition: MetricProtocolDefinition,
    capture_method: str,
    run_id: UUID,
    suite_hash: str,
    source_hash: str,
) -> AnalysisManifestItem:
    if (
        _uuid(row.get("run_id"), "Sampling Run id") != run_id
        or _hash(row.get("suite_hash"), "Sampling Suite hash") != suite_hash
        or _hash(row.get("source_stratum_hash"), "SourceStratum hash") != source_hash
        or _text_value(row, "task_status") != "succeeded"
        or _text_value(row, "attempt_status") != "succeeded"
        or _text_value(row, "source_job_status") != "succeeded"
    ):
        raise PostgresWorkflowCSemanticAdmissionError(
            "Sampling member is not a successful immutable Observation"
        )
    evidence = _mapping(row.get("evidence_json"))
    derived = _mapping(evidence.get("derived_artifact"))
    if capture_method in {"provider_api", "proxy_grounded_api"}:
        if evidence.get("storage_decision") != "allowed" or (
            evidence.get("usage_audience") != "internal_worker"
        ):
            raise PostgresWorkflowCSemanticAdmissionError(
                "Provider Observation artifact is not recoverable for analysis"
            )
        artifact_kind = AnalysisArtifactKind.PROVIDER
        provider_attempt_id = _uuid(
            row.get("provider_attempt_id"), "Provider model Attempt id"
        )
        output_hash = _hash(row.get("output_hash"), "Provider output hash")
        artifact_id = None
    elif capture_method == "manual_ui":
        if _text_value(row, "manual_status") != "committed":
            raise PostgresWorkflowCSemanticAdmissionError(
                "Manual Observation artifact is not committed"
            )
        artifact_kind = AnalysisArtifactKind.MANUAL
        provider_attempt_id = None
        output_hash = None
        artifact_id = _uuid(row.get("artifact_manifest_id"), "manual artifact id")
    else:
        raise PostgresWorkflowCSemanticAdmissionError(
            "Sampling capture method is not admissible for local analysis"
        )
    question_id = _text_value(row, "question_id")
    manifest_hash = _hash(
        row.get("artifact_manifest_hash")
        if artifact_kind is AnalysisArtifactKind.MANUAL
        else derived.get("manifest_hash"),
        "analysis artifact manifest hash",
    )
    content_hash = _hash(
        row.get("artifact_content_hash")
        if artifact_kind is AnalysisArtifactKind.MANUAL
        else derived.get("content_hash"),
        "analysis artifact content hash",
    )
    return AnalysisManifestItem(
        ordinal=ordinal,
        task_id=_uuid(row.get("task_id"), "Sampling Task id"),
        task_key=_hash(row.get("task_key"), "Sampling Task key"),
        question_id=question_id,
        question_version=_text_value(row, "question_version"),
        question_cluster=definition.cluster_for(question_id),
        repetition=_integer(row, "repetition"),
        observation_id=_uuid(row.get("observation_id"), "Observation id"),
        observation_hash=_hash(row.get("observation_hash"), "Observation hash"),
        observation_status=_text_value(row, "observation_status"),
        attempt_id=_uuid(row.get("attempt_id"), "Sampling Attempt id"),
        source_job_id=_uuid(row.get("source_job_id"), "source Job id"),
        provider_model_attempt_id=provider_attempt_id,
        output_hash=output_hash,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
        artifact_manifest_hash=manifest_hash,
        artifact_content_hash=content_hash,
        actual_location_hash=_hash(
            row.get("actual_location_hash"), "actual location hash"
        ),
    )


def _admitted(
    row: Mapping[str, object], *, project_id: UUID, kind: str
) -> _AdmissionResult:
    spec_hash = _hash(row.get("input_hash"), "semantic Job input hash")
    return _AdmissionResult(
        manifest_id=_uuid(row.get("manifest_id"), "analysis manifest id"),
        manifest_hash=_hash(row.get("manifest_hash"), "analysis manifest hash"),
        job=WorkflowCEnqueuedJob(
            project_id=project_id,
            job_id=_uuid(row.get("job_id"), "semantic Job id"),
            kind=kind,
            spec_hash=spec_hash,
            replayed=_boolean(row.get("replayed"), "semantic Job replay marker"),
        ),
    )


def _mapping(value: object | None) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise PostgresWorkflowCSemanticAdmissionError("semantic analysis row is malformed")


def _uuid(value: object | None, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresWorkflowCSemanticAdmissionError(f"{label} is malformed") from error


def _integer(row: Mapping[str, object], field: str) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresWorkflowCSemanticAdmissionError(f"{field} is malformed")
    try:
        return int(value)
    except ValueError as error:
        raise PostgresWorkflowCSemanticAdmissionError(f"{field} is malformed") from error


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise PostgresWorkflowCSemanticAdmissionError(f"{label} is malformed")
    return value


def _hash(value: object | None, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        item not in "0123456789abcdef" for item in value
    ):
        raise PostgresWorkflowCSemanticAdmissionError(f"{label} is malformed")
    return value


def _text(value: str, label: str, *, maximum: int = 500) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise PostgresWorkflowCSemanticAdmissionError(f"{label} is invalid")
    return normalized


def _text_value(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str):
        raise PostgresWorkflowCSemanticAdmissionError(f"{field} is malformed")
    return _text(value, field, maximum=2_000)


def _source_text(row: Mapping[str, object], field: str) -> str:
    return _text_value(row, field)


__all__ = [
    "AdmittedSemanticAnalysis",
    "PostgresWorkflowCSemanticAdmissionError",
    "PostgresWorkflowCSemanticAdmissionRepository",
]
