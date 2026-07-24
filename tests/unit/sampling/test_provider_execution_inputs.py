from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from uuid import uuid4

import pytest

from geo_core.sampling.provider_execution_inputs import (
    ProviderSamplingExecutionInput,
    ProviderSamplingExecutionInputError,
)


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def test_frozen_execution_input_round_trips_and_builds_a_worker_spec() -> None:
    input_value = ProviderSamplingExecutionInput.from_payload(_payload())

    assert ProviderSamplingExecutionInput.from_payload(input_value.payload()) == input_value
    spec = input_value.build_spec(
        run_id=uuid4(),
        task_id=uuid4(),
        attempt_id=uuid4(),
        task_version=2,
        attempt_version=1,
        question_id="q-1",
        question_version="v1",
        admitted_by=uuid4(),
        admitted_at=NOW,
        search_mode="web_search",
    )

    assert spec.question_text == "Which provider should I choose?"
    assert spec.question_hash == _hash("Which provider should I choose?")
    assert spec.prompt.release_hash == _hash("prompt-release")
    assert input_value.input_hash == ProviderSamplingExecutionInput.from_payload(
        input_value.payload()
    ).input_hash


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["questions"][0].update({"text_hash": _hash("wrong")}),
        lambda payload: payload["questions"][0].update({"unexpected": "field"}),
        lambda payload: payload["questions"].append("not-an-object"),
        lambda payload: payload.update({"unexpected": "field"}),
    ],
)
def test_execution_input_rejects_unfrozen_or_unknown_fields(mutate) -> None:
    payload = _payload()
    mutate(payload)

    with pytest.raises(ProviderSamplingExecutionInputError):
        ProviderSamplingExecutionInput.from_payload(payload)


def test_execution_input_rejects_unknown_question_when_building_spec() -> None:
    input_value = ProviderSamplingExecutionInput.from_payload(_payload())

    with pytest.raises(ProviderSamplingExecutionInputError, match="does not contain"):
        input_value.build_spec(
            run_id=uuid4(),
            task_id=uuid4(),
            attempt_id=uuid4(),
            task_version=2,
            attempt_version=1,
            question_id="q-unknown",
            question_version="v1",
            admitted_by=uuid4(),
            admitted_at=NOW,
            search_mode=None,
        )


def _payload() -> dict[str, object]:
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    return {
        "schema_version": 1,
        "runtime_selection_id": str(uuid4()),
        "prompt": {
            "binding_id": str(uuid4()),
            "state_id": str(uuid4()),
            "state_version": 1,
            "release_id": str(uuid4()),
            "release_hash": _hash("prompt-release"),
            "purpose": "geo_measurement",
            "bundle_hash": _hash("prompt-bundle"),
            "system_message": "Return a JSON answer.",
            "answer_field": "answer",
            "output_schema": schema,
            "application_output_schema": schema,
            "temperature": 0.2,
            "max_output_tokens": 256,
            "seed": 7,
            "tool_mode": None,
        },
        "questions": [
            {
                "question_id": "q-1",
                "question_version": "v1",
                "text": "Which provider should I choose?",
                "text_hash": _hash("Which provider should I choose?"),
            }
        ],
        "deadline_at": None,
    }


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
