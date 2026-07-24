"""Run the frozen non-B API workload against an explicitly confirmed test environment."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from collections.abc import Mapping
from typing import Sequence

import httpx

from geo_core.engineering.performance_api_load import (
    ApiLoadTarget,
    PerformanceLoadError,
    diagnostic_api_load_plan,
    execute_api_load,
    frozen_api_load_plan,
)


def _load_header(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PerformanceLoadError("performance authorization header cannot be read") from exc
    if ":" not in raw:
        raise PerformanceLoadError("authorization header file must contain one Name: value line")
    name, value = raw.split(":", 1)
    if not name.strip() or not value.strip() or "\n" in raw or "\r" in raw:
        raise PerformanceLoadError("authorization header file is invalid")
    return {name.strip(): value.strip()}


def _load_json_body(path: Path) -> bytes:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PerformanceLoadError("write payload file must contain JSON") from exc
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


async def _run(arguments: argparse.Namespace) -> int:
    if not arguments.confirm_controlled_performance_run:
        raise PerformanceLoadError("--confirm-controlled-performance-run is required")
    read = ApiLoadTarget(method="GET", url=arguments.read_url)
    write = ApiLoadTarget(
        method=arguments.write_method,
        url=arguments.write_url,
        body=_load_json_body(arguments.write_payload),
    )
    if arguments.diagnostic_duration_seconds is None:
        plan = frozen_api_load_plan(
            read_target=read,
            write_target=write,
            max_in_flight=arguments.max_in_flight,
        )
    else:
        plan = diagnostic_api_load_plan(
            read_target=read,
            write_target=write,
            duration_seconds=arguments.diagnostic_duration_seconds,
            read_rps=arguments.diagnostic_read_rps,
            write_rps=arguments.diagnostic_write_rps,
            max_in_flight=arguments.max_in_flight,
        )
    headers = _load_header(arguments.authorization_header_file)
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("X-GEO-Performance-Run", plan.plan_hash)

    async with httpx.AsyncClient(timeout=httpx.Timeout(arguments.request_timeout_seconds)) as client:
        async def request(
            method: str,
            url: str,
            request_headers: Mapping[str, str],
            body: bytes | None,
        ) -> tuple[int | None, str | None]:
            try:
                response = await client.request(method, url, headers=request_headers, content=body)
            except httpx.HTTPError as exc:
                return None, exc.__class__.__name__
            return response.status_code, None

        report = await execute_api_load(plan, headers=headers, request=request)
    payload = report.to_payload()
    payload["sha256"] = report.sha256
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, default=lambda value: value.isoformat(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "diagnostic_only": report.diagnostic_only,
                "output": str(arguments.output),
                "sha256": report.sha256,
                "planned_read_requests": plan.planned_read_requests,
                "planned_write_requests": plan.planned_write_requests,
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-url", required=True)
    parser.add_argument("--write-url", required=True)
    parser.add_argument("--write-payload", required=True, type=Path)
    parser.add_argument("--write-method", choices=("POST", "PUT", "PATCH"), default="POST")
    parser.add_argument("--authorization-header-file", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--request-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-in-flight", type=int, default=128)
    parser.add_argument("--diagnostic-duration-seconds", type=int)
    parser.add_argument("--diagnostic-read-rps", type=int, default=1)
    parser.add_argument("--diagnostic-write-rps", type=int, default=1)
    parser.add_argument("--confirm-controlled-performance-run", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.request_timeout_seconds <= 0:
        raise SystemExit("request timeout must be positive")
    try:
        return asyncio.run(_run(arguments))
    except PerformanceLoadError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
