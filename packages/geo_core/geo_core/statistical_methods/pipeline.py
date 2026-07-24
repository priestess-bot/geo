"""Family-level paired bootstrap, Holm correction and five-state decisions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, ROUND_HALF_UP

from geo_core.statistical_methods.bootstrap import paired_bootstrap
from geo_core.statistical_methods.contracts import (
    BootstrapEstimate,
    ComparisonInput,
    ComparisonResult,
    StatisticalInterval,
    StatisticalRuleViolation,
    canonical_hash,
    decimal_value,
)
from geo_core.statistical_methods.decision import decide_comparison
from geo_core.statistical_methods.multiplicity import holm_adjust


TWELVE_PLACES = Decimal("0.000000000001")


@dataclass(frozen=True)
class ComparisonFamilyResult:
    family: str
    alpha: Decimal
    correction_method: str
    results: tuple[ComparisonResult, ...]
    family_hash: str = field(init=False)

    def __post_init__(self) -> None:
        results = tuple(sorted(self.results, key=lambda item: item.comparison_id))
        if not results or len({item.comparison_id for item in results}) != len(results):
            raise StatisticalRuleViolation("comparison family results must be non-empty and unique")
        if any(item.family != self.family for item in results):
            raise StatisticalRuleViolation("comparison result belongs to another family")
        object.__setattr__(self, "results", results)
        object.__setattr__(self, "family_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "family": self.family,
            "alpha": decimal_value(self.alpha),
            "correction_method": self.correction_method,
            "results": [item.canonical_value() for item in self.results],
        }


def analyze_comparison_family(
    comparisons: tuple[ComparisonInput, ...],
) -> ComparisonFamilyResult:
    if not comparisons:
        raise StatisticalRuleViolation("comparison family cannot be empty")
    ordered = tuple(sorted(comparisons, key=lambda item: item.protocol.comparison_id))
    protocols = tuple(item.protocol for item in ordered)
    family = protocols[0].family
    alpha = protocols[0].alpha
    correction = protocols[0].correction_method
    bootstrap_method = protocols[0].bootstrap_method
    bootstrap_iterations = protocols[0].bootstrap_iterations
    simultaneous_interval_method = protocols[0].simultaneous_interval_method
    if len({item.comparison_id for item in protocols}) != len(protocols):
        raise StatisticalRuleViolation("comparison ids must be unique within a family")
    if any(
        item.family != family
        or item.alpha != alpha
        or item.correction_method != correction
        or item.bootstrap_method != bootstrap_method
        or item.bootstrap_iterations != bootstrap_iterations
        or item.simultaneous_interval_method != simultaneous_interval_method
        for item in protocols
    ):
        raise StatisticalRuleViolation(
            "family statistical methods must be frozen together"
        )
    if correction != "holm-v1":
        raise StatisticalRuleViolation("only the frozen Holm correction is supported")
    raw = {
        item.protocol.comparison_id: _bootstrap(item, alpha=item.protocol.alpha) for item in ordered
    }
    adjustments = {
        item.comparison_id: item
        for item in holm_adjust(
            {key: estimate.two_sided_p_value for key, estimate in raw.items()},
            family_alpha=alpha,
        )
    }
    simultaneous_alpha = alpha / Decimal(len(ordered))
    results: list[ComparisonResult] = []
    for comparison in ordered:
        comparison_id = comparison.protocol.comparison_id
        adjustment = adjustments[comparison_id]
        adjusted = _bootstrap(comparison, alpha=simultaneous_alpha)
        adjusted_interval = replace(
            adjusted.interval,
            method=comparison.protocol.simultaneous_interval_method,
        )
        conclusion = decide_comparison(
            comparison,
            adjusted_interval=adjusted_interval,
        )
        results.append(
            ComparisonResult(
                comparison_id=comparison_id,
                family=family,
                protocol_frozen_hash=comparison.protocol.frozen_hash,
                input_hash=comparison.input_hash,
                stratum_hash=comparison.protocol.stratum.stratum_hash,
                valid_pair_count=len(comparison.pairs),
                planned_pair_count=comparison.planned_pair_count,
                completion_ratio=_ratio(len(comparison.pairs), comparison.planned_pair_count),
                point_estimate=raw[comparison_id].point_estimate,
                raw_interval=raw[comparison_id].interval,
                adjusted_interval=adjusted_interval,
                raw_p_value=adjustment.raw_p_value,
                adjusted_p_value=adjustment.adjusted_p_value,
                holm_rank=adjustment.rank,
                local_alpha=adjustment.local_alpha,
                a_priori_design_power=comparison.protocol.a_priori_design_power,
                power_plan_hash=comparison.protocol.power_plan_hash,
                power_method_version=comparison.protocol.power_method_version,
                conclusion=conclusion,
                seed_hex=comparison.protocol.seed_hex,
                bootstrap_iterations=comparison.protocol.bootstrap_iterations,
            )
        )
    return ComparisonFamilyResult(
        family=family,
        alpha=alpha,
        correction_method=correction,
        results=tuple(results),
    )


def _bootstrap(comparison: ComparisonInput, *, alpha: Decimal) -> BootstrapEstimate:
    protocol = comparison.protocol
    if comparison.pairs:
        return paired_bootstrap(
            comparison.pairs,
            seed_hex=protocol.seed_hex,
            iterations=protocol.bootstrap_iterations,
            alpha=alpha,
            method=protocol.bootstrap_method,
        )
    interval = StatisticalInterval(
        method=protocol.bootstrap_method,
        alpha=alpha,
        low=Decimal(-1),
        high=Decimal(1),
    )
    return BootstrapEstimate(
        point_estimate=Decimal(0),
        interval=interval,
        two_sided_p_value=Decimal(1),
        seed_hex=protocol.seed_hex,
        iterations=protocol.bootstrap_iterations,
        distribution_hash=canonical_hash([]),
    )


def _ratio(numerator: int, denominator: int) -> Decimal:
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        TWELVE_PLACES, rounding=ROUND_HALF_UP
    )
