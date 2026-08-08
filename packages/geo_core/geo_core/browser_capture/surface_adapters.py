"""Versioned built-in manifests for supported consumer search surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import quote_plus

from geo_core.browser_capture.domain import BrowserCaptureError


BUILTIN_BROWSER_RELEASE = "playwright:1.60.0/chromium"


@dataclass(frozen=True)
class BuiltinSurfaceAdapter:
    key: str
    platform: str
    surface: str
    release_version: str
    parser_release: str
    entry_url_template: str
    allowed_hosts: tuple[str, ...]
    query_input: str
    page_complete: str
    surface_marker: str
    answer: str
    citations: str
    page_location: str
    completion_mode: str
    block_detectors: MappingProxyType[str, str]
    block_text_patterns: MappingProxyType[str, tuple[str, ...]]
    ready_timeout_ms: int = 90_000

    def target_url(self, query: str) -> str:
        value = query.strip()
        if not value:
            raise BrowserCaptureError("Browser Capture query is required")
        return self.entry_url_template.replace("{query}", quote_plus(value))

    def selectors(self) -> dict[str, object]:
        return {
            "adapter_key": self.key,
            "navigation_mode": "direct_query",
            "completion_mode": self.completion_mode,
            "query_input": self.query_input,
            "page_complete": self.page_complete,
            "surface_marker": self.surface_marker,
            "answer": self.answer,
            "citations": self.citations,
            "page_location": self.page_location,
            "block_text_patterns": {
                key: list(patterns) for key, patterns in self.block_text_patterns.items()
            },
            "ready_timeout_ms": self.ready_timeout_ms,
        }


_COMMON_GOOGLE_BLOCKS = MappingProxyType(
    {
        "consent": "form[action*='consent.google'], div[role='dialog'] form[action*='consent']",
        "login": "[data-geo-login-required='true']",
        "captcha": "form[action*='/sorry/'], iframe[src*='recaptcha'], #captcha-form",
        "rate_limit": "[data-geo-rate-limited='true']",
        "ban": "[data-geo-access-denied='true']",
    }
)
_COMMON_GOOGLE_BLOCK_TEXT = MappingProxyType(
    {
        "consent": ("before you continue to google",),
        "login": ("sign in to continue to ai mode", "ai mode isn't available for this account"),
        "captcha": ("our systems have detected unusual traffic", "not a robot"),
        "rate_limit": ("too many requests", "try again later"),
        "ban": ("access denied", "this service is not available"),
    }
)
_COMMON_BING_BLOCKS = MappingProxyType(
    {
        "consent": "#bnp_container, form[action*='consent']",
        "login": "[data-geo-login-required='true']",
        "captcha": "#b_captcha, iframe[src*='captcha'], form[action*='challenge']",
        "rate_limit": "[data-geo-rate-limited='true']",
        "ban": "[data-geo-access-denied='true']",
    }
)
_COMMON_BING_BLOCK_TEXT = MappingProxyType(
    {
        "consent": ("manage your cookie preferences",),
        "login": ("sign in to continue with copilot",),
        "captcha": ("verify that you are not a robot", "complete the challenge"),
        "rate_limit": ("you've reached the limit", "too many requests"),
        "ban": ("access denied", "this service is unavailable"),
    }
)


BUILTIN_SURFACE_ADAPTERS = (
    BuiltinSurfaceAdapter(
        key="google-ai-overviews-browser-v1",
        platform="google",
        surface="google_ai_overviews",
        release_version="2026-08-07.1",
        parser_release="google-ai-overviews-dom-v1",
        entry_url_template=(
            "https://www.google.com/search?hl=en&gl=au&pws=0&safe=active&q={query}"
        ),
        allowed_hosts=("google.com", "www.google.com"),
        query_input="textarea[name='q'], input[name='q']",
        page_complete="#search, main, [role='main']",
        surface_marker="[data-mcpr], [data-snhf], div[jsname='N760b']",
        answer="[data-mcpr], [data-snhf], div[jsname='N760b']",
        citations=(
            "[data-mcpr] a[href^='https://'], [data-snhf] a[href^='https://'], "
            "div[jsname='N760b'] a[href^='https://']"
        ),
        page_location="#swml, .uU7dJb, [data-country]",
        completion_mode="document_ready",
        block_detectors=_COMMON_GOOGLE_BLOCKS,
        block_text_patterns=_COMMON_GOOGLE_BLOCK_TEXT,
    ),
    BuiltinSurfaceAdapter(
        key="google-ai-mode-browser-v1",
        platform="google",
        surface="google_ai_mode",
        release_version="2026-08-07.1",
        parser_release="google-ai-mode-dom-v1",
        entry_url_template=(
            "https://www.google.com/search?udm=50&hl=en&gl=au&pws=0&safe=active&q={query}"
        ),
        allowed_hosts=("google.com", "www.google.com"),
        query_input="textarea, input[name='q']",
        page_complete="main, [role='main']",
        surface_marker=(
            "main [data-message-author-role='assistant'], main [data-snhf], "
            "main div[jsname='N760b']"
        ),
        answer=(
            "main [data-message-author-role='assistant'], main [data-snhf], "
            "main div[jsname='N760b']"
        ),
        citations=(
            "main [data-message-author-role='assistant'] a[href^='https://'], "
            "main [data-snhf] a[href^='https://'], main div[jsname='N760b'] a[href^='https://']"
        ),
        page_location="#swml, .uU7dJb, [data-country]",
        completion_mode="stable_answer",
        block_detectors=_COMMON_GOOGLE_BLOCKS,
        block_text_patterns=_COMMON_GOOGLE_BLOCK_TEXT,
    ),
    BuiltinSurfaceAdapter(
        key="bing-copilot-browser-v1",
        platform="bing",
        surface="bing_copilot",
        release_version="2026-08-07.1",
        parser_release="bing-copilot-dom-v1",
        entry_url_template=(
            "https://www.bing.com/copilotsearch?cc=au&setlang=en-au&q={query}"
        ),
        allowed_hosts=("bing.com", "www.bing.com"),
        query_input="textarea, input[name='q']",
        page_complete="main, #b_content, [role='main']",
        surface_marker=(
            "main [data-content='ai-message'], main [data-testid='copilot-answer'], "
            "main .b_wpt_bl"
        ),
        answer=(
            "main [data-content='ai-message'], main [data-testid='copilot-answer'], "
            "main .b_wpt_bl"
        ),
        citations=(
            "main [data-content='ai-message'] a[href^='https://'], "
            "main [data-testid='copilot-answer'] a[href^='https://'], "
            "main .b_wpt_bl a[href^='https://']"
        ),
        page_location="#b_footer, [data-country]",
        completion_mode="stable_answer",
        block_detectors=_COMMON_BING_BLOCKS,
        block_text_patterns=_COMMON_BING_BLOCK_TEXT,
    ),
)

_BY_KEY = MappingProxyType({item.key: item for item in BUILTIN_SURFACE_ADAPTERS})
_BY_SURFACE = MappingProxyType({item.surface: item for item in BUILTIN_SURFACE_ADAPTERS})


def builtin_surface_adapter(value: str) -> BuiltinSurfaceAdapter:
    key = value.strip()
    try:
        return _BY_KEY[key] if key in _BY_KEY else _BY_SURFACE[key]
    except KeyError:
        raise BrowserCaptureError(f"Unsupported built-in consumer surface: {value}") from None


def block_reason_from_text(
    text: str, patterns: Mapping[str, tuple[str, ...]]
) -> str | None:
    normalized = " ".join(text.casefold().split())
    for reason, candidates in patterns.items():
        if any(candidate in normalized for candidate in candidates):
            return reason
    return None


__all__ = [
    "BUILTIN_BROWSER_RELEASE",
    "BUILTIN_SURFACE_ADAPTERS",
    "BuiltinSurfaceAdapter",
    "block_reason_from_text",
    "builtin_surface_adapter",
]
