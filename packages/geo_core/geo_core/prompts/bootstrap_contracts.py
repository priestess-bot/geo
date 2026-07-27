"""Immutable contracts for default Prompt Program draft and evaluation specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.model_gateway._schema_definition import validate_output_schema_definition
from geo_core.prompts.compiler_versions import (
    BOOTSTRAP_COMPILER_VERSION as _BOOTSTRAP_COMPILER_VERSION,
)
from geo_core.prompts.program_contracts import (
    WORKSPACE_FLOW_PROGRAM_KINDS,
    ModelPolicySnapshot,
    ProgramKind,
    ProgramReleaseStatus,
    ProgramSchemaContract,
    PromptProgramRuleViolation,
    _canonical_hash,
    _canonical_value,
    _freeze_json_object,
    _normalize_purpose,
    _normalize_version,
    _validate_template_variables,
)
from geo_core.prompts.program_models import PromptProgram, PromptProgramRelease


BOOTSTRAP_CATALOG_VERSION = "geo-prompt-bootstrap-v2"
BOOTSTRAP_COMPILER_VERSION = _BOOTSTRAP_COMPILER_VERSION
BOOTSTRAP_TEST_SET_VERSION = 1


class EvalScenario(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    PROMPT_INJECTION = "prompt_injection"
    SUBJECT_MIXUP = "subject_mixup"
    FABRICATED_CITATION = "fabricated_citation"


REQUIRED_EVAL_SCENARIOS = tuple(EvalScenario)


class PromptBootstrapRuleViolation(PromptProgramRuleViolation):
    """Raised when a default draft or fixture violates its frozen contract."""


@dataclass(frozen=True)
class PromptRubricCriterion:
    code: str
    description: str
    weight: int
    blocking: bool

    def __post_init__(self) -> None:
        code = _normalize_version(self.code, field_name="rubric code")
        description = self.description.strip()
        if not description:
            raise PromptBootstrapRuleViolation("rubric description is required")
        if not 1 <= self.weight <= 100:
            raise PromptBootstrapRuleViolation("rubric weight must be between 1 and 100")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "description", description)

    def canonical_value(self) -> Mapping[str, object]:
        return {
            "code": self.code,
            "description": self.description,
            "weight": self.weight,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class PromptEvalFixture:
    fixture_id: str
    scenario: EvalScenario
    description: str
    input_value: Mapping[str, object]
    expected_output: Mapping[str, object]
    expected_valid: bool
    expected_error_code: str | None
    fixture_hash: str = field(init=False)

    def __post_init__(self) -> None:
        fixture_id = _normalize_version(self.fixture_id, field_name="fixture ID")
        description = self.description.strip()
        if not description:
            raise PromptBootstrapRuleViolation("fixture description is required")
        try:
            scenario = EvalScenario(self.scenario)
        except ValueError as exc:
            raise PromptBootstrapRuleViolation("unknown Prompt eval scenario") from exc
        error_code = (self.expected_error_code or "").strip() or None
        if self.expected_valid == (error_code is not None):
            raise PromptBootstrapRuleViolation(
                "fixture validity and expected error code are inconsistent"
            )
        input_value = _freeze_json_object(self.input_value, field_name="fixture input")
        expected_output = _freeze_json_object(
            self.expected_output, field_name="fixture expected output"
        )
        object.__setattr__(self, "fixture_id", fixture_id)
        object.__setattr__(self, "scenario", scenario)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "input_value", input_value)
        object.__setattr__(self, "expected_output", expected_output)
        object.__setattr__(self, "expected_error_code", error_code)
        object.__setattr__(self, "fixture_hash", _canonical_hash(self.canonical_value()))

    def canonical_value(self) -> Mapping[str, object]:
        return {
            "fixture_id": self.fixture_id,
            "scenario": self.scenario.value,
            "description": self.description,
            "input_value": _canonical_value(self.input_value),
            "expected_output": _canonical_value(self.expected_output),
            "expected_valid": self.expected_valid,
            "expected_error_code": self.expected_error_code,
        }


@dataclass(frozen=True)
class PromptBootstrapDraft:
    """Compiled Program objects without any approval, freeze or binding transition."""

    program: PromptProgram
    release: PromptProgramRelease
    status: ProgramReleaseStatus = ProgramReleaseStatus.DRAFT

    def __post_init__(self) -> None:
        if self.status is not ProgramReleaseStatus.DRAFT:
            raise PromptBootstrapRuleViolation("bootstrap output must remain a draft")


@dataclass(frozen=True)
class PromptBootstrapSpec:
    catalog_version: str
    spec_version: str
    program_kind: ProgramKind
    purpose: str
    system_template: str
    user_template: str
    variable_schema_version: str
    variable_schema: Mapping[str, object]
    input_schema_version: str
    input_schema: Mapping[str, object]
    output_schema_version: str
    output_schema: Mapping[str, object]
    application_output_schema_version: str
    application_output_schema: Mapping[str, object]
    model_policy: ModelPolicySnapshot
    compiler_version: str
    application_rules: tuple[str, ...]
    fixtures: tuple[PromptEvalFixture, ...]
    rubric: tuple[PromptRubricCriterion, ...]
    minimum_score: int = 95
    schemas: ProgramSchemaContract = field(init=False)
    test_set_id: UUID = field(init=False)
    test_set_hash: str = field(init=False)
    spec_hash: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            kind = ProgramKind(self.program_kind)
        except ValueError as exc:
            raise PromptBootstrapRuleViolation("unknown bootstrap Program kind") from exc
        if kind not in WORKSPACE_FLOW_PROGRAM_KINDS:
            raise PromptBootstrapRuleViolation(
                "Prompt Program kind has no workspace bootstrap draft"
            )
        catalog_version = _normalize_version(
            self.catalog_version, field_name="bootstrap catalog version"
        )
        spec_version = _normalize_version(self.spec_version, field_name="bootstrap spec version")
        purpose = _normalize_purpose(self.purpose)
        compiler_version = _normalize_version(
            self.compiler_version, field_name="bootstrap compiler version"
        )
        system_template = self.system_template.strip()
        user_template = self.user_template.strip()
        if not system_template or not user_template:
            raise PromptBootstrapRuleViolation("bootstrap system and user templates are required")
        raw_output_schema = self.output_schema
        validate_portable_output_schema(raw_output_schema)
        validate_output_schema_definition(self.application_output_schema)
        application_output_schema = _freeze_json_object(
            self.application_output_schema,
            field_name="bootstrap application output schema",
        )
        schemas = ProgramSchemaContract(
            variable_schema_version=self.variable_schema_version,
            variable_schema=self.variable_schema,
            input_schema_version=self.input_schema_version,
            input_schema=self.input_schema,
            output_schema_version=self.output_schema_version,
            output_schema=self.output_schema,
            application_output_schema_version=self.application_output_schema_version,
            application_output_schema=application_output_schema,
        )
        _validate_template_variables(
            system_template=system_template,
            user_template=user_template,
            variable_schema=schemas.variable_schema,
        )
        rules = tuple(_normalize_rule(rule) for rule in self.application_rules)
        fixtures = tuple(self.fixtures)
        rubric = tuple(self.rubric)
        if not rules or len(rules) != len(set(rules)):
            raise PromptBootstrapRuleViolation("application rules must be non-empty and unique")
        if {fixture.scenario for fixture in fixtures} != set(REQUIRED_EVAL_SCENARIOS):
            raise PromptBootstrapRuleViolation("each bootstrap spec requires all five eval scenarios")
        if len(fixtures) != len(REQUIRED_EVAL_SCENARIOS):
            raise PromptBootstrapRuleViolation("eval scenarios cannot be duplicated")
        if len({fixture.fixture_id for fixture in fixtures}) != len(fixtures):
            raise PromptBootstrapRuleViolation("fixture IDs must be unique")
        if not rubric or sum(item.weight for item in rubric) != 100:
            raise PromptBootstrapRuleViolation("rubric weights must total 100")
        if len({item.code for item in rubric}) != len(rubric):
            raise PromptBootstrapRuleViolation("rubric codes must be unique")
        if not 1 <= self.minimum_score <= 100:
            raise PromptBootstrapRuleViolation("minimum rubric score must be between 1 and 100")
        test_set_hash = _canonical_hash(
            [fixture.canonical_value() for fixture in fixtures]
        )
        object.__setattr__(self, "catalog_version", catalog_version)
        object.__setattr__(self, "spec_version", spec_version)
        object.__setattr__(self, "program_kind", kind)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "compiler_version", compiler_version)
        object.__setattr__(self, "system_template", system_template)
        object.__setattr__(self, "user_template", user_template)
        object.__setattr__(
            self,
            "application_output_schema",
            application_output_schema,
        )
        object.__setattr__(self, "schemas", schemas)
        object.__setattr__(self, "application_rules", rules)
        object.__setattr__(self, "fixtures", fixtures)
        object.__setattr__(self, "rubric", rubric)
        object.__setattr__(self, "test_set_hash", test_set_hash)
        object.__setattr__(
            self,
            "test_set_id",
            uuid5(NAMESPACE_URL, f"geo:{catalog_version}:{purpose}:{test_set_hash}"),
        )
        object.__setattr__(self, "spec_hash", _canonical_hash(self.canonical_value()))

    def canonical_value(self) -> Mapping[str, object]:
        return {
            "catalog_version": self.catalog_version,
            "spec_version": self.spec_version,
            "program_kind": self.program_kind.value,
            "purpose": self.purpose,
            "system_template": self.system_template,
            "user_template": self.user_template,
            "schemas": self.schemas.canonical_value(),
            "model_policy": self.model_policy.canonical_value(),
            "compiler_version": self.compiler_version,
            "application_rules": list(self.application_rules),
            "fixtures": [fixture.canonical_value() for fixture in self.fixtures],
            "rubric": [item.canonical_value() for item in self.rubric],
            "minimum_score": self.minimum_score,
        }

    def compile_draft(self, *, project_id: UUID, owner_id: UUID) -> PromptBootstrapDraft:
        program_id = uuid5(project_id, f"{self.catalog_version}:{self.purpose}")
        program = PromptProgram(
            id=program_id,
            project_id=project_id,
            program_kind=self.program_kind,
            purpose=self.purpose,
            owner_id=owner_id,
        )
        release = PromptProgramRelease.compile(
            id=uuid5(program_id, f"{self.spec_version}:{self.spec_hash}"),
            program=program,
            version=1,
            system_template=self.system_template,
            user_template=self.user_template,
            schemas=self.schemas,
            model_policy=self.model_policy,
            test_set_id=self.test_set_id,
            test_set_version=BOOTSTRAP_TEST_SET_VERSION,
            test_set_hash=self.test_set_hash,
            compiler_version=self.compiler_version,
        )
        return PromptBootstrapDraft(program=program, release=release)

    def admin_draft_payload(self) -> Mapping[str, object]:
        """Return fields matching the existing Admin create-Program request."""

        # ``ProgramSchemaContract.canonical_value`` also carries the derived
        # hashes used for immutable release lineage.  Those values are server
        # derived and deliberately not accepted by the Admin create command.
        schemas = {
            "variable_schema_version": self.schemas.variable_schema_version,
            "variable_schema": _canonical_value(self.schemas.variable_schema),
            "input_schema_version": self.schemas.input_schema_version,
            "input_schema": _canonical_value(self.schemas.input_schema),
            "output_schema_version": self.schemas.output_schema_version,
            "output_schema": _canonical_value(self.schemas.output_schema),
            "application_output_schema_version": (
                self.schemas.application_output_schema_version
            ),
            "application_output_schema": _canonical_value(
                self.schemas.application_output_schema
            ),
        }
        return _freeze_json_object(
            {
                "program_kind": self.program_kind.value,
                "purpose": self.purpose,
                "system_template": self.system_template,
                "user_template": self.user_template,
                "schemas": schemas,
                "model_policy": {
                    "version": self.model_policy.version,
                    "policy": _canonical_value(self.model_policy.policy),
                },
                "test_set_id": str(self.test_set_id),
                "test_set_version": BOOTSTRAP_TEST_SET_VERSION,
                "test_set_hash": self.test_set_hash,
                "compiler_version": self.compiler_version,
                "expected_version": 0,
            },
            field_name="Admin Prompt bootstrap payload",
        )


def thaw_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return cast(dict[str, object], _canonical_value(value))


def validate_portable_output_schema(schema: Mapping[str, object]) -> None:
    """Require the conservative schema subset shared by configured providers."""

    validate_output_schema_definition(schema)
    _validate_portable_branch(schema, path="$", depth=0)


def _validate_portable_branch(schema: object, *, path: str, depth: int) -> None:
    if depth > 64:
        raise PromptBootstrapRuleViolation("portable output schema is too deeply nested")
    if not isinstance(schema, Mapping):
        raise PromptBootstrapRuleViolation(f"portable output schema {path} must be an object")
    forbidden = {
        "$ref",
        "$defs",
        "allOf",
        "anyOf",
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
        "not",
        "oneOf",
        "pattern",
        "prefixItems",
        "uniqueItems",
    }
    used_forbidden = sorted(forbidden.intersection(schema))
    if used_forbidden:
        raise PromptBootstrapRuleViolation(
            f"portable output schema {path} uses {used_forbidden[0]}"
        )
    type_names = _portable_type_names(schema.get("type"), path=path)
    if "object" in type_names and len(type_names) != 1:
        raise PromptBootstrapRuleViolation(
            f"portable output object {path} cannot be nullable or union typed"
        )
    if "array" in type_names and len(type_names) != 1:
        raise PromptBootstrapRuleViolation(
            f"portable output array {path} cannot be nullable or union typed"
        )
    if type_names == ("object",):
        properties = schema.get("properties")
        required = schema.get("required")
        if not isinstance(properties, Mapping) or not isinstance(required, list):
            raise PromptBootstrapRuleViolation(
                f"portable output object {path} requires properties and required"
            )
        if schema.get("additionalProperties") is not False:
            raise PromptBootstrapRuleViolation(
                f"portable output object {path} must reject additional properties"
            )
        if set(required) != set(properties) or len(required) != len(properties):
            raise PromptBootstrapRuleViolation(
                f"portable output object {path} must require every property exactly once"
            )
        for name, child in properties.items():
            _validate_portable_branch(child, path=f"{path}.{name}", depth=depth + 1)
    elif type_names == ("array",):
        if "items" not in schema:
            raise PromptBootstrapRuleViolation(f"portable output array {path} requires items")
        _validate_portable_branch(schema["items"], path=f"{path}[]", depth=depth + 1)


def _portable_type_names(value: object, *, path: str) -> tuple[str, ...]:
    """Accept scalar nullable unions retained by the portable projection."""

    if isinstance(value, str):
        names = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        names = tuple(value)
    else:
        raise PromptBootstrapRuleViolation(
            f"portable output schema {path} requires an explicit JSON type"
        )
    supported = {"object", "array", "string", "number", "integer", "boolean", "null"}
    if (
        not names
        or any(not isinstance(name, str) or name not in supported for name in names)
        or len(names) != len(set(names))
    ):
        raise PromptBootstrapRuleViolation(
            f"portable output schema {path} uses an unsupported JSON type"
        )
    return names


def _normalize_rule(value: str) -> str:
    rule = _normalize_version(value, field_name="application rule")
    if "." not in rule:
        raise PromptBootstrapRuleViolation("application rule must use a namespaced stable ID")
    return rule
