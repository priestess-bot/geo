"""Request-scoped readiness probes for the isolated API surfaces."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import socket
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from geo_core.object_store import ObjectStoreError, S3CompatibleObjectStore


Surface = Literal["internal", "customer"]
ReadinessDependency = Literal["postgres", "valkey", "object_store", "access"]
EXPECTED_DEPENDENCIES: dict[Surface, tuple[ReadinessDependency, ...]] = {
    "customer": ("postgres",),
    "internal": ("postgres", "valkey", "object_store"),
}
DEFAULT_DEPENDENCY_TIMEOUT_SECONDS = 2.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 5.0
_DEPENDENCY_TIMEOUT_BOUNDS = (1, 10)
_TOTAL_TIMEOUT_BOUNDS = (2, 30)


class ReadinessService(Protocol):
    async def check(self) -> "ReadinessResult": ...


class ReadinessConfigurationUnavailable(RuntimeError):
    """A required local dependency setting was absent or unreadable."""


@dataclass(frozen=True)
class DependencyProbe:
    dependency: ReadinessDependency
    check: Callable[[], None]


@dataclass(frozen=True)
class ReadinessFailure:
    dependency: ReadinessDependency
    code: str


@dataclass(frozen=True)
class ReadinessResult:
    failures: tuple[ReadinessFailure, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.failures


class ReadinessChecker:
    """Run all required, read-only dependency probes for one API surface."""

    def __init__(
        self,
        *,
        surface: Surface,
        probes: Sequence[DependencyProbe],
        dependency_timeout_seconds: float = DEFAULT_DEPENDENCY_TIMEOUT_SECONDS,
        total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        dependencies = tuple(probe.dependency for probe in probes)
        if dependencies != EXPECTED_DEPENDENCIES[surface]:
            raise ValueError(
                f"{surface} readiness dependencies must be {EXPECTED_DEPENDENCIES[surface]!r}"
            )
        if dependency_timeout_seconds <= 0 or total_timeout_seconds <= 0:
            raise ValueError("readiness timeouts must be positive")
        if total_timeout_seconds <= dependency_timeout_seconds:
            raise ValueError("total readiness timeout must exceed dependency timeout")
        self._surface = surface
        self._probes = tuple(probes)
        self._dependency_timeout_seconds = dependency_timeout_seconds
        self._total_timeout_seconds = total_timeout_seconds

    async def check(self) -> ReadinessResult:
        tasks = {
            probe.dependency: asyncio.create_task(self._run_probe(probe))
            for probe in self._probes
        }
        done, pending = await asyncio.wait(
            tasks.values(), timeout=self._total_timeout_seconds
        )
        completed = {task: task.result() for task in done}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        failures: list[ReadinessFailure] = []
        for dependency in EXPECTED_DEPENDENCIES[self._surface]:
            task = tasks[dependency]
            failure = (
                ReadinessFailure(dependency, f"{dependency}_timeout")
                if task in pending
                else completed[task]
            )
            if failure is not None:
                failures.append(failure)
        return ReadinessResult(failures=tuple(failures))

    async def _run_probe(self, probe: DependencyProbe) -> ReadinessFailure | None:
        try:
            async with asyncio.timeout(self._dependency_timeout_seconds):
                await asyncio.to_thread(probe.check)
        except TimeoutError:
            return ReadinessFailure(probe.dependency, f"{probe.dependency}_timeout")
        except ReadinessConfigurationUnavailable:
            return ReadinessFailure(probe.dependency, f"{probe.dependency}_not_configured")
        except Exception:
            return ReadinessFailure(probe.dependency, f"{probe.dependency}_unavailable")
        return None


class AccessConfiguredReadiness:
    """Keep dependency probes authoritative while failing closed on missing API wiring."""

    def __init__(self, delegate: ReadinessService, *, access_configured: bool) -> None:
        self._delegate = delegate
        self._access_configured = access_configured

    async def check(self) -> ReadinessResult:
        result = await self._delegate.check()
        if not result.ready or self._access_configured:
            return result
        return ReadinessResult(
            failures=(ReadinessFailure("access", "access_configuration_unavailable"),)
        )


def readiness_checker_from_environment(
    *,
    surface: Surface,
    environment: Mapping[str, str] | None = None,
    dependency_timeout_seconds: float | None = None,
    total_timeout_seconds: float | None = None,
) -> ReadinessChecker:
    """Build the surface-specific probes without contacting any dependency."""

    values = os.environ if environment is None else environment
    resolved_dependency_timeout = (
        dependency_timeout_seconds
        if dependency_timeout_seconds is not None
        else _timeout_setting(
            values,
            "GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS",
            default=int(DEFAULT_DEPENDENCY_TIMEOUT_SECONDS),
            bounds=_DEPENDENCY_TIMEOUT_BOUNDS,
        )
    )
    resolved_total_timeout = (
        total_timeout_seconds
        if total_timeout_seconds is not None
        else _timeout_setting(
            values,
            "GEO_READINESS_TOTAL_TIMEOUT_SECONDS",
            default=int(DEFAULT_TOTAL_TIMEOUT_SECONDS),
            bounds=_TOTAL_TIMEOUT_BOUNDS,
        )
    )
    probes: list[DependencyProbe] = [
        DependencyProbe("postgres", _postgres_probe(values, resolved_dependency_timeout))
    ]
    if surface == "internal":
        probes.extend(
            (
                DependencyProbe("valkey", _valkey_probe(values, resolved_dependency_timeout)),
                DependencyProbe(
                    "object_store",
                    _object_store_probe(values, resolved_dependency_timeout),
                ),
            )
        )
    return ReadinessChecker(
        surface=surface,
        probes=probes,
        dependency_timeout_seconds=resolved_dependency_timeout,
        total_timeout_seconds=resolved_total_timeout,
    )


def _postgres_probe(values: Mapping[str, str], timeout_seconds: float) -> Callable[[], None]:
    try:
        database_url = _secret(values, "GEO_DATABASE_URL")
    except ReadinessConfigurationUnavailable:
        return _configuration_failure

    def check() -> None:
        import psycopg

        timeout = max(1, int(timeout_seconds))
        with psycopg.connect(
            database_url,
            autocommit=True,
            connect_timeout=timeout,
            options=f"-c statement_timeout={timeout * 1000}",
        ) as connection:
            row = connection.execute("SELECT 1").fetchone()
            if row != (1,):
                raise RuntimeError("unexpected PostgreSQL readiness result")

    return check


def _valkey_probe(values: Mapping[str, str], timeout_seconds: float) -> Callable[[], None]:
    broker_url = values.get("GEO_TASK_QUEUE_BROKER_URL", "").strip()
    if not broker_url:
        return _configuration_failure

    def check() -> None:
        from redis import Redis

        client = Redis.from_url(
            broker_url,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )
        try:
            if client.ping() is not True:
                raise RuntimeError("unexpected Valkey readiness result")
        finally:
            client.close()

    return check


def _object_store_probe(
    values: Mapping[str, str], timeout_seconds: float
) -> Callable[[], None]:
    try:
        endpoint = _required(values, "OBJECT_STORE_ENDPOINT")
        bucket = values.get("OBJECT_STORE_BUCKET", "geo-artifacts").strip() or "geo-artifacts"
        access_key = _secret(values, "OBJECT_STORE_ACCESS_KEY")
        secret_key = _secret(values, "OBJECT_STORE_SECRET_KEY")
    except ReadinessConfigurationUnavailable:
        return _configuration_failure
    region = values.get("OBJECT_STORE_REGION", "us-east-1").strip() or "us-east-1"

    def check() -> None:
        store = S3CompatibleObjectStore(
            endpoint=endpoint,
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            auto_create_bucket=False,
            requester=_url_requester(timeout_seconds),
        )
        store.ensure_bucket()

    return check


def _configuration_failure() -> None:
    raise ReadinessConfigurationUnavailable


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise ReadinessConfigurationUnavailable
    return value


def _timeout_setting(
    values: Mapping[str, str],
    name: str,
    *,
    default: int,
    bounds: tuple[int, int],
) -> float:
    raw = values.get(name, "").strip()
    if not raw:
        return float(default)
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer within its supported range") from error
    minimum, maximum = bounds
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be an integer within its supported range")
    return float(value)


def _secret(values: Mapping[str, str], name: str) -> str:
    direct = values.get(name, "").strip()
    file_name = values.get(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ReadinessConfigurationUnavailable
    if file_name:
        try:
            direct = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ReadinessConfigurationUnavailable from error
    if not direct:
        raise ReadinessConfigurationUnavailable
    return direct


def _url_requester(
    timeout_seconds: float,
) -> Callable[[str, str, Mapping[str, str], bytes], tuple[int, Mapping[str, str], bytes]]:
    def request(
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[int, Mapping[str, str], bytes]:
        payload = None if method == "HEAD" else body
        outbound = Request(url, data=payload, headers=dict(headers), method=method)
        try:
            with urlopen(outbound, timeout=timeout_seconds) as response:
                return response.status, dict(response.headers.items()), response.read()
        except HTTPError as error:
            return error.code, dict(error.headers.items()), error.read()
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            raise ObjectStoreError("Object store readiness request failed") from error

    return request
