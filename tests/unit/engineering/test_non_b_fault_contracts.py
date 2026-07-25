from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from scripts.run_non_b_fault_contracts import (
    _build_fault_receipt,
    FaultContractError,
    load_scenarios,
    selected_targets,
    verify_fault_receipt,
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
    runtime_targets = selected_targets(document, include_isolated_runtime=True)
    assert any("test_terminated_worker" in target for target in runtime_targets)
    assert any("test_real_valkey_outage" in target for target in runtime_targets)
    assert any("test_workflow_c_fault_cleanup" in target for target in runtime_targets)
    assert len(runtime_targets) == len(set(runtime_targets))


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


def test_fault_receipt_verifier_accepts_exact_sources_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    contract = root / "contracts/roadmap/non-b-fault-scenarios-v1.json"
    document = load_scenarios(contract)
    targets = selected_targets(document, include_isolated_runtime=False)
    started = datetime(2026, 7, 24, tzinfo=UTC)
    payload = _build_fault_receipt(
        contract_path=contract,
        targets=targets,
        include_isolated_runtime=False,
        started_at=started,
        finished_at=started + timedelta(minutes=1),
        exit_code=0,
        summary={
            "collected": len(targets),
            "errors": 0,
            "failures": 0,
            "skipped": 0,
            "time_seconds": 1.0,
        },
    )
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert verify_fault_receipt(path, contract_path=contract)["accepted"] is True

    payload["contract_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FaultContractError, match="contract hash is stale"):
        verify_fault_receipt(path, contract_path=contract)
