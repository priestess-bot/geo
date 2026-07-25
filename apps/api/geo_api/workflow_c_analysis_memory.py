"""Immutable in-memory Workflow C analysis selector catalog for tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from geo_api.workflow_c_analysis_contracts import (
    AnalyzeComparisonFamilyRequest,
    ComputeDriftRequest,
    ComputeSemanticMetricsRequest,
)
from geo_api.workflow_c_analysis_ports import WorkflowCAnalysisNotFound
from geo_core.semantic_metrics import FrozenMetricSuite, MetricInputSet
from geo_core.statistical_methods import (
    ComparisonInput,
    DriftObservation,
)


@dataclass(frozen=True)
class ResolvedSemanticAnalysis:
    input_set: MetricInputSet
    metric_suite: FrozenMetricSuite


@dataclass(frozen=True)
class ResolvedComparisonAnalysis:
    comparisons: tuple[ComparisonInput, ...]


@dataclass(frozen=True)
class ResolvedDriftAnalysis:
    baseline: tuple[DriftObservation, ...]
    current: tuple[DriftObservation, ...]


class WorkflowCAnalysisInputResolver(Protocol):
    """Production resolves selectors from project-scoped immutable repositories."""

    def semantic(
        self, *, project_id: UUID, selector: ComputeSemanticMetricsRequest
    ) -> ResolvedSemanticAnalysis: ...

    def comparison(
        self, *, project_id: UUID, selector: AnalyzeComparisonFamilyRequest
    ) -> ResolvedComparisonAnalysis: ...

    def drift(
        self, *, project_id: UUID, selector: ComputeDriftRequest
    ) -> ResolvedDriftAnalysis: ...


class _MemoryAnalysisInputResolver:
    """Test-only catalog; no HTTP path can install or mutate its values."""

    def __init__(self) -> None:
        self._semantic: dict[tuple[object, ...], ResolvedSemanticAnalysis] = {}
        self._comparisons: dict[tuple[object, ...], ResolvedComparisonAnalysis] = {}
        self._drift: dict[tuple[object, ...], ResolvedDriftAnalysis] = {}

    def install_semantic(
        self,
        *,
        project_id: UUID,
        selector: ComputeSemanticMetricsRequest,
        resolved: ResolvedSemanticAnalysis,
    ) -> None:
        _install(self._semantic, _semantic_key(project_id, selector), resolved)

    def install_comparison(
        self,
        *,
        project_id: UUID,
        selector: AnalyzeComparisonFamilyRequest,
        resolved: ResolvedComparisonAnalysis,
    ) -> None:
        _install(self._comparisons, _comparison_key(project_id, selector), resolved)

    def install_drift(
        self,
        *,
        project_id: UUID,
        selector: ComputeDriftRequest,
        resolved: ResolvedDriftAnalysis,
    ) -> None:
        _install(self._drift, _drift_key(project_id, selector), resolved)

    def semantic(
        self, *, project_id: UUID, selector: ComputeSemanticMetricsRequest
    ) -> ResolvedSemanticAnalysis:
        return _resolve(self._semantic, _semantic_key(project_id, selector), "semantic")

    def comparison(
        self, *, project_id: UUID, selector: AnalyzeComparisonFamilyRequest
    ) -> ResolvedComparisonAnalysis:
        return _resolve(
            self._comparisons,
            _comparison_key(project_id, selector),
            "comparison",
        )

    def drift(self, *, project_id: UUID, selector: ComputeDriftRequest) -> ResolvedDriftAnalysis:
        return _resolve(self._drift, _drift_key(project_id, selector), "drift")


def _semantic_key(project_id: UUID, selector: ComputeSemanticMetricsRequest) -> tuple[object, ...]:
    return (
        project_id,
        selector.sampling_run_id,
        selector.sampling_run_version,
        selector.suite_hash,
        selector.metric_protocol_id,
        selector.metric_protocol_hash,
        selector.fact_snapshot_id,
        selector.fact_snapshot_hash,
        selector.prompt_release_id,
        selector.prompt_release_hash,
        selector.corpus_version_id,
        selector.corpus_version_hash,
        selector.baseline_snapshot_hash,
    )


def _comparison_key(
    project_id: UUID, selector: AnalyzeComparisonFamilyRequest
) -> tuple[object, ...]:
    return (
        project_id,
        selector.comparison_plan_id,
        selector.comparison_plan_hash,
        selector.baseline_metric_snapshot_hash,
        selector.candidate_metric_snapshot_hash,
    )


def _drift_key(project_id: UUID, selector: ComputeDriftRequest) -> tuple[object, ...]:
    return (
        project_id,
        selector.drift_protocol_id,
        selector.drift_protocol_hash,
        selector.baseline_metric_snapshot_hash,
        selector.current_metric_snapshot_hash,
    )


def _install(values: dict, key: tuple[object, ...], value: object) -> None:
    existing = values.get(key)
    if existing is not None and existing != value:
        raise ValueError("analysis selector already resolves to different immutable input")
    values[key] = value


def _resolve(values: dict, key: tuple[object, ...], label: str):
    result = values.get(key)
    if result is None:
        raise WorkflowCAnalysisNotFound(f"{label} selector does not resolve")
    return result
