"""Export or verify the deterministic non-B performance workload contract."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from geo_core.engineering.performance_profile import PerformanceProfileError
from geo_core.engineering.performance_workload import non_b_performance_workload_v1


def export_workload(path: Path) -> None:
    workload = non_b_performance_workload_v1()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(workload), indent=2, sort_keys=True, default=str) + "\n",
        encoding="ascii",
    )


def verify_workload(path: Path) -> dict[str, Any]:
    try:
        actual = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PerformanceProfileError("performance workload cannot be read") from exc
    expected = json.loads(
        json.dumps(asdict(non_b_performance_workload_v1()), default=str)
    )
    if actual != expected:
        raise PerformanceProfileError("performance workload differs from frozen v1")
    workload = non_b_performance_workload_v1()
    return {
        "workload_id": workload.workload_id,
        "workload_hash": workload.workload_hash,
        "planned_task_count": sum(
            item.planned_task_count for item in workload.sampling_runs
        ),
        "immediately_eligible_task_count": sum(
            item.immediately_eligible_task_count for item in workload.sampling_runs
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "verify"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        export_workload(args.path)
        return 0
    print(json.dumps(verify_workload(args.path), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
