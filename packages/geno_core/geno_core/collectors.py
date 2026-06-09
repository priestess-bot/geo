from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import quote
from urllib.request import Request, urlopen

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
            f"{prompt}. Citations include official, review, and comparison sources."
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
            "supports_html_snapshot": False,
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
        return RawCollectResult(
            answer_present=bool(content),
            surface_triggered=True,
            answer_text=content,
            citations=_citation_dicts(citation_urls),
            screenshot_url=None,
            html_snapshot_url=None,
            raw_payload=payload,
            model_or_surface=self._model,
            account_state=None,
            collector_version="perplexity-sonar-api-v1",
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
            "supports_html_snapshot": False,
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
        return RawCollectResult(
            answer_present=bool(answer_text),
            surface_triggered=True,
            answer_text=answer_text,
            citations=_citation_dicts(citation_urls),
            screenshot_url=None,
            html_snapshot_url=None,
            raw_payload=payload,
            model_or_surface=self._model,
            account_state=None,
            collector_version="openai-web-search-api-v1",
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
