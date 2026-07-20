from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from benchmarks.f019.selection import build_selection_manifest, write_selection_manifest
from geo_core.rag.selection import RagSelectionError, load_rag_selection


ROOT = Path(__file__).resolve().parents[3]


def test_checked_in_selection_records_final_auditable_decision() -> None:
    manifest = json.loads(
        (ROOT / "benchmarks/f019/selection.json").read_text(encoding="utf-8")
    )

    assert manifest["status"] == "selected"
    assert manifest["selected"]["candidate_id"] == "project-native-rag-v1"
    assert manifest["selected"]["reason"] == (
        "project_owned_domain_boundary_and_business_source_of_truth_with_equal_quality"
    )
    assert manifest["policy"]["cost_time_policy"] == "record_only_no_hard_cap"
    comparison = manifest["decision_basis"]["recorded_resource_comparison"]
    assert comparison["project_native"] == {
        "estimated_cost_usd": 0.01015448,
        "model_calls": 44,
        "total_tokens": 45606,
        "wall_clock_ms": 270218,
    }
    assert comparison["llamaindex"] == {
        "estimated_cost_usd": 0.01846698,
        "model_calls": 66,
        "total_tokens": 84235,
        "wall_clock_ms": 384035,
    }
    assert comparison["project_native_reduction_vs_llamaindex"] == {
        "estimated_cost_percent": 45.0128,
        "estimated_cost_usd": 0.0083125,
        "model_calls": 22,
        "model_calls_percent": 33.3333,
        "total_tokens": 38629,
        "total_tokens_percent": 45.8586,
        "wall_clock_ms": 113817,
        "wall_clock_percent": 29.6371,
    }
    assert manifest["qualified_fallbacks"][0]["candidate_id"] == (
        "llamaindex-property-graph-v1"
    )


def test_selection_is_hash_addressed_and_runtime_fails_closed_on_tamper(tmp_path: Path) -> None:
    reports = _reports(tmp_path, llama_available=True)
    selection_path = tmp_path / "selection.json"
    manifest = build_selection_manifest(
        reports,
        selection_path=selection_path,
        generated_at=datetime(2026, 7, 19, tzinfo=UTC),
    )
    write_selection_manifest(manifest, selection_path)

    assert manifest["status"] == "selected"
    assert manifest["selected"]["candidate_id"] == "project-native-rag-v1"
    assert manifest["selected"]["reason"] == (
        "project_owned_domain_boundary_and_business_source_of_truth_with_equal_quality"
    )
    assert manifest["selected"]["selection_algorithm_reason"] == (
        "quality_within_2pp_then_cost_time_then_llamaindex"
    )
    assert manifest["decision_basis"]["domain_boundary"] == {
        "stable_contract_owner": "geo_core.rag.contracts",
        "selected_runtime": "project_owned_adapter",
        "framework_adapter_policy": "optional_adapter_only",
        "framework_objects_cross_domain_or_stable_api": False,
    }
    assert manifest["decision_basis"]["business_source_of_truth"][
        "framework_owned_business_state"
    ] is False
    assert manifest["decision_basis"]["recorded_resource_comparison"]["policy"] == (
        "record_only_no_hard_cap"
    )
    assert manifest["qualified_fallbacks"][0]["candidate_id"] == (
        "llamaindex-property-graph-v1"
    )
    assert manifest["qualified_fallbacks"][0]["activation_requires"] == (
        "new_hash_addressed_reselection_manifest"
    )
    assert manifest["failed_or_dropped_evidence"]["hard_gate_failed_candidates"] == []
    assert manifest["failed_or_dropped_evidence"]["formal_candidate_validation"] == {
        "project-native": {"dropped_candidate_count": 0, "failure_stage": None},
        "llamaindex": {"dropped_candidate_count": 0, "failure_stage": None},
    }
    dispositions = {item["name"]: item["disposition"] for item in manifest["candidates"]}
    assert dispositions == {
        "deterministic": "harness_reference_only",
        "project-native": "selected",
        "llamaindex": "qualified_fallback",
        "graphrag": "unavailable_not_evaluated",
    }
    selected = load_rag_selection(selection_path)
    assert selected.adapter_release == "project-native-rag-v1"

    reports["project-native"].write_text("{}\n", encoding="utf-8")
    with pytest.raises(RagSelectionError, match="missing or has changed"):
        load_rag_selection(selection_path)


def test_llamaindex_absence_is_not_sufficient_to_select_native(tmp_path: Path) -> None:
    reports = _reports(tmp_path, llama_available=False)
    manifest = build_selection_manifest(reports, selection_path=tmp_path / "selection.json")

    assert manifest["status"] == "not_selected"
    assert manifest["selected"] is None
    assert manifest["comparison_note"] == "llamaindex_unavailable_not_a_quality_failure"


def test_incomplete_paid_usage_evidence_fails_selection_closed(tmp_path: Path) -> None:
    reports = _reports(tmp_path, llama_available=True)
    llama_report = json.loads(reports["llamaindex"].read_text(encoding="utf-8"))
    llama_report["usage_evidence"]["measurement_complete"] = False
    reports["llamaindex"].write_text(json.dumps(llama_report) + "\n", encoding="utf-8")

    manifest = build_selection_manifest(reports, selection_path=tmp_path / "selection.json")

    assert manifest["status"] == "not_selected"
    assert manifest["selected"] is None
    assert manifest["comparison_note"] == "candidate_usage_evidence_incomplete"


def _reports(tmp_path: Path, *, llama_available: bool) -> dict[str, Path]:
    values = {
        "deterministic": _report(
            "project-deterministic-baseline-v1", "project_baseline", passed=True, eligible=False
        ),
        "project-native": _report("project-native-rag-v1", "project", passed=True, eligible=True),
        "llamaindex": _report(
            "llamaindex-property-graph-v1",
            "llamaindex",
            passed=llama_available,
            eligible=True,
            available=llama_available,
            estimated_cost_usd=3.0,
            wall_clock_ms=30,
            model_calls=6,
            input_tokens=200,
            output_tokens=300,
        ),
        "graphrag": _report(
            "microsoft-graphrag-isolated-poc",
            "graphrag",
            passed=False,
            eligible=False,
            available=False,
        ),
    }
    paths: dict[str, Path] = {}
    for name, value in values.items():
        path = tmp_path / "reports" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")
        paths[name] = path
    return paths


def _report(
    candidate_id: str,
    adapter_kind: str,
    *,
    passed: bool,
    eligible: bool,
    available: bool = True,
    estimated_cost_usd: float = 2.0,
    wall_clock_ms: int = 20,
    model_calls: int = 4,
    input_tokens: int = 100,
    output_tokens: int = 200,
) -> dict[str, object]:
    return {
        "candidate": {
            "candidate_id": candidate_id,
            "adapter_kind": adapter_kind,
            "eligible_for_selection": eligible,
            "available": available,
            "unavailable_reason": None if available else "dependency_not_installed",
        },
        "dataset": {
            "dataset_version": "2026.07.19.1",
            "manifest_sha256": "a" * 64,
        },
        "status": "passed" if passed else "failed" if available else "unavailable",
        "selection_status": (
            "eligible_candidate_passed"
            if passed and eligible
            else "harness_reference_only"
            if passed
            else "hard_gate_failed"
            if available
            else "not_selectable_unavailable"
        ),
        "quality_score": 0.95 if passed else 0.5 if available else None,
        "gates": {"quality": True} if passed else {"quality": False} if available else None,
        "usage": {
            "estimated_cost_usd": estimated_cost_usd,
            "wall_clock_ms": wall_clock_ms,
            "model_calls": model_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        if available
        else None,
        "usage_evidence": {"measurement_complete": True} if available else None,
        "validation_evidence": {
            "dropped_candidate_count": 0,
            "failure_stage": None,
        }
        if available
        else None,
    }
