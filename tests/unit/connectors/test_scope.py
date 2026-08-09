from __future__ import annotations

import pytest

from geo_core.connectors import ConnectorKind
from geo_core.connectors.scope import (
    ConnectorScopeError,
    scoped_runtime_config,
    validate_google_scope,
)


def test_gsc_scope_normalizes_domain_and_keeps_explicit_site_identity() -> None:
    identity = validate_google_scope(
        kind=ConnectorKind.GOOGLE_SEARCH_CONSOLE,
        source_locator="sc-domain:Example.test",
        streams=("search_analytics_by_date", "search_analytics_by_page"),
        report_spec={},
        date_policy={},
    )

    assert identity.as_dict() == {
        "kind": "google_search_console",
        "source_locator": "sc-domain:example.test",
        "site_url": "sc-domain:example.test",
    }


def test_ga4_scope_requires_property_and_report_dimensions_and_metrics() -> None:
    identity = validate_google_scope(
        kind=ConnectorKind.GOOGLE_ANALYTICS_4,
        source_locator="properties/123456789",
        streams=("reports",),
        report_spec={
            "property_id": "123456789",
            "account_id": "987654321",
            "dimensions": ["date"],
            "metrics": ["sessions"],
        },
        date_policy={"timezone": "Australia/Sydney"},
    )

    assert identity.as_dict() == {
        "kind": "google_analytics_4",
        "source_locator": "properties/123456789",
        "property_id": "123456789",
        "account_id": "987654321",
    }


def test_ga4_scope_rejects_mismatched_property_or_missing_report_shape() -> None:
    with pytest.raises(ConnectorScopeError, match="property_id"):
        validate_google_scope(
            kind=ConnectorKind.GOOGLE_ANALYTICS_4,
            source_locator="properties/123456789",
            streams=("reports",),
            report_spec={
                "property_id": "111111111",
                "dimensions": ["date"],
                "metrics": ["sessions"],
            },
            date_policy={},
        )
    with pytest.raises(ConnectorScopeError, match="dimensions"):
        validate_google_scope(
            kind=ConnectorKind.GOOGLE_ANALYTICS_4,
            source_locator="properties/123456789",
            streams=("reports",),
            report_spec={"metrics": ["sessions"]},
            date_policy={},
        )


def test_scoped_runtime_config_adds_only_non_secret_resource_filters() -> None:
    config = scoped_runtime_config(
        kind=ConnectorKind.GOOGLE_ANALYTICS_4,
        credential={"credentials": {"client_email": "redacted@example.test"}},
        source_locator="properties/123456789",
        streams=("reports",),
        report_spec={"dimensions": ["date"], "metrics": ["sessions"]},
        date_policy={"start_date": "2026-08-01", "end_date": "2026-08-07"},
    )

    assert config["property_ids"] == ["123456789"]
    assert config["custom_reports_array"] == [{
        "name": "reports",
        "dimensions": ["date"],
        "metrics": ["sessions"],
    }]
    assert config["date_ranges_start_date"] == "2026-08-01"
    assert config["date_ranges_end_date"] == "2026-08-07"
    assert config["credentials"] == {"client_email": "redacted@example.test"}
