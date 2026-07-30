"""Frozen domain contracts for raw-first external data synchronization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from uuid import UUID


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_MANIFEST_URI = re.compile(r"^(?:minio|s3)://[^\s]+$")


class ConnectorRuleViolation(ValueError):
    """A connector command violates the frozen data contract."""


class ConnectorKind(StrEnum):
    GOOGLE_SEARCH_CONSOLE = "google_search_console"
    GOOGLE_ANALYTICS_4 = "google_analytics_4"
    GOOGLE_OFFICIAL_REPORT = "google_official_report"
    BING_OFFICIAL_REPORT = "bing_official_report"


class ConnectorSyncMode(StrEnum):
    INITIAL = "initial"
    INCREMENTAL = "incremental"
    BACKFILL = "backfill"


class ConnectorSyncStatus(StrEnum):
    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SchemaCompatibility(StrEnum):
    INITIAL = "initial"
    COMPATIBLE = "compatible"
    BREAKING = "breaking"


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class ConnectorErrorClass(StrEnum):
    AUTH = "auth"
    QUOTA = "quota"
    RATE = "rate"
    SCHEMA = "schema"
    REVOKED = "revoked"
    TRANSIENT = "transient"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class ConnectorSyncPlan:
    """Immutable identity of one initial, incremental, or backfill read."""

    project_id: UUID
    definition_id: UUID
    connection_id: UUID
    scope_id: UUID
    mode: ConnectorSyncMode
    adapter_release: str
    input_checkpoint_id: UUID | None
    input_checkpoint_hash: str
    window_start: datetime | None
    window_end: datetime | None
    requested_by: UUID
    requested_at: datetime
    plan_hash: str = field(init=False)

    def __post_init__(self) -> None:
        mode = ConnectorSyncMode(self.mode)
        _uuid(self.project_id, "project")
        _uuid(self.definition_id, "definition")
        _uuid(self.connection_id, "connection")
        _uuid(self.scope_id, "scope")
        _uuid(self.requested_by, "request actor")
        if self.input_checkpoint_id is not None:
            _uuid(self.input_checkpoint_id, "input checkpoint")
        _hash(self.input_checkpoint_hash, "input checkpoint")
        _text(self.adapter_release, "adapter release", maximum=200)
        _aware(self.requested_at, "requested time")
        if self.window_start is not None:
            _aware(self.window_start, "window start")
        if self.window_end is not None:
            _aware(self.window_end, "window end")
        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_end < self.window_start
        ):
            raise ConnectorRuleViolation("sync window ends before it starts")
        if mode is ConnectorSyncMode.INCREMENTAL and self.input_checkpoint_id is None:
            raise ConnectorRuleViolation("incremental sync requires an input checkpoint")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "plan_hash", canonical_hash(self.canonical_value()))

    @property
    def idempotency_key(self) -> str:
        return f"connector.sync:{self.plan_hash}"

    def canonical_value(self) -> dict[str, object]:
        return {
            "project_id": str(self.project_id),
            "definition_id": str(self.definition_id),
            "connection_id": str(self.connection_id),
            "scope_id": str(self.scope_id),
            "mode": self.mode.value,
            "adapter_release": self.adapter_release,
            "input_checkpoint_id": (
                str(self.input_checkpoint_id) if self.input_checkpoint_id else None
            ),
            "input_checkpoint_hash": self.input_checkpoint_hash,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
        }


@dataclass(frozen=True)
class RawArtifactDescriptor:
    manifest_uri: str
    manifest_hash: str
    content_hash: str
    schema_fingerprint: str
    record_count: int
    byte_size: int
    classification: str
    retention_until: datetime
    encryption_key_reference: str
    producer_commit: str

    def __post_init__(self) -> None:
        if not _MANIFEST_URI.fullmatch(self.manifest_uri):
            raise ConnectorRuleViolation("raw artifact manifest URI is invalid")
        for value, label in (
            (self.manifest_hash, "manifest"),
            (self.content_hash, "content"),
            (self.schema_fingerprint, "schema fingerprint"),
        ):
            _hash(value, label)
        if self.record_count < 0 or self.byte_size < 0:
            raise ConnectorRuleViolation("raw artifact counts cannot be negative")
        if self.classification not in {"internal_raw", "restricted_raw"}:
            raise ConnectorRuleViolation("raw artifact classification is invalid")
        _aware(self.retention_until, "raw artifact retention")
        _text(self.encryption_key_reference, "encryption key reference", maximum=500)
        if not _GIT_SHA.fullmatch(self.producer_commit):
            raise ConnectorRuleViolation("raw artifact producer commit is invalid")


@dataclass(frozen=True)
class ConnectorSyncCommit:
    """Everything required for an atomic projection/checkpoint commit."""

    project_id: UUID
    run_id: UUID
    expected_run_version: int
    expected_checkpoint_hash: str
    artifact: RawArtifactDescriptor
    schema_document: Mapping[str, object]
    schema_hash: str
    compatibility: SchemaCompatibility
    schema_diff: Mapping[str, object]
    projection_kind: str
    projection_row_count: int
    projection_dataset_hash: str
    projection_lineage: Mapping[str, object]
    projection_records: Sequence[Mapping[str, object]]
    next_cursor_state: Mapping[str, object]
    next_watermark: datetime | None
    expected_watermark: datetime | None
    freshness_status: FreshnessStatus
    freshness_reason: str

    def __post_init__(self) -> None:
        _uuid(self.project_id, "project")
        _uuid(self.run_id, "sync run")
        if self.expected_run_version < 1:
            raise ConnectorRuleViolation("expected run version must be positive")
        _hash(self.expected_checkpoint_hash, "expected checkpoint")
        _hash(self.schema_hash, "schema")
        _hash(self.projection_dataset_hash, "projection dataset")
        if canonical_hash(self.schema_document) != self.schema_hash:
            raise ConnectorRuleViolation("schema hash does not match schema document")
        compatibility = SchemaCompatibility(self.compatibility)
        if compatibility is SchemaCompatibility.BREAKING:
            raise ConnectorRuleViolation("breaking schema cannot advance a projection")
        if self.projection_row_count < 0:
            raise ConnectorRuleViolation("projection row count cannot be negative")
        _text(self.projection_kind, "projection kind", maximum=120)
        if not isinstance(self.next_cursor_state, Mapping):
            raise ConnectorRuleViolation("next cursor state must be an object")
        if not isinstance(self.schema_diff, Mapping) or not isinstance(
            self.projection_lineage, Mapping
        ):
            raise ConnectorRuleViolation("schema diff and projection lineage must be objects")
        if self.next_watermark is not None:
            _aware(self.next_watermark, "next watermark")
        if self.expected_watermark is not None:
            _aware(self.expected_watermark, "expected watermark")
        status = FreshnessStatus(self.freshness_status)
        _text(self.freshness_reason, "freshness reason", maximum=500)
        object.__setattr__(self, "schema_document", _mapping(self.schema_document))
        object.__setattr__(self, "schema_diff", _mapping(self.schema_diff))
        object.__setattr__(self, "projection_lineage", _mapping(self.projection_lineage))
        records = tuple(_mapping(record) for record in self.projection_records)
        if len(records) != self.projection_row_count:
            raise ConnectorRuleViolation("projection records do not match row count")
        object.__setattr__(self, "projection_records", records)
        object.__setattr__(self, "next_cursor_state", _mapping(self.next_cursor_state))
        object.__setattr__(self, "compatibility", compatibility)
        object.__setattr__(self, "freshness_status", status)

    @property
    def next_checkpoint_hash(self) -> str:
        return canonical_hash(
            {
                "cursor_state": dict(self.next_cursor_state),
                "watermark": self.next_watermark.isoformat() if self.next_watermark else None,
            }
        )

    @property
    def lag_seconds(self) -> int | None:
        if self.expected_watermark is None or self.next_watermark is None:
            return None
        return max(0, int((self.expected_watermark - self.next_watermark).total_seconds()))


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"cannot canonicalize {type(value).__name__}")


def _mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if any(not isinstance(key, str) for key in value):
        raise ConnectorRuleViolation("object keys must be strings")
    return MappingProxyType(dict(value))


def _uuid(value: UUID, label: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ConnectorRuleViolation(f"{label} is invalid")


def _hash(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ConnectorRuleViolation(f"{label} hash is invalid")


def _text(value: str, label: str, *, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ConnectorRuleViolation(f"{label} is invalid")


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ConnectorRuleViolation(f"{label} must be timezone-aware")
