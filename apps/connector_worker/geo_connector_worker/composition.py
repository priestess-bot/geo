"""Production composition for the isolated PyAirbyte Connector worker."""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.connectors.jobs import CONNECTOR_SYNC_JOB_KIND
from geo_core.connectors.connection_test import (
    CONNECTOR_CONNECTION_TEST_JOB_KIND,
    ConnectorConnectionTestOperation,
    PostgresConnectorConnectionTestRepository,
)
from geo_core.connectors.postgres import PostgresConnectorRepository
from geo_core.connectors.runtime import EncryptedConnectorArtifactWriter
from geo_core.connectors.secret_resolver import build_audited_connector_secret_resolver
from geo_core.connectors.source_builder import (
    build_pyairbyte_connection_test_source,
    build_pyairbyte_source,
)
from geo_core.connectors.worker import (
    ConnectorSyncOperation,
    PostgresConnectorWorkerRepository,
)
from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LostJobLease,
    PostgresDurableJobStore,
)
from geo_core.object_store_config import build_object_store_from_prefix


class ConnectorDispatcher:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        operation: ConnectorSyncOperation,
        connection_test_operation: ConnectorConnectionTestOperation,
        connection_tests: PostgresConnectorConnectionTestRepository,
        worker_id: str,
        lease_for: timedelta,
    ) -> None:
        self._store = store
        self._operation = operation
        self._connection_test_operation = connection_test_operation
        self._connection_tests = connection_tests
        self._worker_id = worker_id
        self._lease_for = lease_for

    def process(self, *, job_id: UUID, project_id: UUID) -> Mapping[str, object]:
        kind = self._connection_tests.job_kind(project_id=project_id, job_id=job_id)
        operation = {
            CONNECTOR_SYNC_JOB_KIND: self._operation,
            CONNECTOR_CONNECTION_TEST_JOB_KIND: self._connection_test_operation,
        }.get(kind)
        if operation is None:
            raise RuntimeError("Connector worker received an unsupported Job kind")
        claim = self._store.claim(
            job_id=job_id,
            project_id=project_id,
            expected_kind=kind,
            worker_id=self._worker_id,
            lease_for=self._lease_for,
        )
        if claim.lease is None:
            return {"status": claim.disposition, "job_id": str(job_id)}
        try:
            return operation.execute(claim.lease)
        except JobCancellationRequested:
            self._store.cancel(claim.lease)
            return {"status": "cancelled", "job_id": str(job_id)}
        except LostJobLease:
            return {"status": "fenced", "job_id": str(job_id)}
        except Exception as error:
            status = self._store.fail(
                claim.lease,
                error_code=(
                    "connector_connection_test_failed"
                    if kind == CONNECTOR_CONNECTION_TEST_JOB_KIND
                    else "connector_sync_failed"
                ),
                details={"classification": type(error).__name__},
                retry_delay=timedelta(seconds=30),
            )
            return {"status": status, "job_id": str(job_id)}


def build_connector_dispatcher(
    *, database_url: str, worker_id: str
) -> ConnectorDispatcher:
    if not database_url.strip() or not worker_id.strip():
        raise RuntimeError("Connector database URL and worker ID are required")

    def connect() -> Any:
        return psycopg.connect(database_url, row_factory=dict_row)

    lease_for = timedelta(seconds=_bounded_int("GEO_JOB_LEASE_SECONDS", 300, 30, 900))
    objects = build_object_store_from_prefix("GEO_CONNECTOR_ARTIFACT_OBJECT_STORE")
    objects.ensure_bucket()
    store = PostgresDurableJobStore(connect)
    repository = PostgresConnectorRepository(connect=connect)
    connection_tests = PostgresConnectorConnectionTestRepository(connect=connect)
    credentials = build_audited_connector_secret_resolver(
        database_url=database_url,
        service_identity_id=_required_uuid("GEO_CONNECTOR_SERVICE_IDENTITY_ID"),
    )
    operation = ConnectorSyncOperation(
        store=store,
        worker_repository=PostgresConnectorWorkerRepository(connect=connect),
        connector_repository=repository,
        credentials=credentials,
        sources=build_pyairbyte_source,
        artifacts=EncryptedConnectorArtifactWriter(
            objects=objects,
            data_key=_load_artifact_key(_required_path("GEO_CONNECTOR_ARTIFACT_KEY_FILE")),
            key_reference=_required("GEO_CONNECTOR_ARTIFACT_KEY_REFERENCE"),
            producer_commit=_producer_commit(),
            retention_days=_bounded_int(
                "GEO_CONNECTOR_ARTIFACT_RETENTION_DAYS", 90, 1, 3650
            ),
        ),
        lease_for=lease_for,
    )
    return ConnectorDispatcher(
        store=store,
        operation=operation,
        connection_test_operation=ConnectorConnectionTestOperation(
            store=store, repository=connection_tests, credentials=credentials,
            sources=build_pyairbyte_connection_test_source, lease_for=lease_for,
        ),
        connection_tests=connection_tests,
        worker_id=worker_id.strip(),
        lease_for=lease_for,
    )


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _required_path(name: str) -> Path:
    path = Path(_required(name))
    if not path.is_file():
        raise RuntimeError(f"{name} must reference a readable file")
    return path


def _required_uuid(name: str) -> UUID:
    try:
        value = UUID(_required(name))
    except ValueError:
        raise RuntimeError(f"{name} must be a UUID") from None
    if value.int == 0:
        raise RuntimeError(f"{name} cannot be nil")
    return value


def _producer_commit() -> str:
    value = _required("GEO_RELEASE_COMMIT")
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise RuntimeError("GEO_RELEASE_COMMIT must be a full lowercase Git SHA")
    return value


def _load_artifact_key(path: Path) -> bytes:
    raw = path.read_bytes()
    if len(raw) == 32:
        return raw
    raw = raw.strip()
    candidates = [raw]
    try:
        candidates.append(bytes.fromhex(raw.decode("ascii")))
    except (UnicodeDecodeError, ValueError):
        pass
    try:
        candidates.append(base64.b64decode(raw, validate=True))
    except ValueError:
        pass
    for value in candidates:
        if len(value) == 32:
            return value
    raise RuntimeError("Connector artifact key must decode to exactly 32 bytes")


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer") from None
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


__all__ = ["ConnectorDispatcher", "build_connector_dispatcher"]
