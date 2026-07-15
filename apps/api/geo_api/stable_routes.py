"""Stable routers shared by the new internal and customer API applications."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status

from geo_api.contracts import (
    AuthIdentity,
    DevToolsStatus,
    EngineeringStatus,
    EngineeringSyncRequest,
    EngineeringWorkItemList,
    HealthStatus,
    JobAccepted,
    JobStatus,
    LogoutResult,
    OffsetPage,
    ProblemDetails,
    ProjectSummary,
)
from geo_api.foundation_services import FoundationServices
from geo_api.problems import ApiProblem


Surface = Literal["internal", "customer"]
AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
PROBLEM_RESPONSES = {
    status_code: {
        "model": ProblemDetails,
        "description": title,
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
    }
    for status_code, title in (
        (400, "Bad Request"),
        (401, "Unauthorized"),
        (403, "Forbidden"),
        (404, "Not Found"),
        (409, "Conflict"),
        (422, "Validation Error"),
        (503, "Service Unavailable"),
    )
}


def health_router(*, service_name: str, surface: Surface) -> APIRouter:
    router = APIRouter(tags=["service"])

    @router.get("/health", response_model=HealthStatus, operation_id="getHealth")
    def health() -> HealthStatus:
        return HealthStatus(status="ok", service=service_name, surface=surface)

    @router.get(
        "/ready",
        response_model=HealthStatus,
        responses={503: PROBLEM_RESPONSES[503]},
        operation_id="getReadiness",
    )
    def readiness(request: Request) -> HealthStatus:
        if not request.app.state.ready:
            raise ApiProblem(
                status=503,
                title="Service Unavailable",
                detail="The API application has not completed startup.",
                type_uri="urn:geo:problem:not-ready",
            )
        return HealthStatus(status="ready", service=service_name, surface=surface)

    return router


def auth_router() -> APIRouter:
    router = APIRouter(prefix="/v1/auth", tags=["authentication"], responses=PROBLEM_RESPONSES)

    @router.get("/me", response_model=AuthIdentity, operation_id="getCurrentIdentity")
    def current_identity(request: Request, authorization: AuthorizationHeader = None) -> AuthIdentity:
        return _services(request).current_identity(authorization=authorization)

    @router.post("/logout", response_model=LogoutResult, operation_id="logout")
    def logout(request: Request, authorization: AuthorizationHeader = None) -> LogoutResult:
        _services(request).logout(authorization=authorization)
        return LogoutResult()

    return router


def projects_router() -> APIRouter:
    router = APIRouter(prefix="/v1/projects", tags=["projects"], responses=PROBLEM_RESPONSES)

    @router.get("", response_model=OffsetPage[ProjectSummary], operation_id="listProjects")
    def list_projects(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> OffsetPage[ProjectSummary]:
        return _services(request).list_projects(limit=limit, offset=offset)

    return router


def jobs_router() -> APIRouter:
    router = APIRouter(prefix="/v1/jobs", tags=["jobs"], responses=PROBLEM_RESPONSES)

    @router.get("", response_model=OffsetPage[JobStatus], operation_id="listJobs")
    def list_jobs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> OffsetPage[JobStatus]:
        return _services(request).list_jobs(limit=limit, offset=offset)

    @router.get("/{job_id}", response_model=JobStatus, operation_id="getJob")
    def get_job(job_id: UUID, request: Request) -> JobStatus:
        job = _services(request).get_job(job_id=job_id)
        if job is None:
            raise ApiProblem(
                status=404,
                title="Not Found",
                detail="The requested job does not exist.",
                type_uri="urn:geo:problem:job-not-found",
            )
        return job

    return router


def engineering_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/engineering",
        tags=["engineering"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get("/status", response_model=EngineeringStatus, operation_id="getEngineeringStatus")
    def engineering_status() -> EngineeringStatus:
        return EngineeringStatus(capabilities=["code", "ci", "runtime-health"])

    @router.get(
        "/work-items",
        response_model=EngineeringWorkItemList,
        operation_id="listEngineeringWorkItems",
    )
    def list_work_items() -> EngineeringWorkItemList:
        # An empty projection is truthful until the GitHub/CI health adapters are connected.
        return EngineeringWorkItemList(items=[])

    @router.post(
        "/synchronizations",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="requestEngineeringSynchronization",
    )
    def request_sync(payload: EngineeringSyncRequest, request: Request) -> JobAccepted:
        return _services(request).request_engineering_sync(payload)

    return router


def dev_tools_router() -> APIRouter:
    router = APIRouter(prefix="/v1/dev-tools", tags=["development tools"])

    @router.get("/status", response_model=DevToolsStatus, operation_id="getDevToolsStatus")
    def dev_tools_status() -> DevToolsStatus:
        return DevToolsStatus()

    return router


def _services(request: Request) -> FoundationServices:
    return request.app.state.services
