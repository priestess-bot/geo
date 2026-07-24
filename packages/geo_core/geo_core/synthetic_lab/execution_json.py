"""Closed-world immutable JSON values used by synthetic execution contracts."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from geo_core.synthetic_lab.domain import SyntheticLabContractError


def freeze_execution_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(
        {str(key): _freeze_execution_json(item) for key, item in value.items()}
    )


def _freeze_execution_json(value: object) -> object:
    if isinstance(value, Mapping):
        return freeze_execution_mapping(value)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_execution_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise SyntheticLabContractError("execution JSON contains an unsupported value")


__all__ = ["freeze_execution_mapping"]
