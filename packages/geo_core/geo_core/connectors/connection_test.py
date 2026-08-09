"""Fenced execution of a Connector connection check without syncing data."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hmac
import re
from typing import Any, Protocol
from uuid import UUID

from geo_core.connectors.contracts import ConnectorKind, canonical_hash
from geo_core.connectors.worker import ConnectorCredentialResolver, ConnectorWorkerError
from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.project_scope import set_project_scope


CONNECTOR_CONNECTION_TEST_JOB_KIND = "connector.connection_test"


class CheckableConnectorSource(Protocol):
    def check_connection(self) -> None: ...


class ConnectionTestSourceBuilder(Protocol):
    def __call__(
        self, *, connector_kind: ConnectorKind, adapter_release: str,
        credential: Mapping[str, object], source_locator: str,
        streams: Sequence[str], report_spec: Mapping[str, object],
        date_policy: Mapping[str, object]
    ) -> CheckableConnectorSource: ...


@dataclass(frozen=True)
class ConnectorConnectionTestScope:
    """The non-secret Scope identity frozen into a connection-test Job."""

    id: UUID
    version: int
    scope_hash: str
    source_locator: str
    streams: tuple[str, ...]
    report_spec: Mapping[str, object]
    date_policy: Mapping[str, object]


@dataclass(frozen=True)
class ConnectorConnectionTestState:
    test_id: UUID
    test_version: int
    connector_kind: ConnectorKind
    adapter_release: str
    secret_reference_id: UUID
    secret_purpose: str
    secret_version: int
    scopes: tuple[ConnectorConnectionTestScope, ...]


class PostgresConnectorConnectionTestRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def job_kind(self, *, project_id: UUID, job_id: UUID) -> str:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                "SELECT kind FROM durable_jobs WHERE project_id = %s AND id = %s",
                (project_id, job_id),
            ).fetchone()
        if row is None or not isinstance(row["kind"], str):
            raise ConnectorWorkerError("Connector Durable Job was not found")
        return row["kind"]

    def load_and_start(
        self, lease: WorkerLease, *, started_at: datetime
    ) -> ConnectorConnectionTestState:
        if lease.kind != CONNECTOR_CONNECTION_TEST_JOB_KIND:
            raise ConnectorWorkerError("Connector Worker received the wrong test Job kind")
        with self._connect() as connection:
            set_project_scope(connection, lease.project_id)
            row = connection.execute(
                """SELECT test.*, spec.spec_hash, spec.spec_payload,
                          durable.input_hash, definition.kind AS connector_kind,
                          connection.status AS connection_status,
                          connection.version AS connection_version,
                          definition.status AS definition_status
                     FROM connector_connection_test_specs spec
                     JOIN durable_jobs durable
                       ON durable.project_id = spec.project_id AND durable.id = spec.job_id
                     JOIN connector_connection_tests test
                       ON test.project_id = spec.project_id AND test.id = spec.test_id
                     JOIN connector_connections connection
                       ON connection.project_id = test.project_id
                      AND connection.id = test.connection_id
                     JOIN connector_definitions definition
                       ON definition.project_id = test.project_id
                      AND definition.id = test.definition_id
                    WHERE spec.project_id = %s AND spec.job_id = %s
                    FOR UPDATE OF test""",
                (lease.project_id, lease.job_id),
            ).fetchone()
            if row is None:
                raise ConnectorWorkerError("Connector connection test spec was not found")
            payload = row["spec_payload"]
            if not isinstance(payload, Mapping) or (
                payload.get("schema_version") != 2
                or set(payload) != {
                    "schema_version", "kind", "project_id", "test_id",
                    "connection_id", "connection_version", "definition_id",
                    "connector_kind", "adapter_release", "secret_reference_id",
                    "secret_purpose", "secret_version", "scopes",
                }
                or not _scope_payload_is_valid(payload.get("scopes"))
                or payload.get("kind") != CONNECTOR_CONNECTION_TEST_JOB_KIND
                or str(payload.get("project_id")) != str(lease.project_id)
                or str(payload.get("test_id")) != str(row["id"])
                or str(payload.get("connection_id")) != str(row["connection_id"])
                or int(payload.get("connection_version", 0)) != row["connection_version"]
                or str(payload.get("adapter_release")) != row["adapter_release"]
                or str(payload.get("secret_reference_id")) != str(row["secret_reference_id"])
                or str(payload.get("secret_purpose")) != row["secret_purpose"]
                or int(payload.get("secret_version", 0)) != row["secret_version"]
                or not hmac.compare_digest(row["spec_hash"], row["input_hash"])
            ):
                raise ConnectorWorkerError("Connector connection test frozen identity changed")
            scopes = _parse_scopes(payload["scopes"])
            scope_rows = connection.execute(
                """SELECT id, connection_id, version, scope_hash, source_locator,
                          streams, report_spec, date_policy
                     FROM connector_scopes
                    WHERE project_id = %s AND connection_id = %s
                      AND status = 'active' AND id = ANY(%s::uuid[])
                    FOR SHARE""",
                (lease.project_id, row["connection_id"], [scope.id for scope in scopes]),
            ).fetchall()
            actual_scopes = {scope_row["id"]: scope_row for scope_row in scope_rows}
            if len(actual_scopes) != len(scopes) or any(
                not _scope_matches(scope, actual_scopes.get(scope.id)) for scope in scopes
            ):
                raise ConnectorWorkerError("Connector connection-test Scope changed or is disabled")
            if row["connection_status"] != "active" or row["definition_status"] != "approved":
                raise ConnectorWorkerError("Connector Connection or Definition is disabled")
            if row["status"] == "queued":
                updated = connection.execute(
                    """UPDATE connector_connection_tests
                          SET status = 'running', version = version + 1, started_at = %s
                        WHERE project_id = %s AND id = %s AND status = 'queued'
                          AND version = %s RETURNING version""",
                    (started_at, lease.project_id, row["id"], row["version"]),
                ).fetchone()
                if updated is None:
                    raise ConnectorWorkerError("Connector connection test start was fenced")
                version = updated["version"]
            elif row["status"] == "running":
                version = row["version"]
            else:
                raise ConnectorWorkerError("Connector connection test is not executable")
            return ConnectorConnectionTestState(
                test_id=row["id"], test_version=version,
                connector_kind=ConnectorKind(row["connector_kind"]),
                adapter_release=row["adapter_release"],
                secret_reference_id=row["secret_reference_id"],
                secret_purpose=row["secret_purpose"], secret_version=row["secret_version"],
                scopes=scopes,
            )


class ConnectorConnectionTestOperation:
    kind = CONNECTOR_CONNECTION_TEST_JOB_KIND

    def __init__(
        self, *, store: PostgresDurableJobStore,
        repository: PostgresConnectorConnectionTestRepository,
        credentials: ConnectorCredentialResolver, sources: ConnectionTestSourceBuilder,
        lease_for: timedelta, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._repository = repository
        self._credentials = credentials
        self._sources = sources
        self._lease_for = lease_for
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        state = self._repository.load_and_start(lease, started_at=self._clock())
        self._store.heartbeat(lease, lease_for=self._lease_for)
        credential = self._credentials.resolve(
            project_id=lease.project_id, reference_id=state.secret_reference_id,
            purpose=state.secret_purpose, version=state.secret_version,
        )
        self._store.heartbeat(lease, lease_for=self._lease_for)
        for scope in state.scopes:
            self._store.heartbeat(lease, lease_for=self._lease_for)
            self._sources(
                connector_kind=state.connector_kind,
                adapter_release=state.adapter_release,
                credential=credential,
                source_locator=scope.source_locator,
                streams=scope.streams,
                report_spec=scope.report_spec,
                date_policy=scope.date_policy,
            ).check_connection()
        finished_at = self._clock()
        result_hash = canonical_hash({
            "test_id": str(state.test_id), "connector_kind": state.connector_kind.value,
            "adapter_release": state.adapter_release, "outcome": "connected",
            "scopes": [
                {"id": str(scope.id), "scope_hash": scope.scope_hash}
                for scope in state.scopes
            ],
        })
        with self._store.fenced_transaction(lease) as connection:
            set_project_scope(connection, lease.project_id)
            updated = connection.execute(
                """UPDATE connector_connection_tests
                      SET status = 'succeeded', version = version + 1,
                          finished_at = %s, result_hash = %s, error_class = NULL
                    WHERE project_id = %s AND id = %s AND status = 'running'
                      AND version = %s RETURNING id""",
                (
                    finished_at, result_hash, lease.project_id,
                    state.test_id, state.test_version,
                ),
            ).fetchone()
            if updated is None:
                raise ConnectorWorkerError("Connector connection test completion was fenced")
            self._store.complete_in_transaction(
                connection, lease,
                result_ref=f"connector-connection-test:{state.test_id}",
                details={"test_id": str(state.test_id), "result_hash": result_hash},
            )
        return {"status": "succeeded", "test_id": str(state.test_id)}


__all__ = [
    "CONNECTOR_CONNECTION_TEST_JOB_KIND",
    "ConnectorConnectionTestScope",
    "ConnectorConnectionTestOperation",
    "PostgresConnectorConnectionTestRepository",
]


_SCOPE_KEYS = {
    "id", "version", "scope_hash", "source_locator", "streams",
    "report_spec", "date_policy",
}
_HASH = re.compile(r"^[0-9a-f]{64}$")


def _scope_payload_is_valid(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    ids: list[str] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != _SCOPE_KEYS:
            return False
        try:
            ids.append(str(UUID(str(item["id"]))))
            if int(item["version"]) < 1:
                return False
        except (TypeError, ValueError):
            return False
        if not isinstance(item["scope_hash"], str) or not _HASH.fullmatch(item["scope_hash"]):
            return False
        if not isinstance(item["source_locator"], str) or not item["source_locator"].strip():
            return False
        streams = item["streams"]
        if (
            not isinstance(streams, list)
            or not streams
            or any(not isinstance(stream, str) or not stream.strip() for stream in streams)
        ):
            return False
        if not isinstance(item["report_spec"], Mapping) or not isinstance(
            item["date_policy"], Mapping
        ):
            return False
    return len(ids) == len(set(ids)) and ids == sorted(ids)


def _parse_scopes(value: object) -> tuple[ConnectorConnectionTestScope, ...]:
    if not _scope_payload_is_valid(value):
        raise ConnectorWorkerError("Connector connection-test Scope snapshot is invalid")
    assert isinstance(value, list)
    return tuple(
        ConnectorConnectionTestScope(
            id=UUID(str(item["id"])),
            version=int(item["version"]),
            scope_hash=str(item["scope_hash"]),
            source_locator=str(item["source_locator"]),
            streams=tuple(str(stream) for stream in item["streams"]),
            report_spec=dict(item["report_spec"]),
            date_policy=dict(item["date_policy"]),
        )
        for item in value
        if isinstance(item, Mapping)
    )


def _scope_matches(
    expected: ConnectorConnectionTestScope, actual: Mapping[str, object] | None
) -> bool:
    if actual is None:
        return False
    streams = actual.get("streams")
    return (
        actual.get("connection_id") is not None
        and actual.get("version") == expected.version
        and actual.get("scope_hash") == expected.scope_hash
        and actual.get("source_locator") == expected.source_locator
        and streams == list(expected.streams)
        and actual.get("report_spec") == dict(expected.report_spec)
        and actual.get("date_policy") == dict(expected.date_policy)
    )
