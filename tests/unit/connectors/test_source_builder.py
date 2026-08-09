from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from geo_core.connectors import ConnectorKind, ConnectorSyncMode, ConnectorSyncPlan
from geo_core.connectors.jobs import ConnectorJobSpec
from geo_core.connectors.source_builder import (
    build_pyairbyte_connection_test_source,
    build_pyairbyte_source,
)
from geo_core.connectors.worker import ConnectorExecutionState, ConnectorWorkerError


def _state() -> ConnectorExecutionState:
    project_id, run_id = uuid4(), uuid4()
    plan = ConnectorSyncPlan(
        project_id=project_id,
        definition_id=uuid4(),
        connection_id=uuid4(),
        scope_id=uuid4(),
        mode=ConnectorSyncMode.INITIAL,
        adapter_release="source-google-search-console:2.1.5",
        input_checkpoint_id=None,
        input_checkpoint_hash="0" * 64,
        window_start=None,
        window_end=None,
        requested_by=uuid4(),
        requested_at=datetime(2026, 7, 28, tzinfo=UTC),
    )
    return ConnectorExecutionState(
        spec=ConnectorJobSpec(project_id, run_id, 1, plan.plan_hash),
        plan=plan,
        run_version=3,
        connector_kind=ConnectorKind.GOOGLE_SEARCH_CONSOLE,
        secret_reference_id=uuid4(),
        secret_purpose="connector.gsc",
        secret_version=1,
        source_locator="sc-domain:example.com",
        streams=("search_analytics_by_date", "search_analytics_by_page"),
        report_spec={},
        date_policy={},
        projection_kind="gsc.search_analytics.v1",
    )


def test_builder_accepts_only_the_frozen_gsc_release_and_streams() -> None:
    source = build_pyairbyte_source(_state(), {"authorization": {"client_id": "x"}})
    assert "secret" not in repr(source).casefold()

    state = _state()
    drifted_plan = replace(state.plan, adapter_release="source-google-search-console:9.9.9")
    with pytest.raises(ConnectorWorkerError, match="release"):
        build_pyairbyte_source(replace(state, plan=drifted_plan), {"key": "value"})
    with pytest.raises(ConnectorWorkerError, match="streams"):
        build_pyairbyte_source(replace(state, streams=("unexpected",)), {"key": "value"})


def test_connection_test_builder_projects_the_frozen_ga4_scope() -> None:
    source = build_pyairbyte_connection_test_source(
        connector_kind=ConnectorKind.GOOGLE_ANALYTICS_4,
        adapter_release="source-google-analytics-data-api:2.9.43",
        credential={"credentials": {"client_email": "runtime-only"}},
        source_locator="properties/123456789",
        streams=("reports",),
        report_spec={"dimensions": ["date"], "metrics": ["sessions"]},
        date_policy={"start_date": "2026-08-01", "end_date": "2026-08-07"},
    )

    assert source._config["property_ids"] == ["123456789"]
    assert source._config["custom_reports_array"] == [{
        "name": "reports",
        "dimensions": ["date"],
        "metrics": ["sessions"],
    }]
    assert source._config["date_ranges_start_date"] == "2026-08-01"
    assert source._config["date_ranges_end_date"] == "2026-08-07"
    assert source._config["credentials"] == {"client_email": "runtime-only"}
