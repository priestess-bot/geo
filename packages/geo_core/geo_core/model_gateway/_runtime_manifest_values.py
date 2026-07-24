"""Strict scalar parsing helpers for the runtime manifest schema."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID


class RuntimeManifestValueError(ValueError):
    pass


def exact_object(
    value: object, *, label: str, keys: set[str]
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise RuntimeManifestValueError(f"{label} must be an object")
    if set(value) != keys:
        raise RuntimeManifestValueError(f"{label} fields differ from the frozen schema")
    return value


def array(value: object, label: str) -> list[object]:
    if not isinstance(value, list) or not value:
        raise RuntimeManifestValueError(f"{label} must be a non-empty array")
    return value


def list_value(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise RuntimeManifestValueError(f"{label} must be an array")
    return value


def text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeManifestValueError(f"{label} must be non-empty text")
    return value.strip()


def uuid_value(value: object, label: str) -> UUID:
    try:
        parsed = UUID(text(value, label))
    except ValueError:
        raise RuntimeManifestValueError(f"{label} must be a UUID") from None
    if parsed.int == 0:
        raise RuntimeManifestValueError(f"{label} cannot be zero")
    return parsed


def datetime_value(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(text(value, label).replace("Z", "+00:00"))
    except ValueError:
        raise RuntimeManifestValueError(f"{label} must be ISO-8601") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeManifestValueError(f"{label} must be timezone-aware")
    return parsed


def integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RuntimeManifestValueError(f"{label} must be a positive integer")
    return value


def boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeManifestValueError(f"{label} must be boolean")
    return value


__all__ = [
    "RuntimeManifestValueError",
    "array",
    "boolean",
    "datetime_value",
    "exact_object",
    "integer",
    "list_value",
    "text",
    "uuid_value",
]
