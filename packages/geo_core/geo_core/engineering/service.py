"""Application service for GitHub ingestion and truthful progress projections."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from uuid import UUID

from geo_core.engineering.domain import WorkItemProjection, evaluate_freshness
from geo_core.engineering.ports import (
    DeliveryReceipt,
    EngineeringEvent,
    EngineeringJobReceipt,
    EngineeringUnitOfWorkFactory,
)


class WebhookAuthenticationError(RuntimeError):
    """A webhook was not signed with the configured GitHub App secret."""


class WebhookConfigurationError(RuntimeError):
    """GitHub ingestion is unavailable until a secret and repository binding exist."""


class EngineeringService:
    persistence_available = True

    def __init__(
        self,
        *,
        unit_of_work_factory: EngineeringUnitOfWorkFactory,
        github_webhook_secret: str | None,
        github_source_available: bool | None = None,
        runtime_source_available: bool = True,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._secret = (github_webhook_secret or "").encode("utf-8")
        self._github_source_available = (
            bool(self._secret)
            if github_source_available is None
            else github_source_available
        )
        self.runtime_available = runtime_source_available
        self._clock = clock

    @property
    def github_available(self) -> bool:
        return self._github_source_available

    def accept_github_delivery(
        self,
        *,
        delivery_id: str,
        event_name: str,
        signature: str,
        body: bytes,
    ) -> DeliveryReceipt:
        if not self._secret:
            raise WebhookConfigurationError("GitHub App webhook secret is not configured")
        if not _valid_signature(secret=self._secret, body=body, candidate=signature):
            raise WebhookAuthenticationError("GitHub webhook signature is invalid")
        if not delivery_id.strip() or not event_name.strip():
            raise ValueError("GitHub delivery and event headers are required")
        try:
            payload = json.loads(body)
            external_repository_id = int(payload["repository"]["id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("GitHub webhook payload must identify a repository") from exc
        if not isinstance(payload, dict):
            raise ValueError("GitHub webhook payload must be an object")
        with self._unit_of_work_factory() as unit_of_work:
            receipt = unit_of_work.repository.record_github_delivery(
                delivery_id=delivery_id,
                event_name=event_name,
                external_repository_id=external_repository_id,
                payload_hash=hashlib.sha256(body).hexdigest(),
                payload=payload,
                received_at=self._clock(),
            )
            unit_of_work.commit()
            return receipt

    def list_work_items(self) -> tuple[WorkItemProjection, ...]:
        now = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            items = tuple(unit_of_work.repository.list_work_items(now=now))
        return items

    def freshness_for(self, item: WorkItemProjection):
        return evaluate_freshness(
            observed_at=item.observed_at,
            now=self._clock(),
            observation_interval=item.observation_interval,
        )

    def request_reconciliation(
        self,
        *,
        repository_id: UUID | None,
        reason: str,
        idempotency_key: str,
    ) -> EngineeringJobReceipt:
        return self._request_job(
            operation="reconcile",
            repository_id=repository_id,
            service_key=None,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def request_health_probe(
        self,
        *,
        repository_id: UUID | None,
        service_key: str,
        reason: str,
        idempotency_key: str,
    ) -> EngineeringJobReceipt:
        return self._request_job(
            operation="health_probe",
            repository_id=repository_id,
            service_key=service_key,
            reason=reason,
            idempotency_key=idempotency_key,
        )

    def _request_job(
        self,
        *,
        operation: str,
        repository_id: UUID | None,
        service_key: str | None,
        reason: str,
        idempotency_key: str,
    ) -> EngineeringJobReceipt:
        with self._unit_of_work_factory() as unit_of_work:
            receipt = unit_of_work.repository.create_job(
                operation=operation,
                repository_id=repository_id,
                service_key=service_key,
                reason=reason,
                idempotency_key=idempotency_key,
                now=self._clock(),
            )
            unit_of_work.commit()
            return receipt

    def events(self, *, after: int, batch_size: int = 100) -> Iterator[EngineeringEvent]:
        with self._unit_of_work_factory() as unit_of_work:
            yield from unit_of_work.repository.list_events(after=after, limit=batch_size)


def _valid_signature(*, secret: bytes, body: bytes, candidate: str) -> bool:
    if not candidate.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, candidate)
