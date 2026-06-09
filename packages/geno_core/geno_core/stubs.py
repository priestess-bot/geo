from __future__ import annotations

from geno_core.models import MarketProfile, RawCollectResult


class NotConfiguredCollectorBackend:
    """Collector adapter placeholder used by M0 until real platform backends are configured."""

    def __init__(self, backend_id: str, platform: str, surface: str, access_method: str) -> None:
        self._backend_id = backend_id
        self._platform = platform
        self._surface = surface
        self._access_method = access_method

    def id(self) -> str:
        return self._backend_id

    def capabilities(self) -> dict[str, object]:
        return {
            "platform": self._platform,
            "surface": self._surface,
            "supports_geo": True,
            "supports_citation": True,
            "access_method": self._access_method,
        }

    def health(self) -> str:
        return "not_configured"

    def collect(
        self,
        *,
        prompt: str,
        market: MarketProfile,
        city: str,
        language: str,
        device: str,
    ) -> RawCollectResult:
        raise NotImplementedError(
            f"{self._backend_id} is an M0 interface stub; configure a real collector adapter."
        )
