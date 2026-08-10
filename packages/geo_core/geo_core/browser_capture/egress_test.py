"""Durable, fenced Australian Egress endpoint self-test."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hmac
from typing import Any, Protocol
from uuid import UUID

from psycopg.types.json import Jsonb

from geo_core.browser_capture.domain import BrowserCaptureError, EgressVerification
from geo_core.browser_capture.playwright_driver import (
    EgressProbe,
    PlaywrightBrowserDriver,
    ProxyLease,
)
from geo_core.browser_capture.routing import BROWSER_EGRESS_TEST_JOB_KIND
from geo_core.browser_capture.worker import (
    BrowserProxyCredentialResolver,
    build_proxy_lease,
)
from geo_core.jobs.postgres import LeaseHeartbeat, PostgresDurableJobStore, WorkerLease
from geo_core.project_scope import set_project_scope


class EgressTestDriver(Protocol):
    def verify_egress(
        self, *, proxy: ProxyLease, probes: tuple[EgressProbe, ...],
        now: datetime | None = None,
    ) -> EgressVerification: ...


@dataclass(frozen=True)
class BrowserEgressTestState:
    test_id: UUID
    test_version: int
    endpoint: Mapping[str, object]


class PostgresBrowserEgressTestRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def job_kind(self, *, project_id: UUID, job_id: UUID) -> str:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                "SELECT kind FROM durable_jobs WHERE project_id = %s AND id = %s",
                (project_id, job_id),
            ).fetchone()
        if row is None or not isinstance(row["kind"], str):
            raise BrowserCaptureError("Browser Durable Job was not found")
        return row["kind"]

    def load_and_start(
        self, lease: WorkerLease, *, started_at: datetime
    ) -> BrowserEgressTestState:
        if lease.kind != BROWSER_EGRESS_TEST_JOB_KIND:
            raise BrowserCaptureError("Browser Worker received the wrong Egress test Job kind")
        with self._connect() as connection:
            set_project_scope(connection, lease.project_id)
            row = connection.execute(
                """SELECT test.*, spec.spec_hash, spec.spec_payload,
                          durable.input_hash, to_jsonb(endpoint_row) AS endpoint,
                          endpoint_row.status AS endpoint_status
                     FROM browser_egress_test_specs spec
                     JOIN durable_jobs durable
                       ON durable.project_id = spec.project_id AND durable.id = spec.job_id
                     JOIN browser_egress_tests test
                       ON test.project_id = spec.project_id AND test.id = spec.test_id
                     JOIN browser_egress_endpoints endpoint_row
                       ON endpoint_row.project_id = test.project_id
                      AND endpoint_row.id = test.endpoint_id
                    WHERE spec.project_id = %s AND spec.job_id = %s
                    FOR UPDATE OF test""",
                (lease.project_id, lease.job_id),
            ).fetchone()
            if row is None:
                raise BrowserCaptureError("Browser Egress test spec was not found")
            payload = row["spec_payload"]
            endpoint = _mapping(row["endpoint"], "Egress Endpoint")
            if not isinstance(payload, Mapping) or (
                payload.get("kind") != BROWSER_EGRESS_TEST_JOB_KIND
                or str(payload.get("project_id")) != str(lease.project_id)
                or str(payload.get("test_id")) != str(row["id"])
                or str(payload.get("endpoint_id")) != str(row["endpoint_id"])
                or str(payload.get("secret_reference_id"))
                != str(row["secret_reference_id"])
                or str(payload.get("secret_purpose")) != row["secret_purpose"]
                or _positive_integer(payload.get("secret_version"), "Secret version")
                != row["secret_version"]
                or not hmac.compare_digest(row["spec_hash"], row["input_hash"])
            ):
                raise BrowserCaptureError("Browser Egress test frozen identity changed")
            frozen_endpoint_fields = (
                "protocol",
                "endpoint_host",
                "endpoint_port",
                "network_type",
                "sticky_mode",
                "expected_country",
                "expected_region",
                "egress_policy_version",
                "egress_cohort_key",
                "provider",
                "pool_product",
                "session_ttl_seconds",
                "max_concurrency",
            )
            if any(
                payload.get(field) != endpoint.get(field)
                for field in frozen_endpoint_fields
            ):
                raise BrowserCaptureError(
                    "Browser Egress test frozen pool profile changed"
                )
            if row["endpoint_status"] != "approved":
                raise BrowserCaptureError("Browser Egress Endpoint is disabled")
            cooldown_until = endpoint.get("cooldown_until")
            if isinstance(cooldown_until, datetime) and cooldown_until > started_at:
                raise BrowserCaptureError("LokiProxy pool is in cooldown")
            if row["status"] == "queued":
                updated = connection.execute(
                    """UPDATE browser_egress_tests
                          SET status = 'running', version = version + 1, started_at = %s
                        WHERE project_id = %s AND id = %s AND status = 'queued'
                          AND version = %s RETURNING version""",
                    (started_at, lease.project_id, row["id"], row["version"]),
                ).fetchone()
                if updated is None:
                    raise BrowserCaptureError("Browser Egress test start was fenced")
                version = updated["version"]
            elif row["status"] == "running":
                version = row["version"]
            else:
                raise BrowserCaptureError("Browser Egress test is not executable")
        return BrowserEgressTestState(row["id"], version, endpoint)


class BrowserEgressTestOperation:
    kind = BROWSER_EGRESS_TEST_JOB_KIND

    def __init__(
        self, *, store: PostgresDurableJobStore,
        repository: PostgresBrowserEgressTestRepository,
        credentials: BrowserProxyCredentialResolver, probes: tuple[EgressProbe, ...],
        lease_for: timedelta, driver: EgressTestDriver | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._repository = repository
        self._credentials = credentials
        self._probes = probes
        self._lease_for = lease_for
        self._driver = driver or PlaywrightBrowserDriver()
        self._clock = clock

    def execute(self, lease: WorkerLease) -> Mapping[str, object]:
        state = self._repository.load_and_start(lease, started_at=self._clock())
        endpoint = state.endpoint
        credential = self._credentials.resolve(
            project_id=lease.project_id,
            reference_id=UUID(str(endpoint["secret_reference_id"])),
            purpose=str(endpoint["secret_purpose"]),
            version=_positive_integer(endpoint.get("secret_version"), "Secret version"),
        )
        proxy = build_proxy_lease(endpoint=endpoint, credential=credential, now=self._clock())
        with LeaseHeartbeat(
            self._store, lease, lease_for=self._lease_for,
            interval=min(self._lease_for / 3, timedelta(seconds=30)),
        ) as heartbeat:
            verification = self._driver.verify_egress(
                proxy=proxy, probes=self._probes, now=self._clock()
            )
            heartbeat.raise_if_stopped()
        representative = verification.pre[0]
        with self._store.fenced_transaction(lease) as connection:
            set_project_scope(connection, lease.project_id)
            updated = connection.execute(
                """UPDATE browser_egress_tests
                      SET status = 'succeeded', version = version + 1,
                          finished_at = %s, outcome = %s, eligible = %s,
                          verification_hash = %s, pre_observations = %s,
                          post_observations = %s, error_class = NULL
                    WHERE project_id = %s AND id = %s AND status = 'running'
                      AND version = %s RETURNING id""",
                (
                    self._clock(), verification.outcome.value, verification.eligible,
                    verification.verification_hash,
                    Jsonb([item.safe_value() for item in verification.pre]),
                    Jsonb([item.safe_value() for item in verification.post]),
                    lease.project_id, state.test_id, state.test_version,
                ),
            ).fetchone()
            if updated is None:
                raise BrowserCaptureError("Browser Egress test completion was fenced")
            self._store.complete_in_transaction(
                connection, lease, result_ref=f"browser-egress-test:{state.test_id}",
                details={
                    "test_id": str(state.test_id),
                    "outcome": verification.outcome.value,
                    "eligible": verification.eligible,
                    "country": representative.country,
                    "asn": representative.asn,
                    "verification_hash": verification.verification_hash,
                },
            )
        return {
            "status": "succeeded", "test_id": str(state.test_id),
            "outcome": verification.outcome.value, "eligible": verification.eligible,
        }


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise BrowserCaptureError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BrowserCaptureError(f"{label} is invalid")
    return value


__all__ = [
    "BROWSER_EGRESS_TEST_JOB_KIND",
    "BrowserEgressTestOperation",
    "PostgresBrowserEgressTestRepository",
]
