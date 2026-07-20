"""Authorization-preserving API use cases for project exports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.object_store import RetrievedObject
from geo_core.project_exports.archive import (
    ProjectExportArchive,
    archive_project_export,
)
from geo_core.project_exports.bundle import build_project_export
from geo_core.project_exports.contracts import ExportAudience, ProjectExportScope
from geo_core.project_exports.errors import ProjectExportRuleViolation
from geo_core.project_exports.job_models import ProjectExportArtifact
from geo_core.project_exports.ports import ProjectExportSource
from geo_core.project_exports.verification import verify_project_export


class ProjectExportRepository(Protocol):
    def enqueue(
        self,
        *,
        scope: ProjectExportScope,
        audience: ExportAudience,
        requested_by: UUID,
        idempotency_key: str,
    ) -> ProjectExportArtifact: ...

    def list(
        self, *, project_id: UUID, audience: ExportAudience
    ) -> tuple[ProjectExportArtifact, ...]: ...

    def get(
        self, *, project_id: UUID, job_id: UUID, audience: ExportAudience
    ) -> ProjectExportArtifact | None: ...


class ArtifactReader(Protocol):
    def get_object(self, *, key: str, expected_hash: str | None = None) -> RetrievedObject: ...


class ProjectExportApplication:
    def __init__(
        self,
        repository: ProjectExportRepository | None = None,
        artifact_reader: ArtifactReader | None = None,
        *,
        source: ProjectExportSource | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_reader = artifact_reader
        self._source = source
        self._now = now or _utc_now

    def request_admin(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID | None,
        idempotency_key: str,
    ) -> ProjectExportArtifact:
        _authorize(principal, project_id, {"owner", "admin", "analyst", "viewer"})
        _idempotency_key(idempotency_key)
        return self._required_repository().enqueue(
            scope=ProjectExportScope(project_id, campaign_id),
            audience=ExportAudience.ADMIN,
            requested_by=principal.identity_id,
            idempotency_key=idempotency_key,
        )

    def request_customer(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        idempotency_key: str,
    ) -> ProjectExportArtifact:
        _authorize(principal, project_id, {"customer"})
        _idempotency_key(idempotency_key)
        return self._required_repository().enqueue(
            scope=ProjectExportScope(project_id, campaign_id),
            audience=ExportAudience.CUSTOMER,
            requested_by=principal.identity_id,
            idempotency_key=idempotency_key,
        )

    def list(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        audience: ExportAudience,
    ) -> tuple[ProjectExportArtifact, ...]:
        _authorize_audience(principal, project_id, audience)
        return self._required_repository().list(project_id=project_id, audience=audience)

    def get(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
        audience: ExportAudience,
    ) -> ProjectExportArtifact:
        _authorize_audience(principal, project_id, audience)
        result = self._required_repository().get(
            project_id=project_id, job_id=job_id, audience=audience
        )
        if result is None:
            raise ProjectExportRuleViolation("project export does not exist")
        return result

    def download(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
        audience: ExportAudience,
    ) -> RetrievedObject:
        artifact = self.get(
            principal,
            project_id=project_id,
            job_id=job_id,
            audience=audience,
        )
        if (
            artifact.status != "succeeded"
            or artifact.storage_key is None
            or artifact.content_hash is None
        ):
            raise ProjectExportRuleViolation("project export artifact is not ready")
        if self._artifact_reader is None:
            raise ProjectExportRuleViolation("project export artifact reader is not configured")
        return self._artifact_reader.get_object(
            key=artifact.storage_key, expected_hash=artifact.content_hash
        )

    def download_customer_latest_approved(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
    ) -> ProjectExportArchive:
        """Render a read-only Customer ZIP from one repeatable-read DB snapshot."""
        _authorize(principal, project_id, {"customer"})
        if self._source is None:
            raise ProjectExportRuleViolation("customer project export source is not configured")
        export_input = self._source.load_customer_latest_approved(
            ProjectExportScope(project_id, campaign_id)
        )
        bundle = build_project_export(export_input, generated_at=self._now())
        verify_project_export(bundle.as_mapping())
        return archive_project_export(bundle)

    def _required_repository(self) -> ProjectExportRepository:
        if self._repository is None:
            raise ProjectExportRuleViolation("project export repository is not configured")
        return self._repository


def _authorize_audience(
    principal: AccessPrincipal,
    project_id: UUID,
    audience: ExportAudience,
) -> None:
    _authorize(
        principal,
        project_id,
        {"customer"}
        if audience == ExportAudience.CUSTOMER
        else {"owner", "admin", "analyst", "viewer"},
    )


def _authorize(
    principal: AccessPrincipal,
    project_id: UUID,
    allowed_roles: set[str],
) -> None:
    role = next(
        (
            membership.role
            for membership in principal.memberships
            if membership.project_id == project_id
        ),
        None,
    )
    if role not in allowed_roles:
        raise ProjectExportRuleViolation("project export is not visible to this principal")


def _idempotency_key(value: str) -> None:
    if not value.strip() or len(value) > 200:
        raise ProjectExportRuleViolation(
            "project export idempotency key must contain 1 to 200 characters"
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)
