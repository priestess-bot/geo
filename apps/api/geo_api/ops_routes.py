from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse, Response

from geo_api.runtime_metrics import METRICS_CONTENT_TYPE, render_runtime_metrics
from geo_core.runtime import build_runtime_diagnostics, runtime_database_diagnostic


router = APIRouter(tags=["ops"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "geo-production-api"}


@router.get("/ready")
def readiness() -> JSONResponse:
    diagnostic = runtime_database_diagnostic()
    status_code = 200 if diagnostic.status == "pass" else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": diagnostic.status,
            "service": "geo-production-api",
            "checks": [asdict(diagnostic)],
        },
    )


@router.get("/v1/runtime-diagnostics")
def runtime_diagnostics() -> dict[str, object]:
    return build_runtime_diagnostics().to_dict()


@router.get("/metrics")
def runtime_metrics() -> Response:
    return Response(content=render_runtime_metrics(), media_type=METRICS_CONTENT_TYPE)


def register_ops_routes(app: FastAPI) -> None:
    app.include_router(router)
