"""Shared PostgreSQL boundary helpers for governed manual sample imports."""

from __future__ import annotations

import base64
import binascii
from typing import Mapping
from uuid import UUID

import psycopg

from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.manual_import_artifacts import (
    MANUAL_IMPORT_ENCRYPTED_MEDIA_TYPE,
    ManualImportArtifactKind,
    ManualImportArtifactRef,
)
from geo_core.synthetic_lab.manual_import_preview import ManualImportUpload
from geo_core.synthetic_lab.ports import (
    SyntheticLabPermissionDenied,
    SyntheticLabPersistenceError,
    SyntheticLabVersionConflict,
)


PREVIEW_SELECT = """SELECT preview.*, state.version, state.status,
       state.idempotency_key_hash, state.request_hash, state.final_manifest_id
FROM synthetic_lab_manual_import_previews AS preview
JOIN LATERAL (
    SELECT * FROM synthetic_lab_manual_import_preview_states AS version
    WHERE version.project_id = preview.project_id AND version.preview_id = preview.id
    ORDER BY version.version DESC LIMIT 1
) AS state ON true
WHERE preview.project_id = %s"""


def preview_summary(row: dict[str, object]) -> dict[str, object]:
    return {
        "preview_id": row["id"],
        "project_id": row["project_id"],
        "style_source_revision_id": row["style_source_revision_id"],
        "channel": row["channel"],
        "filename": row["filename"],
        "import_format": row["import_format"],
        "submitted_by": row["submitted_by"],
        "submitted_at": row["submitted_at"],
        "expires_at": row["expires_at"],
        "preview_manifest_hash": row["preview_manifest_hash"],
        "row_count": row["row_count"],
        "selectable_count": row["selectable_count"],
        "blocked_count": row["blocked_count"],
        "status": row["status"],
        "version": row["version"],
    }


def artifact_ref(row: Mapping[str, object]) -> ManualImportArtifactRef:
    return ManualImportArtifactRef(
        project_id=UUID(str(row["project_id"])),
        artifact_id=UUID(str(row["upload_artifact_id"])),
        kind=ManualImportArtifactKind.TEMPORARY_UPLOAD,
        uri=str(row["upload_object_uri"]),
        object_hash=str(row["upload_object_hash"]),
        plaintext_hash=str(row["upload_plaintext_hash"]),
        key_version=str(row["upload_key_version"]),
        algorithm=str(row["upload_algorithm"]),
        byte_size=int(str(row["upload_byte_size"])),
    )


def assert_upload_row(upload: ManualImportUpload, row: Mapping[str, object]) -> None:
    if (
        upload.preview_id != row["id"]
        or upload.project_id != row["project_id"]
        or upload.style_source_revision_id != row["style_source_revision_id"]
        or upload.submitted_by != row["submitted_by"]
        or upload.filename != row["filename"]
    ):
        raise SyntheticLabPersistenceError("manual import upload lineage changed")


def decode_base64(value: object) -> bytes:
    if not isinstance(value, str):
        raise SyntheticLabContractError("manual import upload must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise SyntheticLabContractError("manual import upload base64 is invalid") from error


def database_error(error: psycopg.Error) -> SyntheticLabPersistenceError:
    if error.sqlstate in {"23505", "40001", "55000"}:
        return SyntheticLabVersionConflict("manual import preview state changed")
    if error.sqlstate in {"23514", "42501", "P0001"}:
        return SyntheticLabPermissionDenied("manual import approval gate rejected the command")
    return SyntheticLabPersistenceError("PostgreSQL rejected the manual import workflow")


def wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = [
    "MANUAL_IMPORT_ENCRYPTED_MEDIA_TYPE",
    "PREVIEW_SELECT",
    "artifact_ref",
    "assert_upload_row",
    "database_error",
    "decode_base64",
    "preview_summary",
    "wipe",
]
