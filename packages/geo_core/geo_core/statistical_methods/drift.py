"""Strict-stratum model, source-composition and business-effect drift reporting."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from geo_core.statistical_methods.contracts import (
    StatisticalRuleViolation,
    StatisticalStratum,
    canonical_hash,
    decimal_value,
)


TWELVE_PLACES = Decimal("0.000000000001")


@dataclass(frozen=True, order=True)
class DriftCohortKey:
    provider: str
    capture_method: str
    locale: str
    region: str
    question_cluster: str


@dataclass(frozen=True, order=True)
class DriftObservation:
    observation_id: str
    stratum: StatisticalStratum
    effect: Decimal

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.effect.is_finite():
            raise StatisticalRuleViolation("drift observation identity and effect are required")

    @property
    def cohort_key(self) -> DriftCohortKey:
        return DriftCohortKey(
            provider=self.stratum.provider,
            capture_method=self.stratum.capture_method,
            locale=self.stratum.locale,
            region=self.stratum.region,
            question_cluster=self.stratum.question_cluster,
        )


@dataclass(frozen=True, order=True)
class ModelDriftSignal:
    cohort: DriftCohortKey
    baseline_models: tuple[str, ...]
    current_models: tuple[str, ...]


@dataclass(frozen=True, order=True)
class SourceDriftSignal:
    cohort: DriftCohortKey
    baseline_compositions: tuple[str, ...]
    current_compositions: tuple[str, ...]


@dataclass(frozen=True, order=True)
class EffectDriftSignal:
    stratum: StatisticalStratum
    baseline_count: int
    current_count: int
    baseline_mean: Decimal
    current_mean: Decimal
    effect_delta: Decimal

    def __post_init__(self) -> None:
        if self.baseline_count < 1 or self.current_count < 1:
            raise StatisticalRuleViolation("effect drift requires both strict strata")


@dataclass(frozen=True)
class DriftReport:
    model_drift: tuple[ModelDriftSignal, ...]
    source_drift: tuple[SourceDriftSignal, ...]
    effect_drift: tuple[EffectDriftSignal, ...]
    unmatched_baseline_strata: tuple[str, ...]
    unmatched_current_strata: tuple[str, ...]
    baseline_input_hash: str
    current_input_hash: str
    method_version: str = "strict-stratum-drift-v1"
    report_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "report_hash", canonical_hash(self.canonical_value()))

    def canonical_value(self) -> dict[str, object]:
        return {
            "model_drift": [
                {
                    "cohort": _cohort_value(item.cohort),
                    "baseline_models": list(item.baseline_models),
                    "current_models": list(item.current_models),
                }
                for item in self.model_drift
            ],
            "source_drift": [
                {
                    "cohort": _cohort_value(item.cohort),
                    "baseline_compositions": list(item.baseline_compositions),
                    "current_compositions": list(item.current_compositions),
                }
                for item in self.source_drift
            ],
            "effect_drift": [
                {
                    "stratum": item.stratum.canonical_value(),
                    "baseline_count": item.baseline_count,
                    "current_count": item.current_count,
                    "baseline_mean": decimal_value(item.baseline_mean),
                    "current_mean": decimal_value(item.current_mean),
                    "effect_delta": decimal_value(item.effect_delta),
                }
                for item in self.effect_drift
            ],
            "unmatched_baseline_strata": list(self.unmatched_baseline_strata),
            "unmatched_current_strata": list(self.unmatched_current_strata),
            "baseline_input_hash": self.baseline_input_hash,
            "current_input_hash": self.current_input_hash,
            "method_version": self.method_version,
        }


def compute_drift_report(
    *,
    baseline: Sequence[DriftObservation],
    current: Sequence[DriftObservation],
) -> DriftReport:
    baseline_values = _freeze_observations(baseline, "baseline")
    current_values = _freeze_observations(current, "current")
    baseline_cohorts = _by_cohort(baseline_values)
    current_cohorts = _by_cohort(current_values)
    model_signals: list[ModelDriftSignal] = []
    source_signals: list[SourceDriftSignal] = []
    for cohort in sorted(set(baseline_cohorts).union(current_cohorts)):
        baseline_group = baseline_cohorts.get(cohort, ())
        current_group = current_cohorts.get(cohort, ())
        baseline_models = tuple(sorted({item.stratum.reported_model for item in baseline_group}))
        current_models = tuple(sorted({item.stratum.reported_model for item in current_group}))
        if baseline_models != current_models:
            model_signals.append(ModelDriftSignal(cohort, baseline_models, current_models))
        baseline_sources = tuple(
            sorted({item.stratum.source_composition_hash for item in baseline_group})
        )
        current_sources = tuple(
            sorted({item.stratum.source_composition_hash for item in current_group})
        )
        if baseline_sources != current_sources:
            source_signals.append(SourceDriftSignal(cohort, baseline_sources, current_sources))

    baseline_strata = _by_stratum(baseline_values)
    current_strata = _by_stratum(current_values)
    shared_hashes = sorted(set(baseline_strata).intersection(current_strata))
    effect_signals: list[EffectDriftSignal] = []
    for stratum_hash in shared_hashes:
        baseline_group = baseline_strata[stratum_hash]
        current_group = current_strata[stratum_hash]
        stratum = baseline_group[0].stratum
        baseline_mean = _mean([item.effect for item in baseline_group])
        current_mean = _mean([item.effect for item in current_group])
        effect_signals.append(
            EffectDriftSignal(
                stratum=stratum,
                baseline_count=len(baseline_group),
                current_count=len(current_group),
                baseline_mean=baseline_mean,
                current_mean=current_mean,
                effect_delta=_quantize(current_mean - baseline_mean),
            )
        )
    return DriftReport(
        model_drift=tuple(model_signals),
        source_drift=tuple(source_signals),
        effect_drift=tuple(sorted(effect_signals)),
        unmatched_baseline_strata=tuple(sorted(set(baseline_strata) - set(current_strata))),
        unmatched_current_strata=tuple(sorted(set(current_strata) - set(baseline_strata))),
        baseline_input_hash=_observations_hash(baseline_values),
        current_input_hash=_observations_hash(current_values),
    )


def _freeze_observations(
    values: Sequence[DriftObservation], label: str
) -> tuple[DriftObservation, ...]:
    ordered = tuple(sorted(values))
    if not ordered or len({item.observation_id for item in ordered}) != len(ordered):
        raise StatisticalRuleViolation(f"{label} drift observations must be non-empty and unique")
    return ordered


def _by_cohort(
    values: Sequence[DriftObservation],
) -> dict[DriftCohortKey, tuple[DriftObservation, ...]]:
    groups: dict[DriftCohortKey, list[DriftObservation]] = defaultdict(list)
    for item in values:
        groups[item.cohort_key].append(item)
    return {key: tuple(items) for key, items in groups.items()}


def _by_stratum(
    values: Sequence[DriftObservation],
) -> dict[str, tuple[DriftObservation, ...]]:
    groups: dict[str, list[DriftObservation]] = defaultdict(list)
    for item in values:
        groups[item.stratum.stratum_hash].append(item)
    return {key: tuple(items) for key, items in groups.items()}


def _observations_hash(values: Sequence[DriftObservation]) -> str:
    return canonical_hash(
        [
            {
                "observation_id": item.observation_id,
                "stratum": item.stratum.canonical_value(),
                "effect": decimal_value(item.effect),
            }
            for item in values
        ]
    )


def _cohort_value(value: DriftCohortKey) -> dict[str, object]:
    return {
        "provider": value.provider,
        "capture_method": value.capture_method,
        "locale": value.locale,
        "region": value.region,
        "question_cluster": value.question_cluster,
    }


def _mean(values: Sequence[Decimal]) -> Decimal:
    return _quantize(sum(values, Decimal(0)) / Decimal(len(values)))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWELVE_PLACES, rounding=ROUND_HALF_UP)
