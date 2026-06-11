from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from geno_core.models import RuntimeNotificationDeliveryStatusInput
from geno_core.repository import PostgresEvidenceRepository
from geno_core.runtime import build_repository_from_env, close_repository_connection


WORKER_ID = "notification-worker"


class NotificationDeliveryRepository(Protocol):
    def claim_next_runtime_notification_delivery(
        self,
        *,
        updated_by: str = WORKER_ID,
        lease_seconds: int = 300,
    ) -> object | None:
        ...

    def update_runtime_notification_delivery_status(
        self,
        update: RuntimeNotificationDeliveryStatusInput,
    ) -> object:
        ...


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _failed_status(*, attempt_count: int, max_attempts: int) -> str:
    return "dead_letter" if attempt_count >= max_attempts else "queued"


def _next_attempt_at(*, attempt_count: int, max_attempts: int, retry_backoff_seconds: int) -> datetime | None:
    if attempt_count >= max_attempts:
        return None
    delay = retry_backoff_seconds * max(1, attempt_count)
    return datetime.now(UTC) + timedelta(seconds=delay)


def process_next_notification_delivery(
    *,
    repository: NotificationDeliveryRepository,
    updated_by: str = WORKER_ID,
    max_attempts: int = 3,
    retry_backoff_seconds: int = 120,
    lease_seconds: int = 300,
    timeout_seconds: float = 5.0,
    requester: Any | None = None,
) -> dict[str, Any]:
    max_attempts = max(1, int(max_attempts))
    retry_backoff_seconds = max(0, int(retry_backoff_seconds))
    lease_seconds = max(1, int(lease_seconds))
    timeout_seconds = max(0.1, float(timeout_seconds))
    delivery_record = repository.claim_next_runtime_notification_delivery(
        updated_by=updated_by,
        lease_seconds=lease_seconds,
    )
    if delivery_record is None:
        return {
            "processed": False,
            "status": "idle",
            "reason": "no queued notification deliveries",
        }

    delivery = dict(getattr(delivery_record, "delivery"))
    delivery_id = str(delivery["id"])
    project_id = str(delivery["project_id"])
    attempt_count = int(delivery.get("attempt_count") or 0)
    delivery_max_attempts = max(max_attempts, int(delivery.get("max_attempts") or max_attempts))
    endpoint_url = str(delivery["endpoint_url"])
    payload = delivery.get("payload") if isinstance(delivery.get("payload"), dict) else {}
    body = _canonical_json_bytes(payload)
    body_hash = hashlib.sha256(body).hexdigest()
    headers = {
        "content-type": "application/json",
        "x-geno-delivery-id": delivery_id,
        "x-geno-notification-id": str(delivery["notification_id"]),
        "x-geno-payload-sha256": body_hash,
    }

    try:
        if requester is None:
            response = httpx.post(endpoint_url, content=body, headers=headers, timeout=timeout_seconds)
            response_status = response.status_code
            response_body = response.content[:4096]
        else:
            response_status, response_body = requester("POST", endpoint_url, headers, body, timeout_seconds)
        response_body_hash = hashlib.sha256(response_body or b"").hexdigest()
        if 200 <= int(response_status) < 300:
            repository.update_runtime_notification_delivery_status(
                RuntimeNotificationDeliveryStatusInput(
                    delivery_id=delivery_id,
                    status="delivered",
                    updated_by=updated_by,
                    response_status=int(response_status),
                    response_body_hash=response_body_hash,
                    reason="runtime notification webhook delivered",
                )
            )
            return {
                "processed": True,
                "status": "delivered",
                "delivery_id": delivery_id,
                "project_id": project_id,
                "attempt_count": attempt_count,
                "max_attempts": delivery_max_attempts,
                "response_status": int(response_status),
                "payload_hash": body_hash,
            }
        failed_status = _failed_status(attempt_count=attempt_count, max_attempts=delivery_max_attempts)
        next_attempt_at = _next_attempt_at(
            attempt_count=attempt_count,
            max_attempts=delivery_max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        repository.update_runtime_notification_delivery_status(
            RuntimeNotificationDeliveryStatusInput(
                delivery_id=delivery_id,
                status=failed_status,
                updated_by=updated_by,
                response_status=int(response_status),
                response_body_hash=response_body_hash,
                error_message=f"Webhook returned HTTP {response_status}",
                next_attempt_at=next_attempt_at,
                reason="runtime notification webhook delivery failed",
            )
        )
        return {
            "processed": True,
            "status": failed_status,
            "delivery_id": delivery_id,
            "project_id": project_id,
            "attempt_count": attempt_count,
            "max_attempts": delivery_max_attempts,
            "response_status": int(response_status),
            "next_attempt_at": next_attempt_at.isoformat() if next_attempt_at else None,
            "payload_hash": body_hash,
        }
    except Exception as exc:
        failed_status = _failed_status(attempt_count=attempt_count, max_attempts=delivery_max_attempts)
        next_attempt_at = _next_attempt_at(
            attempt_count=attempt_count,
            max_attempts=delivery_max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        repository.update_runtime_notification_delivery_status(
            RuntimeNotificationDeliveryStatusInput(
                delivery_id=delivery_id,
                status=failed_status,
                updated_by=updated_by,
                error_message=str(exc),
                next_attempt_at=next_attempt_at,
                reason="runtime notification webhook delivery raised exception",
            )
        )
        return {
            "processed": True,
            "status": failed_status,
            "delivery_id": delivery_id,
            "project_id": project_id,
            "attempt_count": attempt_count,
            "max_attempts": delivery_max_attempts,
            "next_attempt_at": next_attempt_at.isoformat() if next_attempt_at else None,
            "error_message": str(exc),
            "payload_hash": body_hash,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process queued GENO runtime notification deliveries")
    parser.add_argument("--max-deliveries", type=int, default=1, help="Maximum queued deliveries to process before exiting.")
    parser.add_argument("--worker-id", default=WORKER_ID, help="Actor id used in notification delivery audit events.")
    parser.add_argument("--max-attempts", type=int, default=3, help="Dead-letter a delivery after this many attempts.")
    parser.add_argument("--retry-backoff-seconds", type=int, default=120, help="Base delay before retrying failed deliveries.")
    parser.add_argument("--lease-seconds", type=int, default=300, help="Delivery lease duration before reclaim.")
    parser.add_argument("--timeout-seconds", type=float, default=5.0, help="Webhook HTTP timeout in seconds.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    max_deliveries = max(1, args.max_deliveries)
    repository: PostgresEvidenceRepository | None = None
    results: list[dict[str, Any]] = []
    try:
        repository = build_repository_from_env()
        for _ in range(max_deliveries):
            result = process_next_notification_delivery(
                repository=repository,
                updated_by=args.worker_id,
                max_attempts=args.max_attempts,
                retry_backoff_seconds=args.retry_backoff_seconds,
                lease_seconds=args.lease_seconds,
                timeout_seconds=args.timeout_seconds,
            )
            results.append(result)
            if result["status"] == "idle":
                break
    finally:
        if repository is not None:
            close_repository_connection(repository)
    print(json.dumps({"worker": WORKER_ID, "processed_count": len(results), "results": results}, default=str))


if __name__ == "__main__":
    main()
