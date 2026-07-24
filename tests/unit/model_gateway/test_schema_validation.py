from __future__ import annotations

from types import MappingProxyType

import pytest

from geo_core.model_gateway import (
    ModelGatewayErrorCode,
    OutputSchemaDefinitionError,
    StructuredOutputValidationError,
    validate_output_schema_definition,
    validate_structured_output,
)
from geo_core.model_gateway.schema_validation import validate_output_schema_pair


SCHEMA = {
    "$defs": {
        "claim": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "kind", "confidence"],
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "kind": {"enum": ["fact", "experience"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        }
    },
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "claims", "status"],
    "properties": {
        "title": {"type": "string", "minLength": 3, "pattern": "^[A-Z]"},
        "claims": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"$ref": "#/$defs/claim"},
        },
        "status": {
            "oneOf": [
                {"const": "passed"},
                {"const": "completed_with_warning"},
            ]
        },
        "note": {"type": ["string", "null"], "maxLength": 100},
    },
}


def _valid_output() -> dict[str, object]:
    return {
        "title": "Australian review",
        "claims": [
            {
                "id": "8bb80991-8d73-421a-84ae-f029c0c5c40d",
                "kind": "experience",
                "confidence": 0.8,
            }
        ],
        "status": "passed",
        "note": None,
    }


def test_nested_schema_refs_formats_and_combinators_validate() -> None:
    validate_output_schema_definition(SCHEMA)
    validate_structured_output(_valid_output(), SCHEMA)


@pytest.mark.parametrize(
    ("mutate", "path"),
    (
        (lambda value: value.pop("title"), r"\$"),
        (lambda value: value.__setitem__("extra", True), r"\$"),
        (lambda value: value.__setitem__("title", "bad"), r"\$\.title"),
        (
            lambda value: value["claims"][0].__setitem__("kind", "unsupported"),
            r"\$\.claims\[0\]\.kind",
        ),
        (
            lambda value: value["claims"][0].__setitem__("id", "not-a-uuid"),
            r"\$\.claims\[0\]\.id",
        ),
        (lambda value: value.__setitem__("status", "failed"), r"\$\.status"),
    ),
)
def test_invalid_output_reports_a_stable_path(mutate: object, path: str) -> None:
    output = _valid_output()
    mutate(output)  # type: ignore[operator]

    with pytest.raises(StructuredOutputValidationError, match=path) as captured:
        validate_structured_output(output, SCHEMA)

    assert captured.value.code is ModelGatewayErrorCode.SCHEMA_INVALID
    assert "unsupported" not in str(captured.value)


@pytest.mark.parametrize(
    "schema",
    (
        {"type": "object", "unevaluatedProperties": False},
        {"type": "object", "required": "title"},
        {"type": "array", "minItems": -1},
        {"type": "number", "multipleOf": 0},
        {"type": "string", "pattern": "["},
        {"type": "string", "format": "hostname"},
        {"$ref": "#/$defs/missing"},
        {"$ref": "https://example.invalid/schema"},
    ),
)
def test_unsupported_or_malformed_schema_fails_closed(schema: dict[str, object]) -> None:
    with pytest.raises(OutputSchemaDefinitionError) as captured:
        validate_output_schema_definition(schema)

    assert captured.value.code is ModelGatewayErrorCode.NON_RETRYABLE_VALIDATION
    assert captured.value.retryable is False


def test_boolean_subschemas_and_dependent_required_are_supported() -> None:
    schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string"},
            "details": True,
            "forbidden": False,
        },
        "dependentRequired": {"mode": ["details"]},
    }

    validate_structured_output({"mode": "guided", "details": {"idea": "short"}}, schema)
    with pytest.raises(StructuredOutputValidationError, match="requires property details"):
        validate_structured_output({"mode": "guided"}, schema)
    with pytest.raises(StructuredOutputValidationError, match=r"\$\.forbidden"):
        validate_structured_output({"forbidden": "value"}, schema)


def test_json_boolean_is_not_accepted_as_an_integer_or_number() -> None:
    with pytest.raises(StructuredOutputValidationError, match="integer"):
        validate_structured_output(
            {"score": True},
            {
                "type": "object",
                "properties": {"score": {"type": "integer"}},
            },
        )
    with pytest.raises(StructuredOutputValidationError, match="number"):
        validate_structured_output(
            {"score": False},
            {
                "type": "object",
                "properties": {"score": {"type": "number"}},
            },
        )


def test_application_schema_may_strengthen_portable_schema() -> None:
    portable = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    application = {
        "type": "object",
        "properties": {"answer": {"type": "string", "minLength": 1}},
        "required": ["answer"],
        "additionalProperties": False,
    }

    validate_output_schema_pair(portable, application)


def test_application_schema_cannot_weaken_or_drop_portable_fields() -> None:
    portable = {
        "type": "object",
        "properties": {"answer": {"type": "string", "minLength": 1}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    weaker = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": [],
        "additionalProperties": True,
    }

    with pytest.raises(OutputSchemaDefinitionError, match="canonical projection"):
        validate_output_schema_pair(portable, weaker)


def test_frozen_prompt_schema_enforces_tuple_enum_nullable_and_required() -> None:
    schema = MappingProxyType(
        {
            "type": "object",
            "required": ("status", "note"),
            "properties": MappingProxyType(
                {
                    "status": MappingProxyType(
                        {"enum": ("passed", "completed_with_warning")}
                    ),
                    "note": MappingProxyType({"type": ("string", "null")}),
                }
            ),
            "additionalProperties": False,
        }
    )

    validate_output_schema_definition(schema)
    validate_structured_output({"status": "passed", "note": None}, schema)
    with pytest.raises(StructuredOutputValidationError, match="missing required"):
        validate_structured_output({"status": "passed"}, schema)
    with pytest.raises(StructuredOutputValidationError, match="allowed enum"):
        validate_structured_output({"status": "failed", "note": None}, schema)
    with pytest.raises(StructuredOutputValidationError, match="string or null"):
        validate_structured_output({"status": "passed", "note": 7}, schema)
