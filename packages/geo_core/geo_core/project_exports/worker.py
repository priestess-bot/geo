"""Durable F027 rendering, MinIO storage, and fenced finalization."""

from __future__ import annotations

from datetime import timedelta
from typing import Mapping, Protocol

from geo_core.jobs.postgres import LeaseHeartbeat, PostgresDurableJobStore, WorkerLease
from geo_core.object_store import ObjectStoreError
from geo_core.project_exports.archive import archive_project_export
from geo_core.project_exports.bundle import build_project_export
from geo_core.project_exports.contracts import ExportAudience
from geo_core.project_exports.job_models import (
    ProjectExportClaim,
    project_export_storage_key,
)
from geo_core.project_exports.ports import ProjectExportSource
from geo_core.project_exports.verification import verify_project_export


class StoredObjectLike(Protocol):
    uri: str
    content_hash: str


class ProjectExportObjectStore(Protocol):
    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> StoredObjectLike: ...


class ProjectExportWorkerRepository(Protocol):
    def load_claim(self, lease: WorkerLease) -> ProjectExportClaim: ...

    def finalize(
        self,
        lease: WorkerLease,
        claim: ProjectExportClaim,
        *,
        artifact_uri: str,
        storage_key: str,
        content_hash: str,
        manifest_hash: str,
        byte_count: int,
        file_count: int,
    ) -> Mapping[str, object]: ...


class ProjectExportHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: ProjectExportWorkerRepository,
        source: ProjectExportSource,
        object_store: ProjectExportObjectStore,
        lease_for: timedelta,
    ) -> None:
        self._store = store
        self._repository = repository
        self._source = source
        self._object_store = object_store
        self._lease_for = lease_for

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            claim = self._repository.load_claim(lease)
            export_input = (
                self._source.load_admin(claim.scope)
                if claim.audience == ExportAudience.ADMIN
                else self._source.load_customer_latest_approved(claim.scope)
            )
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                bundle = build_project_export(
                    export_input, generated_at=claim.generated_at
                )
                verify_project_export(bundle.as_mapping())
                archive = archive_project_export(bundle)
                storage_key = project_export_storage_key(
                    claim, bundle.manifest.canonical_hash
                )
                stored = self._object_store.put_object(
                    key=storage_key,
                    content=archive.content,
                    content_type="application/zip",
                    expected_hash=archive.content_hash,
                )
                heartbeat.raise_if_stopped()
            details = self._repository.finalize(
                lease,
                claim,
                artifact_uri=stored.uri,
                storage_key=storage_key,
                content_hash=stored.content_hash,
                manifest_hash=bundle.manifest.canonical_hash,
                byte_count=archive.byte_count,
                file_count=archive.file_count,
            )
            return {"status": "succeeded", "job_id": str(lease.job_id), **details}
        except Exception as error:
            retryable = isinstance(error, ObjectStoreError)
            status = self._store.fail(
                lease,
                error_code=type(error).__name__,
                details={"message": str(error)[:2000]},
                retry_delay=timedelta(seconds=30) if retryable else None,
            )
            return {"status": status, "job_id": str(lease.job_id)}
