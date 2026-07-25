"""Validate or execute the frozen non-B failure-injection regression matrix."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Literal, Sequence, TypedDict, cast
from uuid import uuid4
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = ROOT / "contracts/roadmap/non-b-fault-scenarios-v1.json"
ScenarioMode = Literal["deterministic", "isolated_runtime"]


class FaultScenario(TypedDict):
    id: str
    mode: ScenarioMode
    targets: list[str]


class FaultScenarioDocument(TypedDict):
    schema_version: str
    included_workstreams: list[str]
    excluded_workstreams: list[str]
    scenarios: list[FaultScenario]


class FaultContractError(ValueError):
    """Raised when the failure-injection matrix stops proving the frozen scope."""


def load_scenarios(path: Path) -> FaultScenarioDocument:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FaultContractError("fault scenario contract cannot be read") from exc
    if not isinstance(raw, dict):
        raise FaultContractError("fault scenario contract must be a JSON object")
    expected = {
        "schema_version",
        "included_workstreams",
        "excluded_workstreams",
        "scenarios",
    }
    if set(raw) != expected or raw.get("schema_version") != "geo-non-b-fault-scenarios-v1":
        raise FaultContractError("fault scenario contract schema is invalid")
    if raw.get("included_workstreams") != ["A", "C", "D"] or raw.get(
        "excluded_workstreams"
    ) != ["B"]:
        raise FaultContractError("fault scenario contract scope must be exactly non-B")
    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise FaultContractError("fault scenario contract requires scenarios")
    parsed: list[FaultScenario] = []
    seen: set[str] = set()
    for item in scenarios:
        if not isinstance(item, dict) or set(item) != {"id", "mode", "targets"}:
            raise FaultContractError("fault scenario has an unknown or missing field")
        scenario_id = item.get("id")
        mode = item.get("mode")
        targets = item.get("targets")
        if (
            not isinstance(scenario_id, str)
            or not scenario_id
            or scenario_id in seen
            or mode not in {"deterministic", "isolated_runtime"}
            or not isinstance(targets, list)
            or not targets
            or any(not isinstance(target, str) or not target.startswith("tests/") for target in targets)
        ):
            raise FaultContractError("fault scenario identity, mode, or targets are invalid")
        seen.add(scenario_id)
        parsed.append(cast(FaultScenario, item))
    required = {
        "provider_timeout_rate_revoke",
        "cancellation_lease_fencing",
        "relay_and_outbox_recovery",
        "artifact_delete_hold_and_recovery",
        "worker_process_termination_lease_reclaim",
        "real_broker_outage_outbox_replay",
        "partial_object_store_write_cleanup",
        "postgres_minio_valkey_network_runtime",
    }
    if {item["id"] for item in parsed} != required:
        raise FaultContractError("fault scenario coverage is incomplete or changed")
    for item in parsed:
        for target in item["targets"]:
            resolved = ROOT / _target_path(target)
            try:
                resolved.resolve().relative_to(ROOT.resolve())
            except ValueError as exc:
                raise FaultContractError(
                    f"fault scenario target escapes repository: {target}"
                ) from exc
            if not resolved.is_file():
                raise FaultContractError(f"fault scenario target is unavailable: {target}")
    return cast(FaultScenarioDocument, raw)


def selected_targets(
    document: FaultScenarioDocument, *, include_isolated_runtime: bool
) -> tuple[str, ...]:
    selected: list[str] = []
    for scenario in document["scenarios"]:
        if include_isolated_runtime or scenario["mode"] == "deterministic":
            for target in scenario["targets"]:
                if target not in selected:
                    selected.append(target)
    return tuple(selected)


def execute_targets(
    targets: Sequence[str],
    *,
    contract_path: Path,
    include_isolated_runtime: bool,
) -> tuple[int, dict[str, object]]:
    started_at = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="geo-non-b-fault-") as temporary:
        junit_path = Path(temporary) / "junit.xml"
        completed = subprocess.run(
            [
                "uv",
                "run",
                "pytest",
                "-q",
                "--strict-markers",
                "--fail-on-skipped",
                f"--junitxml={junit_path}",
                *targets,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        summary = _junit_summary(junit_path)
    receipt = _build_fault_receipt(
        contract_path=contract_path,
        targets=targets,
        include_isolated_runtime=include_isolated_runtime,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        exit_code=completed.returncode,
        summary=summary,
    )
    return completed.returncode, receipt


def verify_fault_receipt(
    receipt_path: Path,
    *,
    contract_path: Path = DEFAULT_SCENARIOS,
) -> dict[str, object]:
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FaultContractError("fault run receipt cannot be read") from exc
    expected_keys = {
        "schema_version",
        "contract_sha256",
        "included_workstreams",
        "excluded_workstreams",
        "include_isolated_runtime",
        "started_at",
        "finished_at",
        "environment_fingerprint",
        "targets",
        "pytest",
        "receipt_hash",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise FaultContractError("fault run receipt schema is invalid")
    if payload["schema_version"] != "geo-non-b-fault-run-v1":
        raise FaultContractError("fault run receipt version is unsupported")
    if payload["included_workstreams"] != ["A", "C", "D"] or payload[
        "excluded_workstreams"
    ] != ["B"]:
        raise FaultContractError("fault run receipt scope is invalid")
    if payload["contract_sha256"] != _sha256_file(contract_path):
        raise FaultContractError("fault run receipt contract hash is stale")
    if payload["receipt_hash"] != _receipt_hash(payload):
        raise FaultContractError("fault run receipt hash does not match")
    include_runtime = payload["include_isolated_runtime"]
    if not isinstance(include_runtime, bool):
        raise FaultContractError("fault run receipt runtime mode is invalid")
    _validate_receipt_timestamps(payload)
    document = load_scenarios(contract_path)
    expected_targets = selected_targets(document, include_isolated_runtime=include_runtime)
    target_items = payload["targets"]
    if not isinstance(target_items, list):
        raise FaultContractError("fault run receipt target evidence is invalid")
    nodeids: list[str] = []
    for raw_item in target_items:
        if not isinstance(raw_item, dict) or set(raw_item) != {"nodeid", "source_sha256"}:
            raise FaultContractError("fault run receipt target evidence is invalid")
        nodeid = raw_item["nodeid"]
        source_hash = raw_item["source_sha256"]
        if not isinstance(nodeid, str) or not isinstance(source_hash, str):
            raise FaultContractError("fault run receipt target evidence is invalid")
        if source_hash != _sha256_file(ROOT / _target_path(nodeid)):
            raise FaultContractError("fault run receipt source hash is stale")
        nodeids.append(nodeid)
    if nodeids != list(expected_targets):
        raise FaultContractError("fault run receipt target set is incomplete")
    pytest_summary = payload["pytest"]
    if not isinstance(pytest_summary, dict) or set(pytest_summary) != {
        "collected",
        "errors",
        "exit_code",
        "failures",
        "skipped",
        "time_seconds",
    }:
        raise FaultContractError("fault run pytest summary is invalid")
    numeric = tuple(pytest_summary[key] for key in ("collected", "errors", "failures", "skipped"))
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in numeric):
        raise FaultContractError("fault run pytest counters are invalid")
    accepted = (
        pytest_summary["exit_code"] == 0
        and pytest_summary["collected"] >= len(expected_targets)
        and pytest_summary["failures"] == 0
        and pytest_summary["errors"] == 0
        and pytest_summary["skipped"] == 0
    )
    return {
        "accepted": accepted,
        "collected": pytest_summary["collected"],
        "include_isolated_runtime": include_runtime,
        "receipt_hash": payload["receipt_hash"],
        "target_count": len(expected_targets),
    }


def _build_fault_receipt(
    *,
    contract_path: Path,
    targets: Sequence[str],
    include_isolated_runtime: bool,
    started_at: datetime,
    finished_at: datetime,
    exit_code: int,
    summary: dict[str, int | float],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "geo-non-b-fault-run-v1",
        "contract_sha256": _sha256_file(contract_path),
        "included_workstreams": ["A", "C", "D"],
        "excluded_workstreams": ["B"],
        "include_isolated_runtime": include_isolated_runtime,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "environment_fingerprint": _environment_fingerprint(),
        "targets": [
            {"nodeid": target, "source_sha256": _sha256_file(ROOT / _target_path(target))}
            for target in targets
        ],
        "pytest": {**summary, "exit_code": exit_code},
    }
    payload["receipt_hash"] = _receipt_hash(payload)
    return payload


def _junit_summary(path: Path) -> dict[str, int | float]:
    if not path.is_file():
        return {
            "collected": 0,
            "errors": 1,
            "failures": 0,
            "skipped": 0,
            "time_seconds": 0.0,
        }
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        "collected": sum(int(suite.attrib.get("tests", "0")) for suite in suites),
        "errors": sum(int(suite.attrib.get("errors", "0")) for suite in suites),
        "failures": sum(int(suite.attrib.get("failures", "0")) for suite in suites),
        "skipped": sum(int(suite.attrib.get("skipped", "0")) for suite in suites),
        "time_seconds": round(
            sum(float(suite.attrib.get("time", "0")) for suite in suites),
            6,
        ),
    }


def _validate_receipt_timestamps(payload: dict[str, object]) -> None:
    try:
        started = datetime.fromisoformat(cast(str, payload["started_at"]))
        finished = datetime.fromisoformat(cast(str, payload["finished_at"]))
    except (TypeError, ValueError) as exc:
        raise FaultContractError("fault run receipt timestamps are invalid") from exc
    if started.tzinfo is None or finished.tzinfo is None or finished <= started:
        raise FaultContractError("fault run receipt timestamps are invalid")


def _target_path(target: str) -> str:
    return target.split("::", maxsplit=1)[0]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt_hash(payload: dict[str, object]) -> str:
    canonical = dict(payload)
    canonical.pop("receipt_hash", None)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _environment_fingerprint() -> str:
    try:
        docker = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        docker_server = docker.stdout.strip() if docker.returncode == 0 else "unavailable"
    except (OSError, subprocess.TimeoutExpired):
        docker_server = "unavailable"
    identity = {
        "docker_server": docker_server,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _write_private_receipt(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--include-isolated-runtime", action="store_true")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--verify-receipt", type=Path)
    arguments = parser.parse_args(argv)
    try:
        document = load_scenarios(arguments.contract)
        if arguments.verify_receipt is not None:
            result = verify_fault_receipt(
                arguments.verify_receipt,
                contract_path=arguments.contract,
            )
            print(json.dumps(result, sort_keys=True))
            return 0 if result["accepted"] else 2
    except FaultContractError as exc:
        raise SystemExit(str(exc)) from exc
    targets = selected_targets(
        document,
        include_isolated_runtime=arguments.include_isolated_runtime,
    )
    print(
        json.dumps(
            {
                "scenario_count": len(document["scenarios"]),
                "selected_target_count": len(targets),
                "includes_isolated_runtime": arguments.include_isolated_runtime,
                "targets": targets,
            },
            sort_keys=True,
        )
    )
    if not arguments.execute:
        if arguments.receipt is not None:
            raise SystemExit("--receipt requires --execute")
        return 0
    return_code, receipt = execute_targets(
        targets,
        contract_path=arguments.contract,
        include_isolated_runtime=arguments.include_isolated_runtime,
    )
    if arguments.receipt is not None:
        _write_private_receipt(arguments.receipt, receipt)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
