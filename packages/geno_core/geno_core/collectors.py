from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

from geno_core.audit import hash_payload
from geno_core.models import MarketProfile, RawCollectResult


class CollectorConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class JsonHttpResponse:
    status_code: int
    payload: dict[str, object]


class JsonHttpClient:
    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> JsonHttpResponse:
        request = Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
            body = response.read().decode("utf-8")
            return JsonHttpResponse(status_code=response.status, payload=json.loads(body))


def _extract_domain(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


def _citation_dicts(urls: list[str]) -> list[dict[str, object]]:
    return [
        {
            "url": url,
            "domain": _extract_domain(url),
            "position": index,
            "source_type": None,
        }
        for index, url in enumerate(urls, start=1)
    ]


def _api_snapshot_payload(
    *,
    collector_backend_id: str,
    payload: dict[str, object],
    answer_text: str,
    citation_count: int,
) -> tuple[dict[str, object], str, str]:
    payload_hash = hash_payload(payload)
    snapshot = {
        "_geno_api_snapshot": {
            "collector_backend_id": collector_backend_id,
            "snapshot_type": "api_response_html",
            "payload_hash": payload_hash,
            "answer_text_length": len(answer_text),
            "citation_count": citation_count,
        },
        **payload,
    }
    snapshot_hash = hash_payload(snapshot)
    snapshot_url = f"geno-api-snapshot://{collector_backend_id}/{payload_hash}.html"
    return snapshot, snapshot_url, snapshot_hash


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_env(value: str | None) -> str | None:
    stripped = str(value or "").strip()
    return stripped or None


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class FixtureAICollector:
    def __init__(
        self,
        *,
        backend_id: str,
        platform: str,
        surface: str,
        access_method: str,
        model_or_surface: str,
        vendor_cost: float,
    ) -> None:
        self._backend_id = backend_id
        self._platform = platform
        self._surface = surface
        self._access_method = access_method
        self._model_or_surface = model_or_surface
        self.vendor_cost = vendor_cost

    def id(self) -> str:
        return self._backend_id

    def capabilities(self) -> dict[str, object]:
        return {
            "platform": self._platform,
            "surface": self._surface,
            "supports_geo": True,
            "supports_citation": True,
            "supports_screenshot": True,
            "supports_html_snapshot": True,
            "access_method": self._access_method,
        }

    def health(self) -> str:
        return "fixture_ready"

    def collect(
        self,
        *,
        prompt: str,
        market: MarketProfile,
        city: str,
        language: str,
        device: str,
    ) -> RawCollectResult:
        prompt_slug = quote(prompt.lower().replace(" ", "-")[:80], safe="-")
        answer_text = (
            f"{self._platform} fixture answer for {market.market_code}/{city}: "
            f"{prompt}. Citations include official, review, and comparison sources. "
            "Common competitor references include Emma Sleep, Sleeping Duck, and Ecosa."
        )
        citations = [
            {
                "url": f"https://examplebrand.example/au/{prompt_slug}",
                "domain": "examplebrand.example",
                "position": 1,
                "source_type": "official_site",
            },
            {
                "url": f"https://reviews.example/{prompt_slug}",
                "domain": "reviews.example",
                "position": 2,
                "source_type": "review_site",
            },
            {
                "url": f"https://compare.example/{prompt_slug}",
                "domain": "compare.example",
                "position": 3,
                "source_type": "comparison_site",
            },
        ]
        evidence_prefix = f"s3://geno-fixtures/{self._backend_id}/{market.market_code}/{city}/{prompt_slug}"
        return RawCollectResult(
            answer_present=True,
            surface_triggered=True,
            answer_text=answer_text,
            citations=citations,
            screenshot_url=f"{evidence_prefix}.png",
            html_snapshot_url=f"{evidence_prefix}.html",
            raw_payload={
                "prompt": prompt,
                "market_code": market.market_code,
                "city": city,
                "language": language,
                "device": device,
                "platform": self._platform,
                "surface": self._surface,
                "collector_backend_id": self._backend_id,
            },
            model_or_surface=self._model_or_surface,
            account_state=None,
            collector_version="fixture-v1",
        )


class FixturePerplexitySonarCollector(FixtureAICollector):
    def __init__(self) -> None:
        super().__init__(
            backend_id="perplexity.sonar.fixture",
            platform="perplexity",
            surface="sonar",
            access_method="official_api",
            model_or_surface="sonar-fixture",
            vendor_cost=0.002,
        )


class FixtureOpenAIWebSearchCollector(FixtureAICollector):
    def __init__(self) -> None:
        super().__init__(
            backend_id="openai.web_search.fixture",
            platform="chatgpt",
            surface="chatgpt_search",
            access_method="official_api",
            model_or_surface="web-search-fixture",
            vendor_cost=0.003,
        )


class FixtureChatGPTSearchBrowserCollector(FixtureAICollector):
    def __init__(self) -> None:
        super().__init__(
            backend_id="chatgpt_search.browser.fixture",
            platform="chatgpt",
            surface="chatgpt_search",
            access_method="browser",
            model_or_surface="chatgpt-search-browser-fixture",
            vendor_cost=0.004,
        )


class PlaywrightChatGPTSearchCollector:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        start_url: str | None = None,
        browser_name: str | None = None,
        prompt_selector: str | None = None,
        submit_selector: str | None = None,
        answer_selector: str | None = None,
        citation_selector: str | None = None,
        storage_state_path: str | None = None,
        artifact_dir: str | None = None,
        headless: bool | None = None,
        timeout_seconds: float | None = None,
        playwright_factory: Callable[[], object] | None = None,
    ) -> None:
        self._enabled = _env_truthy(os.getenv("GENO_BROWSER_COLLECTOR_ENABLED")) if enabled is None else enabled
        self._start_url = (
            _optional_env(start_url)
            or _optional_env(os.getenv("GENO_BROWSER_START_URL"))
            or _optional_env(os.getenv("CHATGPT_BROWSER_URL"))
            or "https://chatgpt.com/"
        )
        self._browser_name = (
            _optional_env(browser_name)
            or _optional_env(os.getenv("GENO_BROWSER_NAME"))
            or "chromium"
        )
        self._prompt_selector = _optional_env(prompt_selector) or _optional_env(
            os.getenv("GENO_BROWSER_PROMPT_SELECTOR")
        )
        self._submit_selector = _optional_env(submit_selector) or _optional_env(
            os.getenv("GENO_BROWSER_SUBMIT_SELECTOR")
        )
        self._answer_selector = _optional_env(answer_selector) or _optional_env(
            os.getenv("GENO_BROWSER_ANSWER_SELECTOR")
        )
        self._citation_selector = _optional_env(citation_selector) or _optional_env(
            os.getenv("GENO_BROWSER_CITATION_SELECTOR")
        )
        self._storage_state_path = _optional_env(storage_state_path) or _optional_env(
            os.getenv("GENO_BROWSER_STORAGE_STATE")
        )
        self._artifact_dir = _optional_env(artifact_dir) or _optional_env(os.getenv("GENO_BROWSER_ARTIFACT_DIR"))
        self._headless = (
            not _env_truthy(os.getenv("GENO_BROWSER_HEADFUL"))
            if headless is None
            else headless
        )
        self._timeout_seconds = timeout_seconds or float(os.getenv("GENO_BROWSER_TIMEOUT_SECONDS") or "45")
        self._playwright_factory = playwright_factory
        self.vendor_cost = 0.004

    def id(self) -> str:
        return "chatgpt_search.browser.playwright"

    def capabilities(self) -> dict[str, object]:
        return {
            "platform": "chatgpt",
            "surface": "chatgpt_search",
            "supports_geo": True,
            "supports_citation": True,
            "supports_screenshot": True,
            "supports_html_snapshot": True,
            "access_method": "browser",
            "requires_enable_env": "GENO_BROWSER_COLLECTOR_ENABLED",
            "required_selectors": ["GENO_BROWSER_PROMPT_SELECTOR", "GENO_BROWSER_ANSWER_SELECTOR"],
            "optional_selectors": ["GENO_BROWSER_SUBMIT_SELECTOR", "GENO_BROWSER_CITATION_SELECTOR"],
            "artifact_dir_env": "GENO_BROWSER_ARTIFACT_DIR",
        }

    def health(self) -> str:
        if not self._enabled:
            return "not_configured"
        if not self._prompt_selector or not self._answer_selector:
            return "selector_missing"
        if self._storage_state_path and not Path(self._storage_state_path).exists():
            return "session_state_missing"
        if self._playwright_factory is None:
            try:
                import playwright.sync_api  # noqa: F401
            except ModuleNotFoundError:
                return "playwright_missing"
        return "ready"

    def _sync_playwright_factory(self) -> Callable[[], object]:
        if self._playwright_factory is not None:
            return self._playwright_factory
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            raise CollectorConfigurationError(
                "Python package playwright is required for chatgpt_search.browser.playwright"
            ) from exc
        return sync_playwright

    def _ensure_ready(self) -> None:
        health = self.health()
        if health == "ready":
            return
        raise CollectorConfigurationError(
            "chatgpt_search.browser.playwright is not ready: "
            f"{health}. Set GENO_BROWSER_COLLECTOR_ENABLED=1, install Playwright, "
            "and configure GENO_BROWSER_PROMPT_SELECTOR / GENO_BROWSER_ANSWER_SELECTOR."
        )

    def _extract_citations(self, page: object) -> list[dict[str, object]]:
        if not self._citation_selector:
            return []
        try:
            locator = page.locator(self._citation_selector)  # type: ignore[attr-defined]
            raw_values = locator.evaluate_all(
                """
                nodes => nodes.map(node => {
                  if (node.href) return node.href;
                  if (node.getAttribute && node.getAttribute('href')) return node.getAttribute('href');
                  return node.textContent || '';
                }).filter(Boolean)
                """
            )
        except Exception:
            return []
        urls: list[str] = []
        if isinstance(raw_values, list):
            for value in raw_values:
                text = str(value).strip()
                if text.startswith("http") and text not in urls:
                    urls.append(text)
        return _citation_dicts(urls)

    def _artifact_urls(
        self,
        *,
        snapshot_id: str,
        html: str,
        screenshot_bytes: bytes,
    ) -> tuple[str, str]:
        if not self._artifact_dir:
            return (
                f"geno-browser-snapshot://{self.id()}/{snapshot_id}.html",
                f"geno-browser-screenshot://{self.id()}/{snapshot_id}.png",
            )
        artifact_dir = Path(self._artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        html_path = artifact_dir / f"{snapshot_id}.html"
        screenshot_path = artifact_dir / f"{snapshot_id}.png"
        html_path.write_text(html, encoding="utf-8")
        screenshot_path.write_bytes(screenshot_bytes)
        return (html_path.resolve().as_uri(), screenshot_path.resolve().as_uri())

    def collect(
        self,
        *,
        prompt: str,
        market: MarketProfile,
        city: str,
        language: str,
        device: str,
    ) -> RawCollectResult:
        self._ensure_ready()
        timeout_ms = int(self._timeout_seconds * 1000)
        factory = self._sync_playwright_factory()
        with factory() as playwright:
            browser_type = getattr(playwright, self._browser_name, None)
            if browser_type is None:
                raise CollectorConfigurationError(f"Unsupported Playwright browser: {self._browser_name}")
            browser = browser_type.launch(headless=self._headless)
            try:
                context_kwargs: dict[str, object] = {"locale": language}
                if self._storage_state_path:
                    context_kwargs["storage_state"] = self._storage_state_path
                context = browser.new_context(**context_kwargs)
                try:
                    page = context.new_page()
                    page.goto(self._start_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.fill(self._prompt_selector, prompt, timeout=timeout_ms)
                    if self._submit_selector:
                        page.click(self._submit_selector, timeout=timeout_ms)
                    else:
                        page.keyboard.press("Enter")
                    page.wait_for_selector(self._answer_selector, timeout=timeout_ms)
                    answer_text = page.locator(self._answer_selector).last.inner_text(timeout=timeout_ms).strip()
                    final_url = str(page.url)
                    title = str(page.title())
                    html = str(page.content())
                    screenshot_bytes = page.screenshot(full_page=True)
                    citations = self._extract_citations(page)
                finally:
                    context.close()
            finally:
                browser.close()
        html_hash = hash_payload({"html": html})
        screenshot_hash = _sha256_bytes(screenshot_bytes)
        snapshot_id = hash_payload(
            {
                "collector_backend_id": self.id(),
                "start_url": self._start_url,
                "final_url": final_url,
                "prompt": prompt,
                "city": city,
                "html_hash": html_hash,
                "screenshot_hash": screenshot_hash,
            }
        )
        html_snapshot_url, screenshot_url = self._artifact_urls(
            snapshot_id=snapshot_id,
            html=html,
            screenshot_bytes=screenshot_bytes,
        )
        return RawCollectResult(
            answer_present=bool(answer_text),
            surface_triggered=bool(answer_text),
            answer_text=answer_text,
            citations=citations,
            screenshot_url=screenshot_url,
            html_snapshot_url=html_snapshot_url,
            raw_payload={
                "prompt": prompt,
                "market_code": market.market_code,
                "city": city,
                "language": language,
                "device": device,
                "platform": "chatgpt",
                "surface": "chatgpt_search",
                "collector_backend_id": self.id(),
                "_geno_browser_capture": {
                    "capture_type": "browser_ui",
                    "start_url": self._start_url,
                    "final_url": final_url,
                    "page_title": title,
                    "browser_name": self._browser_name,
                    "headless": self._headless,
                    "prompt_selector": self._prompt_selector,
                    "answer_selector": self._answer_selector,
                    "submit_selector_configured": bool(self._submit_selector),
                    "citation_selector_configured": bool(self._citation_selector),
                    "storage_state_configured": bool(self._storage_state_path),
                    "html_snapshot_hash": html_hash,
                    "screenshot_hash": screenshot_hash,
                    "citation_count": len(citations),
                },
            },
            model_or_surface="chatgpt-search-browser",
            account_state="storage_state" if self._storage_state_path else "browser_default",
            collector_version="chatgpt-search-browser-playwright-v1",
            evidence_asset_hashes={"html_snapshot": html_hash, "screenshot": screenshot_hash},
        )


class FixtureGoogleAIOCollector(FixtureAICollector):
    def __init__(self) -> None:
        super().__init__(
            backend_id="google_aio.playwright.fixture",
            platform="google",
            surface="google_aio",
            access_method="browser",
            model_or_surface="google-aio-fixture",
            vendor_cost=0.004,
        )


class FixtureGoogleAIModeCollector(FixtureAICollector):
    def __init__(self) -> None:
        super().__init__(
            backend_id="google_ai_mode.playwright.fixture",
            platform="google",
            surface="google_ai_mode",
            access_method="browser",
            model_or_surface="google-ai-mode-fixture",
            vendor_cost=0.005,
        )


class FixtureThirdPartySerpCollector(FixtureAICollector):
    def __init__(self) -> None:
        super().__init__(
            backend_id="google.third_party_serp.fixture",
            platform="google",
            surface="google_aio",
            access_method="third_party_api",
            model_or_surface="third-party-serp-fixture",
            vendor_cost=0.006,
        )


class FixtureManualBackfillCollector(FixtureAICollector):
    def __init__(self) -> None:
        super().__init__(
            backend_id="google.manual_backfill.fixture",
            platform="google",
            surface="google_ai_mode",
            access_method="manual",
            model_or_surface="manual-backfill-fixture",
            vendor_cost=0.001,
        )


class GoogleSpikeCollectorShell:
    def __init__(
        self,
        *,
        backend_id: str,
        surface: str,
        access_method: str,
        required_env_var: str,
        failure_reason: str = "not_configured",
    ) -> None:
        self._backend_id = backend_id
        self._surface = surface
        self._access_method = access_method
        self._required_env_var = required_env_var
        self._failure_reason = failure_reason

    def id(self) -> str:
        return self._backend_id

    def capabilities(self) -> dict[str, object]:
        return {
            "platform": "google",
            "surface": self._surface,
            "supports_geo": True,
            "supports_citation": True,
            "supports_screenshot": True,
            "supports_html_snapshot": True,
            "access_method": self._access_method,
        }

    def health(self) -> str:
        return "ready" if os.getenv(self._required_env_var) else "not_configured"

    def collect(
        self,
        *,
        prompt: str,
        market: MarketProfile,
        city: str,
        language: str,
        device: str,
    ) -> RawCollectResult:
        if not os.getenv(self._required_env_var):
            raise CollectorConfigurationError(self._failure_reason)
        raise NotImplementedError(
            f"{self._backend_id} requires a runtime implementation for browser/API/manual capture"
        )


class PlaywrightGoogleAIOCollector(GoogleSpikeCollectorShell):
    def __init__(self) -> None:
        super().__init__(
            backend_id="google_aio.playwright",
            surface="google_aio",
            access_method="browser",
            required_env_var="GOOGLE_PLAYWRIGHT_ENABLED",
        )


class PlaywrightAIModeCollector(GoogleSpikeCollectorShell):
    def __init__(self) -> None:
        super().__init__(
            backend_id="google_ai_mode.playwright",
            surface="google_ai_mode",
            access_method="browser",
            required_env_var="GOOGLE_PLAYWRIGHT_ENABLED",
        )


class ThirdPartySerpCollector(GoogleSpikeCollectorShell):
    def __init__(self) -> None:
        super().__init__(
            backend_id="google.third_party_serp",
            surface="google_aio",
            access_method="third_party_api",
            required_env_var="SERP_API_KEY",
        )


class ManualBackfillCollector(GoogleSpikeCollectorShell):
    def __init__(self) -> None:
        super().__init__(
            backend_id="google.manual_backfill",
            surface="google_ai_mode",
            access_method="manual",
            required_env_var="MANUAL_BACKFILL_PATH",
        )


class PerplexitySonarCollector:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "sonar",
        endpoint: str = "https://api.perplexity.ai/chat/completions",
        http_client: JsonHttpClient | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("PERPLEXITY_API_KEY")
        self._model = model
        self._endpoint = endpoint
        self._http_client = http_client or JsonHttpClient()
        self._timeout_seconds = timeout_seconds

    def id(self) -> str:
        return "perplexity.sonar.api"

    def capabilities(self) -> dict[str, object]:
        return {
            "platform": "perplexity",
            "surface": "sonar",
            "supports_geo": True,
            "supports_citation": True,
            "supports_screenshot": False,
            "supports_html_snapshot": True,
            "access_method": "official_api",
        }

    def health(self) -> str:
        return "ready" if self._api_key else "not_configured"

    def build_payload(self, *, prompt: str, market: MarketProfile, city: str, language: str) -> dict[str, object]:
        system_prompt = (
            f"Answer for {market.market} ({market.market_code}), city={city}, language={language}. "
            "Return concise buyer-facing evidence with citations where available."
        )
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }

    def parse_response(self, payload: dict[str, object]) -> RawCollectResult:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Perplexity response missing choices")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ValueError("Perplexity response choice must be an object")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("Perplexity response missing message")
        content = str(message.get("content", ""))
        citation_urls: list[str] = []
        raw_citations = payload.get("citations") or payload.get("search_results") or []
        if isinstance(raw_citations, list):
            for item in raw_citations:
                if isinstance(item, str):
                    citation_urls.append(item)
                elif isinstance(item, dict) and isinstance(item.get("url"), str):
                    citation_urls.append(str(item["url"]))
        citations = _citation_dicts(citation_urls)
        snapshot_payload, snapshot_url, snapshot_hash = _api_snapshot_payload(
            collector_backend_id=self.id(),
            payload=payload,
            answer_text=content,
            citation_count=len(citations),
        )
        return RawCollectResult(
            answer_present=bool(content),
            surface_triggered=True,
            answer_text=content,
            citations=citations,
            screenshot_url=None,
            html_snapshot_url=snapshot_url,
            raw_payload=snapshot_payload,
            model_or_surface=self._model,
            account_state=None,
            collector_version="perplexity-sonar-api-v1",
            evidence_asset_hashes={"html_snapshot": snapshot_hash},
        )

    def collect(
        self,
        *,
        prompt: str,
        market: MarketProfile,
        city: str,
        language: str,
        device: str,
    ) -> RawCollectResult:
        if not self._api_key:
            raise CollectorConfigurationError("PERPLEXITY_API_KEY is required")
        response = self._http_client.post_json(
            url=self._endpoint,
            headers={"Authorization": f"Bearer {self._api_key}"},
            payload=self.build_payload(prompt=prompt, market=market, city=city, language=language),
            timeout_seconds=self._timeout_seconds,
        )
        return self.parse_response(response.payload)


class OpenAIWebSearchCollector:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4.1-mini",
        endpoint: str = "https://api.openai.com/v1/responses",
        http_client: JsonHttpClient | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self._model = model
        self._endpoint = endpoint
        self._http_client = http_client or JsonHttpClient()
        self._timeout_seconds = timeout_seconds

    def id(self) -> str:
        return "openai.web_search.api"

    def capabilities(self) -> dict[str, object]:
        return {
            "platform": "chatgpt",
            "surface": "chatgpt_search",
            "supports_geo": True,
            "supports_citation": True,
            "supports_screenshot": False,
            "supports_html_snapshot": True,
            "access_method": "official_api",
        }

    def health(self) -> str:
        return "ready" if self._api_key else "not_configured"

    def build_payload(self, *, prompt: str, market: MarketProfile, city: str, language: str) -> dict[str, object]:
        return {
            "model": self._model,
            "tools": [{"type": "web_search_preview"}],
            "input": (
                f"Answer for {market.market} ({market.market_code}), city={city}, language={language}. "
                f"Question: {prompt}"
            ),
        }

    def parse_response(self, payload: dict[str, object]) -> RawCollectResult:
        text_parts: list[str] = []
        citation_urls: list[str] = []
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for content_item in content:
                        if not isinstance(content_item, dict):
                            continue
                        if isinstance(content_item.get("text"), str):
                            text_parts.append(str(content_item["text"]))
                        annotations = content_item.get("annotations")
                        if isinstance(annotations, list):
                            for annotation in annotations:
                                if isinstance(annotation, dict) and isinstance(annotation.get("url"), str):
                                    citation_urls.append(str(annotation["url"]))
        fallback_text = payload.get("output_text")
        if not text_parts and isinstance(fallback_text, str):
            text_parts.append(fallback_text)
        answer_text = "\n".join(text_parts).strip()
        citations = _citation_dicts(citation_urls)
        snapshot_payload, snapshot_url, snapshot_hash = _api_snapshot_payload(
            collector_backend_id=self.id(),
            payload=payload,
            answer_text=answer_text,
            citation_count=len(citations),
        )
        return RawCollectResult(
            answer_present=bool(answer_text),
            surface_triggered=True,
            answer_text=answer_text,
            citations=citations,
            screenshot_url=None,
            html_snapshot_url=snapshot_url,
            raw_payload=snapshot_payload,
            model_or_surface=self._model,
            account_state=None,
            collector_version="openai-web-search-api-v1",
            evidence_asset_hashes={"html_snapshot": snapshot_hash},
        )

    def collect(
        self,
        *,
        prompt: str,
        market: MarketProfile,
        city: str,
        language: str,
        device: str,
    ) -> RawCollectResult:
        if not self._api_key:
            raise CollectorConfigurationError("OPENAI_API_KEY is required")
        response = self._http_client.post_json(
            url=self._endpoint,
            headers={"Authorization": f"Bearer {self._api_key}"},
            payload=self.build_payload(prompt=prompt, market=market, city=city, language=language),
            timeout_seconds=self._timeout_seconds,
        )
        return self.parse_response(response.payload)
