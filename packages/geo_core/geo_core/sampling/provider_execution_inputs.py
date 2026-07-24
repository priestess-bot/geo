"""Immutable, server-resolved inputs for durable Provider Sampling attempts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
from types import MappingProxyType
from uuid import UUID

from geo_core.model_gateway import canonical_json_hash
from geo_core.sampling.contracts import SamplingConflict
from geo_core.sampling.postgres_worker_contracts import (
    FrozenProviderPrompt,
    ProviderSamplingWorkerSpec,
    WorkflowCSamplingSpecError,
    parse_frozen_provider_prompt,
    parse_provider_sampling_spec,
)


class ProviderSamplingExecutionInputError(SamplingConflict):
    """A frozen execution input cannot safely produce a Provider Job spec."""


@dataclass(frozen=True)
class ProviderSamplingExecutionQuestion:
    """One exact question text bound to an immutable QuestionSet entry."""

    question_id: str
    question_version: str
    text: str
    text_hash: str

    def __post_init__(self) -> None:
        question_id = _required_text(self.question_id, "question ID", maximum=200)
        question_version = _required_text(
            self.question_version, "question version", maximum=200
        )
        text = _required_text(self.text, "question text", maximum=4_000)
        text_hash = _hash(self.text_hash, "question hash")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != text_hash:
            raise ProviderSamplingExecutionInputError(
                "Provider question text does not match its frozen hash"
            )
        object.__setattr__(self, "question_id", question_id)
        object.__setattr__(self, "question_version", question_version)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "text_hash", text_hash)

    def payload(self) -> dict[str, str]:
        return {
            "question_id": self.question_id,
            "question_version": self.question_version,
            "text": self.text,
            "text_hash": self.text_hash,
        }


@dataclass(frozen=True)
class ProviderSamplingExecutionInput:
    """Secret-free immutable input that can build one Provider Attempt spec."""

    runtime_selection_id: UUID
    prompt: FrozenProviderPrompt
    questions: tuple[ProviderSamplingExecutionQuestion, ...]
    deadline_at: datetime | None
    input_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.runtime_selection_id.int == 0:
            raise ProviderSamplingExecutionInputError(
                "Provider runtime selection ID is invalid"
            )
        if not self.questions:
            raise ProviderSamplingExecutionInputError(
                "Provider execution input requires questions"
            )
        questions = tuple(
            sorted(self.questions, key=lambda item: (item.question_id, item.question_version))
        )
        if len({(item.question_id, item.question_version) for item in questions}) != len(
            questions
        ):
            raise ProviderSamplingExecutionInputError(
                "Provider execution input questions are duplicated"
            )
        if self.deadline_at is not None and (
            self.deadline_at.tzinfo is None or self.deadline_at.utcoffset() is None
        ):
            raise ProviderSamplingExecutionInputError(
                "Provider execution deadline must be timezone-aware"
            )
        object.__setattr__(self, "questions", questions)
        object.__setattr__(self, "input_hash", canonical_json_hash(self.payload()))

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "ProviderSamplingExecutionInput":
        expected = {
            "schema_version",
            "runtime_selection_id",
            "prompt",
            "questions",
            "deadline_at",
        }
        values = _mapping(payload, "Provider execution input")
        if set(values) != expected or values.get("schema_version") != 1:
            raise ProviderSamplingExecutionInputError(
                "Provider execution input schema is invalid"
            )
        questions_value = values.get("questions")
        if not isinstance(questions_value, list):
            raise ProviderSamplingExecutionInputError(
                "Provider execution input questions are invalid"
            )
        questions = tuple(
            _question_from_payload(item) for item in questions_value
        )
        deadline = _timestamp(values.get("deadline_at"), "Provider execution deadline")
        try:
            prompt = parse_frozen_provider_prompt(_mapping(values.get("prompt"), "prompt"))
        except WorkflowCSamplingSpecError as error:
            raise ProviderSamplingExecutionInputError(
                "Provider execution prompt is invalid"
            ) from error
        return cls(
            runtime_selection_id=_uuid(
                values.get("runtime_selection_id"), "Provider runtime selection ID"
            ),
            prompt=prompt,
            questions=questions,
            deadline_at=deadline,
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "runtime_selection_id": str(self.runtime_selection_id),
            "prompt": _prompt_payload(self.prompt),
            "questions": [item.payload() for item in self.questions],
            "deadline_at": (
                self.deadline_at.isoformat() if self.deadline_at is not None else None
            ),
        }

    def build_spec(
        self,
        *,
        run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        task_version: int,
        attempt_version: int,
        question_id: str,
        question_version: str,
        admitted_by: UUID,
        admitted_at: datetime,
        search_mode: str | None,
    ) -> ProviderSamplingWorkerSpec:
        if min(task_version, attempt_version) < 1:
            raise ProviderSamplingExecutionInputError(
                "Provider Attempt versions must be positive"
            )
        if admitted_by.int == 0 or admitted_at.tzinfo is None or admitted_at.utcoffset() is None:
            raise ProviderSamplingExecutionInputError(
                "Provider admission lineage is invalid"
            )
        question = self._question(question_id, question_version)
        payload = {
            "schema_version": 1,
            "kind": "sampling.provider_execute",
            "run_id": str(run_id),
            "task_id": str(task_id),
            "attempt_id": str(attempt_id),
            "task_version": task_version,
            "attempt_version": attempt_version,
            "question": {"text": question.text, "sha256": question.text_hash},
            "runtime_selection_id": str(self.runtime_selection_id),
            "admitted_by": str(admitted_by),
            "admitted_at": admitted_at.isoformat(),
            "prompt": _prompt_payload(self.prompt),
            "search_mode": search_mode,
            "deadline_at": (
                self.deadline_at.isoformat() if self.deadline_at is not None else None
            ),
        }
        try:
            return parse_provider_sampling_spec(payload)
        except WorkflowCSamplingSpecError as error:
            raise ProviderSamplingExecutionInputError(
                "Provider execution input cannot build a Worker spec"
            ) from error

    def _question(
        self, question_id: str, question_version: str
    ) -> ProviderSamplingExecutionQuestion:
        key = (question_id.strip(), question_version.strip())
        for question in self.questions:
            if (question.question_id, question.question_version) == key:
                return question
        raise ProviderSamplingExecutionInputError(
            "Provider execution input does not contain the Sampling question"
        )


def _prompt_payload(prompt: FrozenProviderPrompt) -> dict[str, object]:
    return {
        "binding_id": str(prompt.binding_id),
        "state_id": str(prompt.state_id),
        "state_version": prompt.state_version,
        "release_id": str(prompt.release_id),
        "release_hash": prompt.release_hash,
        "purpose": prompt.purpose,
        "bundle_hash": prompt.bundle_hash,
        "system_message": prompt.system_message,
        "answer_field": prompt.answer_field,
        "output_schema": dict(prompt.output_schema),
        "application_output_schema": dict(prompt.application_output_schema),
        "temperature": prompt.temperature,
        "max_output_tokens": prompt.max_output_tokens,
        "seed": prompt.seed,
        "tool_mode": prompt.tool_mode,
    }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ProviderSamplingExecutionInputError(f"{label} must be an object")
    return MappingProxyType(dict(value))


def _question_from_payload(value: object) -> ProviderSamplingExecutionQuestion:
    question = _mapping(value, "Provider execution question")
    expected = {"question_id", "question_version", "text", "text_hash"}
    if set(question) != expected or not all(
        isinstance(question.get(key), str) for key in expected
    ):
        raise ProviderSamplingExecutionInputError("Provider execution question is invalid")
    return ProviderSamplingExecutionQuestion(
        question_id=str(question["question_id"]),
        question_version=str(question["question_version"]),
        text=str(question["text"]),
        text_hash=str(question["text_hash"]),
    )


def _required_text(value: str, label: str, *, maximum: int) -> str:
    result = value.strip()
    if not result or len(result) > maximum:
        raise ProviderSamplingExecutionInputError(f"{label} is invalid")
    return result


def _hash(value: str, label: str) -> str:
    result = value.strip()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ProviderSamplingExecutionInputError(f"{label} is invalid")
    return result


def _uuid(value: object, label: str) -> UUID:
    try:
        result = UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ProviderSamplingExecutionInputError(f"{label} is invalid") from error
    if result.int == 0:
        raise ProviderSamplingExecutionInputError(f"{label} is invalid")
    return result


def _timestamp(value: object, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProviderSamplingExecutionInputError(f"{label} is invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProviderSamplingExecutionInputError(f"{label} is invalid") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProviderSamplingExecutionInputError(f"{label} must be timezone-aware")
    return result


__all__ = [
    "ProviderSamplingExecutionInput",
    "ProviderSamplingExecutionInputError",
    "ProviderSamplingExecutionQuestion",
]
