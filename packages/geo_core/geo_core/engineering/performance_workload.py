"""Deterministic workload identities for the frozen non-B performance profile."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from typing import Iterator
from uuid import UUID, uuid5

from geo_core.engineering.performance_profile import (
    PerformanceProfile,
    PerformanceProfileError,
    non_b_performance_profile_v1,
)


WORKLOAD_NAMESPACE = UUID("a4dcfe30-460b-5a26-b0d7-78f0624cb901")
STYLE_CHANNELS = (
    "owned_site",
    "amazon",
    "youtube",
    "tiktok",
    "instagram",
    "productreview",
    "reddit",
    "ozbargain",
    "quora",
)
_RUN_SURFACES = (
    ("openai", "web_search", "provider_api"),
    ("gemini", "google_search_grounding", "provider_api"),
    ("perplexity", "sonar", "provider_api"),
    ("microsoft", "bing_grounding", "proxy_grounded_api"),
)


@dataclass(frozen=True)
class LoadProject:
    project_id: UUID
    ordinal: int
    concurrently_active: bool


@dataclass(frozen=True)
class SamplingReplayRun:
    run_id: UUID
    project_id: UUID
    provider: str
    surface: str
    capture_method: str
    planned_task_count: int
    immediately_eligible_task_count: int
    replay_fixture_id: str

    def __post_init__(self) -> None:
        if self.capture_method not in {"provider_api", "proxy_grounded_api"}:
            raise PerformanceProfileError("performance replay cannot include UI capture")
        if self.planned_task_count != 1_000:
            raise PerformanceProfileError("each frozen replay Run requires 1,000 Tasks")
        if self.immediately_eligible_task_count != 100:
            raise PerformanceProfileError("each replay Run requires 100 immediately eligible Tasks")
        if not self.replay_fixture_id.startswith("recording:"):
            raise PerformanceProfileError("performance providers must use frozen recordings")


@dataclass(frozen=True)
class SyntheticReplayLoad:
    channels: tuple[str, ...]
    approved_samples_per_channel: int
    fixed_cases_per_channel: int
    candidates_per_case: int
    experiment_arms: int
    repeats_per_question_per_arm: int


@dataclass(frozen=True)
class ApiReplaySchedule:
    duration_seconds: int
    read_rps: int
    write_rps: int
    total_read_requests: int
    total_write_requests: int


@dataclass(frozen=True)
class SamplingReplayTask:
    task_id: UUID
    run_id: UUID
    project_id: UUID
    ordinal: int
    question_ordinal: int
    repetition: int
    eligible_wave: int
    capture_method: str


@dataclass(frozen=True)
class NonBPerformanceWorkload:
    schema_version: str
    workload_id: str
    performance_profile_hash: str
    projects: tuple[LoadProject, ...]
    sampling_runs: tuple[SamplingReplayRun, ...]
    synthetic: SyntheticReplayLoad
    api_schedule: ApiReplaySchedule
    included_workstreams: tuple[str, ...]
    excluded_workstreams: tuple[str, ...]
    external_call_mode: str
    workload_hash: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "geo-performance-workload-v1":
            raise PerformanceProfileError("unsupported performance workload schema")
        if self.included_workstreams != ("A", "C", "D") or self.excluded_workstreams != (
            "B",
        ):
            raise PerformanceProfileError("performance workload scope must be exactly non-B")
        if self.external_call_mode != "frozen_recording_replay":
            raise PerformanceProfileError("performance workload cannot make live provider calls")
        if len(self.projects) != 10 or sum(item.concurrently_active for item in self.projects) != 4:
            raise PerformanceProfileError("performance workload requires 10/4 Project topology")
        if len({item.project_id for item in self.projects}) != len(self.projects):
            raise PerformanceProfileError("performance Project identities must be unique")
        if len(self.sampling_runs) != 4:
            raise PerformanceProfileError("performance workload requires four concurrent Runs")
        if sum(item.planned_task_count for item in self.sampling_runs) != 4_000:
            raise PerformanceProfileError("performance workload requires 4,000 planned Tasks")
        if sum(item.immediately_eligible_task_count for item in self.sampling_runs) != 400:
            raise PerformanceProfileError("performance workload requires 400 eligible Tasks")
        active_ids = {item.project_id for item in self.projects if item.concurrently_active}
        if {item.project_id for item in self.sampling_runs} != active_ids:
            raise PerformanceProfileError("each active Project must own one Sampling Run")
        if self.synthetic.channels != STYLE_CHANNELS:
            raise PerformanceProfileError("synthetic workload must freeze all nine channels")
        if self.workload_hash is not None and self.workload_hash != self.calculate_hash():
            raise PerformanceProfileError("performance workload hash does not match its content")

    def calculate_hash(self) -> str:
        value = asdict(self)
        value.pop("workload_hash", None)
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("ascii")).hexdigest()

    def with_hash(self) -> "NonBPerformanceWorkload":
        return replace(self, workload_hash=self.calculate_hash())

    def sampling_tasks(self) -> Iterator[SamplingReplayTask]:
        for run in self.sampling_runs:
            for ordinal in range(1, run.planned_task_count + 1):
                zero_based = ordinal - 1
                yield SamplingReplayTask(
                    task_id=uuid5(WORKLOAD_NAMESPACE, f"{run.run_id}:task:{ordinal}"),
                    run_id=run.run_id,
                    project_id=run.project_id,
                    ordinal=ordinal,
                    question_ordinal=(zero_based // 10) + 1,
                    repetition=(zero_based % 10) + 1,
                    eligible_wave=zero_based // run.immediately_eligible_task_count,
                    capture_method=run.capture_method,
                )


def non_b_performance_workload_v1(
    profile: PerformanceProfile | None = None,
) -> NonBPerformanceWorkload:
    frozen = profile or non_b_performance_profile_v1()
    expected = non_b_performance_profile_v1()
    if frozen.profile_hash != expected.profile_hash:
        raise PerformanceProfileError("workload generator requires the exact frozen v1 profile")
    projects = tuple(
        LoadProject(
            project_id=uuid5(WORKLOAD_NAMESPACE, f"{frozen.profile_hash}:project:{ordinal}"),
            ordinal=ordinal,
            concurrently_active=ordinal <= 4,
        )
        for ordinal in range(1, 11)
    )
    runs = tuple(
        SamplingReplayRun(
            run_id=uuid5(WORKLOAD_NAMESPACE, f"{frozen.profile_hash}:run:{ordinal}"),
            project_id=projects[ordinal - 1].project_id,
            provider=provider,
            surface=surface,
            capture_method=capture_method,
            planned_task_count=1_000,
            immediately_eligible_task_count=100,
            replay_fixture_id=f"recording:{provider}:performance-v1",
        )
        for ordinal, (provider, surface, capture_method) in enumerate(_RUN_SURFACES, start=1)
    )
    duration_seconds = frozen.api_targets.duration_minutes * 60
    return NonBPerformanceWorkload(
        schema_version="geo-performance-workload-v1",
        workload_id="performance-workload-v1-non-b",
        performance_profile_hash=frozen.profile_hash or "",
        projects=projects,
        sampling_runs=runs,
        synthetic=SyntheticReplayLoad(
            channels=STYLE_CHANNELS,
            approved_samples_per_channel=frozen.synthetic_lab.approved_samples_per_channel,
            fixed_cases_per_channel=frozen.synthetic_lab.fixed_cases_per_channel,
            candidates_per_case=frozen.synthetic_lab.candidates_per_case,
            experiment_arms=frozen.synthetic_lab.experiment_arms,
            repeats_per_question_per_arm=frozen.synthetic_lab.repeats_per_question_per_arm,
        ),
        api_schedule=ApiReplaySchedule(
            duration_seconds=duration_seconds,
            read_rps=frozen.api_targets.read_rps,
            write_rps=frozen.api_targets.write_rps,
            total_read_requests=duration_seconds * frozen.api_targets.read_rps,
            total_write_requests=duration_seconds * frozen.api_targets.write_rps,
        ),
        included_workstreams=("A", "C", "D"),
        excluded_workstreams=("B",),
        external_call_mode="frozen_recording_replay",
    ).with_hash()


__all__ = [
    "ApiReplaySchedule",
    "LoadProject",
    "NonBPerformanceWorkload",
    "SamplingReplayRun",
    "SamplingReplayTask",
    "SyntheticReplayLoad",
    "non_b_performance_workload_v1",
]
