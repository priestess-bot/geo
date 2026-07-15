"""Stable routers shared by the new internal and customer API applications."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from geo_api.contracts import (
    AuthIdentity,
    CustomerProjectSummary,
    DevToolsStatus,
    HealthStatus,
    JobStatus,
    LogoutResult,
    OffsetPage,
    ProblemDetails,
    ProjectSummary,
)
from geo_api.foundation_services import AuthenticationInput, FoundationServices
from geo_api.problems import ApiProblem


Surface = Literal["internal", "customer"]
AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    status_code: {
        "model": ProblemDetails,
        "description": title,
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}
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
    def current_identity(
        request: Request, authorization: AuthorizationHeader = None
    ) -> AuthIdentity:
        return services_for_request(request).current_identity(
            authentication_input(request, authorization)
        )

    @router.post("/logout", response_model=LogoutResult, operation_id="logout")
    def logout(
        request: Request,
        response: Response,
        authorization: AuthorizationHeader = None,
    ) -> LogoutResult:
        services_for_request(request).logout(authentication_input(request, authorization))
        if request.app.state.surface == "customer":
            response.delete_cookie(
                request.app.state.customer_session_cookie_name,
                httponly=True,
                secure=request.app.state.cookie_secure,
                samesite="lax",
                path="/",
            )
            response.delete_cookie(
                request.app.state.csrf_cookie_name,
                httponly=False,
                secure=request.app.state.cookie_secure,
                samesite="lax",
                path="/",
            )
        return LogoutResult()

    return router


def projects_router(*, surface: Surface) -> APIRouter:
    router = APIRouter(prefix="/v1/projects", tags=["projects"], responses=PROBLEM_RESPONSES)

    if surface == "internal":

        @router.get("", response_model=OffsetPage[ProjectSummary], operation_id="listProjects")
        def list_internal_projects(
            request: Request,
            authorization: AuthorizationHeader = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 50,
            offset: Annotated[int, Query(ge=0)] = 0,
        ) -> OffsetPage[ProjectSummary]:
            return services_for_request(request).list_internal_projects(
                authentication_input(request, authorization), limit=limit, offset=offset
            )
    else:

        @router.get(
            "", response_model=OffsetPage[CustomerProjectSummary], operation_id="listProjects"
        )
        def list_customer_projects(
            request: Request,
            authorization: AuthorizationHeader = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 50,
            offset: Annotated[int, Query(ge=0)] = 0,
        ) -> OffsetPage[CustomerProjectSummary]:
            return services_for_request(request).list_customer_projects(
                authentication_input(request, authorization), limit=limit, offset=offset
            )

    return router


def jobs_router() -> APIRouter:
    router = APIRouter(prefix="/v1/jobs", tags=["jobs"], responses=PROBLEM_RESPONSES)

    @router.get("", response_model=OffsetPage[JobStatus], operation_id="listJobs")
    def list_jobs(
        request: Request,
        authorization: AuthorizationHeader = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> OffsetPage[JobStatus]:
        return services_for_request(request).list_jobs(
            authentication_input(request, authorization), limit=limit, offset=offset
        )

    @router.get("/{job_id}", response_model=JobStatus, operation_id="getJob")
    def get_job(
        job_id: UUID, request: Request, authorization: AuthorizationHeader = None
    ) -> JobStatus:
        job = services_for_request(request).get_job(
            authentication_input(request, authorization), job_id=job_id
        )
        if job is None:
            raise ApiProblem(
                status=404,
                title="Not Found",
                detail="The requested job does not exist.",
                type_uri="urn:geo:problem:job-not-found",
            )
        return job

    return router


def dev_tools_router() -> APIRouter:
    router = APIRouter(prefix="/v1/dev-tools", tags=["development tools"])

    @router.get("/status", response_model=DevToolsStatus, operation_id="getDevToolsStatus")
    def dev_tools_status() -> DevToolsStatus:
        return DevToolsStatus()

    return router


def services_for_request(request: Request) -> FoundationServices:
    return request.app.state.services


def authentication_input(request: Request, authorization: str | None) -> AuthenticationInput:
    return AuthenticationInput(
        authorization=authorization,
        customer_session=request.cookies.get(request.app.state.customer_session_cookie_name),
        development_actor_id=request.headers.get("X-GEO-Actor-ID"),
        development_tenant_id=request.headers.get("X-GEO-Tenant-ID"),
        csrf_cookie=request.cookies.get(request.app.state.csrf_cookie_name),
        csrf_header=request.headers.get("X-GEO-CSRF-Token"),
    )
