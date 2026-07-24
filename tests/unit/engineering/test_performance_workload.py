from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from geo_core.engineering.performance_profile import PerformanceProfileError
from geo_core.engineering.performance_workload import non_b_performance_workload_v1
from scripts.roadmap_performance_workload import export_workload, verify_workload


def test_workload_expands_exact_task_and_concurrency_contract() -> None:
    workload = non_b_performance_workload_v1()
    tasks = tuple(workload.sampling_tasks())

    assert len(tasks) == 4_000
    assert len({item.task_id for item in tasks}) == 4_000
    assert sum(item.eligible_wave == 0 for item in tasks) == 400
    assert {item.capture_method for item in tasks} == {
        "provider_api",
        "proxy_grounded_api",
    }
    assert all(item.question_ordinal <= 100 for item in tasks)
    assert all(1 <= item.repetition <= 10 for item in tasks)


def test_workload_freezes_non_b_synthetic_and_api_volume() -> None:
    workload = non_b_performance_workload_v1()

    assert workload.synthetic.channels == (
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
    assert workload.synthetic.approved_samples_per_channel == 200
    assert workload.api_schedule.total_read_requests == 36_000
    assert workload.api_schedule.total_write_requests == 9_000
    assert workload.external_call_mode == "frozen_recording_replay"


def test_workload_rejects_ui_capture_or_reduced_eligible_set() -> None:
    workload = non_b_performance_workload_v1()
    run = workload.sampling_runs[0]
    with pytest.raises(PerformanceProfileError, match="UI capture"):
        replace(run, capture_method="automated_ui")
    with pytest.raises(PerformanceProfileError, match="100 immediately"):
        replace(run, immediately_eligible_task_count=99)


def test_checked_in_workload_is_exact_and_hash_protected(tmp_path: Path) -> None:
    generated = tmp_path / "workload.json"
    export_workload(generated)
    checked_in = (
        Path(__file__).resolve().parents[3]
        / "benchmarks"
        / "roadmap"
        / "performance-workload-v1-non-b.json"
    )

    assert generated.read_bytes() == checked_in.read_bytes()
    assert verify_workload(checked_in)["planned_task_count"] == 4_000

    payload = json.loads(generated.read_text(encoding="ascii"))
    payload["sampling_runs"][0]["planned_task_count"] = 999
    generated.write_text(json.dumps(payload), encoding="ascii")
    with pytest.raises(PerformanceProfileError, match="differs"):
        verify_workload(generated)
