"""Execute the frozen non-B HTTP API workload without recording request secrets.

The performance result contract deliberately refuses to decide its own outcome.
This module is the equally narrow execution half: it emits a raw measurement
report with the exact planned and completed request counts.  The report can be
combined with independently collected queue, database, object-store and
correctness measurements by the release runner; it is not itself acceptance
evidence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from geo_core.engineering.performance_profile import (
    PerformanceProfile,
    PerformanceProfileError,
    non_b_performance_profile_v1,
)


RawHttpResponse = tuple[int | None, str | None]
AsyncRequest = Callable[[str, str, Mapping[str, str], bytes | None], Awaitable[RawHttpResponse]]


class PerformanceLoadError(PerformanceProfileError):
    """Raised when an HTTP load execution would weaken or expose the contract."""


@dataclass(frozen=True)
class ApiLoadTarget:
    """One endpoint of the frozen read/write workload.

    ``url`` may contain query parameters when the system under test requires
    them, but reports retain only its origin and path.  Headers and bodies are
    supplied at runtime and never serialized into the raw report.
    """

    method: str
    url: str
    body: bytes | None = None

    def __post_init__(self) -> None:
        if self.method not in {"GET", "POST", "PUT", "PATCH"}:
            raise PerformanceLoadError("API load method is not permitted")
        parts = urlsplit(self.url)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username:
            raise PerformanceLoadError("API load target must be an absolute URL without userinfo")
        if self.method == "GET" and self.body is not None:
            raise PerformanceLoadError("GET load target must not have a body")
        if self.method != "GET" and self.body is None:
            raise PerformanceLoadError("write load target requires an explicit body")

    @property
    def report_url(self) -> str:
        parts = urlsplit(self.url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))


@dataclass(frozen=True)
class ApiLoadPlan:
    """A rate plan; only the complete frozen plan is acceptance eligible."""

    profile_id: str
    profile_hash: str
    duration_seconds: int
    read_rps: int
    write_rps: int
    read_target: ApiLoadTarget
    write_target: ApiLoadTarget
    max_in_flight: int = 128
    diagnostic_only: bool = False

    def __post_init__(self) -> None:
        if self.duration_seconds < 1 or self.read_rps < 1 or self.write_rps < 1:
            raise PerformanceLoadError("duration and request rates must be positive")
        if self.max_in_flight < 1 or self.max_in_flight > 1_024:
            raise PerformanceLoadError("max in-flight requests must be between 1 and 1024")
        profile = non_b_performance_profile_v1()
        if self.profile_id != profile.profile_id or self.profile_hash != profile.profile_hash:
            raise PerformanceLoadError("API load plan must bind the frozen performance profile")
        expected_seconds = profile.api_targets.duration_minutes * 60
        if not self.diagnostic_only and (
            self.duration_seconds != expected_seconds
            or self.read_rps != profile.api_targets.read_rps
            or self.write_rps != profile.api_targets.write_rps
        ):
            raise PerformanceLoadError(
                "acceptance API load must use the exact frozen duration and rates"
            )

    @property
    def planned_read_requests(self) -> int:
        return self.duration_seconds * self.read_rps

    @property
    def planned_write_requests(self) -> int:
        return self.duration_seconds * self.write_rps

    @property
    def plan_hash(self) -> str:
        payload = {
            "profile_id": self.profile_id,
            "profile_hash": self.profile_hash,
            "duration_seconds": self.duration_seconds,
            "read_rps": self.read_rps,
            "write_rps": self.write_rps,
            "read_method": self.read_target.method,
            "read_url": self.read_target.report_url,
            "write_method": self.write_target.method,
            "write_url": self.write_target.report_url,
            "max_in_flight": self.max_in_flight,
            "diagnostic_only": self.diagnostic_only,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class HttpMeasurement:
    scheduled_requests: int
    started_requests: int
    completed_requests: int
    successful_responses: int
    unexpected_5xx_responses: int
    transport_failures: int
    latencies_ms: tuple[float, ...]

    def __post_init__(self) -> None:
        counts = (
            self.scheduled_requests,
            self.started_requests,
            self.completed_requests,
            self.successful_responses,
            self.unexpected_5xx_responses,
            self.transport_failures,
        )
        if any(value < 0 for value in counts):
            raise PerformanceLoadError("HTTP measurement counts cannot be negative")
        if self.started_requests > self.scheduled_requests:
            raise PerformanceLoadError("started request count exceeds planned schedule")
        if self.completed_requests > self.started_requests:
            raise PerformanceLoadError("completed request count exceeds started requests")
        if len(self.latencies_ms) != self.completed_requests:
            raise PerformanceLoadError("every completed request needs one latency measurement")
        if any(not math.isfinite(value) or value < 0 for value in self.latencies_ms):
            raise PerformanceLoadError("HTTP latencies must be finite and non-negative")

    def percentiles(self) -> dict[str, float | int]:
        if not self.latencies_ms:
            return {"sample_count": 0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(self.latencies_ms)
        return {
            "sample_count": len(ordered),
            "p50_ms": _percentile(ordered, 0.50),
            "p95_ms": _percentile(ordered, 0.95),
            "p99_ms": _percentile(ordered, 0.99),
            "max_ms": ordered[-1],
        }


@dataclass(frozen=True)
class ApiLoadRawReport:
    schema_version: str
    plan_hash: str
    profile_id: str
    profile_hash: str
    diagnostic_only: bool
    started_at: datetime
    finished_at: datetime
    read_target: str
    write_target: str
    read: HttpMeasurement
    write: HttpMeasurement

    def __post_init__(self) -> None:
        if self.schema_version != "geo-performance-api-load-report-v1":
            raise PerformanceLoadError("unsupported API load report schema")
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise PerformanceLoadError("API load timestamps must be timezone-aware")
        if self.finished_at < self.started_at:
            raise PerformanceLoadError("API load report finish precedes start")

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_payload(), default=_json_default, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()


def validate_api_load_report(report: ApiLoadRawReport, *, plan: ApiLoadPlan) -> tuple[str, ...]:
    """Return fail-closed validation codes for a raw API-load report.

    This deliberately does not declare a complete roadmap performance run
    accepted: queue, worker, object-store and correctness measurements remain
    independently required by :mod:`performance_result`.
    """

    failures: list[str] = []

    def require(condition: bool, code: str) -> None:
        if not condition:
            failures.append(code)

    require(report.plan_hash == plan.plan_hash, "plan_hash_mismatch")
    require(report.profile_id == plan.profile_id, "profile_id_mismatch")
    require(report.profile_hash == plan.profile_hash, "profile_hash_mismatch")
    require(report.diagnostic_only == plan.diagnostic_only, "diagnostic_flag_mismatch")
    require(report.read_target == plan.read_target.report_url, "read_target_mismatch")
    require(report.write_target == plan.write_target.report_url, "write_target_mismatch")
    _validate_measurement(report.read, plan.planned_read_requests, "read", require)
    _validate_measurement(report.write, plan.planned_write_requests, "write", require)
    return tuple(failures)


async def execute_api_load(
    plan: ApiLoadPlan,
    *,
    headers: Mapping[str, str],
    request: AsyncRequest,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ApiLoadRawReport:
    """Execute both streams at their planned rate and retain no request content.

    The scheduler starts from a common monotonic origin.  It records missed
    capacity as a lower ``started_requests`` count rather than silently
    lowering the denominator, so a saturated client cannot be presented as a
    successful acceptance run.
    """

    _validate_runtime_headers(headers)
    started_at = now()
    origin = clock()
    read, write = await asyncio.gather(
        _run_stream(
            target=plan.read_target,
            rps=plan.read_rps,
            duration_seconds=plan.duration_seconds,
            headers=headers,
            request=request,
            max_in_flight=plan.max_in_flight,
            origin=origin,
            clock=clock,
            sleep=sleep,
        ),
        _run_stream(
            target=plan.write_target,
            rps=plan.write_rps,
            duration_seconds=plan.duration_seconds,
            headers=headers,
            request=request,
            max_in_flight=plan.max_in_flight,
            origin=origin,
            clock=clock,
            sleep=sleep,
        ),
    )
    return ApiLoadRawReport(
        schema_version="geo-performance-api-load-report-v1",
        plan_hash=plan.plan_hash,
        profile_id=plan.profile_id,
        profile_hash=plan.profile_hash,
        diagnostic_only=plan.diagnostic_only,
        started_at=started_at,
        finished_at=now(),
        read_target=plan.read_target.report_url,
        write_target=plan.write_target.report_url,
        read=read,
        write=write,
    )


async def _run_stream(
    *,
    target: ApiLoadTarget,
    rps: int,
    duration_seconds: int,
    headers: Mapping[str, str],
    request: AsyncRequest,
    max_in_flight: int,
    origin: float,
    clock: Callable[[], float],
    sleep: Callable[[float], Awaitable[object]],
) -> HttpMeasurement:
    scheduled = duration_seconds * rps
    semaphore = asyncio.Semaphore(max_in_flight)
    samples: list[float] = []
    successes = 0
    five_xx = 0
    transport_failures = 0
    started = 0
    tasks: set[asyncio.Task[RawHttpResponse | tuple[None, str]]] = set()

    async def execute_one() -> RawHttpResponse | tuple[None, str]:
        nonlocal successes, five_xx, transport_failures
        acquired = False
        try:
            await semaphore.acquire()
            acquired = True
            begun = clock()
            try:
                status, error = await request(target.method, target.url, headers, target.body)
            except Exception as exc:  # transport adapters should not terminate a complete run
                status, error = None, exc.__class__.__name__
            samples.append((clock() - begun) * 1000)
            if status is None:
                transport_failures += 1
            elif 500 <= status <= 599:
                five_xx += 1
            elif 200 <= status <= 399:
                successes += 1
            else:
                transport_failures += 1
            return status, error
        finally:
            if acquired:
                semaphore.release()

    for ordinal in range(scheduled):
        due_at = origin + ordinal / rps
        remaining = due_at - clock()
        if remaining > 0:
            await sleep(remaining)
        if semaphore.locked() and len(tasks) >= max_in_flight:
            # Leave the slot visible as unstarted.  Do not turn overload into a
            # hidden slower workload by blocking the rate scheduler forever.
            continue
        started += 1
        task = asyncio.create_task(execute_one())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
    if tasks:
        await asyncio.gather(*tasks)
    return HttpMeasurement(
        scheduled_requests=scheduled,
        started_requests=started,
        completed_requests=len(samples),
        successful_responses=successes,
        unexpected_5xx_responses=five_xx,
        transport_failures=transport_failures,
        latencies_ms=tuple(samples),
    )


def frozen_api_load_plan(
    *,
    read_target: ApiLoadTarget,
    write_target: ApiLoadTarget,
    profile: PerformanceProfile | None = None,
    max_in_flight: int = 128,
) -> ApiLoadPlan:
    """Create the only plan eligible for the v1 API-load acceptance criterion."""

    frozen = profile or non_b_performance_profile_v1()
    return ApiLoadPlan(
        profile_id=frozen.profile_id,
        profile_hash=frozen.profile_hash or "",
        duration_seconds=frozen.api_targets.duration_minutes * 60,
        read_rps=frozen.api_targets.read_rps,
        write_rps=frozen.api_targets.write_rps,
        read_target=read_target,
        write_target=write_target,
        max_in_flight=max_in_flight,
    )


def diagnostic_api_load_plan(
    *,
    read_target: ApiLoadTarget,
    write_target: ApiLoadTarget,
    duration_seconds: int,
    read_rps: int,
    write_rps: int,
    max_in_flight: int = 128,
) -> ApiLoadPlan:
    """Build a deliberately non-acceptance run for endpoint shake-downs."""

    frozen = non_b_performance_profile_v1()
    return ApiLoadPlan(
        profile_id=frozen.profile_id,
        profile_hash=frozen.profile_hash or "",
        duration_seconds=duration_seconds,
        read_rps=read_rps,
        write_rps=write_rps,
        read_target=read_target,
        write_target=write_target,
        max_in_flight=max_in_flight,
        diagnostic_only=True,
    )


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise PerformanceLoadError("cannot calculate percentile without values")
    index = max(0, math.ceil(percentile * len(values)) - 1)
    return values[index]


def _validate_runtime_headers(headers: Mapping[str, str]) -> None:
    for name, value in headers.items():
        if not name.strip() or "\n" in name or "\r" in name:
            raise PerformanceLoadError("HTTP header name is invalid")
        if "\n" in value or "\r" in value:
            raise PerformanceLoadError("HTTP header value is invalid")


def _validate_measurement(
    measurement: HttpMeasurement,
    planned: int,
    prefix: str,
    require: Callable[[bool, str], None],
) -> None:
    require(measurement.scheduled_requests == planned, f"{prefix}_schedule_mismatch")
    require(
        measurement.completed_requests
        == measurement.successful_responses
        + measurement.unexpected_5xx_responses
        + measurement.transport_failures,
        f"{prefix}_outcome_total_mismatch",
    )


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported report value: {type(value).__name__}")


__all__ = [
    "ApiLoadPlan",
    "ApiLoadRawReport",
    "ApiLoadTarget",
    "AsyncRequest",
    "HttpMeasurement",
    "PerformanceLoadError",
    "diagnostic_api_load_plan",
    "execute_api_load",
    "frozen_api_load_plan",
    "validate_api_load_report",
]
