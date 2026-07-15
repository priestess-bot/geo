"""Factory for the isolated GEO internal and customer API applications."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
import os
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.responses import Response

from geo_api.engineering_routes import engineering_router, github_integration_router
from geo_api.engineering_runtime import build_engineering_service
from geo_api.foundation_services import (
    FoundationServices,
    UnavailableFoundationServices,
    services_from_environment,
)
from geo_api.problems import install_problem_handlers
from geo_api.stable_routes import (
    Surface,
    auth_router,
    dev_tools_router,
    health_router,
    jobs_router,
    projects_router,
)


REQUEST_ID_HEADER = "X-Request-ID"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_ACCESS_LOGGER = logging.getLogger("geo_api.access")


@dataclass(frozen=True)
class ApiSettings:
    dev_tools_enabled: bool = False
    customer_session_cookie_name: str = "GEO_CUSTOMER_SESSION"

    @classmethod
    def from_environment(cls) -> "ApiSettings":
        enabled = os.getenv("GEO_DEV_TOOLS_ENABLED", "0").strip().lower() in _TRUE_VALUES
        cookie_name = os.getenv(
            "GEO_CUSTOMER_SESSION_COOKIE_NAME", "GEO_CUSTOMER_SESSION"
        ).strip()
        return cls(
            dev_tools_enabled=enabled,
            customer_session_cookie_name=cookie_name or "GEO_CUSTOMER_SESSION",
        )


def create_api_app(
    *,
    surface: Surface,
    settings: ApiSettings | None = None,
    services: FoundationServices | None = None,
    engineering_service: object | None = None,
) -> FastAPI:
    """Build one API surface without importing the legacy application module."""

    resolved_settings = settings or ApiSettings.from_environment()
    service_name = f"geo-{surface}-api"
    resolved_services = services or services_from_environment(surface=surface)
    service_ready = not isinstance(resolved_services, UnavailableFoundationServices)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.ready = service_ready
        try:
            yield
        finally:
            app.state.ready = False

    app = FastAPI(
        title=f"GEO {surface.title()} API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if surface == "internal" else None,
        redoc_url=None,
    )
    app.state.ready = False
    app.state.surface = surface
    app.state.services = resolved_services
    app.state.customer_session_cookie_name = resolved_settings.customer_session_cookie_name
    app.state.engineering_service = engineering_service or build_engineering_service()
    install_problem_handlers(app)
    _install_request_metadata_middleware(app, surface=surface)

    app.include_router(health_router(service_name=service_name, surface=surface))
    app.include_router(auth_router())
    app.include_router(projects_router(surface=surface))
    app.include_router(jobs_router())
    if surface == "internal":
        app.include_router(engineering_router())
        app.include_router(github_integration_router())
        if resolved_settings.dev_tools_enabled:
            app.include_router(dev_tools_router())
    return app


def _install_request_metadata_middleware(app: FastAPI, *, surface: Surface) -> None:
    @app.middleware("http")
    async def request_metadata(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        started_at = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or "unmatched"
            record = {
                "event": "http_request",
                "request_id": request_id,
                "surface": surface,
                "method": request.method,
                "route": route_path,
                "status_code": status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            }
            _ACCESS_LOGGER.info(json.dumps(record, separators=(",", ":"), sort_keys=True))


def _request_id(candidate: str | None) -> str:
    normalized = (candidate or "").strip()
    if normalized and len(normalized) <= 128 and normalized.isascii():
        return normalized
    return str(uuid4())
