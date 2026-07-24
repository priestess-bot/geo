"""Validation of the supported fail-closed JSON Schema definition subset."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
from typing import TypeGuard

from geo_core.model_gateway.contracts import OutputSchemaDefinitionError


_ANNOTATION_KEYWORDS = {
    "$schema",
    "$id",
    "$comment",
    "title",
    "description",
    "default",
    "examples",
    "deprecated",
    "readOnly",
    "writeOnly",
}
_SUPPORTED_KEYWORDS = _ANNOTATION_KEYWORDS | {
    "$ref",
    "$defs",
    "type",
    "enum",
    "const",
    "required",
    "properties",
    "additionalProperties",
    "minProperties",
    "maxProperties",
    "dependentRequired",
    "items",
    "prefixItems",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
}
_JSON_TYPES = {"null", "boolean", "object", "array", "number", "integer", "string"}
_FORMATS = {"uuid", "date-time", "uri", "email"}


def validate_output_schema_definition(schema: Mapping[str, object]) -> None:
    """Validate all schema branches before a paid provider call is made.

    This intentionally supports a documented, deterministic subset of JSON Schema
    Draft 2020-12. Unknown assertion keywords fail closed instead of being silently
    ignored. Boolean schemas and local JSON Pointer references are supported.
    """

    _check_schema(schema, path="$", root=schema, depth=0)


def resolve_schema_reference(root: Mapping[str, object], reference: str) -> object:
    if reference == "#":
        return root
    if not reference.startswith("#/"):
        raise OutputSchemaDefinitionError(
            f"output schema reference is not a local JSON Pointer: {reference}"
        )
    current: object = root
    for raw_token in reference[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or token not in current:
            raise OutputSchemaDefinitionError(
                f"output schema reference does not exist: {reference}"
            )
        current = current[token]
    if not isinstance(current, (Mapping, bool)):
        raise OutputSchemaDefinitionError(
            f"output schema reference does not point to a schema: {reference}"
        )
    return current


def _check_schema(
    schema: object,
    *,
    path: str,
    root: Mapping[str, object],
    depth: int,
) -> None:
    _guard_depth(depth)
    if isinstance(schema, bool):
        return
    if not isinstance(schema, Mapping):
        raise OutputSchemaDefinitionError(f"output schema {path} must be an object or boolean")
    unknown = sorted(str(key) for key in schema if key not in _SUPPORTED_KEYWORDS)
    if unknown:
        raise OutputSchemaDefinitionError(
            f"output schema {path} uses unsupported keyword: {unknown[0]}"
        )
    _check_type_keyword(schema.get("type"), path=path)
    _check_nonnegative_integer_keywords(
        schema,
        path=path,
        names=("minProperties", "maxProperties", "minItems", "maxItems", "minLength", "maxLength"),
    )
    _check_minimum_not_above_maximum(
        schema, path=path, minimum="minProperties", maximum="maxProperties"
    )
    _check_minimum_not_above_maximum(schema, path=path, minimum="minItems", maximum="maxItems")
    _check_minimum_not_above_maximum(schema, path=path, minimum="minLength", maximum="maxLength")
    _check_numeric_keywords(schema, path=path)
    if "required" in schema:
        _require_unique_strings(schema["required"], path=f"{path}.required")
    if "enum" in schema:
        enum = schema["enum"]
        if not _is_schema_array(enum) or not enum:
            raise OutputSchemaDefinitionError(
                f"output schema {path}.enum must be a non-empty array"
            )
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping) or not all(
            isinstance(name, str) for name in properties
        ):
            raise OutputSchemaDefinitionError(
                f"output schema {path}.properties must be an object with string keys"
            )
        for name, child in properties.items():
            _check_schema(child, path=f"{path}.properties.{name}", root=root, depth=depth + 1)
    if "additionalProperties" in schema:
        _check_schema(
            schema["additionalProperties"],
            path=f"{path}.additionalProperties",
            root=root,
            depth=depth + 1,
        )
    dependent = schema.get("dependentRequired")
    if dependent is not None:
        if not isinstance(dependent, Mapping) or not all(
            isinstance(name, str) for name in dependent
        ):
            raise OutputSchemaDefinitionError(
                f"output schema {path}.dependentRequired must be an object"
            )
        for name, required in dependent.items():
            _require_unique_strings(required, path=f"{path}.dependentRequired.{name}")
    if "items" in schema:
        _check_schema(schema["items"], path=f"{path}.items", root=root, depth=depth + 1)
    prefix_items = schema.get("prefixItems")
    if prefix_items is not None:
        _require_schema_array(prefix_items, path=f"{path}.prefixItems")
        for index, child in enumerate(prefix_items):
            _check_schema(
                child,
                path=f"{path}.prefixItems[{index}]",
                root=root,
                depth=depth + 1,
            )
    for keyword in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(keyword)
        if branches is None:
            continue
        _require_schema_array(branches, path=f"{path}.{keyword}")
        for index, child in enumerate(branches):
            _check_schema(
                child,
                path=f"{path}.{keyword}[{index}]",
                root=root,
                depth=depth + 1,
            )
    if "not" in schema:
        _check_schema(schema["not"], path=f"{path}.not", root=root, depth=depth + 1)
    definitions = schema.get("$defs")
    if definitions is not None:
        if not isinstance(definitions, Mapping) or not all(
            isinstance(name, str) for name in definitions
        ):
            raise OutputSchemaDefinitionError(f"output schema {path}.$defs must be an object")
        for name, child in definitions.items():
            _check_schema(child, path=f"{path}.$defs.{name}", root=root, depth=depth + 1)
    reference = schema.get("$ref")
    if reference is not None:
        if not isinstance(reference, str) or not reference.startswith("#"):
            raise OutputSchemaDefinitionError(
                f"output schema {path} only supports local JSON Pointer references"
            )
        resolve_schema_reference(root, reference)
    _check_pattern(schema.get("pattern"), path=path)
    format_name = schema.get("format")
    if format_name is not None and (
        not isinstance(format_name, str) or format_name not in _FORMATS
    ):
        raise OutputSchemaDefinitionError(
            f"output schema {path}.format is unsupported: {format_name}"
        )
    unique_items = schema.get("uniqueItems")
    if unique_items is not None and not isinstance(unique_items, bool):
        raise OutputSchemaDefinitionError(f"output schema {path}.uniqueItems must be a boolean")


def _check_pattern(pattern: object, *, path: str) -> None:
    if pattern is None:
        return
    if not isinstance(pattern, str):
        raise OutputSchemaDefinitionError(f"output schema {path}.pattern must be a string")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise OutputSchemaDefinitionError(
            f"output schema {path}.pattern is not a valid regular expression"
        ) from exc


def _check_type_keyword(value: object, *, path: str) -> None:
    if value is None:
        return
    names = [value] if isinstance(value, str) else value
    if (
        not _is_schema_array(names)
        or not names
        or not all(isinstance(name, str) and name in _JSON_TYPES for name in names)
    ):
        raise OutputSchemaDefinitionError(f"output schema {path}.type is invalid")
    if len(names) != len(set(names)):
        raise OutputSchemaDefinitionError(f"output schema {path}.type contains duplicates")


def _check_nonnegative_integer_keywords(
    schema: Mapping[str, object], *, path: str, names: tuple[str, ...]
) -> None:
    for name in names:
        value = schema.get(name)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise OutputSchemaDefinitionError(
                f"output schema {path}.{name} must be a non-negative integer"
            )


def _check_minimum_not_above_maximum(
    schema: Mapping[str, object], *, path: str, minimum: str, maximum: str
) -> None:
    lower = schema.get(minimum)
    upper = schema.get(maximum)
    if isinstance(lower, int) and isinstance(upper, int) and lower > upper:
        raise OutputSchemaDefinitionError(f"output schema {path}.{minimum} cannot exceed {maximum}")


def _check_numeric_keywords(schema: Mapping[str, object], *, path: str) -> None:
    for name in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"):
        value = schema.get(name)
        if value is not None and not _is_number(value):
            raise OutputSchemaDefinitionError(f"output schema {path}.{name} must be a number")
        if _is_number(value) and not math.isfinite(float(value)):
            raise OutputSchemaDefinitionError(f"output schema {path}.{name} must be finite")
        if name == "multipleOf" and _is_number(value) and float(value) <= 0:
            raise OutputSchemaDefinitionError(
                f"output schema {path}.multipleOf must be greater than zero"
            )


def _require_unique_strings(value: object, *, path: str) -> None:
    if not _is_schema_array(value) or not all(isinstance(item, str) for item in value):
        raise OutputSchemaDefinitionError(f"output schema {path} must be an array of strings")
    if len(value) != len(set(value)):
        raise OutputSchemaDefinitionError(f"output schema {path} contains duplicates")


def _require_schema_array(value: object, *, path: str) -> None:
    if not _is_schema_array(value) or not value:
        raise OutputSchemaDefinitionError(f"output schema {path} must be a non-empty array")


def _is_schema_array(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _guard_depth(depth: int) -> None:
    if depth > 128:
        raise OutputSchemaDefinitionError("output schema exceeds the maximum nesting depth")


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
