from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from geo_core.engineering.performance_profile import (
    PerformanceProfileError,
    non_b_performance_profile_v1,
)
from geo_core.engineering.performance_result import (
    CorrectnessMeasurement,
    LatencyDistribution,
    PerformanceRunResult,
    ResourceWatermark,
    RuntimeTopologyMeasurement,
    SamplingRunMeasurement,
    StyleChannelMeasurement,
    evaluate_performance_run,
)
from geo_core.engineering.performance_workload import non_b_performance_workload_v1
from scripts.roadmap_performance_result import export_schema, verify_result


def _distribution(count: int, *, p95: float = 100, p99: float = 150) -> LatencyDistribution:
    normalized_p99 = max(p95, p99)
    return LatencyDistribution(count, 50, p95, normalized_p99, max(normalized_p99, 200))


def _accepted_result() -> PerformanceRunResult:
    profile = non_b_performance_profile_v1()
    workload = non_b_performance_workload_v1(profile)
    limits = profile.process_topology.resource_limits
    return PerformanceRunResult(
        schema_version="geo-performance-result-v1",
        run_id="performance-2026-07-23",
        profile_id=profile.profile_id,
        profile_hash=profile.profile_hash or "",
        workload_id=workload.workload_id,
        workload_hash=workload.workload_hash or "",
        environment_fingerprint="a" * 64,
        started_at=datetime(2026, 7, 23, tzinfo=UTC),
        finished_at=datetime(2026, 7, 23, tzinfo=UTC) + timedelta(minutes=30),
        api_load_duration_seconds=1_800,
        diagnostic_only=False,
        project_count=10,
        concurrently_active_projects=4,
        sampling_planned_tasks=4_000,
        sampling_terminal_tasks=4_000,
        sampling_peak_eligible_tasks=400,
        sampling_runs=tuple(
            SamplingRunMeasurement(
                run_id=run.run_id,
                project_id=run.project_id,
                provider=run.provider,
                planned_tasks=run.planned_task_count,
                terminal_tasks=run.planned_task_count,
                peak_eligible_tasks=run.immediately_eligible_task_count,
                dispatch_latency=_distribution(run.planned_task_count, p95=60_000, p99=60_000),
            )
            for run in workload.sampling_runs
        ),
        style_channel_count=9,
        style_approved_sample_count=1_800,
        style_fixed_case_count=360,
        style_candidate_count=1_440,
        offline_experiment_slot_count=10_800,
        style_channels=tuple(
            StyleChannelMeasurement(
                channel=channel,
                approved_sample_count=200,
                fixed_case_count=40,
                candidate_count=160,
                offline_experiment_slot_count=1_200,
            )
            for channel in workload.synthetic.channels
        ),
        read_latency=_distribution(36_000, p95=500),
        write_latency=_distribution(9_000, p95=800, p99=900),
        overall_latency=_distribution(45_000, p95=800, p99=2_000),
        unexpected_5xx_count=449,
        dispatch_latency=_distribution(4_000, p95=60_000, p99=60_000),
        outbox_publish_latency=_distribution(4_000, p95=5_000, p99=5_000),
        maximum_queue_age_seconds=300,
        drain_seconds=600,
        metric_observation_count=1_000,
        metric_recompute_latency=_distribution(10, p95=30_000, p99=30_000),
        topology=RuntimeTopologyMeasurement(
            task_workers=4,
            style_browser_workers=1,
            outbox_relays=1,
            api_database_pool_max_size=10,
            resource_limits=limits,
        ),
        resource_watermarks=tuple(
            ResourceWatermark(
                service=name,
                cpu_peak_cores=float(values["cpus"]),
                memory_peak_bytes=int(values["memory"][:-1])
                * {"M": 1024**2, "G": 1024**3}[values["memory"][-1]],
            )
            for name, values in limits.items()
        ),
        correctness=CorrectnessMeasurement(0, 0, 0, 0),
        raw_report_uri="s3://geo-artifacts/performance/run/report.json",
        raw_report_sha256="b" * 64,
    )


def test_complete_boundary_run_is_accepted() -> None:
    decision = evaluate_performance_run(_accepted_result())

    assert decision.accepted is True
    assert decision.failed_checks == ()


def test_diagnostic_or_weakened_run_cannot_pass() -> None:
    result = replace(
        _accepted_result(),
        diagnostic_only=True,
        sampling_terminal_tasks=3_999,
        unexpected_5xx_count=450,
    )

    decision = evaluate_performance_run(result)

    assert decision.accepted is False
    assert decision.failed_checks == (
        "diagnostic_run",
        "sampling_not_terminal",
        "sampling_terminal_total_mismatch",
        "unexpected_5xx_budget_exceeded",
    )


def test_requests_cannot_be_diluted_across_a_longer_claimed_load_window() -> None:
    result = replace(
        _accepted_result(),
        finished_at=datetime(2026, 7, 23, tzinfo=UTC) + timedelta(minutes=60),
        api_load_duration_seconds=3_600,
    )

    decision = evaluate_performance_run(result)

    assert "read_request_load_low" in decision.failed_checks
    assert "write_request_load_low" in decision.failed_checks


def test_outbox_and_metric_percentiles_require_the_frozen_sample_load() -> None:
    accepted = _accepted_result()
    result = replace(
        accepted,
        outbox_publish_latency=replace(accepted.outbox_publish_latency, sample_count=1),
        metric_recompute_latency=replace(accepted.metric_recompute_latency, sample_count=1),
    )

    decision = evaluate_performance_run(result)

    assert "outbox_sample_load_low" in decision.failed_checks
    assert "metric_recompute_sample_load_low" in decision.failed_checks


def test_missing_style_worker_and_resource_watermark_fail_closed() -> None:
    result = _accepted_result()
    result = replace(
        result,
        topology=replace(result.topology, style_browser_workers=0),
        resource_watermarks=result.resource_watermarks[:-1],
    )

    decision = evaluate_performance_run(result)

    assert "style_browser_topology_mismatch" in decision.failed_checks
    assert "resource_watermarks_incomplete" in decision.failed_checks


def test_aggregate_counts_cannot_hide_a_missing_provider_or_style_channel() -> None:
    accepted = _accepted_result()
    sampling = list(accepted.sampling_runs)
    sampling[0] = replace(sampling[0], terminal_tasks=999)
    sampling[1] = replace(sampling[1], terminal_tasks=1_001, planned_tasks=1_001)
    styles = list(accepted.style_channels)
    styles[0] = replace(styles[0], approved_sample_count=0)
    styles[1] = replace(styles[1], approved_sample_count=400)
    result = replace(accepted, sampling_runs=tuple(sampling), style_channels=tuple(styles))

    decision = evaluate_performance_run(result)

    assert any(item.endswith(":not_terminal") for item in decision.failed_checks)
    assert any(item.endswith(":planned_mismatch") for item in decision.failed_checks)
    assert "style_channel:owned_site:sample_load_low" in decision.failed_checks


def test_aggregate_and_per_dimension_measurements_must_reconcile() -> None:
    accepted = _accepted_result()
    result = replace(
        accepted,
        sampling_planned_tasks=4_001,
        style_fixed_case_count=361,
    )

    decision = evaluate_performance_run(result)

    assert "sampling_planned_total_mismatch" in decision.failed_checks
    assert "style_case_total_mismatch" in decision.failed_checks


def test_result_file_cannot_self_declare_acceptance(tmp_path: Path) -> None:
    payload = asdict(_accepted_result())
    payload["accepted"] = True
    path = tmp_path / "result.json"
    path.write_text(json.dumps(payload, default=str), encoding="utf-8")

    with pytest.raises(PerformanceProfileError, match="cannot declare"):
        verify_result(path)


def test_result_file_rejects_unknown_nested_measurement_fields(tmp_path: Path) -> None:
    payload = asdict(_accepted_result())
    payload["sampling_runs"][0]["claimed_accepted"] = True
    path = tmp_path / "result.json"
    path.write_text(json.dumps(payload, default=str), encoding="utf-8")

    with pytest.raises(PerformanceProfileError, match="unknown fields.*sampling_runs"):
        verify_result(path)


def test_checked_in_result_schema_is_current_and_closed(tmp_path: Path) -> None:
    generated = tmp_path / "schema.json"
    export_schema(generated)
    checked_in = (
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "roadmap"
        / "performance-result-v1.schema.json"
    )

    assert generated.read_bytes() == checked_in.read_bytes()
    schema = json.loads(generated.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert all(
        definition.get("additionalProperties") is False
        for definition in schema["$defs"].values()
        if definition.get("type") == "object"
    )
