"""Production-only composition root for the isolated Style Collection worker."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import psycopg
from psycopg.rows import dict_row

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LostJobLease,
    PostgresDurableJobStore,
)
from geo_core.object_store_config import build_object_store_from_prefix
from geo_core.synthetic_lab.artifact_keyring import load_synthetic_artifact_keyring
from geo_core.synthetic_lab.artifact_keyring_postgres import (
    PostgresArtifactDekVault,
    synchronize_artifact_master_key_canaries,
)
from geo_core.synthetic_lab.collection_execution import StyleCollectionHandler
from geo_core.synthetic_lab.postgres import PostgresCollectionAuthorizationPort
from geo_core.synthetic_lab.postgres_artifacts import PostgresRawArtifactManifestRepository
from geo_core.synthetic_lab.postgres_style_collection import (
    PostgresStyleCollectionRepository,
)
from geo_core.synthetic_lab.postgres_uow import PostgresSyntheticLabUnitOfWorkFactory
from geo_core.synthetic_lab.raw_artifact_crypto import (
    IndependentDekArtifactEncryptor,
    ProjectTierArtifactEncryptor,
)
from geo_core.synthetic_lab.raw_artifact_storage import (
    GovernedRawArtifactStorage,
    RawArtifactStores,
)
from geo_core.synthetic_lab.style_artifact_processing import (
    ConservativeStyleArtifactInspector,
    ZipStyleTextExtractor,
)
from geo_core.synthetic_lab.style_browser import load_style_adapter_registry
from geo_core.synthetic_lab.postgres_style_secret_resolver import (
    build_audited_style_secret_resolver,
)
from geo_style_worker.browser_adapter import PlaywrightStyleCollector


class StyleCollectionDispatcher:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        handler: StyleCollectionHandler,
        worker_id: str,
        lease_for: timedelta,
    ) -> None:
        self._store = store
        self._handler = handler
        self._worker_id = worker_id
        self._lease_for = lease_for

    def process(self, *, job_id: UUID, project_id: UUID) -> Mapping[str, object]:
        claim = self._store.claim(
            job_id=job_id,
            project_id=project_id,
            expected_kind="style.collect",
            worker_id=self._worker_id,
            lease_for=self._lease_for,
        )
        if claim.lease is None:
            return {"status": claim.disposition, "job_id": str(job_id)}
        try:
            return self._handler.handle(claim.lease)
        except JobCancellationRequested:
            self._store.cancel(claim.lease)
            return {"status": "cancelled", "job_id": str(job_id)}
        except LostJobLease:
            return {"status": "fenced", "job_id": str(job_id)}
        except Exception as error:
            status = self._store.fail(
                claim.lease,
                error_code="style_collection_dispatch",
                details={"classification": type(error).__name__},
                retry_delay=timedelta(seconds=30),
            )
            return {"status": status, "job_id": str(job_id)}


def build_style_collection_dispatcher(
    *,
    database_url: str,
    worker_id: str,
) -> StyleCollectionDispatcher:
    normalized_database_url = database_url.strip()
    normalized_worker_id = worker_id.strip()
    if not normalized_database_url or not normalized_worker_id:
        raise RuntimeError("Style Collection database and worker identities are required")

    def connect() -> Any:
        return psycopg.connect(normalized_database_url, row_factory=dict_row)

    store = PostgresDurableJobStore(connect)
    uow_factory = PostgresSyntheticLabUnitOfWorkFactory(connect)
    registry = load_style_adapter_registry(_required_path("GEO_STYLE_ADAPTER_REGISTRY_FILE"))
    keyring = load_synthetic_artifact_keyring(
        _required_path("GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE")
    )
    synchronize_artifact_master_key_canaries(connect, keyring)
    dek_vault = PostgresArtifactDekVault(keyring)
    raw_object_store = build_object_store_from_prefix(
        "GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE"
    )
    derived_object_store = build_object_store_from_prefix(
        "GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE"
    )
    if raw_object_store.bucket == derived_object_store.bucket:
        raise RuntimeError("Synthetic Style raw and derived artifact buckets must differ")
    raw_object_store.ensure_bucket()
    derived_object_store.ensure_bucket()
    artifact_repository = PostgresRawArtifactManifestRepository(
        store=store,
        dek_vault=dek_vault,
    )
    artifacts = GovernedRawArtifactStorage(
        stores=RawArtifactStores(
            encrypted_raw=raw_object_store,
            restricted_independent_dek=raw_object_store,
            derived_project=derived_object_store,
        ),
        encryptor=IndependentDekArtifactEncryptor(dek_vault),
        tier_encryptor=ProjectTierArtifactEncryptor(keyring),
        repository=artifact_repository,
    )
    lease_for = timedelta(seconds=_bounded_int("GEO_JOB_LEASE_SECONDS", 120, 30, 900))
    robots_timeout = _bounded_int("GEO_STYLE_ROBOTS_TIMEOUT_SECONDS", 10, 1, 60)
    collector = PlaywrightStyleCollector(
        registry=registry,
        chromium_executable=str(_required_path("GEO_STYLE_CHROMIUM_EXECUTABLE")),
        allowed_egress_hosts=_required_hosts("GEO_STYLE_ALLOWED_EGRESS_HOSTS"),
        browser_ws_endpoint=_required_browser_ws_endpoint(),
        http_client=httpx.Client(
            follow_redirects=False,
            timeout=robots_timeout,
            trust_env=False,
        ),
    )
    handler = StyleCollectionHandler(
        store=store,
        repository=PostgresStyleCollectionRepository(connect),
        authorizations=PostgresCollectionAuthorizationPort(uow_factory),
        collector=collector,
        secrets=build_audited_style_secret_resolver(
            database_url=normalized_database_url,
            service_identity_id=_required_uuid("GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID"),
        ),
        extractor=ZipStyleTextExtractor(),
        inspector=ConservativeStyleArtifactInspector(),
        artifacts=artifacts,
        lease_for=lease_for,
    )
    return StyleCollectionDispatcher(
        store=store,
        handler=handler,
        worker_id=normalized_worker_id,
        lease_for=lease_for,
    )


def _required_path(name: str) -> Path:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return Path(value)


def _required_uuid(name: str) -> UUID:
    value = os.getenv(name, "").strip()
    try:
        identity_id = UUID(value)
    except (TypeError, ValueError):
        raise RuntimeError(f"{name} must be a UUID") from None
    if identity_id.int == 0:
        raise RuntimeError(f"{name} cannot be the nil UUID")
    return identity_id


def _required_hosts(name: str) -> tuple[str, ...]:
    values = tuple(
        host.strip().lower() for host in os.getenv(name, "").split(",") if host.strip()
    )
    if not values or len(values) != len(set(values)):
        raise RuntimeError(f"{name} must contain unique hosts")
    return values


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} is outside its supported range")
    return value


def _required_browser_ws_endpoint() -> str:
    value = os.getenv("GEO_STYLE_BROWSER_WS_ENDPOINT", "").strip()
    if value != "ws://style-browser-runtime:9222/":
        raise RuntimeError("GEO_STYLE_BROWSER_WS_ENDPOINT must use the isolated runtime")
    return value


__all__ = ["StyleCollectionDispatcher", "build_style_collection_dispatcher"]
