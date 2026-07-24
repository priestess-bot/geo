"""Fenced PostgreSQL adapter for Synthetic artifact retention maintenance."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import psycopg

from geo_core.project_scope import set_project_scope
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.artifact_maintenance_contracts import (
    SyntheticArtifactDeletionLease,
)
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactStorageTier
from geo_core.synthetic_lab.raw_artifact_storage_contracts import RawArtifactStorageError


class PostgresSyntheticArtifactMaintenanceRepository:
    """Delegate every irreversible retention transition to fenced database RPCs."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def stage_due_expirations(
        self,
        *,
        project_id: UUID,
        now: datetime,
        limit: int,
    ) -> int:
        _require_aware(now)
        _require_project_id(project_id)
        if not 1 <= limit <= 1_000:
            raise RawArtifactStorageError("Synthetic artifact expiry batch is invalid")
        value = self._one(
            "SELECT geo_stage_due_synthetic_artifact_expirations(%s, %s, %s)",
            (project_id, now, limit),
            project_id=project_id,
        )
        try:
            staged = int(cast(str | int, value))
        except (TypeError, ValueError):
            raise RawArtifactStorageError("Synthetic artifact expiry result is invalid") from None
        if staged < 0:
            raise RawArtifactStorageError("Synthetic artifact expiry result is invalid")
        return staged

    def claim_deletions(
        self,
        *,
        project_id: UUID,
        worker_id: str,
        now: datetime,
        batch_size: int,
        lease_seconds: int,
    ) -> tuple[SyntheticArtifactDeletionLease, ...]:
        _require_project_id(project_id)
        _require_aware(now)
        if not worker_id.strip() or not 1 <= batch_size <= 100:
            raise RawArtifactStorageError("Synthetic artifact deletion claim is invalid")
        if not 5 <= lease_seconds <= 3_600:
            raise RawArtifactStorageError("Synthetic artifact deletion lease is invalid")
        rows = self._rows(
            """SELECT * FROM geo_claim_synthetic_artifact_deletions(
                   %s, %s, %s, %s, %s
               )""",
            (project_id, worker_id, now, batch_size, lease_seconds),
            project_id=project_id,
        )
        if len(rows) > batch_size:
            raise RawArtifactStorageError("Synthetic artifact deletion claim exceeds batch")
        return tuple(_lease(row) for row in rows)

    def crypto_erase_and_tombstone(
        self,
        lease: SyntheticArtifactDeletionLease,
        *,
        erased_at: datetime,
    ) -> bool:
        _require_aware(erased_at)
        value = self._one(
            """SELECT geo_crypto_erase_and_tombstone_synthetic_artifact(
                   %s, %s, %s, %s, %s, %s, %s
               )""",
            (
                lease.outbox_id,
                lease.project_id,
                lease.artifact_id,
                lease.artifact_generation,
                lease.lease_token,
                _receipt_hash(lease, phase="crypto_erased", occurred_at=erased_at),
                erased_at,
            ),
            project_id=lease.project_id,
        )
        if not isinstance(value, bool):
            raise RawArtifactStorageError("Synthetic artifact crypto-erasure result is invalid")
        return value

    def complete_object_deletion(
        self,
        lease: SyntheticArtifactDeletionLease,
        *,
        deleted_at: datetime,
    ) -> None:
        _require_aware(deleted_at)
        value = self._one(
            """SELECT geo_complete_synthetic_artifact_object_deletion(
                   %s, %s, %s, %s, %s, %s, %s
               )""",
            (
                lease.outbox_id,
                lease.project_id,
                lease.artifact_id,
                lease.artifact_generation,
                lease.lease_token,
                _receipt_hash(lease, phase="object_deleted", occurred_at=deleted_at),
                deleted_at,
            ),
            project_id=lease.project_id,
        )
        if value is not True:
            raise RawArtifactStorageError("Synthetic artifact object deletion was fenced")

    def fail_object_deletion(
        self,
        lease: SyntheticArtifactDeletionLease,
        *,
        error_code: str,
        next_attempt_at: datetime,
    ) -> None:
        _require_aware(next_attempt_at)
        if not error_code or len(error_code) > 63:
            raise RawArtifactStorageError("Synthetic artifact deletion error code is invalid")
        value = self._one(
            """SELECT geo_fail_synthetic_artifact_object_deletion(
                   %s, %s, %s, %s, %s, %s, %s
               )""",
            (
                lease.outbox_id,
                lease.project_id,
                lease.artifact_id,
                lease.artifact_generation,
                lease.lease_token,
                error_code,
                next_attempt_at,
            ),
            project_id=lease.project_id,
        )
        if value is not True:
            raise RawArtifactStorageError("Synthetic artifact deletion retry was fenced")

    def _one(
        self,
        statement: str,
        values: tuple[object, ...],
        *,
        project_id: UUID,
    ) -> object:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(statement, values).fetchone()
            connection.commit()
        except psycopg.Error as error:
            connection.rollback()
            raise RawArtifactStorageError(
                "Synthetic artifact maintenance PostgreSQL transition failed"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        if row is None:
            raise RawArtifactStorageError("Synthetic artifact maintenance returned no result")
        return row[0] if not isinstance(row, Mapping) else next(iter(row.values()))

    def _rows(
        self,
        statement: str,
        values: tuple[object, ...],
        *,
        project_id: UUID,
    ) -> tuple[Mapping[str, Any], ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = tuple(connection.execute(statement, values).fetchall())
            connection.commit()
        except psycopg.Error as error:
            connection.rollback()
            raise RawArtifactStorageError(
                "Synthetic artifact maintenance PostgreSQL claim failed"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        if not all(isinstance(row, Mapping) for row in rows):
            raise RawArtifactStorageError("Synthetic artifact deletion claim row is invalid")
        return rows


def _lease(row: Mapping[str, Any]) -> SyntheticArtifactDeletionLease:
    return SyntheticArtifactDeletionLease(
        outbox_id=_uuid(row, "outbox_id"),
        project_id=_uuid(row, "project_id"),
        artifact_id=_uuid(row, "artifact_id"),
        artifact_generation=_integer(row, "artifact_generation"),
        manifest_hash=_hash(row, "manifest_hash"),
        payload_uri=_uri(row, "payload_uri"),
        manifest_uri=_uri(row, "manifest_uri"),
        storage_tier=ArtifactStorageTier(_text(row, "storage_tier")),
        lease_token=_uuid(row, "lease_token"),
        deletion_fencing_generation=_integer(row, "deletion_fencing_generation"),
    )


def _receipt_hash(
    lease: SyntheticArtifactDeletionLease,
    *,
    phase: str,
    occurred_at: datetime,
) -> str:
    return canonical_hash(
        {
            "schema_version": 1,
            "phase": phase,
            "outbox_id": str(lease.outbox_id),
            "project_id": str(lease.project_id),
            "artifact_id": str(lease.artifact_id),
            "artifact_generation": lease.artifact_generation,
            "deletion_fencing_generation": lease.deletion_fencing_generation,
            "manifest_hash": lease.manifest_hash,
            "payload_uri": lease.payload_uri,
            "manifest_uri": lease.manifest_uri,
            "occurred_at": occurred_at.isoformat(),
        }
    )


def _uuid(row: Mapping[str, Any], name: str) -> UUID:
    try:
        value = UUID(str(row[name]))
    except (KeyError, TypeError, ValueError):
        raise RawArtifactStorageError(
            f"Synthetic artifact deletion field {name} is invalid"
        ) from None
    if value.int == 0:
        raise RawArtifactStorageError(f"Synthetic artifact deletion field {name} is invalid")
    return value


def _integer(row: Mapping[str, Any], name: str) -> int:
    value = row.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RawArtifactStorageError(f"Synthetic artifact deletion field {name} is invalid")
    return value


def _text(row: Mapping[str, Any], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RawArtifactStorageError(f"Synthetic artifact deletion field {name} is invalid")
    return value


def _hash(row: Mapping[str, Any], name: str) -> str:
    value = _text(row, name)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RawArtifactStorageError(f"Synthetic artifact deletion field {name} is invalid")
    return value


def _uri(row: Mapping[str, Any], name: str) -> str:
    value = _text(row, name)
    if not value.startswith("s3://"):
        raise RawArtifactStorageError(f"Synthetic artifact deletion field {name} is invalid")
    return value


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RawArtifactStorageError("Synthetic artifact maintenance time must be timezone-aware")


def _require_project_id(project_id: UUID) -> None:
    if project_id.int == 0:
        raise RawArtifactStorageError("Synthetic artifact maintenance Project is invalid")


__all__ = ["PostgresSyntheticArtifactMaintenanceRepository"]
