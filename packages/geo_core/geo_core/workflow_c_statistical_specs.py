"""Strict immutable payload decoders for Workflow C comparisons and drift."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from geo_core.statistical_methods import (
    ComparisonInput,
    DriftObservation,
    FrozenComparisonProtocol,
    PairedObservation,
    StatisticalStratum,
)
from geo_core.workflow_c_analysis_common import (
    WorkflowCAnalysisWorkerError,
    array_value,
    decimal_value,
    hash_value,
    integer_value,
    object_value,
    only_keys,
    text_value,
    uuid_value,
)
from geo_core.workflow_c_job_specs import WorkflowCJobSpec


def comparison_inputs(spec: WorkflowCJobSpec) -> tuple[ComparisonInput, ...]:
    payload = object_value(spec.payload, "comparison Worker payload")
    admission = analysis_admission_lineage(payload)
    value = object_value(payload.get("comparison"), "comparison Worker input")
    only_keys(value, {"inputs"}, "comparison Worker input")
    raw_inputs = array_value(value.get("inputs"), "comparison inputs")
    if not raw_inputs:
        raise WorkflowCAnalysisWorkerError("comparison inputs are required")
    inputs = tuple(
        comparison_input(object_value(item, "comparison input")) for item in raw_inputs
    )
    if admission is not None:
        if admission.protocol_kind != "comparison_plan":
            raise WorkflowCAnalysisWorkerError("comparison admission kind is invalid")
        for item in inputs:
            if item.protocol.protocol_hash != admission.protocol_hash or (
                item.protocol.baseline_version != f"snapshot:{admission.source_snapshot_hash}"
            ) or (
                item.protocol.candidate_version != f"snapshot:{admission.target_snapshot_hash}"
            ):
                raise WorkflowCAnalysisWorkerError(
                    "comparison input differs from its frozen admission lineage"
                )
    return inputs


def comparison_input(value: Mapping[str, object]) -> ComparisonInput:
    only_keys(
        value,
        {"protocol", "sampling_source_stratum_hash", "planned_pair_count", "pairs"},
        "comparison input",
    )
    protocol = comparison_protocol(object_value(value.get("protocol"), "comparison protocol"))
    pairs = tuple(
        paired_observation(object_value(item, "paired observation"))
        for item in array_value(value.get("pairs"), "comparison pairs")
    )
    return ComparisonInput(
        protocol=protocol,
        sampling_source_stratum_hash=hash_value(
            value.get("sampling_source_stratum_hash"), "sampling source stratum hash"
        ),
        planned_pair_count=integer_value(value.get("planned_pair_count"), "planned pair count"),
        pairs=pairs,
    )


def comparison_protocol(value: Mapping[str, object]) -> FrozenComparisonProtocol:
    allowed = {
        "protocol_hash", "question_set_hash", "baseline_version", "candidate_version",
        "metric_key", "metric_method_version", "comparison_id", "family", "stratum",
        "alpha", "delta", "target_power", "precision", "min_pairs", "power_plan_hash",
        "a_priori_design_power", "power_method_version", "minimum_completion_ratio",
        "bootstrap_iterations", "bootstrap_method", "correction_method",
        "simultaneous_interval_method",
    }
    only_keys(value, allowed, "comparison protocol")
    return FrozenComparisonProtocol(
        protocol_hash=hash_value(value.get("protocol_hash"), "protocol hash"),
        question_set_hash=hash_value(value.get("question_set_hash"), "question set hash"),
        baseline_version=text_value(value.get("baseline_version"), "baseline version"),
        candidate_version=text_value(value.get("candidate_version"), "candidate version"),
        metric_key=text_value(value.get("metric_key"), "metric key"),
        metric_method_version=text_value(value.get("metric_method_version"), "metric method version"),
        comparison_id=text_value(value.get("comparison_id"), "comparison id"),
        family=text_value(value.get("family"), "comparison family"),
        stratum=statistical_stratum(object_value(value.get("stratum"), "comparison stratum")),
        alpha=decimal_value(value.get("alpha"), "alpha"),
        delta=decimal_value(value.get("delta"), "delta"),
        target_power=decimal_value(value.get("target_power"), "target power"),
        precision=decimal_value(value.get("precision"), "precision"),
        min_pairs=integer_value(value.get("min_pairs"), "min pairs"),
        power_plan_hash=hash_value(value.get("power_plan_hash"), "power plan hash"),
        a_priori_design_power=decimal_value(
            value.get("a_priori_design_power"), "a priori design power"
        ),
        power_method_version=text_value(value.get("power_method_version"), "power method version"),
        minimum_completion_ratio=decimal_value(
            value.get("minimum_completion_ratio"), "minimum completion ratio"
        ),
        bootstrap_iterations=integer_value(value.get("bootstrap_iterations"), "bootstrap iterations"),
        bootstrap_method=text_value(value.get("bootstrap_method"), "bootstrap method"),
        correction_method=text_value(value.get("correction_method"), "correction method"),
        simultaneous_interval_method=text_value(
            value.get("simultaneous_interval_method"), "simultaneous interval method"
        ),
    )


def paired_observation(value: Mapping[str, object]) -> PairedObservation:
    only_keys(
        value,
        {
            "pair_id", "question_id", "question_cluster", "stratum_hash",
            "sampling_source_stratum_hash", "capture_method", "baseline", "candidate",
        },
        "paired observation",
    )
    return PairedObservation(
        pair_id=text_value(value.get("pair_id"), "pair id"),
        question_id=text_value(value.get("question_id"), "question id"),
        question_cluster=text_value(value.get("question_cluster"), "question cluster"),
        stratum_hash=hash_value(value.get("stratum_hash"), "pair stratum hash"),
        sampling_source_stratum_hash=hash_value(
            value.get("sampling_source_stratum_hash"), "pair sampling source stratum hash"
        ),
        capture_method=text_value(value.get("capture_method"), "capture method"),
        baseline=decimal_value(value.get("baseline"), "paired baseline"),
        candidate=decimal_value(value.get("candidate"), "paired candidate"),
    )


def drift_inputs(
    spec: WorkflowCJobSpec,
) -> tuple[
    str | None,
    str,
    str,
    tuple[DriftObservation, ...],
    tuple[DriftObservation, ...],
]:
    payload = object_value(spec.payload, "drift Worker payload")
    admission = analysis_admission_lineage(payload)
    value = object_value(payload.get("drift"), "drift Worker input")
    only_keys(
        value,
        {"source_snapshot_hash", "target_snapshot_hash", "baseline", "current"},
        "drift Worker input",
    )
    protocol_hash = None if admission is None else admission.protocol_hash
    if admission is not None and admission.protocol_kind != "drift_protocol":
        raise WorkflowCAnalysisWorkerError("drift admission kind is invalid")
    source_hash = hash_value(value.get("source_snapshot_hash"), "source snapshot hash")
    target_hash = hash_value(value.get("target_snapshot_hash"), "target snapshot hash")
    if source_hash == target_hash:
        raise WorkflowCAnalysisWorkerError("drift source and target snapshots must differ")
    if admission is not None and (
        source_hash != admission.source_snapshot_hash
        or target_hash != admission.target_snapshot_hash
    ):
        raise WorkflowCAnalysisWorkerError(
            "drift snapshots differ from their frozen admission lineage"
        )
    baseline = tuple(
        drift_observation(object_value(item, "baseline drift observation"))
        for item in array_value(value.get("baseline"), "baseline drift observations")
    )
    current = tuple(
        drift_observation(object_value(item, "current drift observation"))
        for item in array_value(value.get("current"), "current drift observations")
    )
    return protocol_hash, source_hash, target_hash, baseline, current


@dataclass(frozen=True)
class AnalysisAdmissionLineage:
    protocol_kind: str
    protocol_id: UUID
    protocol_hash: str
    source_snapshot_hash: str
    target_snapshot_hash: str
    requested_by: str


def analysis_admission_lineage(
    payload: Mapping[str, object],
) -> AnalysisAdmissionLineage | None:
    raw = payload.get("admission")
    if raw is None:
        return None
    value = object_value(raw, "analysis admission lineage")
    only_keys(
        value,
        {
            "protocol_kind",
            "protocol_id",
            "protocol_hash",
            "source_snapshot_hash",
            "target_snapshot_hash",
            "requested_by",
        },
        "analysis admission lineage",
    )
    return AnalysisAdmissionLineage(
        protocol_kind=text_value(value.get("protocol_kind"), "protocol kind"),
        protocol_id=uuid_value(value.get("protocol_id"), "protocol id"),
        protocol_hash=hash_value(value.get("protocol_hash"), "protocol hash"),
        source_snapshot_hash=hash_value(
            value.get("source_snapshot_hash"), "source snapshot hash"
        ),
        target_snapshot_hash=hash_value(
            value.get("target_snapshot_hash"), "target snapshot hash"
        ),
        requested_by=text_value(value.get("requested_by"), "analysis requester"),
    )


def comparison_input_value(value: ComparisonInput) -> dict[str, object]:
    protocol = dict(value.protocol.canonical_value())
    protocol.pop("seed_hex")
    return {
        "protocol": protocol,
        "sampling_source_stratum_hash": value.sampling_source_stratum_hash,
        "planned_pair_count": value.planned_pair_count,
        "pairs": [item.canonical_value() for item in value.pairs],
    }


def drift_observation_value(value: DriftObservation) -> dict[str, object]:
    return {
        "observation_id": value.observation_id,
        "stratum": value.stratum.canonical_value(),
        "effect": str(value.effect),
    }


def drift_observation(value: Mapping[str, object]) -> DriftObservation:
    only_keys(value, {"observation_id", "stratum", "effect"}, "drift observation")
    return DriftObservation(
        observation_id=text_value(value.get("observation_id"), "drift observation id"),
        stratum=statistical_stratum(object_value(value.get("stratum"), "drift stratum")),
        effect=decimal_value(value.get("effect"), "drift effect"),
    )


def statistical_stratum(value: Mapping[str, object]) -> StatisticalStratum:
    only_keys(
        value,
        {
            "provider", "reported_model", "capture_method", "locale", "region",
            "source_composition_hash", "sampling_source_stratum_hash", "question_cluster",
        },
        "statistical stratum",
    )
    return StatisticalStratum(
        provider=text_value(value.get("provider"), "stratum provider"),
        reported_model=text_value(value.get("reported_model"), "stratum model"),
        capture_method=text_value(value.get("capture_method"), "stratum capture method"),
        locale=text_value(value.get("locale"), "stratum locale"),
        region=text_value(value.get("region"), "stratum region"),
        source_composition_hash=hash_value(
            value.get("source_composition_hash"), "source composition hash"
        ),
        sampling_source_stratum_hash=hash_value(
            value.get("sampling_source_stratum_hash"), "sampling source stratum hash"
        ),
        question_cluster=text_value(value.get("question_cluster"), "stratum question cluster"),
    )


__all__ = [
    "comparison_input_value",
    "comparison_inputs",
    "analysis_admission_lineage",
    "drift_inputs",
    "drift_observation_value",
]
