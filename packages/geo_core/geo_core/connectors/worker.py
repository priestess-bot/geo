"""Fenced Connector sync Worker operation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hmac
from typing import Any, Protocol
from uuid import UUID

from geo_core.connectors.contracts import ConnectorKind, ConnectorSyncPlan
from geo_core.connectors.jobs import CONNECTOR_SYNC_JOB_KIND, ConnectorJobSpec
from geo_core.connectors.postgres import PostgresConnectorRepository
from geo_core.connectors.runtime import (
    ConnectorSource,
    ConnectorSyncExecutor,
    EncryptedConnectorArtifactWriter,
)
from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.project_scope import set_project_scope


class ConnectorWorkerError(RuntimeError):
    """A claimed Connector Job differs from its immutable source state."""


class ConnectorCredentialResolver(Protocol):
    def resolve(
        self,
        *,
        project_id: UUID,
        reference_id: UUID,
        purpose: str,
        version: int,
    ) -> Mapping[str, object]: ...


class ConnectorSourceBuilder(Protocol):
    def __call__(
        self,
        state: "ConnectorExecutionState",
        credential: Mapping[str, object],
    ) -> ConnectorSource: ...


@dataclass(frozen=True)
class ConnectorExecutionState:
    spec: ConnectorJobSpec
    plan: ConnectorSyncPlan
    run_version: int
    connector_kind: ConnectorKind
    secret_reference_id: UUID
    secret_purpose: str
    secret_version: int
    source_locator: str
    streams: tuple[str, ...]
    report_spec: Mapping[str, object]
    date_policy: Mapping[str, object]
    projection_kind: str


class PostgresConnectorWorkerRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def load_and_start(self, lease: WorkerLease, *, started_at: datetime) -> ConnectorExecutionState:
        if lease.kind != CONNECTOR_SYNC_JOB_KIND:
            raise ConnectorWorkerError("Connector Worker received the wrong Job kind")
        with self._connect() as connection:
            set_project_scope(connection, lease.project_id)
            row = connection.execute(
                """SELECT spec.spec_hash, spec.spec_payload,
                          run.*, definition.kind AS connector_kind,
                          connection.secret_reference_id, connection.secret_purpose,
                          connection.secret_version, connection.status AS connection_status,
                          scope.source_locator, scope.streams, scope.report_spec, scope.date_policy,
                          scope.status AS scope_status, durable.input_hash
                     FROM connector_job_specs spec
                     JOIN durable_jobs durable
                       ON durable.project_id = spec.project_id AND durable.id = spec.job_id
                     JOIN connector_sync_runs run
                       ON run.project_id = spec.project_id AND run.id = spec.run_id
                     JOIN connector_definitions definition
                       ON definition.project_id = run.project_id
                      AND definition.id = run.definition_id
                     JOIN connector_connections connection
                       ON connection.project_id = run.project_id
                      AND connection.id = run.connection_id
                     JOIN connector_scopes scope
                       ON scope.project_id = run.project_id AND scope.id = run.scope_id
                    WHERE spec.project_id = %s AND spec.job_id = %s
                    FOR UPDATE OF run""",
                (lease.project_id, lease.job_id),
            ).fetchone()
            if row is None:
                raise ConnectorWorkerError("Connector Job spec was not found")
            spec = _parse_spec(row["spec_payload"])
            if (
                spec.project_id != lease.project_id
                or row["durable_job_id"] != lease.job_id
                or not hmac.compare_digest(row["spec_hash"], row["input_hash"])
                or not hmac.compare_digest(row["spec_hash"], spec.spec_hash)
            ):
                raise ConnectorWorkerError("Connector Job/spec/Run identity changed")
            if row["connection_status"] != "active" or row["scope_status"] != "active":
                raise ConnectorWorkerError("Connector Connection or Scope is disabled")
            if row["status"] == "queued":
                updated = connection.execute(
                    """UPDATE connector_sync_runs
                          SET status = 'running', version = version + 1, started_at = %s
                        WHERE project_id = %s AND id = %s AND status = 'queued'
                          AND version = %s
                    RETURNING version""",
                    (started_at, lease.project_id, row["id"], spec.expected_run_version + 1),
                ).fetchone()
                if updated is None:
                    raise ConnectorWorkerError("Connector Run start was fenced")
                run_version = updated["version"]
            elif row["status"] == "running" and row["version"] >= spec.expected_run_version + 2:
                run_version = row["version"]
            else:
                raise ConnectorWorkerError("Connector Run is not executable")
            plan = ConnectorSyncPlan(
                project_id=lease.project_id,
                definition_id=row["definition_id"],
                connection_id=row["connection_id"],
                scope_id=row["scope_id"],
                mode=row["mode"],
                adapter_release=row["adapter_release"],
                input_checkpoint_id=row["input_checkpoint_id"],
                input_checkpoint_hash=row["input_checkpoint_hash"],
                window_start=row["window_start"],
                window_end=row["window_end"],
                requested_by=row["requested_by"],
                requested_at=row["requested_at"],
            )
            if not hmac.compare_digest(plan.plan_hash, spec.plan_hash):
                raise ConnectorWorkerError("Connector Run no longer matches its plan hash")
            streams = row["streams"]
            if not isinstance(streams, list) or any(not isinstance(item, str) for item in streams):
                raise ConnectorWorkerError("Connector Scope streams are invalid")
            return ConnectorExecutionState(
                spec=spec,
                plan=plan,
                run_version=run_version,
                connector_kind=ConnectorKind(row["connector_kind"]),
                secret_reference_id=row["secret_reference_id"],
                secret_purpose=row["secret_purpose"],
                secret_version=row["secret_version"],
                source_locator=row["source_locator"],
                streams=tuple(streams),
                report_spec=dict(row["report_spec"]),
                date_policy=dict(row["date_policy"]),
                projection_kind=_projection_kind(ConnectorKind(row["connector_kind"])),
            )


class ConnectorSyncOperation:
    kind = CONNECTOR_SYNC_JOB_KIND

    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        worker_repository: PostgresConnectorWorkerRepository,
        connector_repository: PostgresConnectorRepository,
        credentials: ConnectorCredentialResolver,
        sources: ConnectorSourceBuilder,
        artifacts: EncryptedConnectorArtifactWriter,
        lease_for: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if lease_for <= timedelta(0):
            raise ValueError("Connector Job lease duration must be positive")
        self._store = store
        self._worker_repository = worker_repository
        self._connector_repository = connector_repository
        self._credentials = credentials
        self._sources = sources
        self._artifacts = artifacts
        self._lease_for = lease_for
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        state = self._worker_repository.load_and_start(lease, started_at=self._clock())
        self._checkpoint(lease)
        credential = self._credentials.resolve(
            project_id=lease.project_id,
            reference_id=state.secret_reference_id,
            purpose=state.secret_purpose,
            version=state.secret_version,
        )
        self._checkpoint(lease)
        executor = ConnectorSyncExecutor(
            repository=self._connector_repository,
            source=self._sources(state, credential),
            artifacts=self._artifacts,
            checkpoint=lambda: self._checkpoint(lease),
            clock=self._clock,
        )
        commit = executor.prepare(
            plan=state.plan,
            run_id=state.spec.run_id,
            expected_run_version=state.run_version,
            projection_kind=state.projection_kind,
            expected_watermark=state.plan.window_end,
        )
        with self._store.fenced_transaction(lease) as connection:
            result = self._connector_repository.commit_success(
                commit, finished_at=self._clock(), connection=connection
            )
            self._store.complete_in_transaction(
                connection,
                lease,
                result_ref=f"connector-sync:{result.run_id}",
                details={
                    "run_id": str(result.run_id),
                    "checkpoint_id": str(result.checkpoint_id),
                    "projection_batch_id": str(result.projection_batch_id),
                },
            )
        return {
            "status": "succeeded",
            "run_id": str(result.run_id),
            "checkpoint_id": str(result.checkpoint_id),
            "projection_batch_id": str(result.projection_batch_id),
        }

    def _checkpoint(self, lease: WorkerLease) -> None:
        self._store.heartbeat(lease, lease_for=self._lease_for)


def _parse_spec(value: object) -> ConnectorJobSpec:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "kind",
        "project_id",
        "run_id",
        "expected_run_version",
        "plan_hash",
    }:
        raise ConnectorWorkerError("Connector Job spec payload is invalid")
    try:
        if value["schema_version"] != 1 or value["kind"] != CONNECTOR_SYNC_JOB_KIND:
            raise ValueError
        return ConnectorJobSpec(
            project_id=UUID(str(value["project_id"])),
            run_id=UUID(str(value["run_id"])),
            expected_run_version=int(str(value["expected_run_version"])),
            plan_hash=str(value["plan_hash"]),
        )
    except (ValueError, TypeError) as error:
        raise ConnectorWorkerError("Connector Job spec payload is invalid") from error


def _projection_kind(kind: ConnectorKind) -> str:
    return {
        ConnectorKind.GOOGLE_SEARCH_CONSOLE: "gsc.search_analytics.v1",
        ConnectorKind.GOOGLE_ANALYTICS_4: "ga4.aggregate_report.v1",
        ConnectorKind.GOOGLE_OFFICIAL_REPORT: "google.official_report.v1",
        ConnectorKind.BING_OFFICIAL_REPORT: "bing.official_report.v1",
    }[kind]


__all__ = [
    "ConnectorCredentialResolver",
    "ConnectorExecutionState",
    "ConnectorSourceBuilder",
    "ConnectorSyncOperation",
    "ConnectorWorkerError",
    "PostgresConnectorWorkerRepository",
]
