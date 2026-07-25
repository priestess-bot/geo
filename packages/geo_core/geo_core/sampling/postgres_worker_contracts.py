"""Frozen, secret-free Worker contracts for durable Workflow C sampling Jobs.

Provider credentials are resolved by the Model Gateway after the durable lease
is acquired. Manual evidence bytes stay in the restricted artifact store and
never travel in a Job message.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from uuid import UUID

from geo_core.sampling.contracts import (
    CaptureMethod,
    LocationControl,
    SamplingRuleViolation,
    SamplingSourceStratum,
)
from geo_core.sampling.provider_execution_contracts import ProviderSamplingPrompt


_HASH = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "run_id",
        "task_id",
        "attempt_id",
        "task_version",
        "attempt_version",
        "question",
        "runtime_selection_id",
        "admitted_by",
        "admitted_at",
        "prompt",
        "search_mode",
        "deadline_at",
    }
)
_MANUAL_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "manual_import_id",
        "run_id",
        "task_id",
        "attempt_id",
        "artifact_manifest_id",
        "artifact_manifest_hash",
        "artifact_content_hash",
        "governance_policy_hash",
        "capture_session_id",
        "task_version",
        "attempt_version",
    }
)
_PROMPT_KEYS = frozenset(
    {
        "binding_id",
        "state_id",
        "state_version",
        "release_id",
        "release_hash",
        "purpose",
        "bundle_hash",
        "system_message",
        "answer_field",
        "output_schema",
        "application_output_schema",
        "temperature",
        "max_output_tokens",
        "seed",
        "tool_mode",
    }
)


class WorkflowCSamplingSpecError(SamplingRuleViolation):
    """A durable sampling command differs from its frozen safe schema."""


@dataclass(frozen=True)
class FrozenProviderPrompt:
    binding_id: UUID
    state_id: UUID
    state_version: int
    release_id: UUID
    release_hash: str
    purpose: str
    bundle_hash: str
    system_message: str
    answer_field: str
    output_schema: Mapping[str, object]
    application_output_schema: Mapping[str, object]
    temperature: float
    max_output_tokens: int
    seed: int | None
    tool_mode: str | None

    def as_provider_prompt(self) -> ProviderSamplingPrompt:
        return ProviderSamplingPrompt(
            binding_id=self.binding_id,
            release_id=self.release_id,
            release_hash=self.release_hash,
            bundle_hash=self.bundle_hash,
            system_message=self.system_message,
            answer_field=self.answer_field,
            output_schema=self.output_schema,
            application_output_schema=self.application_output_schema,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            seed=self.seed,
            tool_mode=self.tool_mode,
        )


@dataclass(frozen=True)
class ProviderSamplingWorkerSpec:
    run_id: UUID
    task_id: UUID
    attempt_id: UUID
    task_version: int
    attempt_version: int
    question_text: str
    question_hash: str
    runtime_selection_id: UUID
    admitted_by: UUID
    admitted_at: datetime
    prompt: FrozenProviderPrompt
    search_mode: str | None
    deadline_at: datetime | None


@dataclass(frozen=True)
class ManualSamplingWorkerSpec:
    manual_import_id: UUID
    run_id: UUID
    task_id: UUID
    attempt_id: UUID
    artifact_manifest_id: UUID
    artifact_manifest_hash: str
    artifact_content_hash: str
    governance_policy_hash: str
    capture_session_id: UUID
    task_version: int
    attempt_version: int


@dataclass(frozen=True)
class SamplingWorkerSource:
    source: SamplingSourceStratum
    questions: Mapping[tuple[str, str], str]


@dataclass(frozen=True)
class ProviderSamplingCommit:
    observation_id: UUID
    observation_hash: str
    evidence_status: str
    ineligible_reasons: tuple[str, ...]
    actual_location: Mapping[str, object]
    actual_location_hash: str
    evidence: Mapping[str, object]
    provider_attempt_id: UUID
    provider_response_hash: str
    output_hash: str
    observed_at: datetime


@dataclass(frozen=True)
class ManualSamplingCommit:
    observation_id: UUID
    observation_hash: str
    evidence_status: str
    ineligible_reasons: tuple[str, ...]
    actual_location: Mapping[str, object]
    actual_location_hash: str
    evidence: Mapping[str, object]
    observed_at: datetime


def parse_provider_sampling_spec(payload: Mapping[str, object]) -> ProviderSamplingWorkerSpec:
    _exact_keys(payload, _PROVIDER_KEYS, "provider sampling")
    _schema(payload, "sampling.provider_execute")
    question = _mapping(payload, "question")
    _exact_keys(question, frozenset({"text", "sha256"}), "provider question")
    question_text = _text(question.get("text"), "provider question text", maximum=4_000)
    question_hash = _hash(question.get("sha256"), "provider question hash")
    if hashlib.sha256(question_text.encode("utf-8")).hexdigest() != question_hash:
        raise WorkflowCSamplingSpecError("provider question hash does not match text")
    search_mode = payload.get("search_mode")
    if search_mode is not None:
        search_mode = _text(search_mode, "provider search mode", maximum=120)
    return ProviderSamplingWorkerSpec(
        run_id=_uuid(payload.get("run_id"), "provider run"),
        task_id=_uuid(payload.get("task_id"), "provider task"),
        attempt_id=_uuid(payload.get("attempt_id"), "provider attempt"),
        task_version=_positive(payload.get("task_version"), "provider task version"),
        attempt_version=_positive(payload.get("attempt_version"), "provider attempt version"),
        question_text=question_text,
        question_hash=question_hash,
        runtime_selection_id=_uuid(
            payload.get("runtime_selection_id"), "provider runtime selection"
        ),
        admitted_by=_uuid(payload.get("admitted_by"), "provider admission actor"),
        admitted_at=_timestamp(payload.get("admitted_at"), "provider admission time"),
        prompt=parse_frozen_provider_prompt(_mapping(payload, "prompt")),
        search_mode=search_mode,
        deadline_at=_optional_timestamp(payload.get("deadline_at"), "provider deadline"),
    )


def parse_manual_sampling_spec(payload: Mapping[str, object]) -> ManualSamplingWorkerSpec:
    _exact_keys(payload, _MANUAL_KEYS, "manual sampling")
    _schema(payload, "sampling.manual_import")
    return ManualSamplingWorkerSpec(
        manual_import_id=_uuid(payload.get("manual_import_id"), "manual import"),
        run_id=_uuid(payload.get("run_id"), "manual run"),
        task_id=_uuid(payload.get("task_id"), "manual task"),
        attempt_id=_uuid(payload.get("attempt_id"), "manual attempt"),
        artifact_manifest_id=_uuid(
            payload.get("artifact_manifest_id"), "manual artifact manifest"
        ),
        artifact_manifest_hash=_hash(
            payload.get("artifact_manifest_hash"), "manual artifact manifest"
        ),
        artifact_content_hash=_hash(
            payload.get("artifact_content_hash"), "manual artifact content"
        ),
        governance_policy_hash=_hash(
            payload.get("governance_policy_hash"), "manual governance policy"
        ),
        capture_session_id=_uuid(
            payload.get("capture_session_id"), "manual capture session"
        ),
        task_version=_positive(payload.get("task_version"), "manual task version"),
        attempt_version=_positive(payload.get("attempt_version"), "manual attempt version"),
    )


def parse_sampling_worker_source(payload: object) -> SamplingWorkerSource:
    values = _mapping_value(payload, "sampling Suite payload")
    # 0040 persists a Suite inside an immutable command envelope.  Older
    # pre-control rows store the canonical Suite directly.  Both forms are
    # intentionally supported here so Worker reads remain compatible across
    # the additive migration; the nested Suite still receives the same strict
    # field validation below.
    if "suite" in values:
        if set(values) != {"schema_version", "suite", "frozen_by", "frozen_at"}:
            raise WorkflowCSamplingSpecError("sampling Suite envelope is invalid")
        if values.get("schema_version") != 1:
            raise WorkflowCSamplingSpecError("sampling Suite envelope version is invalid")
        values = _mapping(values, "suite")
    source_values = _mapping(values, "source_stratum")
    _exact_keys(
        source_values,
        frozenset(
            {
                "platform",
                "surface",
                "configured_model",
                "reported_model",
                "capture_method",
                "adapter_release",
                "locale",
                "region",
                "language",
                "search_mode",
                "account_cohort",
                "egress_policy_category",
                "location_control",
                "location_evidence_hash",
                "requested_country",
                "requested_region",
                "requested_locale",
                "requested_language",
                "effective_country",
                "effective_region",
                "effective_locale",
                "effective_language",
            }
        ),
        "sampling source stratum",
    )
    try:
        source = SamplingSourceStratum(
            platform=_text(source_values.get("platform"), "sampling source platform"),
            surface=_text(source_values.get("surface"), "sampling source surface"),
            configured_model=_text(
                source_values.get("configured_model"), "sampling source configured model"
            ),
            reported_model=_text(
                source_values.get("reported_model"), "sampling source reported model"
            ),
            capture_method=CaptureMethod(
                _text(source_values.get("capture_method"), "sampling source capture method")
            ),
            adapter_release=_text(
                source_values.get("adapter_release"), "sampling source adapter release"
            ),
            locale=_text(source_values.get("locale"), "sampling source locale"),
            region=_text(source_values.get("region"), "sampling source region"),
            language=_text(source_values.get("language"), "sampling source language"),
            search_mode=_text(source_values.get("search_mode"), "sampling source search mode"),
            account_cohort=_text(
                source_values.get("account_cohort"), "sampling source account cohort"
            ),
            egress_policy_category=_text(
                source_values.get("egress_policy_category"),
                "sampling source egress policy category",
            ),
            location_control=LocationControl(
                _text(
                    source_values.get("location_control"),
                    "sampling source location control",
                )
            ),
            location_evidence_hash=_hash(
                source_values.get("location_evidence_hash"),
                "sampling source location evidence",
            ),
            requested_country=_optional_text(source_values.get("requested_country")),
            requested_region=_optional_text(source_values.get("requested_region")),
            requested_locale=_text(
                source_values.get("requested_locale"), "sampling source requested locale"
            ),
            requested_language=_text(
                source_values.get("requested_language"), "sampling source requested language"
            ),
            effective_country=_optional_text(source_values.get("effective_country")),
            effective_region=_optional_text(source_values.get("effective_region")),
            effective_locale=_optional_text(source_values.get("effective_locale")),
            effective_language=_optional_text(source_values.get("effective_language")),
        )
    except (TypeError, ValueError) as error:
        raise WorkflowCSamplingSpecError("sampling source stratum is invalid") from error
    questions_value = values.get("questions")
    if not isinstance(questions_value, list) or not questions_value:
        raise WorkflowCSamplingSpecError("sampling Suite questions are unavailable")
    questions: dict[tuple[str, str], str] = {}
    for item in questions_value:
        question = _mapping_value(item, "sampling Suite question")
        _exact_keys(
            question,
            frozenset({"question_id", "question_version", "text_hash"}),
            "sampling Suite question",
        )
        key = (
            _text(question.get("question_id"), "sampling Suite question ID"),
            _text(question.get("question_version"), "sampling Suite question version"),
        )
        if key in questions:
            raise WorkflowCSamplingSpecError("sampling Suite question is duplicated")
        questions[key] = _hash(question.get("text_hash"), "sampling Suite question hash")
    return SamplingWorkerSource(source=source, questions=questions)


def parse_frozen_provider_prompt(payload: Mapping[str, object]) -> FrozenProviderPrompt:
    """Validate the prompt portion shared by frozen provider execution inputs."""
    _exact_keys(payload, _PROMPT_KEYS, "provider prompt")
    temperature = payload.get("temperature")
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
        raise WorkflowCSamplingSpecError("provider prompt temperature is invalid")
    seed = payload.get("seed")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise WorkflowCSamplingSpecError("provider prompt seed is invalid")
    tool_mode = payload.get("tool_mode")
    if tool_mode is not None:
        tool_mode = _text(tool_mode, "provider prompt tool mode", maximum=120)
    return FrozenProviderPrompt(
        binding_id=_uuid(payload.get("binding_id"), "provider prompt binding"),
        state_id=_uuid(payload.get("state_id"), "provider prompt state"),
        state_version=_positive(payload.get("state_version"), "provider prompt state version"),
        release_id=_uuid(payload.get("release_id"), "provider prompt release"),
        release_hash=_hash(payload.get("release_hash"), "provider prompt release"),
        purpose=_text(payload.get("purpose"), "provider prompt purpose", maximum=120),
        bundle_hash=_hash(payload.get("bundle_hash"), "provider prompt bundle"),
        system_message=_text(
            payload.get("system_message"),
            "provider prompt system message",
            maximum=20_000,
        ),
        answer_field=_text(
            payload.get("answer_field"), "provider prompt answer field", maximum=120
        ),
        output_schema=_mapping(payload, "output_schema"),
        application_output_schema=_mapping(payload, "application_output_schema"),
        temperature=float(temperature),
        max_output_tokens=_positive(
            payload.get("max_output_tokens"), "provider prompt output tokens"
        ),
        seed=seed,
        tool_mode=tool_mode,
    )


def _schema(payload: Mapping[str, object], expected_kind: str) -> None:
    if payload.get("schema_version") != 1 or payload.get("kind") != expected_kind:
        raise WorkflowCSamplingSpecError("sampling Worker spec version or kind is invalid")


def _exact_keys(payload: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    if frozenset(payload) != expected:
        raise WorkflowCSamplingSpecError(f"{label} keys are invalid")


def _mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _mapping_value(payload.get(key), key)


def _mapping_value(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise WorkflowCSamplingSpecError(f"{label} must be an object")
    return dict(value)


def _uuid(value: object, label: str) -> UUID:
    if not isinstance(value, str):
        raise WorkflowCSamplingSpecError(f"{label} ID is invalid")
    try:
        result = UUID(value)
    except ValueError as error:
        raise WorkflowCSamplingSpecError(f"{label} ID is invalid") from error
    if result.int == 0:
        raise WorkflowCSamplingSpecError(f"{label} ID is invalid")
    return result


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise WorkflowCSamplingSpecError(f"{label} hash is invalid")
    return value


def _text(value: object, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise WorkflowCSamplingSpecError(f"{label} is invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise WorkflowCSamplingSpecError(f"{label} is invalid")
    return normalized


def _positive(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkflowCSamplingSpecError(f"{label} is invalid")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value, "sampling source location")


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise WorkflowCSamplingSpecError(f"{label} is invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise WorkflowCSamplingSpecError(f"{label} is invalid") from error
    _require_aware(result, label)
    return result


def _optional_timestamp(value: object, label: str) -> datetime | None:
    return None if value is None else _timestamp(value, label)


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowCSamplingSpecError(f"{label} must be timezone-aware")


__all__ = [
    "FrozenProviderPrompt",
    "ManualSamplingCommit",
    "ManualSamplingWorkerSpec",
    "ProviderSamplingCommit",
    "ProviderSamplingWorkerSpec",
    "SamplingWorkerSource",
    "WorkflowCSamplingSpecError",
    "parse_manual_sampling_spec",
    "parse_frozen_provider_prompt",
    "parse_provider_sampling_spec",
    "parse_sampling_worker_source",
]
