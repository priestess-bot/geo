"""Connector Core contracts and persistence operations."""

from geo_core.connectors.contracts import (
    ConnectorErrorClass,
    ConnectorKind,
    ConnectorRuleViolation,
    ConnectorSyncCommit,
    ConnectorSyncMode,
    ConnectorSyncPlan,
    ConnectorSyncStatus,
    FreshnessStatus,
    RawArtifactDescriptor,
    SchemaCompatibility,
    canonical_hash,
)
from geo_core.connectors.postgres import (
    ConnectorPersistenceError,
    PersistedSyncResult,
    PersistedSyncRun,
    PostgresConnectorRepository,
)
from geo_core.connectors.jobs import (
    CONNECTOR_SYNC_JOB_KIND,
    ConnectorJobError,
    ConnectorJobSpec,
    EnqueuedConnectorJob,
    PostgresConnectorJobRepository,
)

__all__ = [
    "CONNECTOR_SYNC_JOB_KIND",
    "ConnectorErrorClass",
    "ConnectorJobError",
    "ConnectorJobSpec",
    "ConnectorKind",
    "ConnectorPersistenceError",
    "ConnectorRuleViolation",
    "ConnectorSyncCommit",
    "ConnectorSyncMode",
    "ConnectorSyncPlan",
    "ConnectorSyncStatus",
    "FreshnessStatus",
    "EnqueuedConnectorJob",
    "PersistedSyncResult",
    "PersistedSyncRun",
    "PostgresConnectorRepository",
    "PostgresConnectorJobRepository",
    "RawArtifactDescriptor",
    "SchemaCompatibility",
    "canonical_hash",
]
