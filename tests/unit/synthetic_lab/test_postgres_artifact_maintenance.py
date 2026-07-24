from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from geo_core.synthetic_lab.postgres_artifact_maintenance import (
    PostgresSyntheticArtifactMaintenanceRepository,
)


NOW = datetime(2026, 7, 23, 12, tzinfo=UTC)


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def fetchone(self):
        return self._value

    def fetchall(self):
        assert isinstance(self._value, list)
        return self._value


class _Connection:
    def __init__(self, response: object, calls: list[tuple[str, tuple[object, ...]]]) -> None:
        self._response = response
        self._calls = calls
        self.committed = False

    def execute(self, statement: str, values: tuple[object, ...]):
        self._calls.append((statement, values))
        return _Result(self._response)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_postgres_maintenance_uses_fenced_two_stage_rpc_contract() -> None:
    project_id, artifact_id, outbox_id, lease_token = (uuid4() for _ in range(4))
    row: dict[str, Any] = {
        "outbox_id": outbox_id,
        "project_id": project_id,
        "artifact_id": artifact_id,
        "artifact_generation": 7,
        "lease_token": lease_token,
        "deletion_fencing_generation": 3,
        "lease_expires_at": NOW + timedelta(minutes=2),
        "payload_uri": "s3://geo-synthetic-style-raw/synthetic-raw/payload.bin",
        "manifest_uri": "s3://geo-synthetic-style-raw/synthetic-raw/manifest.json",
        "storage_tier": "restricted_independent_dek",
        "content_hash": "b" * 64,
        "manifest_hash": "a" * 64,
    }
    responses = deque([(2,), [row], (True,), (True,), (True,)])
    calls: list[tuple[str, tuple[object, ...]]] = []

    def connect() -> _Connection:
        return _Connection(responses.popleft(), calls)

    repository = PostgresSyntheticArtifactMaintenanceRepository(connect)
    assert repository.stage_due_expirations(project_id=project_id, now=NOW, limit=100) == 2
    (lease,) = repository.claim_deletions(
        project_id=project_id,
        worker_id="synthetic-maintainer",
        now=NOW,
        batch_size=100,
        lease_seconds=120,
    )
    assert repository.crypto_erase_and_tombstone(lease, erased_at=NOW) is True
    repository.complete_object_deletion(lease, deleted_at=NOW)
    repository.fail_object_deletion(
        lease,
        error_code="object_store_error",
        next_attempt_at=NOW + timedelta(seconds=60),
    )

    statements = "\n".join(statement for statement, _values in calls)
    assert "geo_stage_due_synthetic_artifact_expirations" in statements
    assert "geo_claim_synthetic_artifact_deletions" in statements
    assert "geo_crypto_erase_and_tombstone_synthetic_artifact" in statements
    assert "geo_complete_synthetic_artifact_object_deletion" in statements
    assert "geo_fail_synthetic_artifact_object_deletion" in statements
    crypto_values = next(
        values
        for statement, values in calls
        if "geo_crypto_erase_and_tombstone_synthetic_artifact" in statement
    )
    assert crypto_values[:5] == (
        outbox_id,
        project_id,
        artifact_id,
        7,
        lease_token,
    )
    assert crypto_values[5] != row["manifest_hash"]
    complete_values = next(
        values
        for statement, values in calls
        if "geo_complete_synthetic_artifact_object_deletion" in statement
    )
    assert complete_values[5] != crypto_values[5]
