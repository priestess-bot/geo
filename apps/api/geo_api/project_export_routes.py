"""Internal durable and Customer read-only project JSON/CSV exports."""

from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response, status

from geo_api.foundation_services import FoundationServiceUnavailable
from geo_api.monitoring_dependencies import authorize_monitoring_project
from geo_api.problems import ApiProblem
from geo_api.project_export_contracts import (
    AdminProjectExportRequest,
    ProjectExportResponse,
)
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.access.models import AccessPrincipal
from geo_core.project_exports.application import ProjectExportApplication
from geo_core.project_exports.contracts import ExportAudience
from geo_core.project_exports.errors import ProjectExportRuleViolation
from geo_core.project_exports.job_models import ProjectExportArtifact


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]
_ADMIN_ROLES = frozenset({"owner", "admin", "analyst", "viewer"})
_CUSTOMER_ROLES = frozenset({"customer"})


def admin_project_export_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/project-exports",
        tags=["project exports"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "",
        response_model=ProjectExportResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="requestAdminProjectExport",
    )
    def request_export(
        project_id: UUID,
        payload: AdminProjectExportRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ProjectExportResponse:
        principal = _principal(request, authorization, project_id, _ADMIN_ROLES)
        item = _call(
            lambda: _application(request).request_admin(
                principal,
                project_id=project_id,
                campaign_id=payload.campaign_id,
                idempotency_key=idempotency_key,
            )
        )
        return _response(item)

    @router.get(
        "",
        response_model=list[ProjectExportResponse],
        operation_id="listAdminProjectExports",
    )
    def list_exports(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> list[ProjectExportResponse]:
        principal = _principal(request, authorization, project_id, _ADMIN_ROLES)
        items = _call(
            lambda: _application(request).list(
                principal,
                project_id=project_id,
                audience=ExportAudience.ADMIN,
            )
        )
        return [_response(item) for item in items]

    @router.get(
        "/{job_id}/download",
        response_class=Response,
        operation_id="downloadAdminProjectExport",
    )
    def download(
        project_id: UUID,
        job_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Response:
        principal = _principal(request, authorization, project_id, _ADMIN_ROLES)
        artifact = _call(
            lambda: _application(request).download(
                principal,
                project_id=project_id,
                job_id=job_id,
                audience=ExportAudience.ADMIN,
            )
        )
        return _download_response(artifact.content, artifact.content_hash, job_id)

    return router


def customer_project_export_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/project-exports",
        tags=["customer GEO reporting"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get(
        "/campaigns/{campaign_id}/download",
        response_class=Response,
        operation_id="downloadCustomerLatestApprovedProjectExport",
    )
    def download_latest_approved(
        project_id: UUID,
        campaign_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Response:
        principal = _principal(request, authorization, project_id, _CUSTOMER_ROLES)
        archive = _call(
            lambda: _application(request).download_customer_latest_approved(
                principal,
                project_id=project_id,
                campaign_id=campaign_id,
            )
        )
        return _download_response(archive.content, archive.content_hash, campaign_id)

    return router


def _application(request: Request) -> ProjectExportApplication:
    application = request.app.state.project_export_application
    if not isinstance(application, ProjectExportApplication):
        raise FoundationServiceUnavailable("The project export application is not configured.")
    return application


def _principal(
    request: Request,
    authorization: str | None,
    project_id: UUID,
    roles: frozenset[str],
) -> AccessPrincipal:
    return authorize_monitoring_project(request, authorization, project_id, roles)


def _call(operation):
    try:
        return operation()
    except ProjectExportRuleViolation as error:
        detail = str(error)
        if "does not exist" in detail:
            status_code = 404
        elif "not ready" in detail or "idempotency" in detail:
            status_code = 409
        elif "not visible" in detail:
            status_code = 403
        else:
            status_code = 422
        raise ApiProblem(
            status=status_code,
            title="Project Export Error",
            detail=detail,
            type_uri="urn:geo:problem:project-export",
        ) from error


def _response(item: ProjectExportArtifact) -> ProjectExportResponse:
    download_url = (
        f"/v1/projects/{item.project_id}/project-exports/{item.job_id}/download"
        if item.status == "succeeded"
        else None
    )
    return ProjectExportResponse(
        job_id=item.job_id,
        project_id=item.project_id,
        campaign_id=item.campaign_id,
        audience=cast(Literal["admin", "customer"], item.audience.value),
        status=item.status,
        content_hash=item.content_hash,
        manifest_hash=item.manifest_hash,
        byte_count=item.byte_count,
        file_count=item.file_count,
        created_at=item.created_at,
        finalized_at=item.finalized_at,
        error_code=item.error_code,
        download_url=download_url,
    )


def _download_response(content: bytes, content_hash: str, job_id: UUID) -> Response:
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": (f'attachment; filename="geo-project-export-{job_id}.zip"'),
            "ETag": content_hash,
        },
    )
