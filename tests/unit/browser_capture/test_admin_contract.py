from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from geo_api.browser_capture_contracts import CreateSurfaceReleaseRequest
from geo_core.browser_capture.admin import BrowserCaptureAdminService
from geo_core.browser_capture.domain import BrowserCaptureError


def _surface_value() -> dict[str, object]:
    return {
        "platform": "google",
        "surface": "google_ai_overviews",
        "release_version": "google-aio-2026-07",
        "entry_url_template": "https://www.google.com/",
        "allowed_hosts": ["www.google.com"],
        "selectors": {
            "query_input": "textarea[name='q']",
            "page_complete": "#search",
            "surface_marker": "[data-aio]",
            "answer": "[data-answer]",
            "citations": "[data-citation]",
            "page_location": "[data-location]",
        },
        "block_detectors": {"captcha": "form[action*='sorry']"},
        "parser_release": "google-aio-parser-v1",
        "browser_release": "playwright:1.60.0/chromium",
        "authorization_track": "A",
        "authorization_status": "approved",
        "authorization_reference": "legal-review-123",
        "authorization_valid_until": datetime.now(UTC) + timedelta(days=30),
        "terms_version": "2026-07",
    }


def test_surface_transport_requires_every_runtime_selector() -> None:
    value = _surface_value()
    del value["selectors"]["page_location"]

    with pytest.raises(ValidationError, match="page_location"):
        CreateSurfaceReleaseRequest.model_validate(value)


def test_surface_transport_rejects_unknown_block_outcome() -> None:
    value = _surface_value()
    value["block_detectors"] = {"mystery": "#blocked"}

    with pytest.raises(ValidationError, match="unsupported block detector"):
        CreateSurfaceReleaseRequest.model_validate(value)


@pytest.mark.parametrize(
    ("entry_url", "hosts", "message"),
    [
        ("https://www.google.com/", ["www.bing.com"], "allowed host"),
        ("http://www.google.com/", ["www.google.com"], "HTTPS"),
        ("https://user:pass@www.google.com/", ["www.google.com"], "HTTPS"),
    ],
)
def test_admin_rejects_unsafe_entry_url_before_database_access(
    entry_url: str, hosts: list[str], message: str
) -> None:
    value = _surface_value()
    value["entry_url_template"] = entry_url
    value["allowed_hosts"] = hosts
    service = BrowserCaptureAdminService(connect=lambda: pytest.fail("database accessed"))

    with pytest.raises(BrowserCaptureError, match=message):
        service.create_surface_release(
            project_id=uuid4(), actor_id=uuid4(), **value
        )


def test_admin_rejects_unknown_selector_before_database_access() -> None:
    value = _surface_value()
    value["selectors"]["uncontrolled"] = "#unknown"
    service = BrowserCaptureAdminService(connect=lambda: pytest.fail("database accessed"))

    with pytest.raises(BrowserCaptureError, match="unknown"):
        service.create_surface_release(project_id=uuid4(), actor_id=uuid4(), **value)


class _Result:
    def __init__(self, row=None) -> None:
        self._row = row

    def fetchone(self):
        return self._row


class _PoolReplayConnection:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query, _params=None):
        normalized = " ".join(str(query).split())
        self.statements.append(normalized)
        if "set_config('geo.project_id'" in normalized or "pg_advisory_xact_lock" in normalized:
            return _Result()
        if normalized.startswith("SELECT * FROM browser_egress_endpoints"):
            return _Result(self.row)
        raise AssertionError(f"pool replay attempted a write: {normalized}")


def test_lokiproxy_pool_replay_preserves_healthy_profile_without_writes() -> None:
    project_id, actor_id, secret_id = uuid4(), uuid4(), uuid4()
    existing = {
        "id": uuid4(), "status": "approved", "health_status": "healthy",
        "protocol": "http", "endpoint_host": "au.gateway.test", "endpoint_port": 8080,
        "secret_reference_id": secret_id, "secret_purpose": "browser_egress.lokiproxy",
        "secret_version": 1, "expected_region": "NSW", "network_type": "residential",
        "sticky_mode": "credential_session", "egress_policy_version": "lokiproxy-v1",
        "egress_cohort_key": "lokiproxy-au", "provider": "lokiproxy",
        "pool_product": "rotating_residential", "session_ttl_seconds": 600,
        "max_concurrency": 3,
    }
    connection = _PoolReplayConnection(existing)
    service = BrowserCaptureAdminService(connect=lambda: connection)

    replay = service.install_egress_endpoint(
        project_id=project_id, actor_id=actor_id, name="LokiProxy AU", protocol="http",
        endpoint_host="au.gateway.test", endpoint_port=8080,
        secret_reference_id=secret_id, secret_purpose="browser_egress.lokiproxy",
        secret_version=1, expected_region="NSW", network_type="residential",
        egress_policy_version="lokiproxy-v1", egress_cohort_key="lokiproxy-au",
        provider="lokiproxy", pool_product="rotating_residential",
        session_ttl_seconds=600, max_concurrency=3,
    )

    assert replay["id"] == existing["id"]
    assert replay["health_status"] == "healthy"
    assert not any(statement.startswith(("INSERT", "UPDATE")) for statement in connection.statements)
