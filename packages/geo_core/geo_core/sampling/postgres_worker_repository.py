"""Project-scoped PostgreSQL reads and fenced writes for Workflow C sampling."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.project_scope import set_project_scope
from geo_core.sampling.postgres_worker_contracts import (
    ManualSamplingCommit,
    ManualSamplingWorkerSpec,
    ProviderSamplingCommit,
    ProviderSamplingWorkerSpec,
    SamplingWorkerSource,
    parse_sampling_worker_source,
)


class WorkflowCSamplingWorkerError(RuntimeError):
    """Persistent sampling state cannot be safely executed or finalized."""


@dataclass(frozen=True)
class SamplingExecutionState:
    project_id: UUID
    run_id: UUID
    task_id: UUID
    attempt_id: UUID
    durable_job_id: UUID
    task_key: str
    question_id: str
    question_version: str
    task_version: int
    attempt_version: int
    source: SamplingWorkerSource
    run_purpose: str


@dataclass(frozen=True)
class ManualSamplingExecutionState:
    sampling: SamplingExecutionState
    manual_import_id: UUID
    artifact_manifest_id: UUID
    artifact_manifest_hash: str
    artifact_content_hash: str
    governance_policy_hash: str
    capture_session_id: UUID
    manifest_uri: str
    evidence_kind: str
    persisted_content_type: str


class PostgresWorkflowCSamplingRepository:
    """Read Project-scoped inputs and finalize only through fenced SQL RPCs."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def provider_state(
        self, *, project_id: UUID, spec: ProviderSamplingWorkerSpec
    ) -> SamplingExecutionState:
        row = self._sampling_row(
            project_id=project_id,
            run_id=spec.run_id,
            task_id=spec.task_id,
            attempt_id=spec.attempt_id,
        )
        state = sampling_execution_state(row, project_id=project_id)
        assert_provider_state(state, row, spec)
        return state

    def manual_state(
        self, *, project_id: UUID, spec: ManualSamplingWorkerSpec
    ) -> ManualSamplingExecutionState:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT run.id AS run_id, run.status AS run_status, run.purpose,
                          task.id AS task_id, task.task_key, task.question_id,
                          task.question_version, task.status AS task_status,
                          task.version AS task_version,
                          attempt.id AS attempt_id, attempt.durable_job_id,
                          attempt.status AS attempt_status,
                          attempt.version AS attempt_version,
                          suite.payload AS suite_payload,
                          manual.id AS manual_import_id,
                          manual.status AS manual_status,
                          manual.artifact_manifest_id,
                          manual.artifact_manifest_hash AS manual_artifact_manifest_hash,
                          manual.artifact_content_hash AS manual_artifact_content_hash,
                          manual.governance_policy_hash AS manual_governance_policy_hash,
                          manual.capture_session_id AS manual_capture_session_id,
                          artifact.status AS artifact_status,
                          artifact.manifest_uri, artifact.evidence_kind,
                          artifact.persisted_content_type,
                          artifact.expires_at,
                          artifact.redacted_content_hash,
                          artifact.manifest_hash AS artifact_manifest_hash,
                          artifact.governance_policy_hash AS artifact_governance_policy_hash,
                          artifact.capture_session_id AS artifact_capture_session_id
                     FROM workflow_c_sampling_manual_imports AS manual
                     JOIN workflow_c_sampling_attempts AS attempt
                       ON attempt.project_id = manual.project_id
                      AND attempt.id = manual.attempt_id
                     JOIN workflow_c_sampling_tasks AS task
                       ON task.project_id = attempt.project_id AND task.id = attempt.task_id
                     JOIN workflow_c_sampling_runs AS run
                       ON run.project_id = task.project_id AND run.id = task.run_id
                     JOIN workflow_c_sampling_suites AS suite
                       ON suite.project_id = run.project_id AND suite.id = run.suite_id
                     JOIN workflow_c_manual_artifacts AS artifact
                       ON artifact.project_id = manual.project_id
                      AND artifact.artifact_id = manual.artifact_manifest_id
                    WHERE manual.project_id = %s AND manual.id = %s
                      AND manual.run_id = %s AND manual.task_id = %s
                      AND manual.attempt_id = %s""",
                (
                    project_id,
                    spec.manual_import_id,
                    spec.run_id,
                    spec.task_id,
                    spec.attempt_id,
                ),
            ).fetchone()
            connection.rollback()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        if row is None:
            raise WorkflowCSamplingWorkerError("manual sampling lineage does not exist")
        values = row_mapping(row)
        state = sampling_execution_state(values, project_id=project_id)
        assert_manual_state(state, values, spec)
        return ManualSamplingExecutionState(
            sampling=state,
            manual_import_id=uuid_field(values, "manual_import_id"),
            artifact_manifest_id=uuid_field(values, "artifact_manifest_id"),
            artifact_manifest_hash=hash_field(values, "artifact_manifest_hash"),
            artifact_content_hash=hash_field(values, "manual_artifact_content_hash"),
            governance_policy_hash=hash_field(values, "manual_governance_policy_hash"),
            capture_session_id=uuid_field(values, "manual_capture_session_id"),
            manifest_uri=text_field(values, "manifest_uri"),
            evidence_kind=text_field(values, "evidence_kind"),
            persisted_content_type=text_field(values, "persisted_content_type"),
        )

    def commit_provider(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        spec_hash: str,
        state: SamplingExecutionState,
        spec: ProviderSamplingWorkerSpec,
        commit: ProviderSamplingCommit,
    ) -> None:
        row = connection.execute(
            """SELECT * FROM geo_commit_workflow_c_provider_sampling(
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s, %s
               )""",
            (
                lease.project_id,
                lease.job_id,
                lease.lease_token,
                lease.fencing_generation,
                spec_hash,
                state.run_id,
                state.task_id,
                state.attempt_id,
                spec.task_version,
                spec.attempt_version,
                commit.observation_id,
                commit.observation_hash,
                commit.evidence_status,
                json.dumps(list(commit.ineligible_reasons), sort_keys=True),
                json.dumps(dict(commit.actual_location), sort_keys=True),
                commit.actual_location_hash,
                json.dumps(dict(commit.evidence), sort_keys=True),
                commit.provider_attempt_id,
                commit.provider_response_hash,
                commit.output_hash,
                commit.observed_at,
            ),
        ).fetchone()
        assert_commit_row(row, commit.observation_id)

    def commit_manual(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        spec_hash: str,
        state: ManualSamplingExecutionState,
        spec: ManualSamplingWorkerSpec,
        commit: ManualSamplingCommit,
    ) -> None:
        row = connection.execute(
            """SELECT * FROM geo_commit_workflow_c_manual_sampling(
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s
               )""",
            (
                lease.project_id,
                lease.job_id,
                lease.lease_token,
                lease.fencing_generation,
                spec_hash,
                state.sampling.run_id,
                state.sampling.task_id,
                state.sampling.attempt_id,
                spec.task_version,
                spec.attempt_version,
                state.manual_import_id,
                state.artifact_manifest_id,
                state.artifact_manifest_hash,
                state.artifact_content_hash,
                state.governance_policy_hash,
                state.capture_session_id,
                commit.observation_id,
                commit.observation_hash,
                "complete",
                json.dumps([], sort_keys=True),
                json.dumps(dict(commit.actual_location), sort_keys=True),
                commit.actual_location_hash,
                json.dumps(dict(commit.evidence), sort_keys=True),
                commit.observed_at,
            ),
        ).fetchone()
        assert_commit_row(row, commit.observation_id)

    def record_failure(
        self,
        *,
        connection: Any,
        lease: WorkerLease,
        spec_hash: str,
        state: SamplingExecutionState,
        task_version: int,
        attempt_version: int,
        error_code: str,
        retryable: bool,
        occurred_at: datetime,
    ) -> None:
        row = connection.execute(
            """SELECT * FROM geo_record_workflow_c_sampling_failure(
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
               )""",
            (
                lease.project_id,
                lease.job_id,
                lease.lease_token,
                lease.fencing_generation,
                spec_hash,
                state.run_id,
                state.task_id,
                state.attempt_id,
                task_version,
                attempt_version,
                error_code,
                retryable,
                occurred_at,
            ),
        ).fetchone()
        if row is None:
            raise WorkflowCSamplingWorkerError("sampling failure was not fenced")

    def _sampling_row(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
    ) -> Mapping[str, object]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT run.id AS run_id, run.status AS run_status, run.purpose,
                          task.id AS task_id, task.task_key, task.question_id,
                          task.question_version, task.status AS task_status,
                          task.version AS task_version,
                          attempt.id AS attempt_id, attempt.durable_job_id,
                          attempt.status AS attempt_status,
                          attempt.version AS attempt_version,
                          suite.payload AS suite_payload
                     FROM workflow_c_sampling_attempts AS attempt
                     JOIN workflow_c_sampling_tasks AS task
                       ON task.project_id = attempt.project_id AND task.id = attempt.task_id
                     JOIN workflow_c_sampling_runs AS run
                       ON run.project_id = task.project_id AND run.id = task.run_id
                     JOIN workflow_c_sampling_suites AS suite
                       ON suite.project_id = run.project_id AND suite.id = run.suite_id
                    WHERE attempt.project_id = %s AND attempt.id = %s
                      AND attempt.run_id = %s AND attempt.task_id = %s""",
                (project_id, attempt_id, run_id, task_id),
            ).fetchone()
            connection.rollback()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        if row is None:
            raise WorkflowCSamplingWorkerError("provider sampling lineage does not exist")
        return row_mapping(row)


def sampling_execution_state(
    row: Mapping[str, object], *, project_id: UUID
) -> SamplingExecutionState:
    return SamplingExecutionState(
        project_id=project_id,
        run_id=uuid_field(row, "run_id"),
        task_id=uuid_field(row, "task_id"),
        attempt_id=uuid_field(row, "attempt_id"),
        durable_job_id=uuid_field(row, "durable_job_id"),
        task_key=hash_field(row, "task_key"),
        question_id=text_field(row, "question_id"),
        question_version=text_field(row, "question_version"),
        task_version=positive_field(row, "task_version"),
        attempt_version=positive_field(row, "attempt_version"),
        source=parse_sampling_worker_source(row.get("suite_payload")),
        run_purpose=text_field(row, "purpose"),
    )


def assert_provider_state(
    state: SamplingExecutionState,
    row: Mapping[str, object],
    spec: ProviderSamplingWorkerSpec,
) -> None:
    if (
        state.task_version < spec.task_version
        or state.attempt_version < spec.attempt_version
        or row.get("run_status") != "running"
        or row.get("task_status") not in {"queued", "running", "retry_ready"}
        or row.get("attempt_status") not in {"queued", "running"}
        or state.source.source.capture_method.value not in {"provider_api", "proxy_grounded_api"}
        or state.run_purpose != spec.prompt.purpose
    ):
        raise WorkflowCSamplingWorkerError("provider sampling state is not executable")


def assert_manual_state(
    state: SamplingExecutionState,
    row: Mapping[str, object],
    spec: ManualSamplingWorkerSpec,
) -> None:
    expected = (
        uuid_field(row, "manual_import_id") == spec.manual_import_id,
        uuid_field(row, "artifact_manifest_id") == spec.artifact_manifest_id,
        hash_field(row, "manual_artifact_manifest_hash") == spec.artifact_manifest_hash,
        hash_field(row, "manual_artifact_content_hash") == spec.artifact_content_hash,
        hash_field(row, "manual_governance_policy_hash") == spec.governance_policy_hash,
        uuid_field(row, "manual_capture_session_id") == spec.capture_session_id,
        hash_field(row, "redacted_content_hash") == spec.artifact_content_hash,
        hash_field(row, "artifact_manifest_hash") == spec.artifact_manifest_hash,
        hash_field(row, "artifact_governance_policy_hash") == spec.governance_policy_hash,
        uuid_field(row, "artifact_capture_session_id") == spec.capture_session_id,
        state.task_version == spec.task_version,
        state.attempt_version == spec.attempt_version,
        row.get("run_status") == "running",
        row.get("task_status") in {"queued", "running"},
        row.get("attempt_status") in {"queued", "running"},
        row.get("manual_status") == "approved",
        row.get("artifact_status") == "active",
        state.source.source.capture_method.value == "manual_ui",
    )
    if not all(expected):
        raise WorkflowCSamplingWorkerError("manual sampling state is not executable")


def assert_commit_row(row: Any, observation_id: UUID) -> None:
    if row is None:
        raise WorkflowCSamplingWorkerError("sampling completion was not fenced")
    returned = row_mapping(row).get("observation_id")
    if returned is not None and returned != observation_id:
        raise WorkflowCSamplingWorkerError("sampling completion identity changed")


def row_mapping(row: Any) -> Mapping[str, object]:
    if not isinstance(row, Mapping):
        raise WorkflowCSamplingWorkerError("Workflow C PostgreSQL row is invalid")
    return dict(row)


def uuid_field(row: Mapping[str, object], name: str) -> UUID:
    value = row.get(name)
    if not isinstance(value, UUID) or value.int == 0:
        raise WorkflowCSamplingWorkerError(f"Workflow C {name} is invalid")
    return value


def hash_field(row: Mapping[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or len(value) != 64:
        raise WorkflowCSamplingWorkerError(f"Workflow C {name} is invalid")
    return value


def text_field(row: Mapping[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise WorkflowCSamplingWorkerError(f"Workflow C {name} is invalid")
    return value.strip()


def positive_field(row: Mapping[str, object], name: str) -> int:
    value = row.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkflowCSamplingWorkerError(f"Workflow C {name} is invalid")
    return value


__all__ = [
    "ManualSamplingExecutionState",
    "PostgresWorkflowCSamplingRepository",
    "SamplingExecutionState",
    "WorkflowCSamplingWorkerError",
]
