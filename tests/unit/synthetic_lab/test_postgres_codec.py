from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from geo_core.jobs.lifecycle import DomainJobSpec, DurableJob
from geo_core.synthetic_lab.authorization import (
    AuthorizationState,
    create_authorization_record,
)
from geo_core.synthetic_lab.ports import SyntheticLabPersistenceError
from geo_core.synthetic_lab.postgres import build_synthetic_lab_persistence
from geo_core.synthetic_lab.postgres_codec import decode_object, encode_object, payload_hash
from geo_core.synthetic_lab.postgres_execution import build_synthetic_execution_repository


def test_codec_round_trips_registered_immutable_record() -> None:
    record = create_authorization_record(
        id=uuid4(),
        project_id=uuid4(),
        channel="reddit",
        adapter_release="reddit-style-v1",
        version_number=1,
        previous_version_id=None,
        state=AuthorizationState.NOT_ASSESSED,
        evidence_reference_hash=None,
        decided_by=None,
        decided_at=None,
        allowed_purposes=(),
        max_requests_per_period=None,
        period_seconds=None,
        max_concurrency=None,
        expires_at=None,
        decision_reason=None,
    )

    type_name, payload, content_hash = encode_object(record)

    assert decode_object(type_name, payload) == record
    assert content_hash == payload_hash(payload)
    assert content_hash != payload_hash({**payload, "unexpected": True})


def test_codec_rejects_unknown_types_tags_bytes_and_naive_datetimes() -> None:
    with pytest.raises(SyntheticLabPersistenceError, match="not registered"):
        decode_object("builtins.object", {"$type": "builtins.object", "fields": {}})
    with pytest.raises(SyntheticLabPersistenceError, match="tag is invalid"):
        decode_object(
            "geo_core.jobs.lifecycle.DomainJobSpec",
            {"$unknown": "value"},
        )
    with pytest.raises(SyntheticLabPersistenceError, match="byte payloads"):
        encode_object(DomainJobSpec(kind="probe", payload={"probe_hash": b"secret"}))
    job = DurableJob(
        id=uuid4(),
        project_id=uuid4(),
        spec=DomainJobSpec(kind="probe", payload={"probe_hash": "a" * 64}),
        input_hash="b" * 64,
        idempotency_key="probe-v1",
    )
    with pytest.raises(SyntheticLabPersistenceError, match="timezone-aware"):
        encode_object(replace(job, next_run_at=datetime(2026, 7, 23)))


def test_postgres_builders_are_lazy_and_validate_configuration() -> None:
    assert build_synthetic_lab_persistence(None) is None
    assert build_synthetic_lab_persistence(" ") is None
    persistence = build_synthetic_lab_persistence(
        "postgresql://geo_app:unused@127.0.0.1:5432/unused"
    )
    assert persistence is not None
    assert persistence.execution is not None
    assert persistence.collection_authorizations is not None
    assert build_synthetic_execution_repository(
        "postgresql://geo_worker:unused@127.0.0.1:5432/unused"
    ) is not None
    with pytest.raises(ValueError, match="cannot be empty"):
        build_synthetic_execution_repository(" ")


def test_codec_preserves_aware_datetimes() -> None:
    job = DurableJob(
        id=uuid4(),
        project_id=uuid4(),
        spec=DomainJobSpec(kind="probe", payload={"probe_hash": "a" * 64}),
        input_hash="b" * 64,
        idempotency_key="probe-aware-v1",
        next_run_at=datetime(2026, 7, 23, tzinfo=UTC),
    )
    type_name, payload, _ = encode_object(job)
    assert decode_object(type_name, payload) == job
