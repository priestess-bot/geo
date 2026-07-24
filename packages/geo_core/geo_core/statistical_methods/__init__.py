"""Reproducible GEO statistical intervals, comparisons, negative gain and drift."""

from geo_core.statistical_methods.bootstrap import paired_bootstrap
from geo_core.statistical_methods.contracts import (
    BootstrapEstimate,
    ComparisonConclusion,
    ComparisonInput,
    ComparisonResult,
    FrozenComparisonProtocol,
    HolmAdjustment,
    PairedObservation,
    StatisticalInterval,
    StatisticalRuleViolation,
    StatisticalStratum,
)
from geo_core.statistical_methods.decision import decide_comparison
from geo_core.statistical_methods.drift import (
    DriftCohortKey,
    DriftObservation,
    DriftReport,
    EffectDriftSignal,
    ModelDriftSignal,
    SourceDriftSignal,
    compute_drift_report,
)
from geo_core.statistical_methods.intervals import (
    newcombe_difference_interval,
    wilson_interval,
)
from geo_core.statistical_methods.multiplicity import holm_adjust
from geo_core.statistical_methods.negative_gain import (
    ClusterEffect,
    NegativeGainReport,
    QuestionEffect,
    summarize_negative_gain,
)
from geo_core.statistical_methods.pipeline import (
    ComparisonFamilyResult,
    analyze_comparison_family,
)

__all__ = [
    "BootstrapEstimate",
    "ClusterEffect",
    "ComparisonConclusion",
    "ComparisonFamilyResult",
    "ComparisonInput",
    "ComparisonResult",
    "DriftCohortKey",
    "DriftObservation",
    "DriftReport",
    "EffectDriftSignal",
    "FrozenComparisonProtocol",
    "HolmAdjustment",
    "ModelDriftSignal",
    "NegativeGainReport",
    "PairedObservation",
    "QuestionEffect",
    "SourceDriftSignal",
    "StatisticalInterval",
    "StatisticalRuleViolation",
    "StatisticalStratum",
    "analyze_comparison_family",
    "compute_drift_report",
    "decide_comparison",
    "holm_adjust",
    "newcombe_difference_interval",
    "paired_bootstrap",
    "summarize_negative_gain",
    "wilson_interval",
]
