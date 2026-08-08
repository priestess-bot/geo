from __future__ import annotations

from types import MappingProxyType

import pytest

from geo_core.browser_capture.domain import BrowserCaptureError
from geo_core.browser_capture.surface_adapters import (
    BUILTIN_SURFACE_ADAPTERS,
    block_reason_from_text,
    builtin_surface_adapter,
)


def test_builtin_registry_has_one_release_per_supported_consumer_surface() -> None:
    assert {item.surface for item in BUILTIN_SURFACE_ADAPTERS} == {
        "google_ai_overviews",
        "google_ai_mode",
        "bing_copilot",
    }
    assert len({item.key for item in BUILTIN_SURFACE_ADAPTERS}) == 3
    assert all(item.entry_url_template.startswith("https://") for item in BUILTIN_SURFACE_ADAPTERS)
    assert all("{query}" in item.entry_url_template for item in BUILTIN_SURFACE_ADAPTERS)


def test_target_url_encodes_query_without_changing_frozen_manifest() -> None:
    adapter = builtin_surface_adapter("google_ai_mode")

    target = adapter.target_url("best IT support in Sydney & Melbourne")

    assert "q=best+IT+support+in+Sydney+%26+Melbourne" in target
    assert target.startswith("https://www.google.com/search?udm=50")
    assert adapter.selectors()["adapter_key"] == "google-ai-mode-browser-v1"


def test_registry_rejects_unknown_surfaces_and_empty_queries() -> None:
    with pytest.raises(BrowserCaptureError, match="Unsupported"):
        builtin_surface_adapter("consumer_magic")
    with pytest.raises(BrowserCaptureError, match="query is required"):
        builtin_surface_adapter("bing_copilot").target_url("  ")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Our systems have detected unusual traffic from your computer network", "captcha"),
        ("Sign in to continue to AI Mode", "login"),
        ("A normal consumer answer with references", None),
    ],
)
def test_block_text_classification_is_explicit(text: str, expected: str | None) -> None:
    patterns = MappingProxyType(
        {
            "login": ("sign in to continue to ai mode",),
            "captcha": ("our systems have detected unusual traffic",),
        }
    )

    assert block_reason_from_text(text, patterns) == expected
