from __future__ import annotations

from datetime import timedelta
import hashlib
import threading
from typing import Any, Mapping
from uuid import uuid4

import pytest

from geo_core.jobs.postgres import LostJobLease, WorkerLease
from geo_core.knowledge.domain import ProcessingInput, ProcessingResult
from geo_core.knowledge.worker import KnowledgeProcessHandler


class FakeStore:
    def __init__(self, *, heartbeat_error: Exception | None = None) -> None:
        self.heartbeat_called = threading.Event()
        self.heartbeat_error = heartbeat_error

    def heartbeat(self, lease: WorkerLease, *, lease_for: timedelta) -> None:
        del lease, lease_for
        self.heartbeat_called.set()
        if self.heartbeat_error is not None:
            raise self.heartbeat_error


class StubKnowledgeProcessHandler(KnowledgeProcessHandler):
    def __init__(self, store: Any, claim: ProcessingInput) -> None:
        super().__init__(store, lease_for=timedelta(milliseconds=30))
        self.claim = claim
        self.finalized = False
        self.failure: tuple[Exception, bool] | None = None

    def _load(self, lease: WorkerLease) -> ProcessingInput:
        del lease
        return self.claim

    def _finalize(
        self, lease: WorkerLease, claim: ProcessingInput, result: ProcessingResult
    ) -> Mapping[str, object]:
        del lease, claim, result
        self.finalized = True
        return {"status": "succeeded"}

    def _fail(self, lease: WorkerLease, error: Exception, *, retry: bool) -> Mapping[str, object]:
        del lease
        self.failure = (error, retry)
        return {"status": "failed"}


def test_knowledge_worker_renews_lease_during_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    store = FakeStore()
    handler = StubKnowledgeProcessHandler(store, claim)

    def process_source(value: ProcessingInput) -> ProcessingResult:
        assert value == claim
        assert store.heartbeat_called.wait(timeout=1)
        return _result()

    monkeypatch.setattr("geo_core.knowledge.worker.process_source", process_source)

    assert handler.handle(_lease(claim))["status"] == "succeeded"
    assert handler.finalized is True
    assert handler.failure is None


def test_knowledge_worker_checks_heartbeat_failure_before_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    lost_lease = LostJobLease("fenced during parsing")
    store = FakeStore(heartbeat_error=lost_lease)
    handler = StubKnowledgeProcessHandler(store, claim)

    def process_source(value: ProcessingInput) -> ProcessingResult:
        assert value == claim
        assert store.heartbeat_called.wait(timeout=1)
        return _result()

    monkeypatch.setattr("geo_core.knowledge.worker.process_source", process_source)

    with pytest.raises(LostJobLease, match="fenced during parsing"):
        handler.handle(_lease(claim))
    assert handler.finalized is False
    assert handler.failure is None


def _claim() -> ProcessingInput:
    project_id = uuid4()
    return ProcessingInput(
        source_id=uuid4(),
        pipeline_run_id=uuid4(),
        project_id=project_id,
        source_kind="text",
        title="Lease test",
        source_url=None,
        filename=None,
        media_type="text/plain",
        raw_content=b"content",
    )


def _result() -> ProcessingResult:
    content = b"content"
    digest = hashlib.sha256(content).hexdigest()
    return ProcessingResult(
        raw_content=content,
        resolved_url=None,
        raw_text="content",
        cleaned_text="content",
        raw_text_hash=digest,
        cleaned_text_hash=digest,
        parser_version="test-v1",
        chunks=(),
        facts=(),
        findings=(),
    )


def _lease(claim: ProcessingInput) -> WorkerLease:
    return WorkerLease(uuid4(), claim.project_id, "knowledge.process", "worker-1", uuid4(), 1, 1, 3)
