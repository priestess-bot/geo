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
