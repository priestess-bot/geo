import pytest

from geo_core.browser_capture.domain import BrowserCaptureError
from geo_core.browser_capture.session_state import validate_browser_storage_state


def test_storage_state_accepts_supported_consumer_surface_domains() -> None:
    value = validate_browser_storage_state(
        {
            "cookies": [
                {"name": "SID", "value": "redacted", "domain": ".google.com"},
                {"name": "MUID", "value": "redacted", "domain": "www.bing.com"},
            ],
            "origins": [
                {"origin": "https://www.google.com", "localStorage": []},
                {"origin": "https://copilot.microsoft.com", "localStorage": []},
            ],
        }
    )

    assert len(value["cookies"]) == 2
    assert len(value["origins"]) == 2


@pytest.mark.parametrize(
    "value",
    [
        {"cookies": [], "origins": [{"origin": "http://www.google.com"}]},
        {"cookies": [{"domain": "google.com.attacker.example"}], "origins": []},
        {"cookies": [], "origins": [{"origin": "https://bing.com.attacker.example"}]},
        {"cookies": [{"domain": "example.com"}], "origins": []},
        {"cookies": {}, "origins": []},
    ],
)
def test_storage_state_rejects_unsupported_or_malformed_data(
    value: object,
) -> None:
    with pytest.raises(BrowserCaptureError):
        validate_browser_storage_state(value)
