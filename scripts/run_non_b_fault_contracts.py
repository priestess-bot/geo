"""Validate or execute the frozen non-B failure-injection regression matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Literal, Sequence, TypedDict, cast


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
    if raw.get("included_workstreams") != ["A", "C", "D"] or raw.get("excluded_workstreams") != ["B"]:
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
        "postgres_minio_valkey_network_runtime",
    }
    if {item["id"] for item in parsed} != required:
        raise FaultContractError("fault scenario coverage is incomplete or changed")
    for item in parsed:
        for target in item["targets"]:
            resolved = ROOT / target
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
    return tuple(
        target
        for scenario in document["scenarios"]
        if include_isolated_runtime or scenario["mode"] == "deterministic"
        for target in scenario["targets"]
    )


def execute_targets(targets: Sequence[str]) -> int:
    completed = subprocess.run(
        ["uv", "run", "pytest", "-q", "--strict-markers", "--fail-on-skipped", *targets],
        cwd=ROOT,
        check=False,
    )
    return completed.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--include-isolated-runtime", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        document = load_scenarios(arguments.contract)
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
    return execute_targets(targets) if arguments.execute else 0


if __name__ == "__main__":
    raise SystemExit(main())
