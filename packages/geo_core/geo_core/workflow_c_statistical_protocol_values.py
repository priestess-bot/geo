"""Strict scalar and persisted-row values for statistical protocols."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import re
from typing import TypeVar
from uuid import UUID


_KEY = re.compile(r"^[a-z][a-z0-9_.:-]{0,199}$")
_E = TypeVar("_E", bound=StrEnum)


class StatisticalProtocolError(ValueError):
    """A statistical release or lifecycle command is invalid."""


def schema_one(value: Mapping[str, object]) -> None:
    if value.get("schema_version") != 1:
        raise StatisticalProtocolError("statistical protocol schema is invalid")


def only_keys(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise StatisticalProtocolError("statistical protocol fields are invalid")


def enum_value(enum_type: type[_E], value: object, label: str) -> _E:
    if not isinstance(value, str):
        raise StatisticalProtocolError(f"{label} is invalid")
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise StatisticalProtocolError(f"{label} is invalid") from error


def decimal_value(row: Mapping[str, object], key: str) -> Decimal:
    value = row.get(key)
    if not isinstance(value, str):
        raise StatisticalProtocolError(f"{key} must be a canonical decimal string")
    try:
        result = Decimal(value)
    except Exception as error:
        raise StatisticalProtocolError(f"{key} is invalid") from error
    if not result.is_finite():
        raise StatisticalProtocolError(f"{key} must be finite")
    return result


def integer_value(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StatisticalProtocolError(f"{key} must be a positive integer")
    return value


def text_value(value: object, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise StatisticalProtocolError(f"{label} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise StatisticalProtocolError(f"{label} is invalid")
    return normalized


def key_value(value: object, label: str) -> str:
    normalized = text_value(value, label, maximum=200)
    if not _KEY.fullmatch(normalized):
        raise StatisticalProtocolError(f"{label} is invalid")
    return normalized


def row_text(row: Mapping[str, object], key: str) -> str:
    return text_value(row.get(key), key, maximum=2_000)


def optional_text(row: Mapping[str, object], key: str) -> str | None:
    return None if row.get(key) is None else row_text(row, key)


def uuid_value(row: Mapping[str, object], key: str) -> UUID:
    value = row.get(key)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise StatisticalProtocolError(f"{key} is invalid") from error


def optional_uuid(row: Mapping[str, object], key: str) -> UUID | None:
    return None if row.get(key) is None else uuid_value(row, key)


def datetime_value(row: Mapping[str, object], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime):
        raise StatisticalProtocolError(f"{key} is invalid")
    require_aware(value, key)
    return value


def optional_datetime(row: Mapping[str, object], key: str) -> datetime | None:
    return None if row.get(key) is None else datetime_value(row, key)


def require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise StatisticalProtocolError(f"{label} must be timezone-aware")


def mapping_value(value: object | None) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StatisticalProtocolError("statistical protocol row is malformed")
    return value


def idempotency_hash(value: str) -> str:
    normalized = text_value(value, "Idempotency-Key", maximum=200)
    return hashlib.sha256(normalized.encode()).hexdigest()


__all__ = [
    "StatisticalProtocolError",
    "datetime_value",
    "decimal_value",
    "enum_value",
    "idempotency_hash",
    "integer_value",
    "key_value",
    "mapping_value",
    "only_keys",
    "optional_datetime",
    "optional_text",
    "optional_uuid",
    "require_aware",
    "row_text",
    "schema_one",
    "text_value",
    "uuid_value",
]
