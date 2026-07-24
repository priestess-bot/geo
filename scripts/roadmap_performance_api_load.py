"""Verify a raw non-B API load report before it enters a performance evidence set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from pydantic import TypeAdapter, ValidationError

from geo_core.engineering.performance_api_load import (
    ApiLoadRawReport,
    ApiLoadTarget,
    PerformanceLoadError,
    diagnostic_api_load_plan,
    frozen_api_load_plan,
    validate_api_load_report,
)
from geo_core.engineering.strict_dataclass_payload import reject_unknown_dataclass_fields


_ADAPTER = TypeAdapter(ApiLoadRawReport)


def verify_report(
    path: Path,
    *,
    read_url: str,
    write_url: str,
    write_method: str = "POST",
    diagnostic_duration_seconds: int | None = None,
    diagnostic_read_rps: int = 1,
    diagnostic_write_rps: int = 1,
) -> ApiLoadRawReport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PerformanceLoadError("API load report cannot be read") from exc
    if not isinstance(payload, dict):
        raise PerformanceLoadError("API load report must be a JSON object")
    declared_hash = payload.pop("sha256", None)
    if not isinstance(declared_hash, str):
        raise PerformanceLoadError("API load report requires a declared SHA-256")
    reject_unknown_dataclass_fields(
        payload,
        ApiLoadRawReport,
        path="report",
        error_factory=lambda detail: PerformanceLoadError(
            f"API load report contains {detail}"
        ),
    )
    try:
        report = _ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise PerformanceLoadError(f"invalid API load report: {exc}") from exc
    if report.sha256 != declared_hash:
        raise PerformanceLoadError("API load report SHA-256 mismatch")
    read = ApiLoadTarget("GET", read_url)
    write = ApiLoadTarget(write_method, write_url, b"{}")
    if diagnostic_duration_seconds is None:
        plan = frozen_api_load_plan(read_target=read, write_target=write)
    else:
        plan = diagnostic_api_load_plan(
            read_target=read,
            write_target=write,
            duration_seconds=diagnostic_duration_seconds,
            read_rps=diagnostic_read_rps,
            write_rps=diagnostic_write_rps,
        )
    failures = validate_api_load_report(report, plan=plan)
    if failures:
        raise PerformanceLoadError(f"API load report does not match plan: {','.join(failures)}")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--read-url", required=True)
    parser.add_argument("--write-url", required=True)
    parser.add_argument("--write-method", choices=("POST", "PUT", "PATCH"), default="POST")
    parser.add_argument("--diagnostic-duration-seconds", type=int)
    parser.add_argument("--diagnostic-read-rps", type=int, default=1)
    parser.add_argument("--diagnostic-write-rps", type=int, default=1)
    arguments = parser.parse_args(argv)
    try:
        report = verify_report(
            arguments.report,
            read_url=arguments.read_url,
            write_url=arguments.write_url,
            write_method=arguments.write_method,
            diagnostic_duration_seconds=arguments.diagnostic_duration_seconds,
            diagnostic_read_rps=arguments.diagnostic_read_rps,
            diagnostic_write_rps=arguments.diagnostic_write_rps,
        )
    except PerformanceLoadError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"run_sha256": report.sha256, "diagnostic_only": report.diagnostic_only}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
