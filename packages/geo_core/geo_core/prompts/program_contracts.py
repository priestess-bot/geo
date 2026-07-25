"""Shared Prompt Program enums, schema contracts and canonical JSON rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import math
import re
from types import MappingProxyType

from geo_core.model_gateway.contracts import OutputSchemaDefinitionError
from geo_core.model_gateway.schema_validation import (
    project_provider_output_schema,
    validate_output_schema_pair,
    validate_output_schema_definition,
)


_VARIABLE = re.compile(r"\{\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*\}\}")
_PURPOSE = re.compile(r"[a-z][a-z0-9_.-]{2,127}")
LEGACY_BOOTSTRAP_COMPILER_VERSION = "geo-prompt-bootstrap-compiler-v1"
BOOTSTRAP_COMPILER_VERSION = "geo-prompt-bootstrap-compiler-v2"


class PromptProgramRuleViolation(ValueError):
    """Raised when a Prompt Program command would violate a frozen contract."""


class ProgramKind(StrEnum):
    GENERATION = "generation"
    CLAIM_EXTRACTION = "claim_extraction"
    CONFLICT_CHECK = "conflict_check"
    REVISION = "revision"
    STYLE_JUDGE = "style_judge"
    ARBITER = "arbiter"
    METRIC_JUDGE = "metric_judge"
    RECOMMENDATION = "recommendation"
    STYLE_PROFILE = "style_profile"
    OFFLINE_ANSWER = "offline_answer"
    REFERENCE_TRANSLATION = "reference_translation"


CORE_FIRST_PHASE_PROGRAM_KINDS: tuple[ProgramKind, ...] = (
    ProgramKind.GENERATION,
    ProgramKind.CLAIM_EXTRACTION,
    ProgramKind.CONFLICT_CHECK,
    ProgramKind.REVISION,
    ProgramKind.STYLE_JUDGE,
    ProgramKind.ARBITER,
    ProgramKind.METRIC_JUDGE,
    ProgramKind.RECOMMENDATION,
)
AUXILIARY_PROGRAM_KINDS: tuple[ProgramKind, ...] = (
    ProgramKind.STYLE_PROFILE,
    ProgramKind.OFFLINE_ANSWER,
)
FIRST_PHASE_PROGRAM_KINDS: tuple[ProgramKind, ...] = (
    *CORE_FIRST_PHASE_PROGRAM_KINDS,
    *AUXILIARY_PROGRAM_KINDS,
)


class ProgramReleaseStatus(StrEnum):
    DRAFT = "draft"
    TESTED = "tested"
    APPROVED = "approved"
    FROZEN = "frozen"
    RETIRED = "retired"


class ProgramReleaseCommand(StrEnum):
    RECORD_TEST = "record_test"
    APPROVE = "approve"
    FREEZE = "freeze"
    RETIRE = "retire"


@dataclass(frozen=True)
class ProgramSchemaContract:
    """Versioned JSON Schema snapshots used to compile and validate one Release."""

    variable_schema_version: str
    variable_schema: Mapping[str, object]
    input_schema_version: str
    input_schema: Mapping[str, object]
    output_schema_version: str
    output_schema: Mapping[str, object]
    application_output_schema_version: str = ""
    application_output_schema: Mapping[str, object] = field(default_factory=dict)
    output_schema_hash: str = field(init=False)
    application_output_schema_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "variable_schema_version",
            "input_schema_version",
            "output_schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_version(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("variable_schema", "input_schema", "output_schema"):
            schema = _freeze_json_object(getattr(self, field_name), field_name=field_name)
            _validate_object_schema(schema, field_name=field_name)
            object.__setattr__(self, field_name, schema)
        explicit_application_schema = (
            bool(self.application_output_schema_version)
            or bool(self.application_output_schema)
        )
        if bool(self.application_output_schema_version) != bool(
            self.application_output_schema
        ):
            raise PromptProgramRuleViolation(
                "application output schema version and schema must be supplied together"
            )
        application_version = (
            self.output_schema_version
            if not self.application_output_schema_version
            else _normalize_version(
                self.application_output_schema_version,
                field_name="application_output_schema_version",
            )
        )
        application_schema = _freeze_json_object(
            self.output_schema
            if not self.application_output_schema
            else self.application_output_schema,
            field_name="application_output_schema",
        )
        _validate_object_schema(
            application_schema,
            field_name="application_output_schema",
        )
        if explicit_application_schema:
            try:
                validate_output_schema_pair(self.output_schema, application_schema)
            except OutputSchemaDefinitionError as exc:
                raise PromptProgramRuleViolation(
                    "provider output schema must be the deterministic portable "
                    "projection of the application output schema"
                ) from exc
        output_hash = _canonical_hash(self.output_schema)
        application_hash = _canonical_hash(application_schema)
        object.__setattr__(
            self,
            "application_output_schema_version",
            application_version,
        )
        object.__setattr__(self, "application_output_schema", application_schema)
        object.__setattr__(self, "output_schema_hash", output_hash)
        object.__setattr__(
            self,
            "application_output_schema_hash",
            application_hash,
        )

    def canonical_value(self) -> Mapping[str, object]:
        return {
            "variable_schema_version": self.variable_schema_version,
            "variable_schema": _canonical_value(self.variable_schema),
            "input_schema_version": self.input_schema_version,
            "input_schema": _canonical_value(self.input_schema),
            "output_schema_version": self.output_schema_version,
            "output_schema": _canonical_value(self.output_schema),
            "output_schema_hash": self.output_schema_hash,
            "application_output_schema_version": self.application_output_schema_version,
            "application_output_schema": _canonical_value(
                self.application_output_schema
            ),
            "application_output_schema_hash": self.application_output_schema_hash,
        }


@dataclass(frozen=True)
class ModelPolicySnapshot:
    """Provider-neutral, versioned model policy frozen into a Prompt Release."""

    version: str
    policy: Mapping[str, object]
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        version = _normalize_version(self.version, field_name="model policy version")
        policy = _freeze_json_object(self.policy, field_name="model policy")
        if not policy:
            raise PromptProgramRuleViolation("model policy cannot be empty")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "policy", policy)
        object.__setattr__(
            self,
            "policy_hash",
            _canonical_hash({"version": version, "policy": _canonical_value(policy)}),
        )

    def canonical_value(self) -> Mapping[str, object]:
        return {
            "version": self.version,
            "policy": _canonical_value(self.policy),
            "policy_hash": self.policy_hash,
        }


def _validate_template_variables(
    *,
    system_template: str,
    user_template: str,
    variable_schema: Mapping[str, object],
) -> None:
    used = set(_VARIABLE.findall(system_template)) | set(_VARIABLE.findall(user_template))
    properties = variable_schema.get("properties", {})
    assert isinstance(properties, Mapping)
    undeclared = sorted(used - set(properties))
    if undeclared:
        raise PromptProgramRuleViolation(
            f"template variables are not declared by variable_schema: {', '.join(undeclared)}"
        )
    required = set(_schema_string_sequence(variable_schema, "required"))
    optional = sorted(used - required)
    if optional:
        raise PromptProgramRuleViolation(
            "template variables must be required by variable_schema: " + ", ".join(optional)
        )


def _validate_object_schema(schema: Mapping[str, object], *, field_name: str) -> None:
    if schema.get("type") != "object":
        raise PromptProgramRuleViolation(f"{field_name} must be a JSON Schema object")
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise PromptProgramRuleViolation(f"{field_name}.properties must be an object")
    required = _schema_string_sequence(schema, "required")
    unknown_required = sorted(set(required) - set(properties))
    if unknown_required:
        raise PromptProgramRuleViolation(
            f"{field_name}.required contains undeclared properties: "
            + ", ".join(unknown_required)
        )
    # Prompt Programs are immutable runtime contracts.  Rejecting an unsupported
    # deep keyword at authoring time is materially safer than accepting a Release
    # that later fails only after it has been bound to a governed Model call.
    try:
        validate_output_schema_definition(schema)
    except OutputSchemaDefinitionError as exc:
        raise PromptProgramRuleViolation(
            f"{field_name} is not supported by the frozen structured-output schema profile"
        ) from exc


def provider_portable_output_schema(
    application_schema: Mapping[str, object],
) -> dict[str, object]:
    """Prompt boundary wrapper over the Model Gateway projection contract."""

    try:
        return project_provider_output_schema(application_schema)
    except OutputSchemaDefinitionError as exc:
        raise PromptProgramRuleViolation("application output schema is invalid") from exc


def _schema_string_sequence(schema: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = schema.get(key, ())
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        raise PromptProgramRuleViolation(f"JSON Schema {key} must be an array of strings")
    if len(value) != len(set(value)):
        raise PromptProgramRuleViolation(f"JSON Schema {key} values must be unique")
    return value


def _freeze_json_object(value: object, *, field_name: str) -> Mapping[str, object]:
    frozen = _freeze_json(value, path=field_name)
    if not isinstance(frozen, Mapping):
        raise PromptProgramRuleViolation(f"{field_name} must be an object")
    return frozen


def _freeze_json(value: object, *, path: str) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PromptProgramRuleViolation(f"{path} contains a non-string key")
            result[key] = _freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(result)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, path=f"{path}[]") for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise PromptProgramRuleViolation(f"{path} is not canonical JSON data")


def _canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    return value


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return _text_hash(payload)


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_purpose(value: str) -> str:
    normalized = value.strip()
    if not _PURPOSE.fullmatch(normalized):
        raise PromptProgramRuleViolation(
            "Prompt Program purpose must be a lowercase stable key between 3 and 128 characters"
        )
    return normalized


def _normalize_version(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or any(character.isspace() for character in normalized):
        raise PromptProgramRuleViolation(f"{field_name} must be a non-empty stable identifier")
    return normalized


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
