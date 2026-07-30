"""Production composition for the isolated Browser Capture worker."""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.browser_capture.artifacts import EncryptedBrowserArtifactWriter
from geo_core.browser_capture.egress_test import (
    BROWSER_EGRESS_TEST_JOB_KIND,
    BrowserEgressTestOperation,
    PostgresBrowserEgressTestRepository,
)
from geo_core.browser_capture.playwright_driver import EgressProbe
from geo_core.browser_capture.secret_resolver import build_audited_browser_proxy_secret_resolver
from geo_core.browser_capture.worker import (
    BROWSER_CAPTURE_JOB_KIND,
    BrowserCaptureOperation,
    PostgresBrowserCaptureWorkerRepository,
)
from geo_core.jobs.postgres import JobCancellationRequested, LostJobLease, PostgresDurableJobStore
from geo_core.object_store_config import build_object_store_from_prefix


class BrowserCaptureDispatcher:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        operation: BrowserCaptureOperation,
        egress_test_operation: BrowserEgressTestOperation,
        egress_tests: PostgresBrowserEgressTestRepository,
        worker_id: str,
        lease_for: timedelta,
    ) -> None:
        self._store = store
        self._operation = operation
        self._egress_test_operation = egress_test_operation
        self._egress_tests = egress_tests
        self._worker_id = worker_id
        self._lease_for = lease_for

    def process(self, *, job_id: UUID, project_id: UUID) -> Mapping[str, object]:
        kind = self._egress_tests.job_kind(project_id=project_id, job_id=job_id)
        operation = {
            BROWSER_CAPTURE_JOB_KIND: self._operation,
            BROWSER_EGRESS_TEST_JOB_KIND: self._egress_test_operation,
        }.get(kind)
        if operation is None:
            raise RuntimeError("Browser worker received an unsupported Job kind")
        claim = self._store.claim(
            job_id=job_id,
            project_id=project_id,
            expected_kind=kind,
            worker_id=self._worker_id,
            lease_for=self._lease_for,
        )
        if claim.lease is None:
            return {"status": claim.disposition, "job_id": str(job_id)}
        try:
            return operation.execute(claim.lease)
        except JobCancellationRequested:
            self._store.cancel(claim.lease)
            return {"status": "cancelled", "job_id": str(job_id)}
        except LostJobLease:
            return {"status": "fenced", "job_id": str(job_id)}
        except Exception as error:
            status = self._store.fail(
                claim.lease,
                error_code=(
                    "browser_egress_test_failed"
                    if kind == BROWSER_EGRESS_TEST_JOB_KIND
                    else "browser_capture_failed"
                ),
                details={"classification": type(error).__name__},
                retry_delay=timedelta(seconds=60),
            )
            return {"status": status, "job_id": str(job_id)}


def build_browser_capture_dispatcher(
    *, database_url: str, worker_id: str
) -> BrowserCaptureDispatcher:
    if not database_url.strip() or not worker_id.strip():
        raise RuntimeError("Browser Capture database URL and worker ID are required")

    def connect() -> Any:
        return psycopg.connect(database_url, row_factory=dict_row)

    lease_for = timedelta(seconds=_bounded_int("GEO_JOB_LEASE_SECONDS", 300, 60, 900))
    objects = build_object_store_from_prefix("GEO_BROWSER_ARTIFACT_OBJECT_STORE")
    objects.ensure_bucket()
    store = PostgresDurableJobStore(connect)
    probes = _probes()
    credentials = build_audited_browser_proxy_secret_resolver(
        database_url=database_url,
        service_identity_id=_required_uuid("GEO_BROWSER_CAPTURE_SERVICE_IDENTITY_ID"),
    )
    operation = BrowserCaptureOperation(
        store=store,
        repository=PostgresBrowserCaptureWorkerRepository(connect=connect),
        credentials=credentials,
        artifacts=EncryptedBrowserArtifactWriter(
            objects=objects,
            data_key=_load_key(_required_path("GEO_BROWSER_ARTIFACT_KEY_FILE")),
            key_reference=_required("GEO_BROWSER_ARTIFACT_KEY_REFERENCE"),
            producer_commit=_producer_commit(),
            retention_days=_bounded_int("GEO_BROWSER_ARTIFACT_RETENTION_DAYS", 30, 1, 365),
        ),
        probes=probes,
        browser_runtime_release=_required("GEO_BROWSER_RUNTIME_RELEASE"),
        lease_for=lease_for,
    )
    egress_tests = PostgresBrowserEgressTestRepository(connect=connect)
    return BrowserCaptureDispatcher(
        store=store,
        operation=operation,
        egress_test_operation=BrowserEgressTestOperation(
            store=store, repository=egress_tests, credentials=credentials,
            probes=probes, lease_for=lease_for,
        ),
        egress_tests=egress_tests,
        worker_id=worker_id.strip(),
        lease_for=lease_for,
    )


def _probes() -> tuple[EgressProbe, ...]:
    raw = os.getenv("GEO_BROWSER_EGRESS_PROBES_JSON", "").strip()
    value: object = json.loads(raw) if raw else [
        {
            "source": "ipapi",
            "url": "https://ipapi.co/json/",
            "ip_field": "ip",
            "country_field": "country_code",
            "region_field": "region",
            "asn_field": "asn",
        },
        {
            "source": "ipwhois",
            "url": "https://ipwho.is/",
            "ip_field": "ip",
            "country_field": "country_code",
            "region_field": "region",
            "asn_field": "connection.asn",
        },
    ]
    if not isinstance(value, list) or len(value) < 2:
        raise RuntimeError("GEO_BROWSER_EGRESS_PROBES_JSON requires at least two probes")
    try:
        probes = tuple(
            EgressProbe(
                source=str(item["source"]),
                url=str(item["url"]),
                ip_field=str(item["ip_field"]),
                country_field=str(item["country_field"]),
                region_field=str(item["region_field"]),
                asn_field=str(item["asn_field"]),
            )
            for item in value
            if isinstance(item, dict)
        )
    except KeyError as error:
        raise RuntimeError("Browser Egress probe configuration is incomplete") from error
    if len(probes) != len(value) or len({item.source for item in probes}) < 2:
        raise RuntimeError("Browser Egress probes require distinct named sources")
    return probes


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _required_path(name: str) -> Path:
    path = Path(_required(name))
    if not path.is_file():
        raise RuntimeError(f"{name} must reference a readable file")
    return path


def _required_uuid(name: str) -> UUID:
    try:
        value = UUID(_required(name))
    except ValueError:
        raise RuntimeError(f"{name} must be a UUID") from None
    if value.int == 0:
        raise RuntimeError(f"{name} cannot be nil")
    return value


def _producer_commit() -> str:
    value = _required("GEO_RELEASE_COMMIT")
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise RuntimeError("GEO_RELEASE_COMMIT must be a full lowercase Git SHA")
    return value


def _load_key(path: Path) -> bytes:
    raw = path.read_bytes()
    if len(raw) == 32:
        return raw
    raw = raw.strip()
    candidates = [raw]
    try:
        candidates.append(bytes.fromhex(raw.decode("ascii")))
    except (UnicodeDecodeError, ValueError):
        pass
    try:
        candidates.append(base64.b64decode(raw, validate=True))
    except ValueError:
        pass
    for value in candidates:
        if len(value) == 32:
            return value
    raise RuntimeError("Browser artifact key must decode to exactly 32 bytes")


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except ValueError:
        raise RuntimeError(f"{name} must be an integer") from None
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


__all__ = ["BrowserCaptureDispatcher", "build_browser_capture_dispatcher"]
