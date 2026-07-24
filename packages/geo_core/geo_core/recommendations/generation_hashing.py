"""Canonical JSON, hashes, and immutable scalar helpers for generation contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from uuid import UUID

from geo_core.recommendations.errors import RecommendationRuleViolation


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def idempotency_hash(value: str) -> str:
    return text_hash(required(value, "generation Idempotency-Key"))


def canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [canonical_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"{type(value).__name__} is not canonically serializable")


def json_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    canonical = canonical_value(value)
    if not isinstance(canonical, dict):
        raise RecommendationRuleViolation("structured schema must be an object")
    return MappingProxyType(canonical)


def locator(value: Mapping[str, str], label: str) -> Mapping[str, str]:
    normalized = {
        required(key, f"{label} locator key"): required(item, f"{label} locator value")
        for key, item in value.items()
    }
    if not normalized:
        raise RecommendationRuleViolation(f"{label} locator is required")
    return MappingProxyType(dict(sorted(normalized.items())))


def require_hash(value: str, label: str) -> None:
    if not _SHA256.fullmatch(value):
        raise RecommendationRuleViolation(f"{label} must be lowercase SHA-256")


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RecommendationRuleViolation(f"{label} is required")
    return normalized


__all__ = ["canonical_hash", "idempotency_hash"]
