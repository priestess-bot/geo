"""Fail-closed composition port for the Synthetic Lab Internal API."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from geo_core.access.models import AccessPrincipal


class SyntheticLabApiNotFound(RuntimeError):
    """A Synthetic Lab resource is absent from the authenticated Project scope."""


@dataclass(frozen=True)
class SyntheticPageRead:
    items: tuple[object, ...]
    total: int
    limit: int
    offset: int


class SyntheticLabApi(Protocol):
    def resource_inventory(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> object: ...

    def list_authorizations(
        self, principal: AccessPrincipal, *, project_id: UUID, limit: int, offset: int
    ) -> SyntheticPageRead: ...

    def create_authorization(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def decide_authorization(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        authorization_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def revoke_authorization(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        authorization_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def reassess_authorization(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        authorization_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def list_style_sources(
        self, principal: AccessPrincipal, *, project_id: UUID, limit: int, offset: int
    ) -> SyntheticPageRead: ...

    def create_style_source(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def list_import_previews(
        self, principal: AccessPrincipal, *, project_id: UUID, limit: int, offset: int
    ) -> SyntheticPageRead: ...

    def get_import_preview(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        preview_id: UUID,
    ) -> object: ...

    def create_import_preview(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def approve_import_preview(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        preview_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def reject_import_preview(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        preview_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def list_imported_sample_options(
        self, principal: AccessPrincipal, *, project_id: UUID, limit: int, offset: int
    ) -> SyntheticPageRead: ...

    def list_profiles(
        self, principal: AccessPrincipal, *, project_id: UUID, limit: int, offset: int
    ) -> SyntheticPageRead: ...

    def create_profile(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def freeze_profile(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        profile_version_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def submit_profile(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        profile_version_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def decide_profile(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        profile_version_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def list_suites(
        self, principal: AccessPrincipal, *, project_id: UUID, limit: int, offset: int
    ) -> SyntheticPageRead: ...

    def create_suite(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def freeze_suite(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        suite_version_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def list_cases(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        suite_version_id: UUID,
        limit: int,
        offset: int,
    ) -> SyntheticPageRead: ...

    def create_case(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        suite_version_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def enqueue_job(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_kind: str,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def admit_style_collection(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def get_job(self, principal: AccessPrincipal, *, project_id: UUID, job_id: UUID) -> object: ...

    def cancel_job(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...

    def finalize_job(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
        payload: object,
        idempotency_key: str,
    ) -> object: ...


def build_synthetic_lab_api() -> SyntheticLabApi | None:
    """Resolve a future PostgreSQL adapter; absence keeps every route at 503."""

    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    module_name = "geo_core.synthetic_lab.postgres"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name != module_name:
            raise
        return None
    builder = getattr(module, "build_synthetic_lab_api", None)
    if not callable(builder):
        return None
    return cast(SyntheticLabApi, builder(database_url=database_url))


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct


__all__ = [
    "SyntheticLabApi",
    "SyntheticLabApiNotFound",
    "SyntheticPageRead",
    "build_synthetic_lab_api",
]
