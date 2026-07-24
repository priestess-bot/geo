"""Fail-closed application validation for the structured-output schema subset."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import math
import re
from typing import TypeGuard
from urllib.parse import urlparse
from uuid import UUID

from geo_core.model_gateway._schema_definition import (
    resolve_schema_reference,
    validate_output_schema_definition,
)
from geo_core.model_gateway.contracts import (
    OutputSchemaDefinitionError,
    StructuredOutputValidationError,
)
from geo_core.model_gateway.identity import canonical_json_hash


_NON_PORTABLE_ASSERTIONS = frozenset(
    {
        "const",
        "dependentRequired",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "multipleOf",
        "pattern",
        "prefixItems",
        "uniqueItems",
    }
)


def validate_structured_output(output: Mapping[str, object], schema: Mapping[str, object]) -> None:
    """Validate a provider object against a previously frozen schema."""

    validate_output_schema_definition(schema)
    _validate_json_value(output, path="$", depth=0)
    _validate_instance(output, schema, path="$", root=schema, depth=0)


def validate_output_schema_pair(
    provider_schema: Mapping[str, object],
    application_schema: Mapping[str, object],
) -> None:
    """Require the application schema to preserve or strengthen Provider assertions.

    General JSON Schema subsumption is undecidable. This performs a conservative
    proof over the supported subset and rejects pairs it cannot prove safe.
    """
    validate_output_schema_definition(provider_schema)
    validate_output_schema_definition(application_schema)
    projected = project_provider_output_schema(application_schema)
    if canonical_json_hash(projected) != canonical_json_hash(provider_schema):
        raise OutputSchemaDefinitionError(
            "Provider output schema is not the canonical projection of the "
            "application output schema"
        )


def project_provider_output_schema(
    application_schema: Mapping[str, object],
) -> dict[str, object]:
    """Remove only assertions excluded by the frozen Provider-portable contract."""
    validate_output_schema_definition(application_schema)
    projected = _portable_schema_value(application_schema)
    if not isinstance(projected, dict):
        raise OutputSchemaDefinitionError("Provider output schema projection is not an object")
    validate_output_schema_definition(projected)
    return projected


def _portable_schema_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _portable_schema_value(item)
            for key, item in value.items()
            if key not in _NON_PORTABLE_ASSERTIONS
        }
    if isinstance(value, (list, tuple)):
        return [_portable_schema_value(item) for item in value]
    return value


def _validate_instance(
    instance: object,
    schema: object,
    *,
    path: str,
    root: Mapping[str, object],
    depth: int,
) -> None:
    _guard_depth(depth)
    if schema is True:
        return
    if schema is False:
        _invalid(path, "is rejected by a false schema")
    assert isinstance(schema, Mapping)
    reference = schema.get("$ref")
    if isinstance(reference, str):
        _validate_instance(
            instance,
            resolve_schema_reference(root, reference),
            path=path,
            root=root,
            depth=depth + 1,
        )
    expected = schema.get("type")
    if expected is not None and not _matches_type(instance, expected):
        _invalid(path, f"must have JSON type {_type_label(expected)}")
    enum = schema.get("enum")
    if _is_schema_array(enum) and not any(
        _json_equal(instance, member) for member in enum
    ):
        _invalid(path, "is not one of the allowed enum values")
    if "const" in schema and not _json_equal(instance, schema["const"]):
        _invalid(path, "does not equal the required const value")
    _validate_combinators(instance, schema, path=path, root=root, depth=depth)
    if isinstance(instance, Mapping):
        _validate_object(instance, schema, path=path, root=root, depth=depth)
    elif isinstance(instance, list):
        _validate_array(instance, schema, path=path, root=root, depth=depth)
    elif isinstance(instance, str):
        _validate_string(instance, schema, path=path)
    elif _is_number(instance):
        _validate_number(instance, schema, path=path)


def _validate_object(
    instance: Mapping[object, object],
    schema: Mapping[str, object],
    *,
    path: str,
    root: Mapping[str, object],
    depth: int,
) -> None:
    if not all(isinstance(name, str) for name in instance):
        _invalid(path, "must use string object keys")
    minimum = schema.get("minProperties")
    maximum = schema.get("maxProperties")
    if isinstance(minimum, int) and len(instance) < minimum:
        _invalid(path, f"must contain at least {minimum} properties")
    if isinstance(maximum, int) and len(instance) > maximum:
        _invalid(path, f"must contain at most {maximum} properties")
    required = schema.get("required", ())
    assert _is_schema_array(required)
    missing = [name for name in required if name not in instance]
    if missing:
        _invalid(path, f"is missing required property {missing[0]}")
    properties = schema.get("properties", {})
    assert isinstance(properties, Mapping)
    for name, child_schema in properties.items():
        if name in instance:
            _validate_instance(
                instance[name],
                child_schema,
                path=f"{path}.{name}",
                root=root,
                depth=depth + 1,
            )
    additional = schema.get("additionalProperties", True)
    for name, value in instance.items():
        if name in properties:
            continue
        if additional is False:
            _invalid(path, f"contains unexpected property {name}")
        if additional is not True:
            _validate_instance(
                value,
                additional,
                path=f"{path}.{name}",
                root=root,
                depth=depth + 1,
            )
    dependent = schema.get("dependentRequired", {})
    assert isinstance(dependent, Mapping)
    for trigger, dependencies in dependent.items():
        if trigger not in instance:
            continue
        assert _is_schema_array(dependencies)
        for dependency in dependencies:
            if dependency not in instance:
                _invalid(path, f"property {trigger} requires property {dependency}")


def _validate_array(
    instance: list[object],
    schema: Mapping[str, object],
    *,
    path: str,
    root: Mapping[str, object],
    depth: int,
) -> None:
    minimum = schema.get("minItems")
    maximum = schema.get("maxItems")
    if isinstance(minimum, int) and len(instance) < minimum:
        _invalid(path, f"must contain at least {minimum} items")
    if isinstance(maximum, int) and len(instance) > maximum:
        _invalid(path, f"must contain at most {maximum} items")
    if schema.get("uniqueItems") is True:
        for index, item in enumerate(instance):
            if any(_json_equal(item, earlier) for earlier in instance[:index]):
                _invalid(path, "must contain unique items")
    prefix_items = schema.get("prefixItems", [])
    assert _is_schema_array(prefix_items)
    for index, child_schema in enumerate(prefix_items):
        if index >= len(instance):
            break
        _validate_instance(
            instance[index],
            child_schema,
            path=f"{path}[{index}]",
            root=root,
            depth=depth + 1,
        )
    item_schema = schema.get("items")
    if item_schema is not None:
        for index in range(len(prefix_items), len(instance)):
            _validate_instance(
                instance[index],
                item_schema,
                path=f"{path}[{index}]",
                root=root,
                depth=depth + 1,
            )


def _validate_string(value: str, schema: Mapping[str, object], *, path: str) -> None:
    minimum = schema.get("minLength")
    maximum = schema.get("maxLength")
    if isinstance(minimum, int) and len(value) < minimum:
        _invalid(path, f"must contain at least {minimum} characters")
    if isinstance(maximum, int) and len(value) > maximum:
        _invalid(path, f"must contain at most {maximum} characters")
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and re.search(pattern, value) is None:
        _invalid(path, "does not match the required pattern")
    format_name = schema.get("format")
    if format_name == "uuid":
        try:
            UUID(value)
        except ValueError:
            _invalid(path, "must be a UUID")
    elif format_name == "date-time":
        try:
            parsed_datetime = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            _invalid(path, "must be an RFC 3339 date-time")
        if "T" not in value or parsed_datetime.tzinfo is None:
            _invalid(path, "must be an RFC 3339 date-time")
    elif format_name == "uri":
        parsed_uri = urlparse(value)
        if not parsed_uri.scheme:
            _invalid(path, "must be an absolute URI")
    elif format_name == "email" and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is None:
        _invalid(path, "must be an email address")


def _validate_number(value: object, schema: Mapping[str, object], *, path: str) -> None:
    assert _is_number(value)
    number = float(value)
    if not math.isfinite(number):
        _invalid(path, "must be a finite JSON number")
    comparisons = (
        ("minimum", lambda bound: number >= bound, ">="),
        ("maximum", lambda bound: number <= bound, "<="),
        ("exclusiveMinimum", lambda bound: number > bound, ">"),
        ("exclusiveMaximum", lambda bound: number < bound, "<"),
    )
    for keyword, predicate, symbol in comparisons:
        bound = schema.get(keyword)
        if _is_number(bound) and not predicate(float(bound)):
            _invalid(path, f"must be {symbol} {bound}")
    multiple = schema.get("multipleOf")
    if _is_number(multiple):
        quotient = number / float(multiple)
        if not math.isclose(quotient, round(quotient), rel_tol=1e-12, abs_tol=1e-12):
            _invalid(path, f"must be a multiple of {multiple}")


def _validate_combinators(
    instance: object,
    schema: Mapping[str, object],
    *,
    path: str,
    root: Mapping[str, object],
    depth: int,
) -> None:
    for keyword, expected_matches in (("allOf", None), ("anyOf", "at_least_one"), ("oneOf", 1)):
        branches = schema.get(keyword)
        if not _is_schema_array(branches):
            continue
        matches = 0
        for child in branches:
            try:
                _validate_instance(
                    instance,
                    child,
                    path=path,
                    root=root,
                    depth=depth + 1,
                )
            except StructuredOutputValidationError:
                if keyword == "allOf":
                    _invalid(path, "does not satisfy every allOf branch")
            else:
                matches += 1
        if expected_matches == "at_least_one" and matches == 0:
            _invalid(path, "does not satisfy any anyOf branch")
        if expected_matches == 1 and matches != 1:
            _invalid(path, "must satisfy exactly one oneOf branch")
    if "not" in schema:
        try:
            _validate_instance(
                instance,
                schema["not"],
                path=path,
                root=root,
                depth=depth + 1,
            )
        except StructuredOutputValidationError:
            pass
        else:
            _invalid(path, "must not satisfy the excluded schema")


def _matches_type(instance: object, expected: object) -> bool:
    names = [expected] if isinstance(expected, str) else expected
    assert _is_schema_array(names)
    return any(_matches_single_type(instance, name) for name in names)


def _matches_single_type(instance: object, name: object) -> bool:
    if name == "null":
        return instance is None
    if name == "boolean":
        return isinstance(instance, bool)
    if name == "object":
        return isinstance(instance, Mapping)
    if name == "array":
        return isinstance(instance, list)
    if name == "number":
        return _is_number(instance)
    if name == "integer":
        return (
            isinstance(instance, int)
            and not isinstance(instance, bool)
            or (isinstance(instance, float) and math.isfinite(instance) and instance.is_integer())
        )
    if name == "string":
        return isinstance(instance, str)
    return False


def _type_label(value: object) -> str:
    if isinstance(value, str):
        return value
    assert _is_schema_array(value)
    return " or ".join(str(item) for item in value)


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_schema_array(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _json_equal(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if _is_number(left) and _is_number(right):
        return float(left) == float(right)
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(_json_equal(left[key], right[key]) for key in left)
    if _is_schema_array(left) and _is_schema_array(right):
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


def _guard_depth(depth: int) -> None:
    if depth > 128:
        raise StructuredOutputValidationError("structured output exceeds the maximum nesting depth")


def _validate_json_value(value: object, *, path: str, depth: int) -> None:
    _guard_depth(depth)
    if value is None or isinstance(value, (str, bool)):
        return
    if _is_number(value):
        if not math.isfinite(float(value)):
            _invalid(path, "contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]", depth=depth + 1)
        return
    if isinstance(value, Mapping):
        for name, item in value.items():
            if not isinstance(name, str):
                _invalid(path, "must use string object keys")
            _validate_json_value(item, path=f"{path}.{name}", depth=depth + 1)
        return
    _invalid(path, "contains a non-JSON value")


def _invalid(path: str, message: str) -> None:
    raise StructuredOutputValidationError(f"structured output {path} {message}")
