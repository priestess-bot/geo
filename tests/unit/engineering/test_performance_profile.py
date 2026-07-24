from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from geo_core.engineering.performance_profile import (
    ApiTargets,
    FROZEN_RUNTIME_RESOURCE_LIMITS,
    PerformanceProfileError,
    ProcessTopology,
    ProviderSamplingLoad,
    non_b_performance_profile_v1,
)
from scripts.roadmap_performance_profile import export_profile, verify_profile


def test_non_b_profile_freezes_full_applicable_roadmap_load() -> None:
    profile = non_b_performance_profile_v1()

    assert profile.included_workstreams == ("A", "C", "D")
    assert profile.excluded_workstreams == ("B",)
    assert profile.provider_sampling.total_planned_tasks == 4_000
    assert profile.synthetic_lab.fixed_case_count == 360
    assert profile.synthetic_lab.approved_samples_per_channel == 200
    assert profile.replay_external_calls is True
    assert profile.process_topology.api_database_pool_max_size == 10
    assert profile.process_topology.style_browser_workers == 1
    assert profile.process_topology.resource_limits == FROZEN_RUNTIME_RESOURCE_LIMITS
    assert len(profile.profile_hash or "") == 64


def test_profile_rejects_a_diagnostic_sampling_load_as_acceptance() -> None:
    with pytest.raises(PerformanceProfileError, match="cannot be lower"):
        ProviderSamplingLoad(
            concurrent_runs=1,
            planned_tasks_per_run=100,
            concurrently_eligible_tasks=10,
        )


def test_api_target_checks_each_load_dimension_independently() -> None:
    with pytest.raises(PerformanceProfileError, match="API load"):
        ApiTargets(
            duration_minutes=31,
            read_rps=1,
            write_rps=5,
            read_p95_ms_max=500,
            write_p95_ms_max=800,
            overall_p99_ms_max=2_000,
            unexpected_5xx_percent_max="1.0",
        )


def test_process_topology_rejects_missing_or_changed_resource_limits() -> None:
    incomplete = dict(FROZEN_RUNTIME_RESOURCE_LIMITS)
    incomplete.pop("outbox-relay")
    with pytest.raises(PerformanceProfileError, match="CPU and memory"):
        ProcessTopology(
            task_workers=4,
            style_browser_workers=1,
            outbox_relays=1,
            fixed_resource_limits_required=True,
            api_database_pool_max_size=10,
            resource_limits=incomplete,
        )

    with pytest.raises(PerformanceProfileError, match="DB pool"):
        ProcessTopology(
            task_workers=4,
            style_browser_workers=1,
            outbox_relays=1,
            fixed_resource_limits_required=True,
            api_database_pool_max_size=20,
            resource_limits=FROZEN_RUNTIME_RESOURCE_LIMITS,
        )


def test_checked_in_profile_is_current_and_hash_verified(tmp_path: Path) -> None:
    generated = tmp_path / "profile.json"
    export_profile(generated)
    checked_in = (
        Path(__file__).resolve().parents[3]
        / "benchmarks"
        / "roadmap"
        / "performance-profile-v1-non-b.json"
    )

    assert generated.read_bytes() == checked_in.read_bytes()
    assert verify_profile(checked_in).profile_hash == non_b_performance_profile_v1().profile_hash


def test_profile_hash_detects_scope_tampering(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    export_profile(profile_path)
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    payload["project_load"]["total_projects"] = 11
    profile_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PerformanceProfileError, match="invalid performance profile"):
        verify_profile(profile_path)


def test_rehashed_profile_still_cannot_redefine_frozen_v1(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    export_profile(profile_path)
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    payload["process_topology"]["task_workers"] = 5
    unsigned = dict(payload)
    unsigned.pop("profile_hash")
    canonical = json.dumps(unsigned, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    payload["profile_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    profile_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PerformanceProfileError, match="differs from frozen v1"):
        verify_profile(profile_path)
