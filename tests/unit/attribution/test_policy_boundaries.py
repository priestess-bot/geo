from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from geo_core.attribution.application import _attribute


def test_attribution_windows_are_inclusive_and_do_not_promote_old_touches() -> None:
    converted_at = datetime(2026, 7, 28, 5, 0, tzinfo=UTC)
    revenue = {
        "revenue_id": uuid4(), "deal_id": uuid4(), "conversion_id": uuid4(),
        "lead_id": uuid4(), "session_id": uuid4(), "amount": Decimal("10"),
        "currency": "AUD", "conversion_at": converted_at,
    }
    policy = {
        "eligible_touch_types": ["page_view", "click"],
        "last_click_days": 30, "assisted_days": 90,
    }
    too_old = _touch(converted_at - timedelta(days=90, seconds=1))
    assisted_edge = _touch(converted_at - timedelta(days=90))
    last_edge = _touch(converted_at - timedelta(days=30))

    result = _attribute(revenue, [too_old, assisted_edge, last_edge], policy)

    assert result["direct"] is False
    assert result["first_click"]["touch_id"] == str(assisted_edge["id"])
    assert result["last_click"]["touch_id"] == str(last_edge["id"])
    assert [item["touch_id"] for item in result["assisted"]] == [
        str(assisted_edge["id"]), str(last_edge["id"]),
    ]


def test_assisted_without_last_click_is_explicitly_unassigned() -> None:
    converted_at = datetime(2026, 7, 28, 5, 0, tzinfo=UTC)
    revenue = {
        "revenue_id": uuid4(), "deal_id": uuid4(), "conversion_id": uuid4(),
        "lead_id": uuid4(), "session_id": uuid4(), "amount": Decimal("10"),
        "currency": "AUD", "conversion_at": converted_at,
    }
    result = _attribute(
        revenue,
        [_touch(converted_at - timedelta(days=31))],
        {"eligible_touch_types": ["click"], "last_click_days": 30, "assisted_days": 90},
    )

    assert result["direct"] is False
    assert result["last_click"] is None
    assert result["unassigned"] is True


def _touch(occurred_at: datetime) -> dict[str, object]:
    return {
        "id": uuid4(), "trace_link_id": uuid4(), "touch_type": "click",
        "occurred_at": occurred_at, "campaign_id": uuid4(), "question_set_id": None,
        "package_version_id": None, "content_asset_key": "article:v1",
        "verified_url": "https://example.test/article", "utm": {"source": "geo"},
    }
