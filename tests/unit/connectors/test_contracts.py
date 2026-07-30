from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from geo_core.connectors import (
    ConnectorRuleViolation,
    ConnectorSyncCommit,
    ConnectorSyncMode,
    ConnectorSyncPlan,
    FreshnessStatus,
    RawArtifactDescriptor,
    SchemaCompatibility,
    canonical_hash,
)


NOW = datetime(2026, 7, 28, 2, 0, tzinfo=UTC)


def test_sync_plan_has_stable_identity_and_incremental_requires_checkpoint() -> None:
    values = dict(
        project_id=uuid4(),
        definition_id=uuid4(),
        connection_id=uuid4(),
        scope_id=uuid4(),
        mode=ConnectorSyncMode.INITIAL,
        adapter_release="source-google-search-console:2.1.5",
        input_checkpoint_id=None,
        input_checkpoint_hash="0" * 64,
        window_start=NOW - timedelta(days=2),
        window_end=NOW - timedelta(days=1),
        requested_by=uuid4(),
        requested_at=NOW,
    )
    first = ConnectorSyncPlan(**values)
    second = ConnectorSyncPlan(**{**values, "requested_at": NOW + timedelta(hours=1)})
    assert first.plan_hash == second.plan_hash
    assert first.idempotency_key == f"connector.sync:{first.plan_hash}"

    with pytest.raises(ConnectorRuleViolation, match="input checkpoint"):
        ConnectorSyncPlan(**{**values, "mode": ConnectorSyncMode.INCREMENTAL})


def test_commit_rejects_breaking_schema_and_computes_checkpoint_and_lag() -> None:
    schema = {"fields": [{"name": "date", "type": "date"}]}
    values = dict(
        project_id=uuid4(),
        run_id=uuid4(),
        expected_run_version=2,
        expected_checkpoint_hash="1" * 64,
        artifact=RawArtifactDescriptor(
            manifest_uri="minio://geo-connectors/run/manifest.json",
            manifest_hash="2" * 64,
            content_hash="3" * 64,
            schema_fingerprint="4" * 64,
            record_count=12,
            byte_size=2048,
            classification="internal_raw",
            retention_until=NOW + timedelta(days=90),
            encryption_key_reference="connector-dek:v1",
            producer_commit="5" * 40,
        ),
        schema_document=schema,
        schema_hash=canonical_hash(schema),
        compatibility=SchemaCompatibility.COMPATIBLE,
        schema_diff={},
        projection_kind="gsc.search_analytics.v1",
        projection_row_count=12,
        projection_dataset_hash="6" * 64,
        projection_lineage={"business_key": ["date", "query", "page"]},
        projection_records=tuple(
            {"date": "2026-07-27", "query": f"query-{index}"}
            for index in range(12)
        ),
        next_cursor_state={"date": "2026-07-27"},
        next_watermark=NOW - timedelta(hours=2),
        expected_watermark=NOW,
        freshness_status=FreshnessStatus.FRESH,
        freshness_reason="source watermark is within policy",
    )
    commit = ConnectorSyncCommit(**values)
    assert len(commit.next_checkpoint_hash) == 64
    assert commit.lag_seconds == 7200

    with pytest.raises(ConnectorRuleViolation, match="breaking schema"):
        ConnectorSyncCommit(**{**values, "compatibility": SchemaCompatibility.BREAKING})


def test_raw_artifact_rejects_uncontrolled_or_untraceable_payload() -> None:
    with pytest.raises(ConnectorRuleViolation, match="manifest URI"):
        RawArtifactDescriptor(
            manifest_uri="https://example.test/raw.json",
            manifest_hash="1" * 64,
            content_hash="2" * 64,
            schema_fingerprint="3" * 64,
            record_count=1,
            byte_size=1,
            classification="internal_raw",
            retention_until=NOW,
            encryption_key_reference="dek:v1",
            producer_commit="4" * 40,
        )
