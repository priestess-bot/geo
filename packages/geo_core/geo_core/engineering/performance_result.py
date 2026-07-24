"""Fail-closed acceptance contract for the frozen non-B performance run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re
from collections.abc import Callable, Mapping
from uuid import UUID

from geo_core.engineering.performance_profile import (
    PerformanceProfile,
    PerformanceProfileError,
    non_b_performance_profile_v1,
)
from geo_core.engineering.performance_workload import (
    NonBPerformanceWorkload,
    non_b_performance_workload_v1,
)


_SHA256 = re.compile(r"[0-9a-f]{64}")
_MEMORY_MULTIPLIERS = {"K": 1024, "M": 1024**2, "G": 1024**3}


@dataclass(frozen=True)
class LatencyDistribution:
    sample_count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float

    def __post_init__(self) -> None:
        values = (self.p50_ms, self.p95_ms, self.p99_ms, self.max_ms)
        if self.sample_count < 1 or any(not math.isfinite(value) or value < 0 for value in values):
            raise PerformanceProfileError("latency measurements must be finite and non-negative")
        if tuple(sorted(values)) != values:
            raise PerformanceProfileError("latency percentiles must be monotonic")


@dataclass(frozen=True)
class RuntimeTopologyMeasurement:
    task_workers: int
    style_browser_workers: int
    outbox_relays: int
    api_database_pool_max_size: int
    resource_limits: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class ResourceWatermark:
    service: str
    cpu_peak_cores: float
    memory_peak_bytes: int

    def __post_init__(self) -> None:
        if not self.service.strip():
            raise PerformanceProfileError("resource watermark service is required")
        if not math.isfinite(self.cpu_peak_cores) or self.cpu_peak_cores < 0:
            raise PerformanceProfileError("resource CPU watermark is invalid")
        if self.memory_peak_bytes < 0:
            raise PerformanceProfileError("resource memory watermark is invalid")


@dataclass(frozen=True)
class CorrectnessMeasurement:
    cross_project_reads: int
    duplicate_terminal_states: int
    lost_outbox_messages: int
    hash_mismatches: int

    def __post_init__(self) -> None:
        if any(value < 0 for value in self.values()):
            raise PerformanceProfileError("correctness counters cannot be negative")

    def values(self) -> tuple[int, ...]:
        return (
            self.cross_project_reads,
            self.duplicate_terminal_states,
            self.lost_outbox_messages,
            self.hash_mismatches,
        )


@dataclass(frozen=True)
class SamplingRunMeasurement:
    run_id: UUID
    project_id: UUID
    provider: str
    planned_tasks: int
    terminal_tasks: int
    peak_eligible_tasks: int
    dispatch_latency: LatencyDistribution

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise PerformanceProfileError("sampling run provider is required")
        if self.planned_tasks < 1:
            raise PerformanceProfileError("sampling run planned task count must be positive")
        if not 0 <= self.terminal_tasks <= self.planned_tasks:
            raise PerformanceProfileError("sampling run terminal count exceeds its denominator")
        if not 0 <= self.peak_eligible_tasks <= self.planned_tasks:
            raise PerformanceProfileError("sampling run eligible count exceeds its denominator")


@dataclass(frozen=True)
class StyleChannelMeasurement:
    channel: str
    approved_sample_count: int
    fixed_case_count: int
    candidate_count: int
    offline_experiment_slot_count: int

    def __post_init__(self) -> None:
        if not self.channel.strip():
            raise PerformanceProfileError("style channel is required")
        if any(
            value < 0
            for value in (
                self.approved_sample_count,
                self.fixed_case_count,
                self.candidate_count,
                self.offline_experiment_slot_count,
            )
        ):
            raise PerformanceProfileError("style channel measurements cannot be negative")


@dataclass(frozen=True)
class PerformanceRunResult:
    schema_version: str
    run_id: str
    profile_id: str
    profile_hash: str
    workload_id: str
    workload_hash: str
    environment_fingerprint: str
    started_at: datetime
    finished_at: datetime
    api_load_duration_seconds: int
    diagnostic_only: bool
    project_count: int
    concurrently_active_projects: int
    sampling_planned_tasks: int
    sampling_terminal_tasks: int
    sampling_peak_eligible_tasks: int
    sampling_runs: tuple[SamplingRunMeasurement, ...]
    style_channel_count: int
    style_approved_sample_count: int
    style_fixed_case_count: int
    style_candidate_count: int
    offline_experiment_slot_count: int
    style_channels: tuple[StyleChannelMeasurement, ...]
    read_latency: LatencyDistribution
    write_latency: LatencyDistribution
    overall_latency: LatencyDistribution
    unexpected_5xx_count: int
    dispatch_latency: LatencyDistribution
    outbox_publish_latency: LatencyDistribution
    maximum_queue_age_seconds: float
    drain_seconds: float
    metric_observation_count: int
    metric_recompute_latency: LatencyDistribution
    topology: RuntimeTopologyMeasurement
    resource_watermarks: tuple[ResourceWatermark, ...]
    correctness: CorrectnessMeasurement
    raw_report_uri: str
    raw_report_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "geo-performance-result-v1":
            raise PerformanceProfileError("unsupported performance result schema")
        if not self.run_id.strip():
            raise PerformanceProfileError("performance run id is required")
        for value, label in (
            (self.profile_hash, "profile hash"),
            (self.workload_hash, "workload hash"),
            (self.environment_fingerprint, "environment fingerprint"),
            (self.raw_report_sha256, "raw report hash"),
        ):
            if _SHA256.fullmatch(value) is None:
                raise PerformanceProfileError(f"performance {label} must be SHA-256")
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise PerformanceProfileError("performance run timestamps must be timezone-aware")
        if self.finished_at <= self.started_at:
            raise PerformanceProfileError("performance run finish must follow start")
        elapsed_seconds = (self.finished_at - self.started_at).total_seconds()
        if (
            not isinstance(self.api_load_duration_seconds, int)
            or isinstance(self.api_load_duration_seconds, bool)
            or self.api_load_duration_seconds < 1
            or self.api_load_duration_seconds > elapsed_seconds
        ):
            raise PerformanceProfileError(
                "API load duration must be a positive window within the performance run"
            )
        if self.unexpected_5xx_count < 0:
            raise PerformanceProfileError("unexpected 5xx count cannot be negative")
        for queue_value in (self.maximum_queue_age_seconds, self.drain_seconds):
            if not math.isfinite(queue_value) or queue_value < 0:
                raise PerformanceProfileError("queue measurements must be finite and non-negative")
        if not self.raw_report_uri.startswith(("s3://", "minio://", "artifact://")):
            raise PerformanceProfileError("raw report must use an immutable artifact URI")
        services = tuple(item.service for item in self.resource_watermarks)
        if len(set(services)) != len(services):
            raise PerformanceProfileError("resource watermark services must be unique")
        sampling_ids = tuple(item.run_id for item in self.sampling_runs)
        if len(set(sampling_ids)) != len(sampling_ids):
            raise PerformanceProfileError("sampling run measurements must be unique")
        style_names = tuple(item.channel for item in self.style_channels)
        if len(set(style_names)) != len(style_names):
            raise PerformanceProfileError("style channel measurements must be unique")


@dataclass(frozen=True)
class PerformanceRunDecision:
    accepted: bool
    failed_checks: tuple[str, ...]


def evaluate_performance_run(
    result: PerformanceRunResult,
    *,
    profile: PerformanceProfile | None = None,
    workload: NonBPerformanceWorkload | None = None,
) -> PerformanceRunDecision:
    """Derive acceptance; result payloads cannot assert their own pass state."""
    frozen_profile = profile or non_b_performance_profile_v1()
    frozen_workload = workload or non_b_performance_workload_v1(frozen_profile)
    failures: list[str] = []

    def require(condition: bool, code: str) -> None:
        if not condition:
            failures.append(code)

    require(result.profile_id == frozen_profile.profile_id, "profile_id_mismatch")
    require(result.profile_hash == frozen_profile.profile_hash, "profile_hash_mismatch")
    require(result.workload_id == frozen_workload.workload_id, "workload_id_mismatch")
    require(result.workload_hash == frozen_workload.workload_hash, "workload_hash_mismatch")
    require(not result.diagnostic_only, "diagnostic_run")
    require(
        result.api_load_duration_seconds
        >= frozen_profile.api_targets.duration_minutes * 60,
        "duration_below_frozen_load",
    )
    require(result.project_count >= frozen_profile.project_load.total_projects, "project_load_low")
    require(
        result.concurrently_active_projects >= frozen_profile.project_load.concurrently_active,
        "active_project_load_low",
    )
    require(
        result.sampling_planned_tasks >= frozen_profile.provider_sampling.total_planned_tasks,
        "sampling_planned_load_low",
    )
    require(
        result.sampling_terminal_tasks >= frozen_profile.provider_sampling.total_planned_tasks,
        "sampling_not_terminal",
    )
    require(
        result.sampling_peak_eligible_tasks
        >= frozen_profile.provider_sampling.concurrently_eligible_tasks,
        "sampling_eligible_load_low",
    )
    _check_sampling_runs(result, frozen_workload, frozen_profile, require)
    synthetic = frozen_profile.synthetic_lab
    require(result.style_channel_count >= synthetic.style_channels, "style_channel_load_low")
    require(
        result.style_approved_sample_count
        >= synthetic.style_channels * synthetic.approved_samples_per_channel,
        "style_sample_load_low",
    )
    require(result.style_fixed_case_count >= synthetic.fixed_case_count, "style_case_load_low")
    require(
        result.style_candidate_count >= synthetic.fixed_case_count * synthetic.candidates_per_case,
        "style_candidate_load_low",
    )
    require(
        result.offline_experiment_slot_count
        >= synthetic.fixed_case_count
        * synthetic.experiment_arms
        * synthetic.repeats_per_question_per_arm,
        "offline_experiment_load_low",
    )
    _check_style_channels(result, frozen_workload, require)

    api = frozen_profile.api_targets
    require(
        result.read_latency.sample_count >= result.api_load_duration_seconds * api.read_rps,
        "read_request_load_low",
    )
    require(
        result.write_latency.sample_count >= result.api_load_duration_seconds * api.write_rps,
        "write_request_load_low",
    )
    require(result.read_latency.p95_ms <= api.read_p95_ms_max, "read_p95_exceeded")
    require(result.write_latency.p95_ms <= api.write_p95_ms_max, "write_p95_exceeded")
    require(
        result.overall_latency.sample_count
        >= result.read_latency.sample_count + result.write_latency.sample_count,
        "overall_request_load_low",
    )
    require(result.overall_latency.p99_ms <= api.overall_p99_ms_max, "overall_p99_exceeded")
    request_count = result.read_latency.sample_count + result.write_latency.sample_count
    unexpected_5xx_percent = 100 * result.unexpected_5xx_count / request_count
    require(
        unexpected_5xx_percent < float(api.unexpected_5xx_percent_max),
        "unexpected_5xx_budget_exceeded",
    )

    queue = frozen_profile.queue_targets
    require(
        result.dispatch_latency.sample_count
        >= frozen_profile.provider_sampling.total_planned_tasks,
        "dispatch_sample_load_low",
    )
    require(
        result.dispatch_latency.p95_ms <= queue.eligible_dispatch_p95_seconds_max * 1000,
        "dispatch_p95_exceeded",
    )
    require(
        result.outbox_publish_latency.p95_ms <= queue.outbox_publish_p95_seconds_max * 1000,
        "outbox_p95_exceeded",
    )
    require(
        result.outbox_publish_latency.sample_count
        >= frozen_profile.provider_sampling.total_planned_tasks,
        "outbox_sample_load_low",
    )
    require(result.maximum_queue_age_seconds <= queue.queue_age_seconds_max, "queue_age_exceeded")
    require(result.drain_seconds <= queue.drain_seconds_max, "queue_drain_exceeded")

    computation = frozen_profile.computation_targets
    require(
        result.metric_observation_count >= computation.metric_observation_count,
        "metric_observation_load_low",
    )
    require(
        result.metric_recompute_latency.sample_count
        >= computation.metric_recompute_sample_count,
        "metric_recompute_sample_load_low",
    )
    require(
        result.metric_recompute_latency.p95_ms
        <= computation.metric_recompute_p95_seconds_max * 1000,
        "metric_recompute_p95_exceeded",
    )
    require(not any(result.correctness.values()), "correctness_budget_exceeded")
    _check_topology(result, frozen_profile, require)
    return PerformanceRunDecision(accepted=not failures, failed_checks=tuple(failures))


def _check_sampling_runs(
    result: PerformanceRunResult,
    workload: NonBPerformanceWorkload,
    profile: PerformanceProfile,
    require: Callable[[bool, str], None],
) -> None:
    measured = {item.run_id: item for item in result.sampling_runs}
    expected = {item.run_id: item for item in workload.sampling_runs}
    require(set(measured) == set(expected), "sampling_run_measurements_incomplete")
    require(
        result.sampling_planned_tasks == sum(item.planned_tasks for item in measured.values()),
        "sampling_planned_total_mismatch",
    )
    require(
        result.sampling_terminal_tasks == sum(item.terminal_tasks for item in measured.values()),
        "sampling_terminal_total_mismatch",
    )
    require(
        result.sampling_peak_eligible_tasks
        == sum(item.peak_eligible_tasks for item in measured.values()),
        "sampling_eligible_total_mismatch",
    )
    for run_id, frozen in expected.items():
        item = measured.get(run_id)
        if item is None:
            continue
        prefix = f"sampling_run:{run_id}"
        require(item.project_id == frozen.project_id, f"{prefix}:project_mismatch")
        require(item.provider == frozen.provider, f"{prefix}:provider_mismatch")
        require(item.planned_tasks == frozen.planned_task_count, f"{prefix}:planned_mismatch")
        require(item.terminal_tasks == frozen.planned_task_count, f"{prefix}:not_terminal")
        require(
            item.peak_eligible_tasks >= frozen.immediately_eligible_task_count,
            f"{prefix}:eligible_load_low",
        )
        require(
            item.dispatch_latency.sample_count >= frozen.planned_task_count,
            f"{prefix}:dispatch_samples_low",
        )
        require(
            item.dispatch_latency.p95_ms
            <= profile.queue_targets.eligible_dispatch_p95_seconds_max * 1000,
            f"{prefix}:dispatch_p95_exceeded",
        )


def _check_style_channels(
    result: PerformanceRunResult,
    workload: NonBPerformanceWorkload,
    require: Callable[[bool, str], None],
) -> None:
    measured = {item.channel: item for item in result.style_channels}
    expected_channels = set(workload.synthetic.channels)
    require(set(measured) == expected_channels, "style_channel_measurements_incomplete")
    require(result.style_channel_count == len(measured), "style_channel_total_mismatch")
    require(
        result.style_approved_sample_count
        == sum(item.approved_sample_count for item in measured.values()),
        "style_sample_total_mismatch",
    )
    require(
        result.style_fixed_case_count == sum(item.fixed_case_count for item in measured.values()),
        "style_case_total_mismatch",
    )
    require(
        result.style_candidate_count == sum(item.candidate_count for item in measured.values()),
        "style_candidate_total_mismatch",
    )
    require(
        result.offline_experiment_slot_count
        == sum(item.offline_experiment_slot_count for item in measured.values()),
        "style_experiment_total_mismatch",
    )
    synthetic = workload.synthetic
    for channel in synthetic.channels:
        item = measured.get(channel)
        if item is None:
            continue
        prefix = f"style_channel:{channel}"
        require(
            item.approved_sample_count >= synthetic.approved_samples_per_channel,
            f"{prefix}:sample_load_low",
        )
        require(
            item.fixed_case_count >= synthetic.fixed_cases_per_channel,
            f"{prefix}:case_load_low",
        )
        require(
            item.candidate_count
            >= synthetic.fixed_cases_per_channel * synthetic.candidates_per_case,
            f"{prefix}:candidate_load_low",
        )
        require(
            item.offline_experiment_slot_count
            >= synthetic.fixed_cases_per_channel
            * synthetic.experiment_arms
            * synthetic.repeats_per_question_per_arm,
            f"{prefix}:experiment_load_low",
        )


def _check_topology(
    result: PerformanceRunResult,
    profile: PerformanceProfile,
    require: Callable[[bool, str], None],
) -> None:
    expected = profile.process_topology
    actual = result.topology
    require(actual.task_workers == expected.task_workers, "task_worker_topology_mismatch")
    require(
        actual.style_browser_workers == expected.style_browser_workers,
        "style_browser_topology_mismatch",
    )
    require(actual.outbox_relays == expected.outbox_relays, "outbox_topology_mismatch")
    require(
        actual.api_database_pool_max_size == expected.api_database_pool_max_size,
        "api_pool_topology_mismatch",
    )
    require(
        {name: dict(values) for name, values in actual.resource_limits.items()}
        == {name: dict(values) for name, values in expected.resource_limits.items()},
        "resource_limit_topology_mismatch",
    )
    watermarks = {item.service: item for item in result.resource_watermarks}
    require(set(watermarks) == set(expected.resource_limits), "resource_watermarks_incomplete")
    for service, limits in expected.resource_limits.items():
        item = watermarks.get(service)
        if item is None:
            continue
        require(
            item.cpu_peak_cores <= float(limits["cpus"]),
            f"resource_cpu_exceeded:{service}",
        )
        require(
            item.memory_peak_bytes <= _memory_bytes(limits["memory"]),
            f"resource_memory_exceeded:{service}",
        )


def _memory_bytes(value: str) -> int:
    suffix = value[-1].upper()
    if suffix not in _MEMORY_MULTIPLIERS:
        raise PerformanceProfileError("unsupported frozen memory unit")
    return int(value[:-1]) * _MEMORY_MULTIPLIERS[suffix]


__all__ = [
    "CorrectnessMeasurement",
    "LatencyDistribution",
    "PerformanceRunDecision",
    "PerformanceRunResult",
    "ResourceWatermark",
    "RuntimeTopologyMeasurement",
    "evaluate_performance_run",
]
