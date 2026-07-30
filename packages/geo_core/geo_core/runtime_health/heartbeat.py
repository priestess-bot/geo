"""Heartbeat emitters shared by Dramatiq subprocesses and the Relay loop."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time
from typing import Callable

from geo_core.runtime_health.repository import (
    HeartbeatStatus,
    RuntimeHealthRepository,
    ServiceType,
)


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeartbeatIdentity:
    service_type: ServiceType
    container_id: str
    instance_id: str
    release_version: str


class RuntimeHeartbeat:
    """Rate-limited heartbeat for a service's real control loop."""

    def __init__(
        self,
        repository: RuntimeHealthRepository,
        identity: HeartbeatIdentity,
        *,
        interval_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 1 <= interval_seconds <= 300:
            raise ValueError("heartbeat interval must be between 1 and 300 seconds")
        self._repository = repository
        self._identity = identity
        self._interval_seconds = interval_seconds
        self._monotonic = monotonic
        self._last_pulse: float | None = None

    def pulse(self, *, status: HeartbeatStatus = "ready", force: bool = False) -> bool:
        now = self._monotonic()
        if (
            not force
            and self._last_pulse is not None
            and now - self._last_pulse < self._interval_seconds
        ):
            return False
        self._repository.record_heartbeat(
            service_type=self._identity.service_type,
            container_id=self._identity.container_id,
            instance_id=self._identity.instance_id,
            release_version=self._identity.release_version,
            status=status,
        )
        self._last_pulse = now
        return True


class PeriodicHeartbeat:
    """Background heartbeat started only after a Dramatiq consumer thread boots."""

    def __init__(self, heartbeat: RuntimeHeartbeat, *, interval_seconds: float) -> None:
        self._heartbeat = heartbeat
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def mark_starting(self) -> None:
        self._safe_pulse("starting", force=True)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._stop_event.clear()
            self._safe_pulse("ready", force=True)
            self._thread = threading.Thread(
                target=self._run,
                name="geo-runtime-heartbeat",
                daemon=True,
            )
            self._thread.start()

    def mark_failed(self) -> None:
        self._safe_pulse("failed", force=True)

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._thread = None
            self._stop_event.set()
        thread.join(timeout=max(self._interval_seconds, 1.0) + 1.0)
        self._safe_pulse("stopping", force=True)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            self._safe_pulse("ready", force=True)

    def _safe_pulse(self, status: HeartbeatStatus, *, force: bool) -> None:
        try:
            self._heartbeat.pulse(status=status, force=force)
        except Exception as error:
            LOGGER.error("runtime heartbeat update failed: %s", error.__class__.__name__)
