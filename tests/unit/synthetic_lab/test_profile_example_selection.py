from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest

from geo_core.synthetic_lab.ports import SyntheticLabPersistenceError
from geo_core.synthetic_lab.postgres_manual_import import PostgresManualImportService


class _Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(
        self,
        rows: dict[UUID, dict[str, object]],
        calls: list[tuple[str, tuple[object, ...]]],
    ) -> None:
        self._rows = rows
        self._calls = calls

    def execute(self, statement: str, values: tuple[object, ...]) -> _Rows:
        self._calls.append((statement, values))
        if "set_config('geo.project_id'" in statement:
            return _Rows([])
        assert "sample.short_example_eligible" in statement
        project_id, sample_ids, limit = values
        assert isinstance(project_id, UUID)
        assert isinstance(sample_ids, list)
        selected = [self._rows[item] for item in sample_ids if item in self._rows]
        selected.sort(
            key=lambda row: (str(row["normalized_text_hash"]), str(row["id"]))
        )
        return _Rows(selected[: int(limit)])

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class _Artifacts:
    def __init__(self, texts: dict[UUID, str]) -> None:
        self._texts = texts

    def load(self, reference: Any) -> bytearray:
        return bytearray(self._texts[reference.artifact_id].encode("utf-8"))


@pytest.mark.parametrize("sample_count", (200, 205))
def test_profile_example_selection_is_bounded_and_input_order_independent(
    sample_count: int,
) -> None:
    project_id = uuid4()
    namespace = uuid4()
    sample_ids = tuple(uuid5(namespace, f"sample:{index}") for index in range(sample_count))
    texts = {
        sample_id: f"Approved anonymous Australian example {index}: " + ("x" * 120)
        for index, sample_id in enumerate(sample_ids)
    }
    rows = {
        sample_id: {
            "id": sample_id,
            "normalized_text_hash": _hash(text),
            "object_uri": f"s3://synthetic-examples/{sample_id}.bin",
            "object_hash": _hash(f"encrypted:{sample_id}"),
            "plaintext_hash": _hash(text),
            "key_version": "1",
            "algorithm": "AES-256-GCM/HKDF-project-artifact/v1",
            "byte_size": len(text.encode("utf-8")) + 64,
        }
        for sample_id, text in texts.items()
    }
    calls: list[tuple[str, tuple[object, ...]]] = []
    service = PostgresManualImportService(
        connection_factory=lambda: _Connection(rows, calls),
        artifacts=_Artifacts(texts),  # type: ignore[arg-type]
    )

    selected = service.load_profile_examples(
        project_id=project_id,
        sample_ids=sample_ids,
    )
    reordered = service.load_profile_examples(
        project_id=project_id,
        sample_ids=tuple(reversed(sample_ids)),
    )

    assert selected == reordered
    assert len(selected) == 24
    assert all(len(text) <= 240 for _sample_id, text in selected)
    selection_calls = [
        (statement, values)
        for statement, values in calls
        if "sample.short_example_eligible" in statement
    ]
    assert len(selection_calls) == 2
    assert all("ORDER BY sample.normalized_text_hash, sample.id" in item[0] for item in selection_calls)
    assert all(len(item[1][1]) == sample_count and item[1][2] == 24 for item in selection_calls)


def test_profile_example_selection_reports_the_eligible_sample_shortfall() -> None:
    project_id = uuid4()
    sample_ids = tuple(uuid4() for _ in range(23))
    rows = {
        sample_id: {
            "id": sample_id,
            "normalized_text_hash": _hash(f"sample:{index}"),
            "object_uri": f"s3://synthetic-examples/{sample_id}.bin",
            "object_hash": _hash(f"encrypted:{sample_id}"),
            "plaintext_hash": _hash(f"text:{sample_id}"),
            "key_version": "1",
            "algorithm": "AES-256-GCM/HKDF-project-artifact/v1",
            "byte_size": 128,
        }
        for index, sample_id in enumerate(sample_ids)
    }
    service = PostgresManualImportService(
        connection_factory=lambda: _Connection(rows, []),
        artifacts=_Artifacts({}),  # type: ignore[arg-type]
    )

    with pytest.raises(
        SyntheticLabPersistenceError,
        match=(
            r"found 23 approved, unique, short-example-eligible samples; requires 24\. "
            r"Import, anonymize, and approve 1 more eligible sample before retrying"
        ),
    ):
        service.load_profile_examples(project_id=project_id, sample_ids=sample_ids)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
