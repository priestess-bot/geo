from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from geo_core.sampling.postgres_suites import PostgresSamplingSuiteRepository


PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


class _CommandCaptured(Exception):
    pass


class _Connection:
    def __init__(self) -> None:
        self.parameters: tuple[object, ...] | None = None
        self.closed = False

    def execute(self, statement: str, parameters=None):
        if "set_config" in statement:
            return object()
        self.parameters = parameters
        raise _CommandCaptured

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_legacy_suite_command_hash_keeps_pre_0126_shape() -> None:
    connection = _Connection()
    suite = _suite(question_ids=("q-1",))
    input_option = _input_option()

    with pytest.raises(_CommandCaptured):
        PostgresSamplingSuiteRepository(connect=lambda: connection).create_suite(
            suite,
            input_option=input_option,
            idempotency_key="suite:legacy",
        )

    assert connection.parameters is not None
    assert connection.parameters[3] == _json_hash(
        {
            "operation": "create",
            "suite_id": str(suite.id),
            "suite_hash": suite.suite_hash,
            "input_option_hash": input_option.option_hash,
            "frozen_by": suite.frozen_by,
        }
    )
    assert connection.parameters[7].obj.keys() == {
        "schema_version",
        "suite",
        "frozen_by",
        "frozen_at",
    }


def test_explicit_ten_question_selection_is_included_in_hash_and_payload() -> None:
    connection = _Connection()
    question_ids = tuple(f"q-{index}" for index in range(10))
    suite = _suite(question_ids=question_ids)
    input_option = _input_option()

    with pytest.raises(_CommandCaptured):
        PostgresSamplingSuiteRepository(connect=lambda: connection).create_suite(
            suite,
            input_option=input_option,
            idempotency_key="suite:pilot",
            selected_question_set_item_ids=question_ids,
        )

    assert connection.parameters is not None
    expected = {
        "operation": "create",
        "suite_id": str(suite.id),
        "suite_hash": suite.suite_hash,
        "input_option_hash": input_option.option_hash,
        "frozen_by": suite.frozen_by,
        "question_set_item_ids": list(question_ids),
    }
    assert connection.parameters[3] == _json_hash(expected)
    assert connection.parameters[7].obj["question_set_item_ids"] == list(question_ids)


def _input_option() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=PROJECT_ID,
        option_hash="a" * 64,
    )


def _suite(*, question_ids: tuple[str, ...]) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        project_id=PROJECT_ID,
        suite_hash="b" * 64,
        frozen_by="operator",
        frozen_at=NOW,
        questions=tuple(SimpleNamespace(question_id=value) for value in question_ids),
        canonical_value=lambda: {
            "project_id": str(PROJECT_ID),
            "questions": [{"question_id": value} for value in question_ids],
        },
    )


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
