from __future__ import annotations


class StaticAUGeoProvider:
    def __init__(self) -> None:
        self._cities = {
            "Australia": {"scope": "country", "gl": "au", "hl": "en-AU"},
            "Sydney": {"scope": "city", "gl": "au", "hl": "en-AU", "near": "Sydney, New South Wales"},
            "Melbourne": {"scope": "city", "gl": "au", "hl": "en-AU", "near": "Melbourne, Victoria"},
            "Brisbane": {"scope": "city", "gl": "au", "hl": "en-AU", "near": "Brisbane, Queensland"},
            "Perth": {"scope": "city", "gl": "au", "hl": "en-AU", "near": "Perth, Western Australia"},
            "Adelaide": {"scope": "city", "gl": "au", "hl": "en-AU", "near": "Adelaide, South Australia"},
        }

    def resolve(self, *, market_code: str, city: str, language: str, device: str) -> dict[str, object]:
        if market_code != "AU":
            raise ValueError(f"StaticAUGeoProvider only supports AU, got {market_code}")
        if city not in self._cities:
            raise ValueError(f"Unsupported AU city: {city}")
        return {
            "market_code": market_code,
            "city": city,
            "language": language,
            "device": device,
            **self._cities[city],
        }
