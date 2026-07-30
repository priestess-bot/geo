from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from geo_core.connectors import ConnectorSyncMode, ConnectorSyncPlan
from geo_core.connectors.pyairbyte_source import GSC_CONNECTOR_RELEASE, gsc_source


class FakeSource:
    def __init__(self) -> None:
        self.read_arguments = None

    def read(self, **arguments):
        self.read_arguments = arguments
        record = SimpleNamespace(data={"date": "2026-07-27T00:00:00+00:00", "clicks": 4})
        dataset = SimpleNamespace(records=[record])
        return {
            "search_analytics_by_date": dataset,
            "search_analytics_by_page": SimpleNamespace(records=[]),
        }

    def get_stream_json_schema(self, stream):
        return {"type": "object", "title": stream}

    def check(self):
        return SimpleNamespace(status="succeeded")


def test_gsc_uses_pinned_release_and_projects_cursor_without_leaking_config() -> None:
    captured = {}
    source = FakeSource()

    def factory(name, **kwargs):
        captured.update(name=name, **kwargs)
        return source

    adapter = gsc_source(config={"credentials": "secret-value"}, source_factory=factory)
    plan = ConnectorSyncPlan(
        project_id=uuid4(),
        definition_id=uuid4(),
        connection_id=uuid4(),
        scope_id=uuid4(),
        mode=ConnectorSyncMode.INITIAL,
        adapter_release=f"source-google-search-console:{GSC_CONNECTOR_RELEASE}",
        input_checkpoint_id=None,
        input_checkpoint_hash="0" * 64,
        window_start=None,
        window_end=None,
        requested_by=uuid4(),
        requested_at=datetime(2026, 7, 28, tzinfo=UTC),
    )
    batch = adapter.read(plan)

    assert captured["version"] == GSC_CONNECTOR_RELEASE
    assert captured["install_if_missing"] is True
    assert source.read_arguments["force_full_refresh"] is True
    assert batch.cursor_state["value"] == ["2026-07-27T00:00:00+00:00"]
    assert batch.watermark == datetime(2026, 7, 27, tzinfo=UTC)
    assert "secret-value" not in repr(batch)


def test_connection_check_uses_the_same_pinned_release_without_reading_records() -> None:
    captured = {}
    source = FakeSource()

    def factory(name, **kwargs):
        captured.update(name=name, **kwargs)
        return source

    adapter = gsc_source(config={"credentials": "secret-value"}, source_factory=factory)
    adapter.check_connection()

    assert captured["version"] == GSC_CONNECTOR_RELEASE
    assert captured["install_if_missing"] is True
    assert source.read_arguments is None
