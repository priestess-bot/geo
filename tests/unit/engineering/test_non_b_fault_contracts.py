from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_non_b_fault_contracts import (
    FaultContractError,
    load_scenarios,
    selected_targets,
)


def test_checked_in_failure_matrix_has_all_required_scenarios_and_existing_targets() -> None:
    root = Path(__file__).resolve().parents[3]
    document = load_scenarios(root / "contracts/roadmap/non-b-fault-scenarios-v1.json")

    assert document["included_workstreams"] == ["A", "C", "D"]
    assert document["excluded_workstreams"] == ["B"]
    assert len(selected_targets(document, include_isolated_runtime=False)) > 0
    assert len(selected_targets(document, include_isolated_runtime=True)) > len(
        selected_targets(document, include_isolated_runtime=False)
    )


def test_fault_matrix_rejects_removed_required_scenario(tmp_path: Path) -> None:
    payload = {
        "schema_version": "geo-non-b-fault-scenarios-v1",
        "included_workstreams": ["A", "C", "D"],
        "excluded_workstreams": ["B"],
        "scenarios": [],
    }
    path = tmp_path / "faults.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FaultContractError, match="requires scenarios"):
        load_scenarios(path)


def test_fault_matrix_rejects_target_that_escapes_repository(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "contracts/roadmap/non-b-fault-scenarios-v1.json").read_text(encoding="utf-8")
    )
    payload["scenarios"][0]["targets"][0] = "tests/../../../outside.py"
    path = tmp_path / "faults.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FaultContractError, match="escapes repository"):
        load_scenarios(path)
