"""Raw-first Connector runtime shared by fixtures and external adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from typing import Protocol
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from geo_core.connectors.contracts import (
    ConnectorSyncCommit,
    ConnectorSyncPlan,
    FreshnessStatus,
    RawArtifactDescriptor,
    SchemaCompatibility,
    canonical_hash,
)
from geo_core.connectors.postgres import PersistedSyncResult, PostgresConnectorRepository
from geo_core.object_store import StoredObject


class ConnectorRuntimeError(RuntimeError):
    """A source read or governed raw-artifact write failed."""


@dataclass(frozen=True)
class ConnectorSourceBatch:
    records: tuple[Mapping[str, object], ...]
    cursor_state: Mapping[str, object]
    watermark: datetime | None
    schema_document: Mapping[str, object]
    source_fingerprint: str
    compatibility: SchemaCompatibility
    schema_diff: Mapping[str, object]

    def __post_init__(self) -> None:
        if any(not isinstance(record, Mapping) for record in self.records):
            raise ConnectorRuntimeError("source batch records must be objects")
        if self.watermark is not None and (
            self.watermark.tzinfo is None or self.watermark.utcoffset() is None
        ):
            raise ConnectorRuntimeError("source watermark must be timezone-aware")
        if len(self.source_fingerprint) != 64:
            raise ConnectorRuntimeError("source fingerprint is invalid")


class ConnectorSource(Protocol):
    def read(self, plan: ConnectorSyncPlan) -> ConnectorSourceBatch: ...


class ConnectorObjectStore(Protocol):
    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObject: ...


class ConnectorLeaseCheckpoint(Protocol):
    def __call__(self) -> None: ...


class EncryptedConnectorArtifactWriter:
    """Encrypt raw JSONL before it reaches object storage, then write its manifest."""

    def __init__(
        self,
        *,
        objects: ConnectorObjectStore,
        data_key: bytes,
        key_reference: str,
        producer_commit: str,
        retention_days: int = 90,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(data_key) != 32:
            raise ConnectorRuntimeError("connector artifact data key must be 32 bytes")
        if not key_reference.strip():
            raise ConnectorRuntimeError("connector artifact key reference is required")
        if retention_days < 1:
            raise ConnectorRuntimeError("connector artifact retention must be positive")
        self._objects = objects
        self._data_key = data_key
        self._key_reference = key_reference
        self._producer_commit = producer_commit
        self._retention_days = retention_days
        self._clock = clock

    def persist(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
        records: Sequence[Mapping[str, object]],
        schema_fingerprint: str,
        classification: str = "internal_raw",
    ) -> RawArtifactDescriptor:
        payload = _jsonl(records)
        plaintext_hash = hashlib.sha256(payload).hexdigest()
        nonce = os.urandom(12)
        aad = f"geo-connector:{project_id}:{run_id}:{schema_fingerprint}".encode()
        ciphertext = AESGCM(self._data_key).encrypt(nonce, payload, aad)
        encrypted_hash = hashlib.sha256(ciphertext).hexdigest()
        prefix = f"connectors/{project_id}/{run_id}"
        raw = self._objects.put_object(
            key=f"{prefix}/records.jsonl.aesgcm",
            content=ciphertext,
            content_type="application/octet-stream",
            expected_hash=encrypted_hash,
        )
        created_at = self._clock()
        manifest_value = {
            "schema_version": "geo-connector-raw-manifest-v1",
            "project_id": str(project_id),
            "sync_run_id": str(run_id),
            "payload_uri": raw.uri,
            "payload_ciphertext_sha256": encrypted_hash,
            "payload_plaintext_sha256": plaintext_hash,
            "schema_fingerprint": schema_fingerprint,
            "record_count": len(records),
            "byte_size": len(ciphertext),
            "classification": classification,
            "retention_until": (created_at + timedelta(days=self._retention_days)).isoformat(),
            "encryption": {
                "algorithm": "AES-256-GCM",
                "key_reference": self._key_reference,
                "nonce_hex": nonce.hex(),
                "aad_sha256": hashlib.sha256(aad).hexdigest(),
            },
            "producer_commit": self._producer_commit,
            "created_at": created_at.isoformat(),
        }
        manifest = json.dumps(
            manifest_value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode()
        manifest_hash = hashlib.sha256(manifest).hexdigest()
        stored_manifest = self._objects.put_object(
            key=f"{prefix}/manifest.json",
            content=manifest,
            content_type="application/json",
            expected_hash=manifest_hash,
        )
        return RawArtifactDescriptor(
            manifest_uri=stored_manifest.uri,
            manifest_hash=manifest_hash,
            content_hash=plaintext_hash,
            schema_fingerprint=schema_fingerprint,
            record_count=len(records),
            byte_size=len(ciphertext),
            classification=classification,
            retention_until=created_at + timedelta(days=self._retention_days),
            encryption_key_reference=self._key_reference,
            producer_commit=self._producer_commit,
        )


class ConnectorSyncExecutor:
    def __init__(
        self,
        *,
        repository: PostgresConnectorRepository,
        source: ConnectorSource,
        artifacts: EncryptedConnectorArtifactWriter,
        checkpoint: ConnectorLeaseCheckpoint = lambda: None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._source = source
        self._artifacts = artifacts
        self._checkpoint = checkpoint
        self._clock = clock

    def execute(
        self,
        *,
        plan: ConnectorSyncPlan,
        run_id: UUID,
        expected_run_version: int,
        projection_kind: str,
        expected_watermark: datetime | None,
        connection: object | None = None,
    ) -> PersistedSyncResult:
        commit = self.prepare(
            plan=plan,
            run_id=run_id,
            expected_run_version=expected_run_version,
            projection_kind=projection_kind,
            expected_watermark=expected_watermark,
        )
        result = self._repository.commit_success(
            commit,
            finished_at=self._clock(),
            connection=connection,
        )
        self._checkpoint()
        return result

    def prepare(
        self,
        *,
        plan: ConnectorSyncPlan,
        run_id: UUID,
        expected_run_version: int,
        projection_kind: str,
        expected_watermark: datetime | None,
    ) -> ConnectorSyncCommit:
        """Perform external I/O and return a commit ready for a fenced transaction."""
        self._checkpoint()
        batch = self._source.read(plan)
        self._checkpoint()
        artifact = self._artifacts.persist(
            project_id=plan.project_id,
            run_id=run_id,
            records=batch.records,
            schema_fingerprint=batch.source_fingerprint,
        )
        self._checkpoint()
        dataset_hash = canonical_hash(tuple(_canonical_record(row) for row in batch.records))
        freshness, reason = _freshness(batch.watermark, expected_watermark)
        return ConnectorSyncCommit(
            project_id=plan.project_id,
            run_id=run_id,
            expected_run_version=expected_run_version,
            expected_checkpoint_hash=plan.input_checkpoint_hash,
            artifact=artifact,
            schema_document=batch.schema_document,
            schema_hash=canonical_hash(batch.schema_document),
            compatibility=batch.compatibility,
            schema_diff=batch.schema_diff,
            projection_kind=projection_kind,
            projection_row_count=len(batch.records),
            projection_dataset_hash=dataset_hash,
            projection_lineage={
                "adapter_release": plan.adapter_release,
                "source_fingerprint": batch.source_fingerprint,
                "mode": plan.mode.value,
            },
            projection_records=tuple(_canonical_record(row) for row in batch.records),
            next_cursor_state=batch.cursor_state,
            next_watermark=batch.watermark,
            expected_watermark=expected_watermark,
            freshness_status=freshness,
            freshness_reason=reason,
        )


def _jsonl(records: Sequence[Mapping[str, object]]) -> bytes:
    lines = [
        json.dumps(_canonical_record(record), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        for record in records
    ]
    return (("\n".join(lines) + "\n") if lines else "").encode()


def _canonical_record(record: Mapping[str, object]) -> dict[str, object]:
    if any(not isinstance(key, str) for key in record):
        raise ConnectorRuntimeError("record keys must be strings")
    # Round-trip rejects unserializable values and removes mutable mappings.
    return json.loads(json.dumps(dict(record), ensure_ascii=True, sort_keys=True))


def _freshness(
    observed: datetime | None, expected: datetime | None
) -> tuple[FreshnessStatus, str]:
    if observed is None or expected is None:
        return FreshnessStatus.UNKNOWN, "source or expected watermark is unavailable"
    lag = max(0, int((expected - observed).total_seconds()))
    if lag <= 172_800:
        return FreshnessStatus.FRESH, f"source watermark lag is {lag} seconds"
    return FreshnessStatus.STALE, f"source watermark lag is {lag} seconds"


__all__ = [
    "ConnectorRuntimeError",
    "ConnectorSource",
    "ConnectorSourceBatch",
    "ConnectorSyncExecutor",
    "EncryptedConnectorArtifactWriter",
]
