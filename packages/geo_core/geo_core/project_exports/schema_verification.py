"""Manifest descriptor schema verification for F027 exports."""

from __future__ import annotations

import hashlib
from typing import Mapping

from geo_core.project_exports.constants import (
    DATA_JSON_PATH,
    PROJECT_EXPORT_SCHEMA_VERSION,
)
from geo_core.project_exports.errors import ProjectExportVerificationError
from geo_core.project_exports.schemas import CSV_SCHEMAS


def verify_descriptor(files: Mapping[str, bytes], descriptor: Mapping[str, object]) -> None:
    expected_keys = {
        "path",
        "media_type",
        "schema_version",
        "row_count",
        "byte_count",
        "sha256",
        "columns",
    }
    if set(descriptor) != expected_keys:
        raise ProjectExportVerificationError(
            "manifest file descriptor does not match the public field whitelist"
        )
    path = _text(descriptor["path"], "file path")
    content = _required_file(files, path)
    if descriptor["schema_version"] != PROJECT_EXPORT_SCHEMA_VERSION:
        raise ProjectExportVerificationError(f"{path} has an unsupported schema version")
    if _integer(descriptor["byte_count"], f"{path} byte_count") != len(content):
        raise ProjectExportVerificationError(f"{path} byte count mismatch")
    if descriptor["sha256"] != hashlib.sha256(content).hexdigest():
        raise ProjectExportVerificationError(f"{path} SHA-256 mismatch")
    media_type = "application/json" if path == DATA_JSON_PATH else "text/csv; charset=utf-8"
    if descriptor["media_type"] != media_type:
        raise ProjectExportVerificationError(f"{path} media type mismatch")
    expected_columns = [
        {"name": name, "type": value_type} for name, value_type in CSV_SCHEMAS.get(path, ())
    ]
    if descriptor["columns"] != expected_columns:
        raise ProjectExportVerificationError(f"{path} column schema mismatch")
    if _integer(descriptor["row_count"], f"{path} row_count") < 0:
        raise ProjectExportVerificationError(f"{path} row_count must be non-negative")


def _required_file(files: Mapping[str, bytes], path: str) -> bytes:
    try:
        value = files[path]
    except KeyError as exc:
        raise ProjectExportVerificationError(f"missing export file {path}") from exc
    if not isinstance(value, bytes):
        raise ProjectExportVerificationError(f"export file {path} must be bytes")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectExportVerificationError(f"{label} must be non-empty text")
    return value


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProjectExportVerificationError(f"{label} must be an integer")
    return value
