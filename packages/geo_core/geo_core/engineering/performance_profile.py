"""Frozen, scope-aware performance targets for the non-B roadmap workstreams."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from typing import Mapping


class PerformanceProfileError(ValueError):
    """Raised when a profile can be weakened or misrepresented."""


FROZEN_RUNTIME_RESOURCE_LIMITS: Mapping[str, Mapping[str, str]] = {
    "postgres": {"cpus": "2.0", "memory": "4G"},
    "minio": {"cpus": "1.5", "memory": "2G"},
    "valkey": {"cpus": "0.5", "memory": "512M"},
    "internal-api": {"cpus": "2.0", "memory": "2G"},
    "customer-api": {"cpus": "1.0", "memory": "1G"},
    "task-worker": {"cpus": "4.0", "memory": "8G"},
    "style-browser-worker": {"cpus": "1.5", "memory": "2G"},
    "synthetic-artifact-maintenance-worker": {"cpus": "0.5", "memory": "512M"},
    "workflow-c-maintenance-scheduler": {"cpus": "0.25", "memory": "256M"},
    "workflow-c-maintenance-worker": {"cpus": "0.5", "memory": "512M"},
    "recommendation-artifact-maintenance-worker": {"cpus": "0.5", "memory": "512M"},
    "recommendation-artifact-maintenance-scheduler": {"cpus": "0.25", "memory": "256M"},
    "outbox-relay": {"cpus": "0.5", "memory": "512M"},
    "admin-web": {"cpus": "1.0", "memory": "1G"},
    "customer-web": {"cpus": "1.0", "memory": "1G"},
}


@dataclass(frozen=True)
class ProjectLoad:
    total_projects: int
    concurrently_active: int

    def __post_init__(self) -> None:
        if self.total_projects < 10 or self.concurrently_active < 4:
            raise PerformanceProfileError("project load cannot be lower than roadmap v1")
        if self.concurrently_active > self.total_projects:
            raise PerformanceProfileError("active projects cannot exceed total projects")


@dataclass(frozen=True)
class ProviderSamplingLoad:
    concurrent_runs: int
    planned_tasks_per_run: int
    concurrently_eligible_tasks: int

    def __post_init__(self) -> None:
        if (
            self.concurrent_runs < 4
            or self.planned_tasks_per_run < 1_000
            or self.concurrently_eligible_tasks < 400
        ):
            raise PerformanceProfileError("provider sampling load cannot be lower than roadmap v1")

    @property
    def total_planned_tasks(self) -> int:
        return self.concurrent_runs * self.planned_tasks_per_run


@dataclass(frozen=True)
class SyntheticLabLoad:
    style_channels: int
    approved_samples_per_channel: int
    fixed_cases_per_channel: int
    candidates_per_case: int
    experiment_arms: int
    repeats_per_question_per_arm: int

    def __post_init__(self) -> None:
        minimum = (9, 200, 40, 4, 3, 10)
        actual = (
            self.style_channels,
            self.approved_samples_per_channel,
            self.fixed_cases_per_channel,
            self.candidates_per_case,
            self.experiment_arms,
            self.repeats_per_question_per_arm,
        )
        if any(value < threshold for value, threshold in zip(actual, minimum, strict=True)):
            raise PerformanceProfileError("synthetic lab load is below the frozen acceptance set")

    @property
    def fixed_case_count(self) -> int:
        return self.style_channels * self.fixed_cases_per_channel


@dataclass(frozen=True)
class ProcessTopology:
    task_workers: int
    style_browser_workers: int
    outbox_relays: int
    fixed_resource_limits_required: bool
    api_database_pool_max_size: int
    resource_limits: Mapping[str, Mapping[str, str]]

    def __post_init__(self) -> None:
        if self.task_workers < 4 or self.style_browser_workers != 1 or self.outbox_relays < 1:
            raise PerformanceProfileError("worker topology is below the frozen roadmap target")
        if not self.fixed_resource_limits_required:
            raise PerformanceProfileError("performance evidence requires fixed resource limits")
        if self.api_database_pool_max_size != 10:
            raise PerformanceProfileError("performance evidence requires the frozen API DB pool")
        normalized = {service: dict(limit) for service, limit in self.resource_limits.items()}
        expected = {
            service: dict(limit) for service, limit in FROZEN_RUNTIME_RESOURCE_LIMITS.items()
        }
        if normalized != expected:
            raise PerformanceProfileError(
                "runtime CPU and memory limits must match the frozen v1 topology"
            )


@dataclass(frozen=True)
class ApiTargets:
    duration_minutes: int
    read_rps: int
    write_rps: int
    read_p95_ms_max: int
    write_p95_ms_max: int
    overall_p99_ms_max: int
    unexpected_5xx_percent_max: str

    def __post_init__(self) -> None:
        if self.duration_minutes < 30 or self.read_rps < 20 or self.write_rps < 5:
            raise PerformanceProfileError("API load is below roadmap v1")
        if (
            self.read_p95_ms_max > 500
            or self.write_p95_ms_max > 800
            or self.overall_p99_ms_max > 2_000
            or self.unexpected_5xx_percent_max != "1.0"
        ):
            raise PerformanceProfileError("API acceptance targets cannot be weakened")


@dataclass(frozen=True)
class QueueTargets:
    eligible_dispatch_p95_seconds_max: int
    queue_age_seconds_max: int
    outbox_publish_p95_seconds_max: int
    drain_seconds_max: int

    def __post_init__(self) -> None:
        limits = (60, 300, 5, 600)
        actual = (
            self.eligible_dispatch_p95_seconds_max,
            self.queue_age_seconds_max,
            self.outbox_publish_p95_seconds_max,
            self.drain_seconds_max,
        )
        if any(value > limit for value, limit in zip(actual, limits, strict=True)):
            raise PerformanceProfileError("queue acceptance targets cannot be weakened")


@dataclass(frozen=True)
class ComputationTargets:
    metric_observation_count: int
    metric_recompute_sample_count: int
    metric_recompute_p95_seconds_max: int

    def __post_init__(self) -> None:
        if (
            self.metric_observation_count < 1_000
            or self.metric_recompute_sample_count < 10
            or self.metric_recompute_p95_seconds_max > 30
        ):
            raise PerformanceProfileError("metric computation target cannot be weakened")


@dataclass(frozen=True)
class CorrectnessTargets:
    cross_project_reads_max: int = 0
    duplicate_terminal_states_max: int = 0
    lost_outbox_messages_max: int = 0
    hash_mismatches_max: int = 0

    def __post_init__(self) -> None:
        if any(asdict(self).values()):
            raise PerformanceProfileError("correctness error budgets must remain zero")


@dataclass(frozen=True)
class PerformanceProfile:
    schema_version: str
    profile_id: str
    included_workstreams: tuple[str, ...]
    excluded_workstreams: tuple[str, ...]
    excluded_dimensions: Mapping[str, str]
    replay_external_calls: bool
    project_load: ProjectLoad
    provider_sampling: ProviderSamplingLoad
    synthetic_lab: SyntheticLabLoad
    process_topology: ProcessTopology
    api_targets: ApiTargets
    queue_targets: QueueTargets
    computation_targets: ComputationTargets
    correctness_targets: CorrectnessTargets
    profile_hash: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "geo-performance-profile-v1":
            raise PerformanceProfileError("unsupported performance profile schema")
        if tuple(self.included_workstreams) != ("A", "C", "D"):
            raise PerformanceProfileError("non-B profile must cover exactly A, C, and D")
        if tuple(self.excluded_workstreams) != ("B",):
            raise PerformanceProfileError("workstream B must remain explicitly excluded")
        required_exclusions = {
            "connector_sync",
            "consumer_ui_browser_capture",
            "page_artifact_bundle",
            "browser_capture_worker",
        }
        if set(self.excluded_dimensions) != required_exclusions:
            raise PerformanceProfileError("all B-owned load dimensions need explicit exclusions")
        if any(not reason.strip() for reason in self.excluded_dimensions.values()):
            raise PerformanceProfileError("excluded dimensions require a concrete scope reason")
        if not self.replay_external_calls:
            raise PerformanceProfileError("load tests must not consume live provider quotas")
        if self.profile_hash is not None and self.profile_hash != self.calculate_hash():
            raise PerformanceProfileError("performance profile hash does not match its content")

    def calculate_hash(self) -> str:
        payload = asdict(self)
        payload.pop("profile_hash", None)
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def with_hash(self) -> "PerformanceProfile":
        return replace(self, profile_hash=self.calculate_hash())


def non_b_performance_profile_v1() -> PerformanceProfile:
    return PerformanceProfile(
        schema_version="geo-performance-profile-v1",
        profile_id="performance-profile-v1-non-b",
        included_workstreams=("A", "C", "D"),
        excluded_workstreams=("B",),
        excluded_dimensions={
            "connector_sync": "owned by excluded Workstream B",
            "consumer_ui_browser_capture": "owned by excluded Workstream B",
            "page_artifact_bundle": "roadmap target is specific to excluded browser capture",
            "browser_capture_worker": "owned by excluded Workstream B",
        },
        replay_external_calls=True,
        project_load=ProjectLoad(total_projects=10, concurrently_active=4),
        provider_sampling=ProviderSamplingLoad(
            concurrent_runs=4,
            planned_tasks_per_run=1_000,
            concurrently_eligible_tasks=400,
        ),
        synthetic_lab=SyntheticLabLoad(
            style_channels=9,
            approved_samples_per_channel=200,
            fixed_cases_per_channel=40,
            candidates_per_case=4,
            experiment_arms=3,
            repeats_per_question_per_arm=10,
        ),
        process_topology=ProcessTopology(
            task_workers=4,
            style_browser_workers=1,
            outbox_relays=1,
            fixed_resource_limits_required=True,
            api_database_pool_max_size=10,
            resource_limits=FROZEN_RUNTIME_RESOURCE_LIMITS,
        ),
        api_targets=ApiTargets(
            duration_minutes=30,
            read_rps=20,
            write_rps=5,
            read_p95_ms_max=500,
            write_p95_ms_max=800,
            overall_p99_ms_max=2_000,
            unexpected_5xx_percent_max="1.0",
        ),
        queue_targets=QueueTargets(
            eligible_dispatch_p95_seconds_max=60,
            queue_age_seconds_max=300,
            outbox_publish_p95_seconds_max=5,
            drain_seconds_max=600,
        ),
        computation_targets=ComputationTargets(
            metric_observation_count=1_000,
            metric_recompute_sample_count=10,
            metric_recompute_p95_seconds_max=30,
        ),
        correctness_targets=CorrectnessTargets(),
    ).with_hash()
