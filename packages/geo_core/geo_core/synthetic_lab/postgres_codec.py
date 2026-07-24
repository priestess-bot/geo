"""Closed-world JSON codec for Synthetic Lab persistence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
import importlib
import inspect
import json
import math
from typing import Any
from uuid import UUID

from geo_core.secrets.models import SecretVersionHandle
from geo_core.synthetic_lab.ports import SyntheticLabPersistenceError


_ALLOWED_MODULES = (
    "geo_core.jobs.lifecycle",
    "geo_core.jobs.postgres",
    "geo_core.model_gateway.contracts",
    "geo_core.model_gateway.releases",
    "geo_core.prompts.program_contracts",
    "geo_core.synthetic_lab.application_support",
    "geo_core.synthetic_lab.authorization",
    "geo_core.synthetic_lab.collection_execution_contracts",
    "geo_core.synthetic_lab.child_model_calls",
    "geo_core.synthetic_lab.corpus",
    "geo_core.synthetic_lab.domain",
    "geo_core.synthetic_lab.evaluation",
    "geo_core.synthetic_lab.execution_contracts",
    "geo_core.synthetic_lab.generation",
    "geo_core.synthetic_lab.offline_experiment",
    "geo_core.synthetic_lab.offline_results",
    "geo_core.synthetic_lab.ports",
    "geo_core.synthetic_lab.raw_artifact_governance",
    "geo_core.synthetic_lab.review_cases",
    "geo_core.synthetic_lab.revision",
    "geo_core.synthetic_lab.sample_import",
    "geo_core.synthetic_lab.style_application",
)

_ALLOWED_TYPES = (SecretVersionHandle,)


def _registry() -> dict[str, type[Any]]:
    registered: dict[str, type[Any]] = {
        f"{candidate.__module__}.{candidate.__qualname__}": candidate
        for candidate in _ALLOWED_TYPES
    }
    for module_name in _ALLOWED_MODULES:
        module = importlib.import_module(module_name)
        for candidate in vars(module).values():
            if not inspect.isclass(candidate) or candidate.__module__ != module_name:
                continue
            if not (is_dataclass(candidate) or issubclass(candidate, Enum)):
                continue
            type_name = f"{module_name}.{candidate.__qualname__}"
            registered[type_name] = candidate
    return registered


_TYPES = _registry()


def encode_object(value: object) -> tuple[str, dict[str, object], str]:
    """Return the registered root type, tagged JSON payload, and canonical hash."""

    type_name = _type_name(value)
    payload = _encode(value)
    if not isinstance(payload, dict):
        raise SyntheticLabPersistenceError("Synthetic Lab persisted roots must be structured")
    return type_name, payload, payload_hash(payload)


def decode_object(type_name: str, payload: Mapping[str, object]) -> object:
    expected = _TYPES.get(type_name)
    if expected is None:
        raise SyntheticLabPersistenceError("stored Synthetic Lab result type is not registered")
    value = _decode(dict(payload))
    if not isinstance(value, expected):
        raise SyntheticLabPersistenceError("stored Synthetic Lab result type does not match payload")
    return value


def payload_hash(payload: Mapping[str, object]) -> str:
    from hashlib import sha256

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _type_name(value: object) -> str:
    name = f"{type(value).__module__}.{type(value).__qualname__}"
    if _TYPES.get(name) is not type(value):
        raise SyntheticLabPersistenceError(
            f"Synthetic Lab persistence type is not registered: {type(value).__name__}"
        )
    return name


def _encode(value: object) -> object:
    if isinstance(value, UUID):
        return {"$uuid": str(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise SyntheticLabPersistenceError("Synthetic Lab datetime must be timezone-aware")
        return {"$datetime": value.isoformat()}
    if isinstance(value, Enum):
        return {"$enum": _type_name(value), "value": _encode(value.value)}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SyntheticLabPersistenceError("Synthetic Lab JSON cannot contain NaN/Infinity")
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "$type": _type_name(value),
            "fields": {
                item.name: _encode(getattr(value, item.name))
                for item in fields(value)
                if item.init
            },
        }
    if isinstance(value, Mapping):
        return {
            "$map": [
                [_encode(key), _encode(item)]
                for key, item in sorted(
                    value.items(), key=lambda pair: _sort_key(_encode(pair[0]))
                )
            ]
        }
    if isinstance(value, tuple):
        return {"$tuple": [_encode(item) for item in value]}
    if isinstance(value, list):
        return {"$list": [_encode(item) for item in value]}
    if isinstance(value, (set, frozenset)):
        items = sorted((_encode(item) for item in value), key=_sort_key)
        return {"$frozenset" if isinstance(value, frozenset) else "$set": items}
    if isinstance(value, bytes):
        raise SyntheticLabPersistenceError("Synthetic Lab persistence rejects byte payloads")
    raise SyntheticLabPersistenceError(
        f"Synthetic Lab value is not JSON-safe: {type(value).__name__}"
    )


def _decode(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        raise SyntheticLabPersistenceError("untagged Synthetic Lab JSON arrays are invalid")
    if not isinstance(value, dict):
        raise SyntheticLabPersistenceError("stored Synthetic Lab JSON shape is invalid")
    if set(value) == {"$uuid"}:
        return UUID(_string(value["$uuid"], "UUID"))
    if set(value) == {"$datetime"}:
        parsed = datetime.fromisoformat(_string(value["$datetime"], "datetime"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise SyntheticLabPersistenceError("stored Synthetic Lab datetime is naive")
        return parsed
    if set(value) == {"$enum", "value"}:
        enum_type = _registered(_string(value["$enum"], "enum"), enum=True)
        return enum_type(_decode(value["value"]))
    if set(value) == {"$type", "fields"}:
        data_type = _registered(_string(value["$type"], "type"), enum=False)
        raw_fields = value["fields"]
        if not isinstance(raw_fields, dict):
            raise SyntheticLabPersistenceError("stored Synthetic Lab fields are invalid")
        allowed = {item.name for item in fields(data_type) if item.init}
        if set(raw_fields) != allowed:
            raise SyntheticLabPersistenceError("stored Synthetic Lab field set changed")
        return data_type(**{key: _decode(item) for key, item in raw_fields.items()})
    if set(value) == {"$map"}:
        pairs = value["$map"]
        if not isinstance(pairs, list):
            raise SyntheticLabPersistenceError("stored Synthetic Lab map is invalid")
        result: dict[object, object] = {}
        for pair in pairs:
            if not isinstance(pair, list) or len(pair) != 2:
                raise SyntheticLabPersistenceError("stored Synthetic Lab map entry is invalid")
            key = _decode(pair[0])
            if key in result:
                raise SyntheticLabPersistenceError("stored Synthetic Lab map has duplicate keys")
            result[key] = _decode(pair[1])
        return result
    for tag, constructor in (
        ("$tuple", tuple),
        ("$list", list),
        ("$set", set),
        ("$frozenset", frozenset),
    ):
        if set(value) == {tag}:
            items = value[tag]
            if not isinstance(items, list):
                raise SyntheticLabPersistenceError("stored Synthetic Lab sequence is invalid")
            return constructor(_decode(item) for item in items)
    raise SyntheticLabPersistenceError("stored Synthetic Lab JSON tag is invalid")


def _registered(type_name: str, *, enum: bool) -> type[Any]:
    candidate = _TYPES.get(type_name)
    if candidate is None or (issubclass(candidate, Enum) is not enum):
        raise SyntheticLabPersistenceError("stored Synthetic Lab type is not registered")
    return candidate


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SyntheticLabPersistenceError(f"stored Synthetic Lab {label} is invalid")
    return value


def _sort_key(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = ["decode_object", "encode_object", "payload_hash"]
