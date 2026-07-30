"""Dramatiq actor isolated to Browser Capture Jobs."""

from __future__ import annotations

import os
import socket
import threading
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware
import psycopg

from geo_browser_capture_worker.composition import build_browser_capture_dispatcher
from geo_core.browser_capture.routing import BROWSER_CAPTURE_ACTOR, BROWSER_CAPTURE_QUEUE
from geo_core.runtime_health import (
    HeartbeatIdentity,
    PeriodicHeartbeat,
    RuntimeHealthRepository,
    RuntimeHeartbeat,
)


def _secret_setting(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_path = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_path:
        raise RuntimeError(f"configure {name} directly or by file, not both")
    if file_path:
        direct = Path(file_path).read_text(encoding="utf-8").strip()
    if not direct:
        raise RuntimeError(f"{name} or {name}_FILE is required")
    return direct


broker_url = os.getenv("GEO_TASK_QUEUE_BROKER_URL", "").strip()
if not broker_url:
    raise RuntimeError("GEO_TASK_QUEUE_BROKER_URL is required")
class RuntimeHeartbeatMiddleware(Middleware):
    def __init__(self) -> None:
        self._periodic: PeriodicHeartbeat | None = None
        self._lock = threading.Lock()
        self._boot_failed = False

    def after_process_boot(self, broker) -> None:
        del broker
        heartbeat = self._heartbeat()
        heartbeat.mark_starting()
        try:
            dispatcher()
            Path("/tmp/geo-worker-ready").touch(mode=0o600)
        except Exception:
            self._boot_failed = True
            heartbeat.mark_failed()
            Path("/tmp/geo-worker-ready").unlink(missing_ok=True)
            raise

    def after_consumer_thread_boot(self, broker, thread) -> None:
        del broker, thread
        if not self._boot_failed:
            self._heartbeat().start()

    def before_consumer_thread_shutdown(self, broker, thread) -> None:
        del broker, thread
        with self._lock:
            periodic = self._periodic
        if periodic is not None:
            periodic.stop()
        Path("/tmp/geo-worker-ready").unlink(missing_ok=True)

    def _heartbeat(self) -> PeriodicHeartbeat:
        with self._lock:
            if self._periodic is None:
                interval = _heartbeat_interval()
                identity = _heartbeat_identity("browser_capture_worker")
                repository = RuntimeHealthRepository(
                    lambda: psycopg.connect(_secret_setting("GEO_DATABASE_URL"))
                )
                heartbeat = RuntimeHeartbeat(
                    repository, identity, interval_seconds=interval
                )
                self._periodic = PeriodicHeartbeat(
                    heartbeat, interval_seconds=float(interval)
                )
            return self._periodic


broker = RedisBroker(url=broker_url)
broker.add_middleware(RuntimeHeartbeatMiddleware())
dramatiq.set_broker(broker)


@lru_cache(maxsize=1)
def dispatcher():
    return build_browser_capture_dispatcher(
        database_url=_secret_setting("GEO_DATABASE_URL"),
        worker_id=os.getenv(
            "GEO_BROWSER_CAPTURE_WORKER_ID", f"browser-capture:{socket.gethostname()}"
        ).strip(),
    )


def _heartbeat_interval() -> int:
    try:
        value = int(os.getenv("GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS", "10"))
    except ValueError:
        raise RuntimeError("GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS must be an integer") from None
    if not 1 <= value <= 300:
        raise RuntimeError("GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS must be between 1 and 300")
    return value


def _heartbeat_identity(service_type: str) -> HeartbeatIdentity:
    container_id = os.getenv("GEO_RUNTIME_CONTAINER_ID", socket.gethostname()).strip()
    release = os.getenv("GEO_RELEASE_COMMIT", "development").strip()
    if not container_id or len(container_id.encode()) > 200:
        raise RuntimeError("runtime container identity is invalid")
    instance_id = f"{container_id}:{service_type}:{os.getpid()}"
    return HeartbeatIdentity(service_type, container_id, instance_id, release)


@dramatiq.actor(
    actor_name=BROWSER_CAPTURE_ACTOR,
    queue_name=BROWSER_CAPTURE_QUEUE,
    max_retries=0,
    time_limit=900_000,
)
def process_browser_capture_job(job_id: str, project_id: str) -> dict[str, object]:
    return dict(dispatcher().process(job_id=UUID(job_id), project_id=UUID(project_id)))
