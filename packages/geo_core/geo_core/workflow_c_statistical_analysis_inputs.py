"""Comparison and drift input construction from frozen snapshots."""

from __future__ import annotations

from collections import Counter

from geo_core.statistical_methods import (
    ComparisonInput,
    DriftObservation,
    FrozenComparisonProtocol,
    PairedObservation,
    StatisticalStratum,
)
from geo_core.statistical_methods.contracts import canonical_hash
from geo_core.workflow_c_statistical_protocols import (
    ComparisonPlanDefinition,
    DriftProtocolDefinition,
)
from geo_core.workflow_c_statistical_snapshot_inputs import (
    PostgresWorkflowCStatisticalAdmissionError,
    _ApprovedProtocol,
    _MetricSnapshot,
)


def _comparison_inputs(
    *,
    protocol: _ApprovedProtocol,
    baseline: _MetricSnapshot,
    candidate: _MetricSnapshot,
) -> tuple[ComparisonInput, ...]:
    definition = protocol.definition
    if not isinstance(definition, ComparisonPlanDefinition):
        raise PostgresWorkflowCStatisticalAdmissionError(
            "comparison admission requires a Comparison Plan"
        )
    if baseline.metric_suite_hash != candidate.metric_suite_hash:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "comparison snapshots use different Metric Suites"
        )
    if baseline.source_stratum_hash != candidate.source_stratum_hash or (
        baseline.capture_method != candidate.capture_method
    ):
        raise PostgresWorkflowCStatisticalAdmissionError(
            "comparison snapshots cannot mix SourceStratum or capture-method denominators"
        )
    if baseline.question_set_hash != candidate.question_set_hash:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "comparison snapshots use different QuestionSets"
        )
    baseline_by_id = {item.question_id: item for item in baseline.questions}
    candidate_by_id = {item.question_id: item for item in candidate.questions}
    baseline_inventory = {
        key: (value.question_cluster, value.planned_slot_count)
        for key, value in baseline_by_id.items()
    }
    candidate_inventory = {
        key: (value.question_cluster, value.planned_slot_count)
        for key, value in candidate_by_id.items()
    }
    if baseline_inventory != candidate_inventory:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "comparison snapshots have different frozen question denominators"
        )
    available_clusters = {item.question_cluster for item in baseline.questions}
    missing_clusters = set(definition.question_clusters) - available_clusters
    if missing_clusters:
        raise PostgresWorkflowCStatisticalAdmissionError(
            "Comparison Plan references absent question clusters"
        )
    source_composition_hash = canonical_hash(
        {
            "baseline_sampling_suite_hash": baseline.sampling_suite_hash,
            "candidate_sampling_suite_hash": candidate.sampling_suite_hash,
        }
    )
    results: list[ComparisonInput] = []
    for cluster in definition.question_clusters:
        baseline_questions = tuple(
            item for item in baseline.questions if item.question_cluster == cluster
        )
        stratum = _statistical_stratum(
            baseline,
            question_cluster=cluster,
            source_composition_hash=source_composition_hash,
        )
        frozen = FrozenComparisonProtocol(
            protocol_hash=protocol.definition_hash,
            question_set_hash=baseline.question_set_hash,
            baseline_version=f"snapshot:{baseline.snapshot_hash}",
            candidate_version=f"snapshot:{candidate.snapshot_hash}",
            metric_key=definition.metric_key,
            metric_method_version=definition.metric_method_version,
            comparison_id=f"comparison-{canonical_hash({'cluster': cluster})[:24]}",
            family=definition.family,
            stratum=stratum,
            alpha=definition.alpha,
            delta=definition.delta,
            target_power=definition.target_power,
            precision=definition.precision,
            min_pairs=definition.min_pairs,
            power_plan_hash=definition.power_plan_hash,
            a_priori_design_power=definition.a_priori_design_power,
            power_method_version=definition.power_method_version,
            minimum_completion_ratio=definition.minimum_completion_ratio,
            bootstrap_iterations=definition.bootstrap_iterations,
            bootstrap_method=definition.bootstrap_method,
            correction_method=definition.correction_method,
            simultaneous_interval_method=definition.simultaneous_interval_method,
        )
        pairs: tuple[PairedObservation, ...] = ()
        if baseline.evidence_status == candidate.evidence_status == "complete":
            pairs = tuple(
                PairedObservation(
                    pair_id=f"question:{item.question_id}",
                    question_id=item.question_id,
                    question_cluster=cluster,
                    stratum_hash=stratum.stratum_hash,
                    sampling_source_stratum_hash=baseline.source_stratum_hash,
                    capture_method=baseline.capture_method,
                    baseline=item.score,
                    candidate=candidate_by_id[item.question_id].score,
                )
                for item in baseline_questions
            )
        results.append(
            ComparisonInput(
                protocol=frozen,
                sampling_source_stratum_hash=baseline.source_stratum_hash,
                planned_pair_count=len(baseline_questions),
                pairs=pairs,
            )
        )
    return tuple(results)


def _drift_inputs(
    *,
    protocol: _ApprovedProtocol,
    baseline: _MetricSnapshot,
    current: _MetricSnapshot,
) -> tuple[tuple[DriftObservation, ...], tuple[DriftObservation, ...]]:
    definition = protocol.definition
    if not isinstance(definition, DriftProtocolDefinition):
        raise PostgresWorkflowCStatisticalAdmissionError(
            "drift admission requires a Drift Protocol"
        )
    for snapshot, label in ((baseline, "baseline"), (current, "current")):
        counts = Counter(item.question_cluster for item in snapshot.questions)
        if not counts or any(
            count < definition.minimum_question_count for count in counts.values()
        ):
            raise PostgresWorkflowCStatisticalAdmissionError(
                f"{label} drift snapshot is below the frozen per-cluster question minimum"
            )
    return _drift_observations(baseline), _drift_observations(current)


def _drift_observations(
    snapshot: _MetricSnapshot,
) -> tuple[DriftObservation, ...]:
    return tuple(
        DriftObservation(
            observation_id=f"{snapshot.snapshot_hash}:{item.question_id}",
            stratum=_statistical_stratum(
                snapshot,
                question_cluster=item.question_cluster,
                source_composition_hash=snapshot.sampling_suite_hash,
            ),
            effect=item.score,
        )
        for item in snapshot.questions
    )
def _statistical_stratum(
    snapshot: _MetricSnapshot,
    *,
    question_cluster: str,
    source_composition_hash: str,
) -> StatisticalStratum:
    return StatisticalStratum(
        provider=snapshot.source.platform,
        reported_model=snapshot.source.reported_model,
        capture_method=snapshot.capture_method,
        locale=snapshot.source.locale,
        region=snapshot.source.region,
        source_composition_hash=source_composition_hash,
        sampling_source_stratum_hash=snapshot.source_stratum_hash,
        question_cluster=question_cluster,
    )
