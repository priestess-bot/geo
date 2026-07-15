"""Problem Details exceptions and FastAPI handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from geo_api.contracts import ProblemDetails
from geo_api.foundation_services import FoundationServiceUnavailable
from geo_core.access.models import (
    AccessConfigurationUnavailable,
    AccessForbidden,
    AccessPersistenceUnavailable,
    AuthenticationRequired,
    CsrfRejected,
    IdempotencyConflict,
    InvitationConsumed,
    InvitationInvalid,
    InvitationSurfaceMismatch,
    MembershipConflict,
    MembershipNotFound,
    MembershipSafetyViolation,
)
from geo_core.placements.domain import (
    ConcurrencyConflict,
    PlacementConflict,
    PlacementNotFound,
    PlacementRuleViolation,
)


_LOGGER = logging.getLogger("geo_api.errors")


class ApiProblem(RuntimeError):
    def __init__(
        self,
        *,
        status: int,
        title: str,
        detail: str,
        type_uri: str = "about:blank",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail
        self.type_uri = type_uri
        self.headers = headers or {}


def install_problem_handlers(app: FastAPI) -> None:
    """Make every framework and application error use one public contract."""

    @app.exception_handler(ApiProblem)
    async def api_problem_handler(request: Request, exc: ApiProblem) -> JSONResponse:
        return _response(request, exc)

    @app.exception_handler(FoundationServiceUnavailable)
    async def unavailable_handler(
        request: Request, exc: FoundationServiceUnavailable
    ) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=503,
                title="Service Unavailable",
                detail=str(exc),
                type_uri="urn:geo:problem:service-unavailable",
                headers={"Retry-After": "30"},
            ),
        )

    @app.exception_handler(AuthenticationRequired)
    async def authentication_handler(request: Request, exc: AuthenticationRequired) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=401,
                title="Unauthorized",
                detail=str(exc),
                type_uri="urn:geo:problem:authentication-required",
                headers={"WWW-Authenticate": "Bearer"},
            ),
        )

    @app.exception_handler(AccessForbidden)
    async def access_forbidden_handler(request: Request, exc: AccessForbidden) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=403,
                title="Forbidden",
                detail=str(exc),
                type_uri="urn:geo:problem:access-forbidden",
            ),
        )

    @app.exception_handler(AccessPersistenceUnavailable)
    async def access_persistence_handler(
        request: Request, exc: AccessPersistenceUnavailable
    ) -> JSONResponse:
        _LOGGER.warning(
            "Access persistence unavailable",
            extra={"request_id": getattr(request.state, "request_id", "unknown")},
        )
        return _response(
            request,
            ApiProblem(
                status=503,
                title="Service Unavailable",
                detail="The access persistence service is unavailable.",
                type_uri="urn:geo:problem:service-unavailable",
                headers={"Retry-After": "30"},
            ),
        )

    @app.exception_handler(AccessConfigurationUnavailable)
    async def access_configuration_handler(
        request: Request, exc: AccessConfigurationUnavailable
    ) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=503,
                title="Service Unavailable",
                detail=str(exc),
                type_uri="urn:geo:problem:access-configuration",
            ),
        )

    @app.exception_handler(CsrfRejected)
    async def csrf_handler(request: Request, exc: CsrfRejected) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=403,
                title="Forbidden",
                detail=str(exc),
                type_uri="urn:geo:problem:csrf-rejected",
            ),
        )

    @app.exception_handler(InvitationInvalid)
    async def invitation_invalid_handler(request: Request, exc: InvitationInvalid) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=400,
                title="Invalid Invitation",
                detail=str(exc),
                type_uri="urn:geo:problem:invitation-invalid",
            ),
        )

    @app.exception_handler(InvitationSurfaceMismatch)
    async def invitation_surface_handler(
        request: Request, exc: InvitationSurfaceMismatch
    ) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=409,
                title="Invitation Surface Mismatch",
                detail=str(exc),
                type_uri="urn:geo:problem:invitation-surface-mismatch",
            ),
        )

    @app.exception_handler(InvitationConsumed)
    async def invitation_conflict_handler(
        request: Request, exc: InvitationConsumed
    ) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=409,
                title="Invitation Conflict",
                detail=str(exc),
                type_uri="urn:geo:problem:invitation-conflict",
            ),
        )

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_conflict_handler(
        request: Request, exc: IdempotencyConflict
    ) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=409,
                title="Idempotency Conflict",
                detail=str(exc),
                type_uri="urn:geo:problem:idempotency-conflict",
            ),
        )

    @app.exception_handler(MembershipNotFound)
    async def membership_not_found_handler(
        request: Request, exc: MembershipNotFound
    ) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=404,
                title="Membership Not Found",
                detail=str(exc),
                type_uri="urn:geo:problem:membership-not-found",
            ),
        )

    @app.exception_handler(MembershipConflict)
    @app.exception_handler(MembershipSafetyViolation)
    async def membership_conflict_handler(request: Request, exc: Exception) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=409,
                title="Membership Conflict",
                detail=str(exc),
                type_uri="urn:geo:problem:membership-conflict",
            ),
        )

    @app.exception_handler(PlacementRuleViolation)
    async def placement_rule_handler(request: Request, exc: PlacementRuleViolation) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=422,
                title="Placement Rule Violation",
                detail=str(exc),
                type_uri="urn:geo:problem:placement-rule-violation",
            ),
        )

    @app.exception_handler(ConcurrencyConflict)
    async def concurrency_handler(request: Request, exc: ConcurrencyConflict) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=409,
                title="Concurrency Conflict",
                detail=str(exc),
                type_uri="urn:geo:problem:stale-version",
            ),
        )

    @app.exception_handler(PlacementConflict)
    async def placement_conflict_handler(request: Request, exc: PlacementConflict) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=409,
                title="Placement State Conflict",
                detail=str(exc),
                type_uri="urn:geo:problem:placement-state-conflict",
            ),
        )

    @app.exception_handler(PlacementNotFound)
    async def placement_not_found_handler(request: Request, exc: PlacementNotFound) -> JSONResponse:
        return _response(
            request,
            ApiProblem(
                status=404,
                title="Placement Resource Not Found",
                detail=str(exc),
                type_uri="urn:geo:problem:placement-not-found",
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = (
            exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        )
        return _response(
            request,
            ApiProblem(
                status=exc.status_code,
                title=_status_title(exc.status_code),
                detail=detail,
                headers=dict(exc.headers or {}),
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors: list[dict[str, object]] = [
            {
                "location": [str(part) for part in error.get("loc", ())],
                "message": str(error.get("msg", "Invalid value")),
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors()
        ]
        return _response(
            request,
            ApiProblem(
                status=422,
                title="Validation Error",
                detail="The request did not satisfy the API contract.",
                type_uri="urn:geo:problem:validation-error",
            ),
            errors=errors,
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        _LOGGER.exception(
            "Unhandled API exception",
            extra={"request_id": getattr(request.state, "request_id", "unknown")},
        )
        return _response(
            request,
            ApiProblem(
                status=500,
                title="Internal Server Error",
                detail="The request could not be completed.",
                type_uri="urn:geo:problem:internal-error",
            ),
        )


def _response(
    request: Request,
    problem: ApiProblem,
    *,
    errors: list[dict[str, object]] | None = None,
) -> JSONResponse:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    payload = ProblemDetails(
        type=problem.type_uri,
        title=problem.title,
        status=problem.status,
        detail=problem.detail,
        instance=request.url.path,
        request_id=request_id,
        errors=errors,
    )
    headers = dict(problem.headers)
    headers.setdefault("X-Request-ID", request_id)
    return JSONResponse(
        status_code=problem.status,
        content=payload.model_dump(mode="json", exclude_none=True),
        headers=headers,
        media_type="application/problem+json",
    )


def _status_title(status: int) -> str:
    return {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        409: "Conflict",
        422: "Validation Error",
        429: "Too Many Requests",
        503: "Service Unavailable",
    }.get(status, "Request Failed")
