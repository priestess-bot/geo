"""Export and verify the frozen non-B roadmap performance profile."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Sequence

from pydantic import TypeAdapter, ValidationError

from geo_core.engineering.performance_profile import (
    PerformanceProfile,
    PerformanceProfileError,
    non_b_performance_profile_v1,
)


_ADAPTER = TypeAdapter(PerformanceProfile)


def export_profile(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(non_b_performance_profile_v1()), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def verify_profile(path: Path) -> PerformanceProfile:
    try:
        actual = _ADAPTER.validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PerformanceProfileError(f"unable to read performance profile: {path}") from exc
    except ValidationError as exc:
        raise PerformanceProfileError(f"invalid performance profile: {exc}") from exc
    if actual != non_b_performance_profile_v1():
        raise PerformanceProfileError("performance profile differs from frozen v1")
    return actual


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("output", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("profile", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "export":
            export_profile(arguments.output)
            return 0
        profile = verify_profile(arguments.profile)
    except PerformanceProfileError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"profile_id": profile.profile_id, "profile_hash": profile.profile_hash}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
