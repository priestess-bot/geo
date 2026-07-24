"""Canonical, secret-safe identity hashing for model-call contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from uuid import UUID


def canonical_json_hash(value: object) -> str:
    try:
        encoded = json.dumps(
            _plain_json(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("model-call value is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def hash_secret_identifier(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("model-call idempotency key cannot be empty")
    return hashlib.sha256(normalized.encode()).hexdigest()


def _plain_json(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical datetime must be timezone-aware")
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("canonical JSON object keys must be strings")
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    raise ValueError("model-call value is not JSON-compatible")


__all__ = ["canonical_json_hash", "hash_secret_identifier"]
