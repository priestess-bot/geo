"""Deterministic Prompt Program rendering and fixed-input Release diffs."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import json

from geo_core.prompts.program_contracts import (
    BOOTSTRAP_COMPILER_VERSION,
    LEGACY_BOOTSTRAP_COMPILER_VERSION,
    ProgramReleaseStatus,
    PromptProgramRuleViolation,
    _VARIABLE,
    _canonical_hash,
    _canonical_value,
    _freeze_json_object,
    _schema_string_sequence,
    _text_hash,
)
from geo_core.prompts.program_models import (
    CompiledProgramPrompt,
    ProgramReleaseDiff,
    ProgramReleaseState,
    PromptProgramRelease,
    _assert_state_matches_release,
)


_MAX_REQUEST_JSON_BYTES = 100_000
_MAX_REQUEST_JSON_DEPTH = 64
_MAX_REQUEST_JSON_NODES = 20_000
_MAX_JSON_NUMBER_DIGITS = 256
_MAX_JSON_NUMBER_EXPONENT = 308


def render_program_release(
    *, release: PromptProgramRelease, variables: Mapping[str, object]
) -> CompiledProgramPrompt:
    frozen_variables = _freeze_json_object(variables, field_name="Prompt Program variables")
    render_variables = _variables_for_compiler(release, frozen_variables)
    required = set(_schema_string_sequence(release.schemas.variable_schema, "required"))
    missing = sorted(required - set(render_variables))
    if missing:
        raise PromptProgramRuleViolation(f"missing Prompt Program variables: {', '.join(missing)}")
    properties = release.schemas.variable_schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise PromptProgramRuleViolation("variable_schema.properties must be an object")
    if release.schemas.variable_schema.get("additionalProperties") is False:
        unknown = sorted(set(render_variables) - set(properties))
        if unknown:
            raise PromptProgramRuleViolation(
                f"unknown Prompt Program variables: {', '.join(unknown)}"
            )

    compiled_system = _render_template(release.system_template, render_variables)
    compiled_system = _with_output_schema_contract(
        compiled_system, release.schemas.application_output_schema
    )
    compiled_user = _render_template(release.user_template, render_variables)
    return CompiledProgramPrompt(
        release_id=release.id,
        release_hash=release.release_hash,
        variable_input_hash=_canonical_hash(_canonical_value(render_variables)),
        compiled_system=compiled_system,
        compiled_system_hash=_text_hash(compiled_system),
        compiled_user=compiled_user,
        compiled_user_hash=_text_hash(compiled_user),
        output_schema_version=release.schemas.output_schema_version,
        model_policy_version=release.model_policy.version,
        model_policy_hash=release.model_policy.policy_hash,
    )


def compare_candidate_to_approved(
    *,
    approved_release: PromptProgramRelease,
    approved_state: ProgramReleaseState,
    candidate_release: PromptProgramRelease,
    candidate_state: ProgramReleaseState,
    fixed_variables: Mapping[str, object],
) -> ProgramReleaseDiff:
    """Diff a candidate against the current approved/frozen Release on fixed input."""

    _assert_state_matches_release(state=approved_state, release=approved_release)
    _assert_state_matches_release(state=candidate_state, release=candidate_release)
    if approved_state.status not in {
        ProgramReleaseStatus.APPROVED,
        ProgramReleaseStatus.FROZEN,
    }:
        raise PromptProgramRuleViolation("the diff baseline must be approved or frozen")
    if candidate_state.status not in {
        ProgramReleaseStatus.DRAFT,
        ProgramReleaseStatus.TESTED,
    }:
        raise PromptProgramRuleViolation("the diff candidate must be draft or tested")
    _assert_same_program(approved_release, candidate_release)
    if candidate_release.version <= approved_release.version:
        raise PromptProgramRuleViolation("candidate Release version must follow the baseline")

    approved_prompt = render_program_release(
        release=approved_release, variables=fixed_variables
    )
    candidate_prompt = render_program_release(
        release=candidate_release, variables=fixed_variables
    )
    baseline = approved_release.diffable_value()
    candidate = candidate_release.diffable_value()
    changed_fields = tuple(
        sorted(key for key in baseline if baseline[key] != candidate[key])
    )
    return ProgramReleaseDiff(
        base_release_id=approved_release.id,
        base_release_hash=approved_release.release_hash,
        candidate_release_id=candidate_release.id,
        candidate_release_hash=candidate_release.release_hash,
        changed_fields=changed_fields,
        fixed_input_hash=approved_prompt.variable_input_hash,
        base_system_hash=approved_prompt.compiled_system_hash,
        candidate_system_hash=candidate_prompt.compiled_system_hash,
        base_user_hash=approved_prompt.compiled_user_hash,
        candidate_user_hash=candidate_prompt.compiled_user_hash,
    )


def _assert_same_program(
    baseline: PromptProgramRelease, candidate: PromptProgramRelease
) -> None:
    identities = (
        "project_id",
        "program_id",
        "program_kind",
        "purpose",
    )
    if any(getattr(baseline, name) != getattr(candidate, name) for name in identities):
        raise PromptProgramRuleViolation(
            "Prompt Program diffs require the same project, Program kind and purpose"
        )


def _render_template(template: str, variables: Mapping[str, object]) -> str:
    missing = sorted(set(_VARIABLE.findall(template)) - set(variables))
    if missing:
        raise PromptProgramRuleViolation(f"missing Prompt Program variables: {', '.join(missing)}")
    return _VARIABLE.sub(
        lambda match: _render_value(variables[match.group(1)]),
        template,
    )


def _with_output_schema_contract(
    compiled_system: str, application_output_schema: Mapping[str, object]
) -> str:
    """Expose the frozen contract to JSON-mode providers and the Admin preview."""

    schema = json.dumps(
        _canonical_value(application_output_schema),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (
        f"{compiled_system}\n\n"
        "Return a JSON object that satisfies this exact output contract. Do not add "
        "fields, prose, Markdown, or code fences.\n"
        f"<output_json_schema>\n{schema}\n</output_json_schema>"
    )


def _render_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _variables_for_compiler(
    release: PromptProgramRelease, variables: Mapping[str, object]
) -> Mapping[str, object]:
    if "request_json" not in variables:
        return variables
    if release.compiler_version == LEGACY_BOOTSTRAP_COMPILER_VERSION:
        return variables
    if release.compiler_version == BOOTSTRAP_COMPILER_VERSION:
        properties = release.schemas.variable_schema.get("properties", {})
        strict_properties = (
            frozenset(str(key) for key in properties)
            if release.schemas.variable_schema.get("additionalProperties") is False
            and isinstance(properties, Mapping)
            else None
        )
        normalized = _normalize_render_variables(
            variables, expanded_keys=strict_properties
        )
        if (
            strict_properties is not None
        ):
            return _freeze_json_object(
                {
                    key: value
                    for key, value in normalized.items()
                    if key in strict_properties
                },
                field_name="Prompt Program render variables",
            )
        return normalized
    raise PromptProgramRuleViolation(
        "request_json requires a supported versioned Prompt compiler"
    )


def _normalize_render_variables(
    variables: Mapping[str, object],
    *,
    expanded_keys: frozenset[str] | None,
) -> Mapping[str, object]:
    """Normalize the v2 bootstrap JSON envelope under deterministic budgets."""

    request_json = variables["request_json"]
    if not isinstance(request_json, str):
        raise PromptProgramRuleViolation("request_json must be a pre-serialized JSON string")
    try:
        encoded_size = len(request_json.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise PromptProgramRuleViolation("request_json must contain valid Unicode") from exc
    if encoded_size > _MAX_REQUEST_JSON_BYTES:
        raise PromptProgramRuleViolation("request_json exceeds the UTF-8 byte budget")
    try:
        parsed = json.loads(
            request_json,
            parse_constant=_reject_json_constant,
            parse_float=_parse_exact_decimal,
            object_pairs_hook=_unique_json_object,
        )
    except RecursionError as exc:
        raise PromptProgramRuleViolation(
            "request_json exceeds the strict JSON nesting budget"
        ) from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise PromptProgramRuleViolation("request_json must contain valid strict JSON") from exc

    _assert_request_json_budget(parsed)
    canonical = _canonical_json(parsed)
    safe = (
        canonical.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    normalized = dict(variables)
    normalized["request_json"] = safe
    if isinstance(parsed, Mapping):
        for key, value in parsed.items():
            name = str(key)
            if expanded_keys is None or name in expanded_keys:
                normalized.setdefault(name, _slot_render_value(value))
    return _freeze_json_object(normalized, field_name="Prompt Program render variables")


def _slot_render_value(value: object) -> object:
    """Keep strings natural and all other context slots as exact JSON fragments."""

    return value if isinstance(value, str) else _canonical_json(value)


def _reject_json_constant(token: str) -> object:
    raise ValueError(f"non-JSON numeric constant: {token}")


def _parse_exact_decimal(token: str) -> Decimal:
    value = Decimal(token)
    _assert_decimal_budget(value)
    return value


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("request_json contains duplicate object keys")
        result[key] = value
    return result


def _assert_request_json_budget(value: object) -> None:
    nodes = 0
    pending: list[tuple[object, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_REQUEST_JSON_NODES:
            raise PromptProgramRuleViolation("request_json exceeds the JSON node budget")
        if depth > _MAX_REQUEST_JSON_DEPTH:
            raise PromptProgramRuleViolation("request_json exceeds the JSON depth budget")
        if isinstance(current, Mapping):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
        elif isinstance(current, Decimal):
            _assert_decimal_budget(current)
        elif isinstance(current, int) and not isinstance(current, bool):
            if len(str(abs(current))) > _MAX_JSON_NUMBER_DIGITS:
                raise PromptProgramRuleViolation(
                    "request_json integer exceeds the numeric digit budget"
                )


def _assert_decimal_budget(value: Decimal) -> None:
    if not value.is_finite():
        raise ValueError("request_json contains a non-finite number")
    if len(value.as_tuple().digits) > _MAX_JSON_NUMBER_DIGITS:
        raise ValueError("request_json number exceeds the numeric digit budget")
    if not value.is_zero() and abs(value.adjusted()) > _MAX_JSON_NUMBER_EXPONENT:
        raise ValueError("request_json number exceeds the numeric exponent budget")


def _canonical_json(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True, allow_nan=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        if value.is_zero():
            return "0"
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered
    if isinstance(value, list):
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    if isinstance(value, Mapping):
        return "{" + ",".join(
            f"{json.dumps(key, ensure_ascii=True)}:{_canonical_json(value[key])}"
            for key in sorted(value)
        ) + "}"
    raise PromptProgramRuleViolation("request_json contains an unsupported JSON value")
