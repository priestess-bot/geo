"""Dramatiq actor isolated to authorized Style Collection jobs."""

from __future__ import annotations

from functools import lru_cache
import os
import socket
import threading
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware
import psycopg

from geo_core.runtime_health import PeriodicHeartbeat, RuntimeHealthRepository, RuntimeHeartbeat
from geo_style_worker.preflight import STYLE_QUEUE, load_composition_factory
from geo_worker.config import (
    runtime_heartbeat_identity,
    runtime_heartbeat_interval_seconds,
    secret_setting,
)


class StyleBrowserHeartbeatMiddleware(Middleware):
    def __init__(self) -> None:
        self._periodic: PeriodicHeartbeat | None = None
        self._lock = threading.Lock()

    def after_process_boot(self, broker) -> None:
        del broker
        self._heartbeat().mark_starting()

    def after_consumer_thread_boot(self, broker, thread) -> None:
        del broker, thread
        self._heartbeat().start()

    def before_consumer_thread_shutdown(self, broker, thread) -> None:
        del broker, thread
        with self._lock:
            periodic = self._periodic
        if periodic is not None:
            periodic.stop()

    def _heartbeat(self) -> PeriodicHeartbeat:
        with self._lock:
            if self._periodic is None:
                interval = runtime_heartbeat_interval_seconds()
                database_url = secret_setting("GEO_DATABASE_URL")
                repository = RuntimeHealthRepository(lambda: psycopg.connect(database_url))
                heartbeat = RuntimeHeartbeat(
                    repository,
                    runtime_heartbeat_identity(
                        "style_browser_worker",
                        process_id=os.getpid(),
                    ),
                    interval_seconds=interval,
                )
                self._periodic = PeriodicHeartbeat(
                    heartbeat,
                    interval_seconds=float(interval),
                )
            return self._periodic


broker_url = os.getenv("GEO_TASK_QUEUE_BROKER_URL", "").strip()
if not broker_url:
    raise RuntimeError("GEO_TASK_QUEUE_BROKER_URL is required")
broker = RedisBroker(url=broker_url)
broker.add_middleware(StyleBrowserHeartbeatMiddleware())
dramatiq.set_broker(broker)


@lru_cache(maxsize=1)
def dispatcher():
    factory = load_composition_factory()
    return factory(
        database_url=secret_setting("GEO_DATABASE_URL"),
        worker_id=os.getenv("GEO_STYLE_WORKER_ID", f"style:{socket.gethostname()}").strip(),
    )


@dramatiq.actor(
    actor_name="process_style_collection_job",
    queue_name=STYLE_QUEUE,
    max_retries=0,
    time_limit=900_000,
)
def process_style_collection_job(job_id: str, project_id: str) -> dict[str, object]:
    return dict(dispatcher().process(job_id=UUID(job_id), project_id=UUID(project_id)))
