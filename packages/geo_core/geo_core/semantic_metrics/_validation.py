"""Shared validation and canonicalization primitives for semantic metrics."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import hashlib
import json
import re
from types import MappingProxyType


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,199}$")


class SemanticMetricRuleViolation(ValueError):
    """A semantic metric contract is incomplete or internally inconsistent."""


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def decimal_value(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def aliases(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted({text(item, label).casefold() for item in values}))
    if not normalized:
        raise SemanticMetricRuleViolation(f"{label} must not be empty")
    return normalized


def key(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if not KEY_PATTERN.fullmatch(normalized):
        raise SemanticMetricRuleViolation(f"{label} is invalid")
    return normalized


def text(value: str, label: str, *, maximum: int = 500) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise SemanticMetricRuleViolation(
            f"{label} is required and must be at most {maximum} characters"
        )
    return normalized


def optional_text(value: str | None, label: str) -> str | None:
    return text(value, label) if value is not None else None


def finite(value: Decimal, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise SemanticMetricRuleViolation(f"{label} must be a finite Decimal")


def ratio(value: Decimal, label: str) -> None:
    finite(value, label)
    if not Decimal(0) <= value <= Decimal(1):
        raise SemanticMetricRuleViolation(f"{label} must be in [0, 1]")


def freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(values))
