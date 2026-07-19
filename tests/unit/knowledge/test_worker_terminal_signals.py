from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from geo_core.jobs.postgres import JobCancellationRequested, LostJobLease, WorkerLease
from geo_core.knowledge.question_worker import KnowledgeQuestionGenerateHandler
from geo_core.knowledge.rag_worker import KnowledgeRagExtractHandler
from geo_core.rag import RagSelection


class _RaisingRepository:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def load(self, lease: WorkerLease) -> Any:
        del lease
        raise self._error


class _NoFailureStore:
    def fail(self, *args: object, **kwargs: object) -> str:
        del args, kwargs
        raise AssertionError("terminal worker signals must reach the dispatcher")


@pytest.mark.parametrize(
    "error",
    [
        JobCancellationRequested("cancel requested"),
        LostJobLease("lease fenced"),
    ],
)
@pytest.mark.parametrize("kind", ["rag", "question"])
def test_knowledge_workers_pass_terminal_signals_to_dispatcher(error: Exception, kind: str) -> None:
    store = _NoFailureStore()
    selection = RagSelection("project-native-rag-v1", "project-native-rag-v1", "v1", "d" * 64)
    common: dict[str, Any] = {
        "store": store,
        "repository": _RaisingRepository(error),
        "gateway": object(),
        "object_store": object(),
        "selection": selection,
        "selection_manifest_hash": "b" * 64,
        "lease_for": timedelta(seconds=30),
    }
    handler = (
        KnowledgeRagExtractHandler(**common)
        if kind == "rag"
        else KnowledgeQuestionGenerateHandler(**common)
    )
    lease = WorkerLease(uuid4(), uuid4(), f"knowledge.{kind}", "worker", uuid4(), 1, 1, 3)

    with pytest.raises(type(error), match=str(error)):
        handler.handle(lease)
