"""Shared scalar validation for immutable Model Gateway persistence contracts."""

from __future__ import annotations

from datetime import datetime
import re
from uuid import UUID

from geo_core.secrets.models import SecretVersionHandle


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def require_hash(value: str, label: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} hash must be lowercase SHA-256")


def require_uuid(value: UUID, label: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{label} ID must be a non-zero UUID")


def require_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} cannot be empty")


def require_data_decision(value: str) -> None:
    if value not in {"allowed", "prohibited"}:
        raise ValueError("raw-artifact storage decision must be allowed or prohibited")


def require_provider_secret_handle(
    handle: SecretVersionHandle,
    *,
    project_id: UUID,
    provider: str,
) -> None:
    if not isinstance(handle, SecretVersionHandle):
        raise ValueError("provider secret handle must be an immutable SecretVersionHandle")
    if handle.project_id != project_id:
        raise ValueError("provider secret handle project does not match model-call project")
    if handle.purpose != f"model_provider.{provider}":
        raise ValueError("provider secret handle purpose does not match model route")


def require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


__all__ = [
    "require_aware",
    "require_data_decision",
    "require_hash",
    "require_provider_secret_handle",
    "require_text",
    "require_uuid",
]
