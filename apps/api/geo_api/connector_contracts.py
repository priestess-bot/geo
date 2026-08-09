"""Admin transport contracts for Connector Core."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from geo_api.contracts import StrictContract
from geo_core.connectors.contracts import ConnectorKind, ConnectorSyncMode


class InstallConnectorDefinitionRequest(StrictContract):
    kind: ConnectorKind


class ConnectorDefinitionResponse(StrictContract):
    id: UUID
    kind: ConnectorKind
    adapter_release: str
    runtime_release: str
    status: Literal["draft", "approved", "retired"]
    created_by: UUID
    created_at: datetime
    approved_by: UUID | None = None
    approved_at: datetime | None = None


class CreateConnectorConnectionRequest(StrictContract):
    definition_id: UUID
    name: str = Field(min_length=1, max_length=200)
    secret_reference_id: UUID
    # Kept optional for older clients. The server derives and verifies this
    # value from the approved definition; the Admin UI renders it read-only.
    secret_purpose: str | None = Field(
        default=None, pattern=r"^connector\.[a-z0-9_.-]+$", max_length=128
    )
    secret_version: int = Field(ge=1)


class ConnectorConnectionResponse(StrictContract):
    id: UUID
    definition_id: UUID
    name: str
    secret_reference_id: UUID
    secret_purpose: str
    secret_version: int
    status: str
    version: int
    created_at: datetime


class SetConnectorConnectionStatusRequest(StrictContract):
    status: Literal["active", "disabled"]
    expected_version: int = Field(ge=1)


class RotateConnectorSecretRequest(StrictContract):
    secret_version: int = Field(ge=1)
    expected_version: int = Field(ge=1)


class TestConnectorConnectionRequest(StrictContract):
    expected_version: int = Field(ge=1)


class ConnectorConnectionTestResponse(StrictContract):
    test_id: UUID
    job_id: UUID
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    replayed: bool


class ConnectorConnectionTestInventoryItem(StrictContract):
    id: UUID
    connection_id: UUID
    definition_id: UUID
    durable_job_id: UUID
    adapter_release: str
    secret_reference_id: UUID
    secret_purpose: str
    secret_version: int
    status: str
    version: int
    requested_by: UUID
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_hash: str | None = None
    error_class: str | None = None


class CreateConnectorScopeRequest(StrictContract):
    connection_id: UUID
    source_locator: str = Field(min_length=1, max_length=500)
    streams: list[str] = Field(min_length=1, max_length=20)
    locale: str = Field(default="en-AU", min_length=2, max_length=32)
    report_spec: dict[str, object] = Field(default_factory=dict)
    date_policy: dict[str, object] = Field(default_factory=dict)


class ConnectorScopeResponse(StrictContract):
    id: UUID
    connection_id: UUID
    source_locator: str
    streams: list[str]
    report_spec: dict[str, object]
    locale: str
    date_policy: dict[str, object]
    scope_hash: str | None = None
    status: str
    version: int
    created_at: datetime


class StartConnectorSyncRequest(StrictContract):
    mode: ConnectorSyncMode
    window_start: datetime | None = None
    window_end: datetime | None = None


class ConnectorSyncAccepted(StrictContract):
    run_id: UUID
    job_id: UUID
    status: Literal["queued"]
    replayed: bool
    plan_hash: str


class ConnectorRunResponse(StrictContract):
    id: UUID
    scope_id: UUID
    mode: ConnectorSyncMode
    status: str
    version: int
    durable_job_id: UUID | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_class: str | None = None
    projection_batch_id: UUID | None = None
    checkpoint_id: UUID | None = None
    freshness_status: str | None = None
    freshness_reason: str | None = None
    projected_row_count: int | None = None
    cancel_requested_at: datetime | None = None


class CancelConnectorSyncRequest(StrictContract):
    expected_version: int = Field(ge=1)


class ConnectorSyncControlResponse(StrictContract):
    run_id: UUID
    job_id: UUID
    status: Literal["cancel_requested", "cancelled"]


class ConnectorInventoryResponse(StrictContract):
    definitions: list[ConnectorDefinitionResponse]
    connections: list[ConnectorConnectionResponse]
    scopes: list[ConnectorScopeResponse]
    runs: list[ConnectorRunResponse]
    connection_tests: list[ConnectorConnectionTestInventoryItem]


__all__ = [
    "ConnectorConnectionResponse",
    "ConnectorConnectionTestResponse",
    "ConnectorDefinitionResponse",
    "ConnectorInventoryResponse",
    "ConnectorScopeResponse",
    "ConnectorSyncControlResponse",
    "ConnectorSyncAccepted",
    "CancelConnectorSyncRequest",
    "CreateConnectorConnectionRequest",
    "CreateConnectorScopeRequest",
    "InstallConnectorDefinitionRequest",
    "RotateConnectorSecretRequest",
    "SetConnectorConnectionStatusRequest",
    "StartConnectorSyncRequest",
    "TestConnectorConnectionRequest",
]
