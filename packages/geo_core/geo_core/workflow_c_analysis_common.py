"""Shared strict decoding and serialization primitives for Workflow C analysis."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import json
from typing import Any
from uuid import UUID

from geo_core.workflow_c_job_specs import WorkflowCJobSpecError


class WorkflowCAnalysisWorkerError(RuntimeError):
    """A frozen Workflow C analysis specification cannot be safely executed."""


def object_value(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WorkflowCJobSpecError(f"{label} must be an object")
    return value


def array_value(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise WorkflowCJobSpecError(f"{label} must be an array")
    return tuple(value)


def only_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise WorkflowCJobSpecError(f"{label} has an unexpected schema")


def text_value(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowCJobSpecError(f"{label} must be text")
    return value


def optional_text_value(value: object, label: str) -> str | None:
    return None if value is None else text_value(value, label)


def hash_value(value: object, label: str) -> str:
    text = text_value(value, label)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise WorkflowCJobSpecError(f"{label} must be a SHA-256 hash")
    return text


def integer_value(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise WorkflowCJobSpecError(f"{label} must be an integer")
    return value


def optional_integer_value(value: object, label: str) -> int | None:
    return None if value is None else integer_value(value, label)


def boolean_value(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise WorkflowCJobSpecError(f"{label} must be a boolean")
    return value


def uuid_value(value: object, label: str) -> UUID:
    if not isinstance(value, str):
        raise WorkflowCJobSpecError(f"{label} must be a UUID")
    try:
        return UUID(value)
    except ValueError as error:
        raise WorkflowCJobSpecError(f"{label} must be a UUID") from error


def decimal_value(value: object, label: str) -> Decimal:
    if not isinstance(value, str):
        raise WorkflowCJobSpecError(f"{label} must be a canonical decimal string")
    try:
        decimal = Decimal(value)
    except InvalidOperation as error:
        raise WorkflowCJobSpecError(f"{label} must be a decimal") from error
    if not decimal.is_finite():
        raise WorkflowCJobSpecError(f"{label} must be finite")
    return decimal


def ratio_decimal_value(value: object, label: str) -> Decimal:
    decimal = decimal_value(value, label)
    if not Decimal(0) <= decimal <= Decimal(1):
        raise WorkflowCJobSpecError(f"{label} must be in [0, 1]")
    return decimal


def mapping_row(cursor: Any) -> Mapping[str, object] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    if not isinstance(row, Mapping):
        raise WorkflowCAnalysisWorkerError("Workflow C analysis query must use mapping rows")
    return dict(row)


def json_value(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def canonical_json(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else json_value(value)


def decimal_equal(value: object, expected: Decimal) -> bool:
    if isinstance(value, Decimal):
        return value == expected
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        try:
            return Decimal(value) == expected
        except InvalidOperation:
            return False
    return False


__all__ = [
    "WorkflowCAnalysisWorkerError",
    "array_value",
    "boolean_value",
    "canonical_json",
    "decimal_equal",
    "decimal_value",
    "hash_value",
    "integer_value",
    "json_value",
    "mapping_row",
    "object_value",
    "only_keys",
    "optional_integer_value",
    "optional_text_value",
    "ratio_decimal_value",
    "text_value",
    "uuid_value",
]
