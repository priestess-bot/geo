"""Safe reconstruction of Secret Store domain records from PostgreSQL rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import UUID

from .models import (
    EncryptedSecretVersion,
    SecretAuditAction,
    SecretAuditEvent,
    SecretReference,
    SecretVersionHandle,
    SecretVersionStatus,
)
from .ports import (
    SecretAggregate,
    SecretCommandOutcome,
    SecretCommandRecord,
    SecretOperation,
    StoredSecretVersion,
)


def aggregate_from_rows(
    reference_row: Mapping[str, Any],
    version_rows: Sequence[Mapping[str, Any]],
) -> SecretAggregate:
    reference = SecretReference(
        id=cast(UUID, reference_row["id"]),
        project_id=cast(UUID, reference_row["project_id"]),
        purpose=str(reference_row["purpose"]),
        created_at=reference_row["created_at"],
    )
    versions = tuple(version_from_row(row) for row in version_rows)
    return SecretAggregate(
        reference=reference,
        aggregate_version=int(reference_row["aggregate_version"]),
        current_version=cast(int | None, reference_row["current_version"]),
        created_by=cast(UUID, reference_row["created_by"]),
        updated_at=reference_row["updated_at"],
        versions=versions,
    )


def version_from_row(row: Mapping[str, Any]) -> StoredSecretVersion:
    handle = SecretVersionHandle(
        reference_id=cast(UUID, row["reference_id"]),
        project_id=cast(UUID, row["project_id"]),
        purpose=str(row["purpose"]),
        version=int(row["version"]),
    )
    envelope = EncryptedSecretVersion(
        handle=handle,
        ciphertext=bytes(row["ciphertext"]),
        data_nonce=bytes(row["data_nonce"]),
        wrapped_data_key=bytes(row["wrapped_data_key"]),
        wrap_nonce=bytes(row["wrap_nonce"]),
        master_key_version=int(row["master_key_version"]),
        algorithm=str(row["algorithm"]),
        created_at=row["created_at"],
    )
    return StoredSecretVersion(
        envelope=envelope,
        status=SecretVersionStatus(str(row["status"])),
        created_by=cast(UUID, row["created_by"]),
        verified_by=cast(UUID | None, row["verified_by"]),
        verified_at=row["verified_at"],
        activated_by=cast(UUID | None, row["activated_by"]),
        activated_at=row["activated_at"],
        revoked_by=cast(UUID | None, row["revoked_by"]),
        revoked_at=row["revoked_at"],
    )


def command_from_row(row: Mapping[str, Any]) -> SecretCommandRecord:
    handle = SecretVersionHandle(
        reference_id=cast(UUID, row["reference_id"]),
        project_id=cast(UUID, row["project_id"]),
        purpose=str(row["purpose"]),
        version=int(row["version"]),
    )
    return SecretCommandRecord(
        project_id=handle.project_id,
        operation=SecretOperation(str(row["operation"])),
        idempotency_key_hash=str(row["idempotency_key_hash"]),
        request_hash=str(row["request_hash"]),
        outcome=SecretCommandOutcome(
            handle=handle,
            aggregate_version=int(row["aggregate_version"]),
            status=SecretVersionStatus(str(row["status"])),
        ),
        recorded_at=row["recorded_at"],
    )


def audit_from_row(row: Mapping[str, Any]) -> SecretAuditEvent:
    return SecretAuditEvent(
        id=cast(UUID, row["id"]),
        reference_id=cast(UUID, row["reference_id"]),
        project_id=cast(UUID, row["project_id"]),
        purpose=str(row["purpose"]),
        version=int(row["version"]),
        action=SecretAuditAction(str(row["action"])),
        actor_id=cast(UUID, row["actor_id"]),
        occurred_at=row["occurred_at"],
        master_key_version=int(row["master_key_version"]),
    )


VERSION_COLUMNS = """reference_id, project_id, purpose, version,
    ciphertext, data_nonce, wrapped_data_key, wrap_nonce,
    master_key_version, algorithm, created_at, status, created_by,
    verified_by, verified_at, activated_by, activated_at, revoked_by, revoked_at"""


__all__ = [
    "VERSION_COLUMNS",
    "aggregate_from_rows",
    "audit_from_row",
    "command_from_row",
    "version_from_row",
]
