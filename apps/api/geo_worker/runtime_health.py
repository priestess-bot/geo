"""Safe Compose healthcheck for Task Worker and Outbox Relay."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os

from dramatiq.brokers.redis import RedisBroker
import psycopg

from geo_core.runtime_health import RuntimeHealthRepository
from geo_core.runtime_health.repository import ServiceType
from geo_worker.config import (
    runtime_expected_instances,
    runtime_health_thresholds,
    runtime_heartbeat_identity,
    secret_setting,
)


def broker_ping(broker_url: str) -> bool:
    broker = RedisBroker(url=broker_url)
    try:
        return bool(broker.client.ping())
    finally:
        broker.client.close()


def evaluate_heartbeat_health(
    *,
    service_type: ServiceType,
    repository: RuntimeHealthRepository,
    container_id: str,
    broker_probe: Callable[[], bool],
) -> tuple[int, dict[str, object]]:
    thresholds = runtime_health_thresholds()
    expected_instances = runtime_expected_instances(service_type)
    reported_thresholds = {
        **thresholds.as_dict(),
        "expected_instances": expected_instances,
    }
    checks: dict[str, str] = {
        "database": "ok",
        "broker": "ok",
        "consumer_heartbeat": "ok",
        "queue_progress": "ok",
    }
    try:
        findings = repository.findings(
            service_type=service_type,
            container_id=container_id,
            expected_instances=expected_instances,
            thresholds=thresholds,
        )
    except Exception:
        checks["database"] = "error"
        return 2, {
            "status": "error",
            "error_code": "runtime_database_probe_failed",
            "service_type": service_type,
            "thresholds": reported_thresholds,
            "checks": checks,
            "findings": [],
        }

    try:
        broker_ok = broker_probe()
    except Exception:
        broker_ok = False
    if not broker_ok:
        checks["broker"] = "error"
        return 2, {
            "status": "error",
            "error_code": "runtime_broker_probe_failed",
            "service_type": service_type,
            "thresholds": reported_thresholds,
            "checks": checks,
            "findings": [item.public_dict() for item in findings],
        }

    heartbeat_bad = any(item.category == "runtime_heartbeat" for item in findings)
    queue_bad = any(item.category != "runtime_heartbeat" for item in findings)
    if heartbeat_bad:
        checks["consumer_heartbeat"] = "unhealthy"
    if queue_bad:
        checks["queue_progress"] = "unhealthy"
    unhealthy = heartbeat_bad or queue_bad
    return int(unhealthy), {
        "status": "unhealthy" if unhealthy else "ok",
        "error_code": "runtime_findings_present" if unhealthy else None,
        "service_type": service_type,
        "thresholds": reported_thresholds,
        "checks": checks,
        "findings": [item.public_dict() for item in findings],
    }


def _heartbeat_command(service_type: ServiceType) -> int:
    database_url = secret_setting("GEO_DATABASE_URL")
    broker_url = os.getenv("GEO_TASK_QUEUE_BROKER_URL", "redis://valkey:6379/0").strip()
    if not broker_url:
        raise RuntimeError("GEO_TASK_QUEUE_BROKER_URL is required")
    identity = runtime_heartbeat_identity(service_type, process_id=os.getpid())
    repository = RuntimeHealthRepository(lambda: psycopg.connect(database_url))
    exit_code, payload = evaluate_heartbeat_health(
        service_type=service_type,
        repository=repository,
        container_id=identity.container_id,
        broker_probe=lambda: broker_ping(broker_url),
    )
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Check GEO worker runtime health")
    subparsers = parser.add_subparsers(dest="command", required=True)
    heartbeat = subparsers.add_parser("heartbeat", help="check heartbeat and queue progress")
    heartbeat.add_argument(
        "--service-type",
        required=True,
        choices=("task_worker", "outbox_relay"),
    )
    args = parser.parse_args()
    try:
        return _heartbeat_command(args.service_type)
    except Exception:
        payload: dict[str, object] = {
            "status": "error",
            "error_code": "runtime_health_configuration_invalid",
            "service_type": getattr(args, "service_type", None),
            "findings": [],
        }
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
