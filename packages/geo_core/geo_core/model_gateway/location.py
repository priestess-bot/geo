"""Requested and effective Provider location controls for sampling lineage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from geo_core.model_gateway.identity import canonical_json_hash


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")
_LOCALE = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")


class ModelLocationControl(StrEnum):
    COUNTRY = "country"
    MARKET_LANGUAGE = "market_language"
    LANGUAGE_ONLY = "language_only"
    NOT_CONTROLLED = "not_controlled"


@dataclass(frozen=True)
class RequestedModelLocation:
    country_code: str | None
    region_code: str | None
    locale: str
    language: str

    def __post_init__(self) -> None:
        country = _optional_geo(self.country_code, uppercase=True)
        region = _optional_geo(self.region_code, uppercase=True)
        locale = self.locale.strip()
        language = self.language.strip().lower()
        if country is not None and _COUNTRY.fullmatch(country) is None:
            raise ValueError("requested model country must be ISO 3166-1 alpha-2")
        if not locale or _LOCALE.fullmatch(locale) is None:
            raise ValueError("requested model locale is invalid")
        if _LANGUAGE.fullmatch(language) is None:
            raise ValueError("requested model language is invalid")
        object.__setattr__(self, "country_code", country)
        object.__setattr__(self, "region_code", region)
        object.__setattr__(self, "locale", locale)
        object.__setattr__(self, "language", language)

    def canonical_value(self) -> dict[str, str | None]:
        return {
            "country_code": self.country_code,
            "region_code": self.region_code,
            "locale": self.locale,
            "language": self.language,
        }


@dataclass(frozen=True)
class EffectiveModelLocation:
    control: ModelLocationControl
    country_code: str | None
    region_code: str | None
    locale: str | None
    language: str | None
    evidence_hash: str

    def __post_init__(self) -> None:
        control = ModelLocationControl(self.control)
        country = _optional_geo(self.country_code, uppercase=True)
        region = _optional_geo(self.region_code, uppercase=True)
        locale = _optional_geo(self.locale)
        language = _optional_geo(self.language)
        if _SHA256.fullmatch(self.evidence_hash) is None:
            raise ValueError("effective model location evidence must be SHA-256")
        if country is not None and _COUNTRY.fullmatch(country) is None:
            raise ValueError("effective model country must be ISO 3166-1 alpha-2")
        if locale is not None and _LOCALE.fullmatch(locale) is None:
            raise ValueError("effective model locale is invalid")
        if language is not None and _LANGUAGE.fullmatch(language.lower()) is None:
            raise ValueError("effective model language is invalid")
        if control is ModelLocationControl.COUNTRY:
            valid = country is not None and all(
                value is None for value in (region, locale, language)
            )
        elif control is ModelLocationControl.MARKET_LANGUAGE:
            valid = (
                country is None
                and region is None
                and locale is not None
                and language is not None
            )
        elif control is ModelLocationControl.LANGUAGE_ONLY:
            valid = (
                country is None
                and region is None
                and locale is None
                and language is not None
            )
        else:
            valid = all(value is None for value in (country, region, locale, language))
        if not valid:
            raise ValueError("effective model location shape differs from its control")
        object.__setattr__(self, "control", control)
        object.__setattr__(self, "country_code", country)
        object.__setattr__(self, "region_code", region)
        object.__setattr__(self, "locale", locale)
        object.__setattr__(self, "language", language.lower() if language else None)

    def canonical_value(self) -> dict[str, str | None]:
        return {
            "control": self.control.value,
            "country_code": self.country_code,
            "region_code": self.region_code,
            "locale": self.locale,
            "language": self.language,
            "evidence_hash": self.evidence_hash,
        }


def uncontrolled_model_location(
    *, provider: str, adapter_release_hash: str, reason: str
) -> EffectiveModelLocation:
    return EffectiveModelLocation(
        control=ModelLocationControl.NOT_CONTROLLED,
        country_code=None,
        region_code=None,
        locale=None,
        language=None,
        evidence_hash=canonical_json_hash(
            {
                "schema_version": 1,
                "provider": provider,
                "adapter_release_hash": adapter_release_hash,
                "classification": "not_controlled",
                "reason": reason,
            }
        ),
    )


def _optional_geo(value: str | None, *, uppercase: bool = False) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 64 or not normalized.isascii():
        raise ValueError("model location value is invalid")
    return normalized.upper() if uppercase else normalized


__all__ = [
    "EffectiveModelLocation",
    "ModelLocationControl",
    "RequestedModelLocation",
    "uncontrolled_model_location",
]
