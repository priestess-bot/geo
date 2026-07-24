from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from geo_core.engineering.performance_api_load import (
    ApiLoadPlan,
    ApiLoadTarget,
    PerformanceLoadError,
    diagnostic_api_load_plan,
    execute_api_load,
    frozen_api_load_plan,
    validate_api_load_report,
)
from scripts.roadmap_performance_api_load import verify_report


def test_frozen_plan_has_exact_v1_schedule_and_redacts_query_from_identity() -> None:
    plan = frozen_api_load_plan(
        read_target=ApiLoadTarget("GET", "https://staging.example.test/read?token=never-report"),
        write_target=ApiLoadTarget("POST", "https://staging.example.test/write", b"{}"),
    )

    assert plan.duration_seconds == 1_800
    assert plan.planned_read_requests == 36_000
    assert plan.planned_write_requests == 9_000
    assert "never-report" not in plan.plan_hash
    assert plan.read_target.report_url == "https://staging.example.test/read"


def test_acceptance_plan_rejects_weakened_rate_or_duration() -> None:
    frozen = frozen_api_load_plan(
        read_target=ApiLoadTarget("GET", "https://staging.example.test/read"),
        write_target=ApiLoadTarget("POST", "https://staging.example.test/write", b"{}"),
    )
    with pytest.raises(PerformanceLoadError, match="exact frozen"):
        ApiLoadPlan(
            profile_id=frozen.profile_id,
            profile_hash=frozen.profile_hash,
            duration_seconds=1,
            read_rps=1,
            write_rps=1,
            read_target=ApiLoadTarget("GET", "https://staging.example.test/read"),
            write_target=ApiLoadTarget("POST", "https://staging.example.test/write", b"{}"),
        )


def test_targets_reject_userinfo_and_implicit_write_body() -> None:
    with pytest.raises(PerformanceLoadError, match="userinfo"):
        ApiLoadTarget("GET", "https://token@example.test/read")
    with pytest.raises(PerformanceLoadError, match="explicit body"):
        ApiLoadTarget("POST", "https://example.test/write")


def test_diagnostic_execution_never_hides_missed_requests_or_headers() -> None:
    plan = diagnostic_api_load_plan(
        read_target=ApiLoadTarget("GET", "https://staging.example.test/read?secret=query"),
        write_target=ApiLoadTarget("POST", "https://staging.example.test/write", b"{}"),
        duration_seconds=1,
        read_rps=2,
        write_rps=1,
    )
    values = iter((0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))

    def clock() -> float:
        return next(values, 0.0)

    async def sleep(_: float) -> None:
        return None

    async def request(method: str, url: str, headers: dict[str, str], body: bytes | None):
        assert headers["Authorization"] == "Bearer secret"
        assert body in {None, b"{}"}
        return (503 if method == "POST" else 200), None

    report = asyncio.run(
        execute_api_load(
            plan,
            headers={"Authorization": "Bearer secret"},
            request=request,
            clock=clock,
            sleep=sleep,
        )
    )

    assert report.diagnostic_only is True
    assert report.read.scheduled_requests == 2
    assert report.read.completed_requests == 2
    assert report.write.unexpected_5xx_responses == 1
    serialized = str(report.to_payload())
    assert "Bearer secret" not in serialized
    assert "secret=query" not in serialized
    assert validate_api_load_report(report, plan=plan) == ()


def test_raw_report_checksum_and_plan_identity_are_verified(tmp_path: Path) -> None:
    plan = diagnostic_api_load_plan(
        read_target=ApiLoadTarget("GET", "https://staging.example.test/read"),
        write_target=ApiLoadTarget("POST", "https://staging.example.test/write", b"{}"),
        duration_seconds=1,
        read_rps=1,
        write_rps=1,
    )

    async def request(_: str, __: str, ___: dict[str, str], ____: bytes | None):
        return 200, None

    report = asyncio.run(execute_api_load(plan, headers={}, request=request))
    payload = report.to_payload() | {"sha256": report.sha256}
    path = tmp_path / "raw-report.json"
    path.write_text(json.dumps(payload, default=lambda value: value.isoformat()), encoding="utf-8")

    verified = verify_report(
        path,
        read_url="https://staging.example.test/read",
        write_url="https://staging.example.test/write",
        diagnostic_duration_seconds=1,
    )
    assert verified.sha256 == report.sha256

    payload["read"]["scheduled_requests"] = 2
    path.write_text(json.dumps(payload, default=lambda value: value.isoformat()), encoding="utf-8")
    with pytest.raises(PerformanceLoadError, match="SHA-256 mismatch"):
        verify_report(
            path,
            read_url="https://staging.example.test/read",
            write_url="https://staging.example.test/write",
            diagnostic_duration_seconds=1,
        )


def test_report_verifier_preserves_the_declared_controlled_write_method(tmp_path: Path) -> None:
    plan = diagnostic_api_load_plan(
        read_target=ApiLoadTarget("GET", "https://staging.example.test/read"),
        write_target=ApiLoadTarget("PATCH", "https://staging.example.test/write", b"{}"),
        duration_seconds=1,
        read_rps=1,
        write_rps=1,
    )

    async def request(_: str, __: str, ___: dict[str, str], ____: bytes | None):
        return 204, None

    report = asyncio.run(execute_api_load(plan, headers={}, request=request))
    path = tmp_path / "raw-report.json"
    path.write_text(
        json.dumps(report.to_payload() | {"sha256": report.sha256}, default=lambda value: value.isoformat()),
        encoding="utf-8",
    )

    assert verify_report(
        path,
        read_url="https://staging.example.test/read",
        write_url="https://staging.example.test/write",
        write_method="PATCH",
        diagnostic_duration_seconds=1,
    ).sha256 == report.sha256
