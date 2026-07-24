from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal

import pytest

from geo_core.statistical_methods import (
    ComparisonInput,
    FrozenComparisonProtocol,
    PairedObservation,
    StatisticalStratum,
)


ProtocolFactory = Callable[..., FrozenComparisonProtocol]
InputFactory = Callable[..., ComparisonInput]


@pytest.fixture
def protocol_factory() -> ProtocolFactory:
    def make(
        *,
        comparison_id: str = "comparison-one",
        question_cluster: str = "purchase",
        capture_method: str = "provider_api",
        delta: Decimal = Decimal("0.05"),
        precision: Decimal = Decimal("0.10"),
        min_pairs: int = 3,
        family: str = "primary-family",
        candidate_version: str = "candidate-v2",
        a_priori_design_power: Decimal = Decimal("0.90"),
        bootstrap_iterations: int = 500,
        bootstrap_method: str = "paired-bootstrap-percentile-v1",
        simultaneous_interval_method: str = (
            "paired-bootstrap-percentile-bonferroni-family-v1"
        ),
    ) -> FrozenComparisonProtocol:
        stratum = StatisticalStratum(
            provider="openai",
            reported_model="model-v1",
            capture_method=capture_method,
            locale="en-AU",
            region="AU",
            source_composition_hash="c" * 64,
            sampling_source_stratum_hash="d" * 64,
            question_cluster=question_cluster,
        )
        return FrozenComparisonProtocol(
            protocol_hash="a" * 64,
            question_set_hash="b" * 64,
            baseline_version="baseline-v1",
            candidate_version=candidate_version,
            metric_key="recommendation",
            metric_method_version="semantic-metric-v1",
            comparison_id=comparison_id,
            family=family,
            stratum=stratum,
            alpha=Decimal("0.05"),
            delta=delta,
            target_power=Decimal("0.80"),
            precision=precision,
            min_pairs=min_pairs,
            power_plan_hash="e" * 64,
            a_priori_design_power=a_priori_design_power,
            minimum_completion_ratio=Decimal("0.80"),
            bootstrap_iterations=bootstrap_iterations,
            bootstrap_method=bootstrap_method,
            simultaneous_interval_method=simultaneous_interval_method,
        )

    return make


@pytest.fixture
def input_factory() -> InputFactory:
    def make(
        *,
        protocol: FrozenComparisonProtocol,
        deltas: Sequence[Decimal],
        planned_pair_count: int | None = None,
    ) -> ComparisonInput:
        pairs = tuple(
            PairedObservation(
                pair_id=f"pair-{index:02d}",
                question_id=f"question-{index:02d}",
                question_cluster=protocol.stratum.question_cluster,
                stratum_hash=protocol.stratum.stratum_hash,
                sampling_source_stratum_hash=(
                    protocol.stratum.sampling_source_stratum_hash
                ),
                capture_method=protocol.stratum.capture_method,
                baseline=Decimal(0),
                candidate=delta,
            )
            for index, delta in enumerate(deltas, start=1)
        )
        return ComparisonInput(
            protocol=protocol,
            sampling_source_stratum_hash=(
                protocol.stratum.sampling_source_stratum_hash
            ),
            planned_pair_count=planned_pair_count or len(pairs),
            pairs=pairs,
        )

    return make
