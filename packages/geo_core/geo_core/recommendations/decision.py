"""Immutable decision fields carried by a recommendation evidence graph."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from geo_core.recommendations.errors import RecommendationRuleViolation


@dataclass(frozen=True)
class RecommendationDecision:
    impact_chain: tuple[str, ...]
    risk: str
    effort: str
    business_value: str
    confidence: Decimal
    counterevidence: tuple[str, ...]
    validation_plan: tuple[str, ...]
    stale_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "impact_chain",
            _normalise_texts(self.impact_chain, "impact chain", required=True),
        )
        object.__setattr__(self, "risk", _required_text(self.risk, "decision risk"))
        object.__setattr__(self, "effort", _required_text(self.effort, "decision effort"))
        object.__setattr__(
            self,
            "business_value",
            _required_text(self.business_value, "decision business value"),
        )
        try:
            confidence = Decimal(str(self.confidence))
        except InvalidOperation as error:
            raise RecommendationRuleViolation("decision confidence must be numeric") from error
        if not confidence.is_finite() or not Decimal("0") <= confidence <= Decimal("1"):
            raise RecommendationRuleViolation("decision confidence must be between 0 and 1")
        confidence = Decimal("0") if confidence.is_zero() else confidence.normalize()
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(
            self,
            "counterevidence",
            _normalise_texts(self.counterevidence, "counterevidence", required=False),
        )
        object.__setattr__(
            self,
            "validation_plan",
            _normalise_texts(self.validation_plan, "validation plan", required=True),
        )
        object.__setattr__(
            self,
            "stale_conditions",
            _normalise_texts(self.stale_conditions, "stale conditions", required=True),
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "impact_chain": list(self.impact_chain),
            "risk": self.risk,
            "effort": self.effort,
            "business_value": self.business_value,
            "confidence": str(self.confidence),
            "counterevidence": list(self.counterevidence),
            "validation_plan": list(self.validation_plan),
            "stale_conditions": list(self.stale_conditions),
        }


def _normalise_texts(values: tuple[str, ...], label: str, *, required: bool) -> tuple[str, ...]:
    result = tuple(_required_text(value, label) for value in values)
    if len(set(result)) != len(result):
        raise RecommendationRuleViolation(f"{label} entries must be unique")
    if required and not result:
        raise RecommendationRuleViolation(f"{label} is required")
    return result


def _required_text(value: str, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise RecommendationRuleViolation(f"{label} is required")
    return clean
