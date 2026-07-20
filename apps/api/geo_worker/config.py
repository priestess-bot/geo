from __future__ import annotations

import os
from pathlib import Path
import socket

from geo_core.runtime_health import HeartbeatIdentity, RuntimeHealthThresholds
from geo_core.runtime_health.repository import ServiceType


def secret_setting(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise RuntimeError(f"configure {name} directly or by file, not both")
    if file_name:
        try:
            direct = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"{name}_FILE cannot be read") from exc
    if not direct:
        raise RuntimeError(f"{name} or {name}_FILE is required")
    return direct


def bounded_int_setting(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def runtime_heartbeat_interval_seconds() -> int:
    return bounded_int_setting(
        "GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS", 10, minimum=1, maximum=300
    )


def runtime_health_thresholds() -> RuntimeHealthThresholds:
    thresholds = RuntimeHealthThresholds(
        heartbeat_stale_seconds=bounded_int_setting(
            "GEO_RUNTIME_HEARTBEAT_STALE_SECONDS", 30, minimum=1, maximum=3_600
        ),
        queued_stale_seconds=bounded_int_setting(
            "GEO_RUNTIME_QUEUED_STALE_SECONDS", 600, minimum=1, maximum=604_800
        ),
        running_grace_seconds=bounded_int_setting(
            "GEO_RUNTIME_RUNNING_GRACE_SECONDS", 60, minimum=0, maximum=86_400
        ),
        outbox_stale_seconds=bounded_int_setting(
            "GEO_RUNTIME_OUTBOX_STALE_SECONDS", 300, minimum=1, maximum=604_800
        ),
        failure_window_seconds=bounded_int_setting(
            "GEO_RUNTIME_FAILURE_WINDOW_SECONDS", 86_400, minimum=1, maximum=2_592_000
        ),
    )
    if thresholds.heartbeat_stale_seconds <= runtime_heartbeat_interval_seconds():
        raise RuntimeError(
            "GEO_RUNTIME_HEARTBEAT_STALE_SECONDS must exceed "
            "GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS"
        )
    return thresholds


def runtime_expected_instances(service_type: ServiceType) -> int:
    if service_type == "task_worker":
        return bounded_int_setting(
            "GEO_RUNTIME_EXPECTED_TASK_WORKER_INSTANCES", 1, minimum=1, maximum=100
        )
    return bounded_int_setting(
        "GEO_RUNTIME_EXPECTED_OUTBOX_RELAY_INSTANCES", 1, minimum=1, maximum=100
    )


def runtime_heartbeat_identity(
    service_type: ServiceType, *, process_id: int
) -> HeartbeatIdentity:
    container_id = os.getenv("GEO_RUNTIME_CONTAINER_ID", socket.gethostname()).strip()
    release_version = os.getenv("GEO_RELEASE_VERSION", "development").strip()
    if not container_id or len(container_id.encode()) > 200:
        raise RuntimeError("GEO_RUNTIME_CONTAINER_ID must contain at most 200 bytes")
    if not release_version or len(release_version.encode()) > 200:
        raise RuntimeError("GEO_RELEASE_VERSION must contain at most 200 bytes")
    instance_id = f"{container_id}:{service_type}:{process_id}"
    if len(instance_id.encode()) > 240:
        raise RuntimeError("runtime instance identity exceeds 240 bytes")
    return HeartbeatIdentity(service_type, container_id, instance_id, release_version)
