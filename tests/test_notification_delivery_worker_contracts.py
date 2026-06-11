from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, datetime

from geno_core.models import RuntimeNotificationDelivery, RuntimeNotificationDeliveryStatusInput
from geno_core.webhook_signing import verify_runtime_notification_webhook_signature
from workers.notification_worker.run_notification_deliveries import process_next_notification_delivery


class FakeNotificationDeliveryRepository:
    def __init__(self, delivery: RuntimeNotificationDelivery | None) -> None:
        self.delivery = delivery
        self.claimed_by: str | None = None
        self.lease_seconds: int | None = None
        self.status_updates: list[RuntimeNotificationDeliveryStatusInput] = []

    def claim_next_runtime_notification_delivery(
        self,
        *,
        updated_by: str = "notification-worker",
        lease_seconds: int = 300,
    ) -> RuntimeNotificationDelivery | None:
        self.claimed_by = updated_by
        self.lease_seconds = lease_seconds
        return self.delivery

    def update_runtime_notification_delivery_status(
        self,
        update: RuntimeNotificationDeliveryStatusInput,
    ) -> RuntimeNotificationDelivery:
        self.status_updates.append(update)
        assert self.delivery is not None
        return self.delivery


def _delivery_record(
    *,
    attempt_count: int = 1,
    max_attempts: int = 3,
    subscription_metadata: dict[str, object] | None = None,
) -> RuntimeNotificationDelivery:
    now = datetime(2026, 6, 12, tzinfo=UTC)
    return RuntimeNotificationDelivery(
        delivery={
            "id": "118e5c66-7bb4-558e-ab97-e74ef9928b46",
            "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
            "notification_id": "3ba5d5b7-8759-557b-a8a8-7297f98e2339",
            "subscription_id": "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8",
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "status": "sending",
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
            "lease_expires_at": now,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {
                "notification": {
                    "id": "3ba5d5b7-8759-557b-a8a8-7297f98e2339",
                    "notification_type": "report_export_job",
                    "severity": "warning",
                    "title": "Report export failed",
                },
                "delivery_version": "runtime_notification_delivery_v1",
            },
            "created_at": now,
            "updated_by": "notification-worker",
            "updated_at": now,
        },
        notification={"id": "3ba5d5b7-8759-557b-a8a8-7297f98e2339", "title": "Report export failed"},
        subscription={
            "id": "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8",
            "endpoint_url": "https://hooks.example.com/geno",
            "metadata": subscription_metadata or {},
        },
        audit_events=(),
    )


class NotificationDeliveryWorkerContractsTest(unittest.TestCase):
    def test_process_next_notification_delivery_posts_webhook_and_marks_delivered(self) -> None:
        repository = FakeNotificationDeliveryRepository(_delivery_record())
        requests: list[tuple[str, str, dict[str, str], bytes, float]] = []

        def requester(
            method: str,
            url: str,
            headers: dict[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> tuple[int, bytes]:
            requests.append((method, url, dict(headers), body, timeout_seconds))
            return 204, b""

        result = process_next_notification_delivery(
            repository=repository,
            updated_by="notification-worker",
            lease_seconds=120,
            timeout_seconds=2.5,
            default_signing_secret_env=None,
            requester=requester,
        )

        self.assertEqual(result["status"], "delivered")
        self.assertEqual(repository.claimed_by, "notification-worker")
        self.assertEqual(repository.lease_seconds, 120)
        self.assertEqual(repository.status_updates[-1].status, "delivered")
        self.assertEqual(repository.status_updates[-1].response_status, 204)
        self.assertEqual(repository.status_updates[-1].reason, "runtime notification webhook delivered")
        self.assertEqual(requests[0][0], "POST")
        self.assertEqual(requests[0][1], "https://hooks.example.com/geno")
        self.assertEqual(requests[0][2]["content-type"], "application/json")
        self.assertEqual(requests[0][2]["x-geno-delivery-id"], "118e5c66-7bb4-558e-ab97-e74ef9928b46")
        self.assertEqual(requests[0][2]["x-geno-notification-id"], "3ba5d5b7-8759-557b-a8a8-7297f98e2339")
        self.assertEqual(requests[0][4], 2.5)
        body_payload = json.loads(requests[0][3].decode("utf-8"))
        self.assertEqual(body_payload["delivery_version"], "runtime_notification_delivery_v1")
        self.assertEqual(result["payload_hash"], requests[0][2]["x-geno-payload-sha256"])
        self.assertFalse(result["signed"])

    def test_process_next_notification_delivery_signs_webhook_from_subscription_secret_env(self) -> None:
        repository = FakeNotificationDeliveryRepository(
            _delivery_record(subscription_metadata={"signing_secret_env": "GENO_TEST_WEBHOOK_SECRET"})
        )
        os.environ["GENO_TEST_WEBHOOK_SECRET"] = "test-secret"
        requests: list[tuple[str, str, dict[str, str], bytes, float]] = []

        def requester(
            method: str,
            url: str,
            headers: dict[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> tuple[int, bytes]:
            requests.append((method, url, dict(headers), body, timeout_seconds))
            return 200, b"ok"

        try:
            result = process_next_notification_delivery(
                repository=repository,
                default_signing_secret_env=None,
                requester=requester,
            )
        finally:
            os.environ.pop("GENO_TEST_WEBHOOK_SECRET", None)

        self.assertEqual(result["status"], "delivered")
        self.assertTrue(result["signed"])
        self.assertEqual(requests[0][2]["x-geno-signature-version"], "runtime_notification_webhook_hmac_sha256_v1")
        self.assertEqual(
            requests[0][2]["x-geno-signature-input"],
            "timestamp.delivery_id.notification_id.payload_sha256",
        )
        verification = verify_runtime_notification_webhook_signature(
            headers=requests[0][2],
            body=requests[0][3],
            secret="test-secret",
        )
        self.assertTrue(verification.valid, verification.reason)
        self.assertTrue(requests[0][2]["x-geno-signature-timestamp"].isdigit())

    def test_process_next_notification_delivery_requeues_missing_subscription_secret_env(self) -> None:
        repository = FakeNotificationDeliveryRepository(
            _delivery_record(
                attempt_count=1,
                max_attempts=3,
                subscription_metadata={"signing_secret_env": "GENO_MISSING_WEBHOOK_SECRET"},
            )
        )

        result = process_next_notification_delivery(
            repository=repository,
            default_signing_secret_env=None,
            requester=lambda *args: (204, b""),
        )

        self.assertEqual(result["status"], "queued")
        self.assertFalse(result["signed"])
        self.assertEqual(repository.status_updates[-1].status, "queued")
        self.assertIn("GENO_MISSING_WEBHOOK_SECRET", repository.status_updates[-1].error_message or "")

    def test_process_next_notification_delivery_signs_with_default_secret_env(self) -> None:
        repository = FakeNotificationDeliveryRepository(_delivery_record())
        os.environ["GENO_DEFAULT_WEBHOOK_SECRET"] = "default-secret"
        requests: list[tuple[str, str, dict[str, str], bytes, float]] = []

        def requester(
            method: str,
            url: str,
            headers: dict[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> tuple[int, bytes]:
            requests.append((method, url, dict(headers), body, timeout_seconds))
            return 202, b"accepted"

        try:
            result = process_next_notification_delivery(
                repository=repository,
                default_signing_secret_env="GENO_DEFAULT_WEBHOOK_SECRET",
                requester=requester,
            )
        finally:
            os.environ.pop("GENO_DEFAULT_WEBHOOK_SECRET", None)

        self.assertEqual(result["status"], "delivered")
        self.assertTrue(result["signed"])
        verification = verify_runtime_notification_webhook_signature(
            headers=requests[0][2],
            body=requests[0][3],
            secret="default-secret",
        )
        self.assertTrue(verification.valid, verification.reason)

    def test_process_next_notification_delivery_requeues_non_2xx_before_max_attempts(self) -> None:
        repository = FakeNotificationDeliveryRepository(_delivery_record(attempt_count=1, max_attempts=3))

        def requester(
            method: str,
            url: str,
            headers: dict[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> tuple[int, bytes]:
            return 503, b"temporary failure"

        result = process_next_notification_delivery(
            repository=repository,
            retry_backoff_seconds=30,
            default_signing_secret_env=None,
            requester=requester,
        )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(repository.status_updates[-1].status, "queued")
        self.assertEqual(repository.status_updates[-1].response_status, 503)
        self.assertEqual(repository.status_updates[-1].error_message, "Webhook returned HTTP 503")
        self.assertIsNotNone(repository.status_updates[-1].next_attempt_at)

    def test_process_next_notification_delivery_dead_letters_exception_at_max_attempts(self) -> None:
        repository = FakeNotificationDeliveryRepository(_delivery_record(attempt_count=3, max_attempts=3))

        def requester(
            method: str,
            url: str,
            headers: dict[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> tuple[int, bytes]:
            raise RuntimeError("webhook timeout")

        result = process_next_notification_delivery(
            repository=repository,
            default_signing_secret_env=None,
            requester=requester,
        )

        self.assertEqual(result["status"], "dead_letter")
        self.assertEqual(repository.status_updates[-1].status, "dead_letter")
        self.assertEqual(repository.status_updates[-1].error_message, "webhook timeout")
        self.assertIsNone(repository.status_updates[-1].next_attempt_at)


if __name__ == "__main__":
    unittest.main()
