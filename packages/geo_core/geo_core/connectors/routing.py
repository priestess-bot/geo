"""Stable broker identities for the isolated Connector worker."""

CONNECTOR_SYNC_QUEUE = "connector-sync"
CONNECTOR_SYNC_ACTOR = "process_connector_sync_job"
CONNECTOR_SYNC_OUTBOX_TOPICS = frozenset({"connector.sync.queued"})
CONNECTOR_OUTBOX_TOPICS = frozenset({
    "connector.sync.queued", "connector.connection_test.queued"
})

__all__ = [
    "CONNECTOR_SYNC_ACTOR",
    "CONNECTOR_OUTBOX_TOPICS",
    "CONNECTOR_SYNC_OUTBOX_TOPICS",
    "CONNECTOR_SYNC_QUEUE",
]
