from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from benchmarks.f019.adapters import (
    DeterministicBaselineAdapter,
    graphrag_adapter,
    llamaindex_adapter,
)
from benchmarks.f019.dataset import load_dataset
from benchmarks.f019.runner import run_candidate, write_report
from benchmarks.f019.scoring import score_candidate, select_candidate


def test_deterministic_fixture_baseline_executes_offline_and_passes_harness_gate(
    tmp_path: Path,
) -> None:
    report = run_candidate(DeterministicBaselineAdapter())
    destination = tmp_path / "report.json"
    write_report(report, destination)
    persisted = json.loads(destination.read_text(encoding="utf-8"))

    assert persisted["status"] == "passed"
    assert persisted["selection_status"] == "harness_reference_only"
    assert persisted["candidate"]["eligible_for_selection"] is False
    assert all(persisted["gates"].values())
    assert persisted["quality_score"] == 1.0
    assert persisted["metrics"]["fact_precision_diagnostic"] == 1.0
    assert persisted["metrics"]["fact_recall_diagnostic"] == 1.0
    assert persisted["metrics"]["duplicate_count"] == 0
    assert persisted["metrics"]["orphan_count"] == 0
    assert persisted["metrics"]["regression_count"] == 0
    assert persisted["usage"]["model_calls"] == 0
    assert persisted["cost_time_policy"] == "record_only_no_hard_cap"
    assert select_candidate([persisted])["selected_candidate_id"] is None


def test_missing_framework_dependencies_are_unavailable_without_fake_scores(monkeypatch) -> None:
    monkeypatch.setattr(
        "benchmarks.f019.adapters.importlib.util.find_spec", lambda _name: None
    )

    for adapter in (llamaindex_adapter(), graphrag_adapter()):
        report = run_candidate(adapter)
        assert report["status"] == "unavailable"
        assert report["selection_status"] == "not_selectable_unavailable"
        assert report["metrics"] is None
        assert report["gates"] is None
        assert report["quality_score"] is None
        assert report["usage"] is None
        assert report["raw_candidate_output"]["base"] is None
        assert report["raw_candidate_output"]["delta"] is None

    graph_report = run_candidate(graphrag_adapter())
    assert graph_report["candidate"]["eligible_for_selection"] is False


def test_installed_framework_without_executor_is_still_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "benchmarks.f019.adapters.importlib.util.find_spec", lambda _name: object()
    )
    monkeypatch.setattr(
        "benchmarks.f019.adapters.importlib.metadata.version", lambda _name: "pinned-test"
    )

    report = run_candidate(llamaindex_adapter())

    assert report["status"] == "unavailable"
    assert report["candidate"]["framework_version"] == "llama-index-core-pinned-test"
    assert report["candidate"]["unavailable_reason"] == "model_invoker_not_configured"
    assert report["quality_score"] is None


def test_project_leakage_is_a_hard_failure() -> None:
    dataset = load_dataset()
    run = DeterministicBaselineAdapter().run(dataset.documents, dataset.delta_operations)
    assert run.base is not None
    leaked_fact = replace(run.base.facts[0], project_id="project-boreal")
    leaked_base = replace(run.base, facts=(leaked_fact, *run.base.facts[1:]))

    report = score_candidate(replace(run, base=leaked_base), dataset)

    assert report["status"] == "failed"
    assert report["gates"]["project_leakage"] is False
    assert report["metrics"]["project_leakage_count"] > 0


def test_approval_bypass_and_publishable_simulation_are_hard_failures() -> None:
    dataset = load_dataset()
    run = DeterministicBaselineAdapter().run(dataset.documents, dataset.delta_operations)
    assert run.base is not None
    approved_fact = replace(
        run.base.facts[0],
        control=replace(
            run.base.facts[0].control,
            workflow_status="approved",
            requires_human_approval=False,
        ),
    )
    publishable_simulation = replace(
        run.base.simulations[0], test_only=False, publication_eligible=True
    )
    unsafe_base = replace(
        run.base,
        facts=(approved_fact, *run.base.facts[1:]),
        simulations=(publishable_simulation, *run.base.simulations[1:]),
    )

    report = score_candidate(replace(run, base=unsafe_base), dataset)

    assert report["status"] == "failed"
    assert report["gates"]["approval_bypass"] is False
    assert report["gates"]["test_only_publication"] is False


def test_exact_five_percent_unsupported_questions_remains_inside_gate() -> None:
    dataset = load_dataset()
    run = DeterministicBaselineAdapter().run(dataset.documents, dataset.delta_operations)
    assert run.base is not None
    questions = list(run.base.questions)
    questions[0] = replace(questions[0], source_fact_ids=())
    questions[1] = replace(questions[1], source_fact_ids=())

    report = score_candidate(replace(run, base=replace(run.base, questions=tuple(questions))), dataset)

    assert report["metrics"]["unsupported_question_rate"] == 0.05
    assert report["gates"]["unsupported_question_rate"] is True
    assert report["status"] == "passed"


def test_incremental_duplicate_is_a_hard_failure() -> None:
    dataset = load_dataset()
    run = DeterministicBaselineAdapter().run(dataset.documents, dataset.delta_operations)
    assert run.delta is not None
    duplicated_delta = replace(run.delta, facts=(*run.delta.facts, run.delta.facts[0]))

    report = score_candidate(replace(run, delta=duplicated_delta), dataset)

    assert report["status"] == "failed"
    assert report["gates"]["incremental_duplicate"] is False
    assert report["metrics"]["duplicate_count"] == 1


def test_selection_uses_quality_before_unbounded_cost() -> None:
    expensive = _selection_report(
        "higher-quality", "project", quality=0.96, cost=1_000_000.0, duration=99_000_000
    )
    cheap = _selection_report("lower-quality", "llamaindex", quality=0.93, cost=0.01, duration=1)

    selection = select_candidate([cheap, expensive])

    assert selection["selected_candidate_id"] == "higher-quality"
    assert selection["reason"] == "quality_margin_at_least_2pp"


def test_exactly_two_percentage_points_is_not_a_cost_time_tie() -> None:
    expensive = _selection_report(
        "higher-quality", "project", quality=0.97, cost=1_000_000.0, duration=99_000_000
    )
    cheap = _selection_report("lower-quality", "llamaindex", quality=0.95, cost=0.01, duration=1)

    assert select_candidate([cheap, expensive])["selected_candidate_id"] == "higher-quality"


def test_selection_compares_cost_then_time_only_inside_two_percentage_points() -> None:
    costly = _selection_report("costly", "project", quality=0.95, cost=20.0, duration=10)
    cheap = _selection_report("cheap", "project", quality=0.94, cost=2.0, duration=500)
    same_cost_slow = _selection_report(
        "same-cost-slow", "project", quality=0.95, cost=2.0, duration=900
    )

    assert select_candidate([costly, cheap])["selected_candidate_id"] == "cheap"
    assert select_candidate([same_cost_slow, cheap])["selected_candidate_id"] == "cheap"


def test_selection_prefers_llamaindex_only_after_quality_cost_and_time_tie() -> None:
    project = _selection_report("project", "project", quality=0.95, cost=2.0, duration=20)
    llamaindex = _selection_report(
        "llamaindex", "llamaindex", quality=0.95, cost=2.0, duration=20
    )

    selection = select_candidate([project, llamaindex])

    assert selection["selected_candidate_id"] == "llamaindex"
    assert selection["reason"] == "quality_within_2pp_then_cost_time_then_llamaindex"


def _selection_report(
    candidate_id: str,
    adapter_kind: str,
    *,
    quality: float,
    cost: float,
    duration: int,
) -> dict[str, object]:
    return {
        "candidate": {
            "candidate_id": candidate_id,
            "adapter_kind": adapter_kind,
            "eligible_for_selection": True,
        },
        "status": "passed",
        "quality_score": quality,
        "usage": {"estimated_cost_usd": cost, "wall_clock_ms": duration},
    }
