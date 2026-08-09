"""Opt-in GSC/GA4 canary admission tests.

These tests never guess credentials.  They skip unless an operator explicitly
enables them and supplies project-scoped IDs for the Secret Store reference.
"""

from __future__ import annotations

import os

import pytest

from scripts.gsc_ga4_connector_canary import main


pytestmark = pytest.mark.live


@pytest.mark.parametrize(
    ("kind", "prefix"),
    (
        ("google_search_console", "GSC"),
        ("google_analytics_4", "GA4"),
    ),
)
def test_google_connector_live_connection_test_is_explicitly_opt_in(kind: str, prefix: str) -> None:
    if os.getenv("GEO_RUN_LIVE_CONNECTOR_TESTS", "").strip() != "1":
        pytest.skip("set GEO_RUN_LIVE_CONNECTOR_TESTS=1 to enqueue a real Connector test")
    names = {
        "GEO_CONNECTOR_DATABASE_URL": (
            os.getenv("GEO_CONNECTOR_DATABASE_URL", "").strip()
            or os.getenv("GEO_DATABASE_URL", "").strip()
        ),
        "project": os.getenv(f"GEO_CONNECTOR_LIVE_{prefix}_PROJECT_ID", "").strip(),
        "connection": os.getenv(f"GEO_CONNECTOR_LIVE_{prefix}_CONNECTION_ID", "").strip(),
        "scope": os.getenv(f"GEO_CONNECTOR_LIVE_{prefix}_SCOPE_ID", "").strip(),
        "secret_reference": os.getenv(
            f"GEO_CONNECTOR_LIVE_{prefix}_SECRET_REFERENCE_ID", ""
        ).strip(),
        "actor": os.getenv(f"GEO_CONNECTOR_LIVE_{prefix}_ACTOR_ID", "").strip(),
        "version": os.getenv(f"GEO_CONNECTOR_LIVE_{prefix}_CONNECTION_VERSION", "").strip(),
    }
    missing = [name for name, value in names.items() if not value]
    if missing:
        message = f"missing explicit live Connector inputs: {', '.join(missing)}"
        if os.getenv("GEO_CONNECTOR_LIVE_REQUIRED", "").strip() == "1":
            pytest.fail(message)
        pytest.skip(message)
    assert main(
        [
            "--kind",
            kind,
            "--mode",
            "test",
            "--project-id",
            names["project"],
            "--connection-id",
            names["connection"],
            "--scope-id",
            names["scope"],
            "--actor-id",
            names["actor"],
            "--secret-reference-id",
            names["secret_reference"],
            "--expected-version",
            names["version"],
            "--idempotency-key",
            f"live-{prefix.lower()}-connector-test",
        ]
    ) == 0
