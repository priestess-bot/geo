from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets import SecretValue
from geo_core.workflow_c_job_specs import (
    PostgresWorkflowCJobSpecWriter,
    PostgresWorkflowCJobSpecRepository,
    WORKFLOW_C_JOB_KINDS,
    WorkflowCJobSpec,
    WorkflowCJobSpecError,
)


def test_job_spec_requires_canonical_hash_schema_and_safe_nested_payload() -> None:
    payload = _payload()

    spec = WorkflowCJobSpec(
        project_id=uuid4(),
        job_id=uuid4(),
        kind="workflow_c.alert.notify",
        spec_hash=_hash(payload),
        payload=payload,
        created_at=datetime.now(UTC),
    )

    assert spec.payload["kind"] == "workflow_c.alert.notify"
    with pytest.raises(WorkflowCJobSpecError, match="secret or credential"):
        WorkflowCJobSpec(
            project_id=uuid4(),
            job_id=uuid4(),
            kind="workflow_c.alert.notify",
            spec_hash=_hash({**payload, "nested": {"token": "forbidden"}}),
            payload={**payload, "nested": {"token": "forbidden"}},
            created_at=datetime.now(UTC),
        )


@pytest.mark.parametrize(
    "field_name",
    (
        "api-key",
        "access_token",
        "client_secret",
        "cookie",
        "proxy_url",
        "refresh_token",
        "session_token",
        "storage-state",
    ),
)
def test_job_spec_rejects_expanded_credential_fields_recursively(field_name: str) -> None:
    payload = {**_payload(), "nested": {"items": [{field_name: "forbidden"}]}}

    with pytest.raises(WorkflowCJobSpecError, match="secret or credential"):
        WorkflowCJobSpec(
            project_id=uuid4(),
            job_id=uuid4(),
            kind="workflow_c.alert.notify",
            spec_hash=_hash(payload),
            payload=payload,
            created_at=datetime.now(UTC),
        )


def test_job_spec_rejects_a_secret_object_before_canonical_json_hashing() -> None:
    payload = {**_payload(), "nested": {"safe_label": SecretValue("must-not-persist")}}

    with pytest.raises(WorkflowCJobSpecError, match="secret or credential"):
        WorkflowCJobSpec(
            project_id=uuid4(),
            job_id=uuid4(),
            kind="workflow_c.alert.notify",
            spec_hash="a" * 64,
            payload=payload,
            created_at=datetime.now(UTC),
        )


def test_job_spec_allows_secret_reference_lineage_and_token_limits() -> None:
    payload = {
        **_payload(),
        "secret_reference_id": str(uuid4()),
        "prompt": {"max_output_tokens": 256},
    }

    spec = WorkflowCJobSpec(
        project_id=uuid4(),
        job_id=uuid4(),
        kind="workflow_c.alert.notify",
        spec_hash=_hash(payload),
        payload=payload,
        created_at=datetime.now(UTC),
    )

    assert spec.payload["secret_reference_id"] == payload["secret_reference_id"]


def test_job_spec_accepts_only_the_minimal_semantic_v2_manifest_pointer() -> None:
    manifest_id = uuid4()
    payload: dict[str, object] = {
        "schema_version": 2,
        "kind": "workflow_c.analysis.semantic_metrics",
        "semantic_metrics": {
            "manifest_id": str(manifest_id),
            "manifest_hash": "a" * 64,
        },
    }

    spec = WorkflowCJobSpec(
        project_id=uuid4(),
        job_id=uuid4(),
        kind="workflow_c.analysis.semantic_metrics",
        spec_hash=_hash(payload),
        payload=payload,
        created_at=datetime.now(UTC),
    )

    assert spec.payload["semantic_metrics"] == payload["semantic_metrics"]


@pytest.mark.parametrize(
    "kind,pointer",
    (
        (
            "workflow_c.alert.notify",
            {"manifest_id": str(uuid4()), "manifest_hash": "a" * 64},
        ),
        (
            "workflow_c.analysis.semantic_metrics",
            {"manifest_id": "not-a-uuid", "manifest_hash": "a" * 64},
        ),
        (
            "workflow_c.analysis.semantic_metrics",
            {"manifest_id": str(uuid4()), "manifest_hash": "A" * 64},
        ),
        (
            "workflow_c.analysis.semantic_metrics",
            {
                "manifest_id": str(uuid4()),
                "manifest_hash": "a" * 64,
                "answer_text": "must never enter a Job spec",
            },
        ),
    ),
)
def test_job_spec_rejects_noncanonical_semantic_v2_pointers(
    kind: str, pointer: dict[str, object]
) -> None:
    payload: dict[str, object] = {
        "schema_version": 2,
        "kind": kind,
        "semantic_metrics": pointer,
    }

    with pytest.raises(WorkflowCJobSpecError):
        WorkflowCJobSpec(
            project_id=uuid4(),
            job_id=uuid4(),
            kind=kind,
            spec_hash=_hash(payload),
            payload=payload,
            created_at=datetime.now(UTC),
        )


def test_generic_writer_rejects_semantic_v2_before_database_access() -> None:
    payload: dict[str, object] = {
        "schema_version": 2,
        "kind": "workflow_c.analysis.semantic_metrics",
        "semantic_metrics": {
            "manifest_id": str(uuid4()),
            "manifest_hash": "a" * 64,
        },
    }
    connection = _WriterConnection(
        project_id=uuid4(), job_id=uuid4(), payload=payload
    )

    with pytest.raises(WorkflowCJobSpecError, match="atomic semantic admission"):
        PostgresWorkflowCJobSpecWriter(lambda: connection).enqueue(
            project_id=connection.project_id,
            kind="workflow_c.analysis.semantic_metrics",
            payload=payload,
            idempotency_key="semantic-v2-cannot-use-generic-writer",
        )

    assert connection.queries == []


def test_job_spec_rejects_an_unknown_worker_kind_before_database_access() -> None:
    payload = _payload(kind="workflow_c.unsupported")

    with pytest.raises(WorkflowCJobSpecError, match="kind is unsupported"):
        WorkflowCJobSpec(
            project_id=uuid4(),
            job_id=uuid4(),
            kind="workflow_c.unsupported",
            spec_hash=_hash(payload),
            payload=payload,
            created_at=datetime.now(UTC),
        )

    assert len(WORKFLOW_C_JOB_KINDS) == 10


def test_job_spec_rejects_non_utf8_canonical_payloads() -> None:
    payload = _payload()
    payload["summary"] = "invalid-surrogate-\ud800"

    with pytest.raises(WorkflowCJobSpecError, match="not canonical JSON"):
        WorkflowCJobSpec(
            project_id=uuid4(),
            job_id=uuid4(),
            kind="workflow_c.alert.notify",
            spec_hash="a" * 64,
            payload=payload,
            created_at=datetime.now(UTC),
        )


def test_postgres_repository_requires_the_current_fenced_lease() -> None:
    lease = _lease()
    payload = _payload()
    connection = _Connection(
        {
            "project_id": lease.project_id,
            "job_id": lease.job_id,
            "kind": lease.kind,
            "spec_hash": _hash(payload),
            "spec_payload": payload,
            "created_at": datetime.now(UTC),
            "input_hash": _hash(payload),
            "durable_kind": lease.kind,
            "status": "running",
            "lease_token": lease.lease_token,
            "fencing_generation": lease.fencing_generation,
            "lease_expires_at": datetime.now(UTC) + timedelta(minutes=1),
        }
    )

    spec = PostgresWorkflowCJobSpecRepository(lambda: connection).load(lease)

    assert spec.job_id == lease.job_id
    assert connection.closed
    assert connection.rolled_back
    assert any("workflow_c_job_specs" in query for query in connection.queries)


def test_postgres_repository_rejects_a_stale_fencing_token() -> None:
    lease = _lease()
    payload = _payload()
    connection = _Connection(
        {
            "project_id": lease.project_id,
            "job_id": lease.job_id,
            "kind": lease.kind,
            "spec_hash": _hash(payload),
            "spec_payload": payload,
            "created_at": datetime.now(UTC),
            "input_hash": _hash(payload),
            "durable_kind": lease.kind,
            "status": "running",
            "lease_token": uuid4(),
            "fencing_generation": lease.fencing_generation,
            "lease_expires_at": datetime.now(UTC) + timedelta(minutes=1),
        }
    )

    with pytest.raises(WorkflowCJobSpecError, match="no longer belongs"):
        PostgresWorkflowCJobSpecRepository(lambda: connection).load(lease)


def test_postgres_repository_binds_metric_child_to_its_encrypted_task_hash() -> None:
    job_id, parent_job_id, batch_id = uuid4(), uuid4(), uuid4()
    task_hash = "a" * 64
    lease = WorkerLease(
        job_id=job_id,
        project_id=uuid4(),
        kind="workflow_c.metric_judge",
        worker_id="test-worker",
        lease_token=uuid4(),
        fencing_generation=2,
        attempt_count=1,
        max_attempts=3,
    )
    payload = {
        "schema_version": 1,
        "kind": "workflow_c.metric_judge",
        "metric_model_child": {
            "child_job_id": str(job_id),
            "parent_job_id": str(parent_job_id),
            "batch_id": str(batch_id),
            "role": "metric_judge",
            "parent_input_hash": "b" * 64,
            "task_hash": task_hash,
        },
    }
    connection = _Connection(
        {
            "project_id": lease.project_id,
            "job_id": lease.job_id,
            "kind": lease.kind,
            "spec_hash": _hash(payload),
            "spec_payload": payload,
            "created_at": datetime.now(UTC),
            "input_hash": task_hash,
            "durable_kind": lease.kind,
            "status": "running",
            "lease_token": lease.lease_token,
            "fencing_generation": lease.fencing_generation,
            "lease_expires_at": datetime.now(UTC) + timedelta(minutes=1),
        }
    )

    spec = PostgresWorkflowCJobSpecRepository(lambda: connection).load(lease)

    assert spec.spec_hash == _hash(payload)
    assert spec.payload["metric_model_child"]["task_hash"] == task_hash
    connection._row["input_hash"] = "c" * 64
    with pytest.raises(WorkflowCJobSpecError, match="task differs"):
        PostgresWorkflowCJobSpecRepository(lambda: connection).load(lease)


def test_writer_uses_the_atomic_job_spec_producer_in_one_project_transaction() -> None:
    project_id = uuid4()
    job_id = uuid4()
    payload = _payload(kind="workflow_c.alert.notify")
    connection = _WriterConnection(
        project_id=project_id,
        job_id=job_id,
        payload=payload,
    )

    result = PostgresWorkflowCJobSpecWriter(lambda: connection).enqueue(
        project_id=project_id,
        kind="workflow_c.alert.notify",
        payload=payload,
        idempotency_key="workflow-c-drift:fixture",
    )

    assert result.job_id == job_id
    assert not result.replayed
    assert connection.committed
    assert connection.closed
    assert not connection.rolled_back
    joined = "\n".join(connection.queries)
    assert "geo_enqueue_workflow_c_job_spec" in joined
    assert "INSERT INTO durable_jobs" not in joined
    assert "INSERT INTO workflow_c_job_specs" not in joined
    assert "INSERT INTO broker_outbox" not in joined


def test_writer_rejects_an_analytical_job_before_it_can_reach_postgres() -> None:
    connection = _WriterConnection(
        project_id=uuid4(),
        job_id=uuid4(),
        payload=_payload(kind="workflow_c.analysis.drift"),
    )

    with pytest.raises(WorkflowCJobSpecError, match="drift Worker input"):
        PostgresWorkflowCJobSpecWriter(lambda: connection).enqueue(
            project_id=connection.project_id,
            kind="workflow_c.analysis.drift",
            payload=connection.payload,
            idempotency_key="workflow-c-drift:invalid",
        )

    assert connection.queries == []


def _payload(*, kind: str = "workflow_c.alert.notify") -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": kind,
        "notification_id": str(uuid4()),
        "secret_reference_id": str(uuid4()),
    }


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _lease() -> WorkerLease:
    return WorkerLease(
        job_id=uuid4(),
        project_id=uuid4(),
        kind="workflow_c.alert.notify",
        worker_id="test-worker",
        lease_token=uuid4(),
        fencing_generation=2,
        attempt_count=1,
        max_attempts=3,
    )


class _Cursor:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Connection:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row
        self.queries: list[str] = []
        self.rolled_back = False
        self.closed = False

    def execute(self, query: str, _params: object = None) -> _Cursor:
        self.queries.append(query)
        return _Cursor(self._row if "workflow_c_job_specs" in query else None)

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _WriterConnection:
    def __init__(self, *, project_id, job_id, payload: dict[str, object]) -> None:
        self.project_id = project_id
        self.job_id = job_id
        self.payload = payload
        self.queries: list[str] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, query: str, _params: object = None) -> _Cursor:
        self.queries.append(query)
        if "geo_enqueue_workflow_c_job_spec" in query:
            return _Cursor(
                {"job_id": self.job_id, "input_hash": _hash(self.payload), "replayed": False}
            )
        return _Cursor(None)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True
