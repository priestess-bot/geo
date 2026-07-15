"""Problem Details exceptions and FastAPI handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from geo_api.contracts import ProblemDetails
from geo_api.foundation_services import FoundationServiceUnavailable


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

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
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
