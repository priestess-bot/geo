"""F027 API contract tests for audience isolation and ZIP downloads."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from geo_core.access.models import AccessForbidden, AccessPrincipal, MembershipRecord
from geo_core.object_store import RetrievedObject
from geo_core.project_exports.application import ProjectExportApplication
from geo_core.project_exports.contracts import (
    AdminProjectExportInput,
    CustomerLatestApprovedProjectExportInput,
    ExportAudience,
    ProjectExportData,
    ProjectExportScope,
)
from geo_core.project_exports.job_models import ProjectExportArtifact


NOW = datetime(2026, 7, 19, tzinfo=UTC)


class PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def require_project_role(
        self,
        authentication: object,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> AccessPrincipal:
        del authentication
        membership = next(
            (item for item in self.principal.memberships if item.project_id == project_id),
            None,
        )
        if membership is None or membership.role not in allowed_roles:
            raise AccessForbidden("project membership is required")
        return self.principal


class MemoryRepository:
    def __init__(self) -> None:
        self.items: dict[tuple[UUID, ExportAudience], ProjectExportArtifact] = {}

    def enqueue(
        self,
        *,
        scope: ProjectExportScope,
        audience: ExportAudience,
        requested_by: UUID,
        idempotency_key: str,
    ) -> ProjectExportArtifact:
        del requested_by, idempotency_key
        item = ProjectExportArtifact(
            job_id=uuid4(),
            project_id=scope.project_id,
            campaign_id=scope.campaign_id,
            audience=audience,
            status="succeeded",
            artifact_uri="s3://geo/project-export.zip",
            storage_key="project-export.zip",
            content_hash="a" * 64,
            manifest_hash="b" * 64,
            byte_count=7,
            file_count=3,
            created_at=NOW,
            finalized_at=NOW,
            error_code=None,
        )
        self.items[(item.job_id, audience)] = item
        return item

    def list(
        self, *, project_id: UUID, audience: ExportAudience
    ) -> tuple[ProjectExportArtifact, ...]:
        return tuple(
            item
            for (job_id, item_audience), item in self.items.items()
            if job_id and item_audience == audience and item.project_id == project_id
        )

    def get(
        self, *, project_id: UUID, job_id: UUID, audience: ExportAudience
    ) -> ProjectExportArtifact | None:
        item = self.items.get((job_id, audience))
        return item if item and item.project_id == project_id else None


class MemoryReader:
    def get_object(self, *, key: str, expected_hash: str | None = None) -> RetrievedObject:
        assert key == "project-export.zip"
        assert expected_hash == "a" * 64
        return RetrievedObject(
            content=b"ZIPDATA",
            bucket="geo",
            key=key,
            content_type="application/zip",
            content_hash="a" * 64,
            etag=None,
        )


class MemorySource:
    def load_admin(self, scope: ProjectExportScope) -> AdminProjectExportInput:
        raise AssertionError(f"unexpected Admin source read for {scope}")

    def load_customer_latest_approved(
        self, scope: ProjectExportScope
    ) -> CustomerLatestApprovedProjectExportInput:
        return CustomerLatestApprovedProjectExportInput(
            scope=scope,
            data=ProjectExportData.from_mappings(),
        )


def test_f027_api_admin_requests_project_or_campaign_and_downloads_zip() -> None:
    project_id, campaign_id = uuid4(), uuid4()
    app = _app("internal", "admin", project_id)
    with TestClient(app) as client:
        whole = client.post(
            f"/v1/projects/{project_id}/project-exports",
            headers={"Idempotency-Key": "whole-project"},
            json={"campaign_id": None},
        )
        campaign = client.post(
            f"/v1/projects/{project_id}/project-exports",
            headers={"Idempotency-Key": "one-campaign"},
            json={"campaign_id": str(campaign_id)},
        )
        download = client.get(campaign.json()["download_url"])

    assert whole.status_code == campaign.status_code == 202
    assert whole.json()["campaign_id"] is None
    assert campaign.json()["campaign_id"] == str(campaign_id)
    assert download.status_code == 200
    assert download.content == b"ZIPDATA"
    assert download.headers["content-type"] == "application/zip"


def test_f027_api_customer_download_is_read_only_and_campaign_scoped() -> None:
    project_id, campaign_id = uuid4(), uuid4()
    app = _app("customer", "customer", project_id)
    with TestClient(app) as client:
        result = client.get(
            f"/v1/projects/{project_id}/project-exports/campaigns/" f"{campaign_id}/download",
        )
        forbidden_write = client.post(
            f"/v1/projects/{project_id}/project-exports/campaigns/{campaign_id}",
        )

    assert result.status_code == 200
    assert result.content.startswith(b"PK")
    assert result.headers["content-type"] == "application/zip"
    assert result.headers["content-disposition"] == (
        f'attachment; filename="geo-project-export-{campaign_id}.zip"'
    )
    assert forbidden_write.status_code == 404


def _app(surface: str, role: str, project_id: UUID):
    tenant_id, identity_id = uuid4(), uuid4()
    principal = AccessPrincipal(
        identity_id,
        "subject",
        tenant_id,
        (MembershipRecord(project_id, tenant_id, role),),
        "session",
    )
    application = ProjectExportApplication(
        MemoryRepository(),
        MemoryReader(),
        source=MemorySource(),
        now=lambda: NOW,
    )
    return create_api_app(
        surface=surface,  # type: ignore[arg-type]
        services=PrincipalServices(principal),  # type: ignore[arg-type]
        project_export_application=application,
    )
