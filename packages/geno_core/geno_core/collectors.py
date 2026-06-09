from __future__ import annotations

from urllib.parse import quote

from geno_core.models import MarketProfile, RawCollectResult


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
