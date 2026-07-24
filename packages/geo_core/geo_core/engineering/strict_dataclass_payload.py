"""Closed JSON payload helpers for standard-library dataclass evidence contracts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from types import UnionType
from typing import Callable, Union, get_args, get_origin, get_type_hints


def close_dataclass_json_schema(payload: dict[str, object]) -> dict[str, object]:
    """Mark the root and every dataclass definition as a closed JSON object."""

    payload["additionalProperties"] = False
    definitions = payload.get("$defs")
    if isinstance(definitions, dict):
        for definition in definitions.values():
            if isinstance(definition, dict) and definition.get("type") == "object":
                definition["additionalProperties"] = False
    return payload


def reject_unknown_dataclass_fields(
    value: object,
    expected: object,
    *,
    path: str,
    error_factory: Callable[[str], Exception] = ValueError,
) -> None:
    """Reject fields TypeAdapter would otherwise ignore in nested dataclasses."""

    if isinstance(expected, type) and is_dataclass(expected):
        if not isinstance(value, dict):
            return
        hints = get_type_hints(expected)
        allowed = {item.name for item in fields(expected)}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise error_factory(f"unknown fields at {path}: {', '.join(unknown)}")
        for name, child in value.items():
            reject_unknown_dataclass_fields(
                child,
                hints[name],
                path=f"{path}.{name}",
                error_factory=error_factory,
            )
        return
    origin = get_origin(expected)
    if origin in (Union, UnionType):
        candidates = tuple(
            candidate
            for candidate in get_args(expected)
            if isinstance(candidate, type) and is_dataclass(candidate)
        )
        if isinstance(value, dict) and len(candidates) == 1:
            reject_unknown_dataclass_fields(
                value,
                candidates[0],
                path=path,
                error_factory=error_factory,
            )
        return
    if origin not in (tuple, list) or not isinstance(value, list):
        return
    arguments = get_args(expected)
    if not arguments:
        return
    item_type = arguments[0]
    for index, child in enumerate(value):
        reject_unknown_dataclass_fields(
            child,
            item_type,
            path=f"{path}[{index}]",
            error_factory=error_factory,
        )


__all__ = ["close_dataclass_json_schema", "reject_unknown_dataclass_fields"]
