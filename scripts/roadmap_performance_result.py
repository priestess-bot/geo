"""Validate a measured non-B performance run against the frozen v1 profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from pydantic import TypeAdapter, ValidationError

from geo_core.engineering.performance_profile import PerformanceProfileError
from geo_core.engineering.performance_result import (
    PerformanceRunResult,
    evaluate_performance_run,
)
from geo_core.engineering.strict_dataclass_payload import (
    close_dataclass_json_schema,
    reject_unknown_dataclass_fields,
)


_ADAPTER = TypeAdapter(PerformanceRunResult)


def export_schema(path: Path) -> None:
    payload = close_dataclass_json_schema(_ADAPTER.json_schema())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_result(path: Path) -> tuple[PerformanceRunResult, tuple[str, ...]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PerformanceProfileError("performance result cannot be read") from exc
    except json.JSONDecodeError as exc:
        raise PerformanceProfileError("performance result is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise PerformanceProfileError("performance result must be a JSON object")
    if {"accepted", "failed_checks"}.intersection(payload):
        raise PerformanceProfileError("performance result cannot declare its own decision")
    reject_unknown_dataclass_fields(
        payload,
        PerformanceRunResult,
        path="result",
        error_factory=lambda detail: PerformanceProfileError(
            f"performance result contains {detail}"
        ),
    )
    try:
        result = _ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise PerformanceProfileError(f"invalid performance result: {exc}") from exc
    decision = evaluate_performance_run(result)
    return result, decision.failed_checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-schema")
    export.add_argument("output", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("result", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.command == "export-schema":
        export_schema(arguments.output)
        return 0
    try:
        result, failures = verify_result(arguments.result)
    except PerformanceProfileError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        json.dumps(
            {
                "accepted": not failures,
                "failed_checks": failures,
                "run_id": result.run_id,
            },
            sort_keys=True,
        )
    )
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
