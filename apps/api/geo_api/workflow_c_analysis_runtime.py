"""Server-resolved deterministic semantic, comparison and drift runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol
from uuid import UUID

from geo_api.workflow_c_analysis_contracts import (
    AnalyzeComparisonFamilyRequest,
    ComputeDriftRequest,
    ComputeSemanticMetricsRequest,
)
from geo_core.semantic_metrics import (
    FrozenMetricSuite,
    MetricInputSet,
    SemanticMetricSnapshot,
    compute_semantic_metric_snapshot,
)
from geo_core.statistical_methods import (
    ComparisonFamilyResult,
    ComparisonInput,
    DriftObservation,
    DriftReport,
    analyze_comparison_family,
    compute_drift_report,
)
from geo_core.workflow_c_analysis_reads import (
    StoredComparisonFamily,
    StoredDriftReport,
    StoredSemanticMetricSnapshot,
)


class WorkflowCAnalysisNotFound(RuntimeError):
    """A project-scoped selector or analysis projection does not exist."""


class WorkflowCAnalysisUnavailable(RuntimeError):
    """A durable analysis command has not yet been safely admitted."""


SemanticSnapshotProjection = SemanticMetricSnapshot | StoredSemanticMetricSnapshot
ComparisonFamilyProjection = ComparisonFamilyResult | StoredComparisonFamily
DriftReportProjection = DriftReport | StoredDriftReport


class WorkflowCAnalysisPort(Protocol):
    """The full API route shape, with durable reads and explicitly gated writes."""

    def compute_semantic_metrics(
        self, *, project_id: UUID, payload: ComputeSemanticMetricsRequest
    ) -> SemanticSnapshotProjection: ...

    def analyze_comparisons(
        self, *, project_id: UUID, payload: AnalyzeComparisonFamilyRequest
    ) -> ComparisonFamilyProjection: ...

    def compute_drift(
        self, *, project_id: UUID, payload: ComputeDriftRequest
    ) -> DriftReportProjection: ...

    def get_semantic_snapshot(
        self, *, project_id: UUID, snapshot_hash: str
    ) -> SemanticSnapshotProjection: ...

    def list_semantic_snapshots(
        self, *, project_id: UUID
    ) -> tuple[SemanticSnapshotProjection, ...]: ...

    def get_comparison_family(
        self, *, project_id: UUID, family_hash: str
    ) -> ComparisonFamilyProjection: ...

    def list_comparison_families(
        self, *, project_id: UUID
    ) -> tuple[ComparisonFamilyProjection, ...]: ...

    def get_drift_report(self, *, project_id: UUID, report_hash: str) -> DriftReportProjection: ...

    def list_drift_reports(self, *, project_id: UUID) -> tuple[DriftReportProjection, ...]: ...


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


class WorkflowCAnalysisRuntime:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        input_resolver: WorkflowCAnalysisInputResolver | None = None,
    ) -> None:
        self._lock = RLock()
        self._clock = clock
        self._input_resolver = input_resolver or _MemoryAnalysisInputResolver()
        self._semantic: dict[tuple[UUID, str], SemanticMetricSnapshot] = {}
        self._comparisons: dict[tuple[UUID, str], ComparisonFamilyResult] = {}
        self._drift: dict[tuple[UUID, str], DriftReport] = {}

    def install_semantic_inputs(
        self,
        *,
        project_id: UUID,
        selector: ComputeSemanticMetricsRequest,
        input_set: MetricInputSet,
        metric_suite: FrozenMetricSuite,
    ) -> None:
        judge = metric_suite.judge_version
        if (
            selector.metric_protocol_hash != metric_suite.suite_hash
            or selector.prompt_release_id != judge.prompt_release_id
            or selector.prompt_release_hash != judge.prompt_release_hash
            or selector.corpus_version_hash != input_set.approved_corpus_hash
        ):
            raise ValueError("semantic selector differs from its frozen server input")
        resolver = self._memory_resolver()
        resolver.install_semantic(
            project_id=project_id,
            selector=selector,
            resolved=ResolvedSemanticAnalysis(input_set, metric_suite),
        )

    def install_comparison_inputs(
        self,
        *,
        project_id: UUID,
        selector: AnalyzeComparisonFamilyRequest,
        comparisons: tuple[ComparisonInput, ...],
    ) -> None:
        resolver = self._memory_resolver()
        resolver.install_comparison(
            project_id=project_id,
            selector=selector,
            resolved=ResolvedComparisonAnalysis(comparisons),
        )

    def install_drift_inputs(
        self,
        *,
        project_id: UUID,
        selector: ComputeDriftRequest,
        baseline: tuple[DriftObservation, ...],
        current: tuple[DriftObservation, ...],
    ) -> None:
        resolver = self._memory_resolver()
        resolver.install_drift(
            project_id=project_id,
            selector=selector,
            resolved=ResolvedDriftAnalysis(baseline, current),
        )

    def compute_semantic_metrics(
        self, *, project_id: UUID, payload: ComputeSemanticMetricsRequest
    ) -> SemanticMetricSnapshot:
        resolved = self._input_resolver.semantic(project_id=project_id, selector=payload)
        snapshot = compute_semantic_metric_snapshot(
            input_set=resolved.input_set,
            suite=resolved.metric_suite,
            computed_at=self._clock(),
        )
        with self._lock:
            self._semantic[(project_id, snapshot.snapshot_hash)] = snapshot
        return snapshot

    def analyze_comparisons(
        self, *, project_id: UUID, payload: AnalyzeComparisonFamilyRequest
    ) -> ComparisonFamilyResult:
        resolved = self._input_resolver.comparison(project_id=project_id, selector=payload)
        result = analyze_comparison_family(resolved.comparisons)
        with self._lock:
            self._comparisons[(project_id, result.family_hash)] = result
        return result

    def compute_drift(self, *, project_id: UUID, payload: ComputeDriftRequest) -> DriftReport:
        resolved = self._input_resolver.drift(project_id=project_id, selector=payload)
        result = compute_drift_report(
            baseline=resolved.baseline,
            current=resolved.current,
        )
        with self._lock:
            self._drift[(project_id, result.report_hash)] = result
        return result

    def get_semantic_snapshot(
        self, *, project_id: UUID, snapshot_hash: str
    ) -> SemanticMetricSnapshot:
        return self._projection(
            self._semantic,
            (project_id, snapshot_hash),
            "semantic metric snapshot",
        )

    def list_semantic_snapshots(self, *, project_id: UUID) -> tuple[SemanticMetricSnapshot, ...]:
        return self._project_values(self._semantic, project_id)

    def get_comparison_family(
        self, *, project_id: UUID, family_hash: str
    ) -> ComparisonFamilyResult:
        return self._projection(
            self._comparisons,
            (project_id, family_hash),
            "comparison family result",
        )

    def list_comparison_families(self, *, project_id: UUID) -> tuple[ComparisonFamilyResult, ...]:
        return self._project_values(self._comparisons, project_id)

    def get_drift_report(self, *, project_id: UUID, report_hash: str) -> DriftReport:
        return self._projection(
            self._drift,
            (project_id, report_hash),
            "drift report",
        )

    def list_drift_reports(self, *, project_id: UUID) -> tuple[DriftReport, ...]:
        return self._project_values(self._drift, project_id)

    def _memory_resolver(self) -> _MemoryAnalysisInputResolver:
        if not isinstance(self._input_resolver, _MemoryAnalysisInputResolver):
            raise RuntimeError("only the memory resolver accepts test fixtures")
        return self._input_resolver

    def _projection(self, values: dict, key: tuple[UUID, str], label: str):
        with self._lock:
            result = values.get(key)
        if result is None:
            raise WorkflowCAnalysisNotFound(f"{label} does not exist")
        return result

    def _project_values(self, values: dict, project_id: UUID) -> tuple:
        with self._lock:
            matches = tuple(
                item for (item_project, _), item in values.items() if item_project == project_id
            )
        return tuple(sorted(matches, key=_projection_hash))


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


def _projection_hash(value: object) -> str:
    for name in ("snapshot_hash", "family_hash", "report_hash"):
        candidate = getattr(value, name, None)
        if isinstance(candidate, str):
            return candidate
    raise TypeError("analysis projection does not expose an immutable hash")
