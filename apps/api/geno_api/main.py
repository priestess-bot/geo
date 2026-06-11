from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from dataclasses import asdict
from collections.abc import Mapping

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, Response

from geno_core.action_plan import (
    build_action_plan_audit_event,
    build_action_recommendations,
    build_retest_schedule,
    build_retest_comparison_audit_event,
    compare_retest_windows,
)
from geno_core.analysis_pipeline import analyze_and_score_records
from geno_core.bootstrap import DEFAULT_AU_COMPETITORS, build_au_project_bootstrap
from geno_core.collection import (
    build_manual_backfill_record,
    build_p0a_collection_plan,
    run_collection_slice,
    run_fixture_collection_slice,
)
from geno_core.collectors import (
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
)
from geno_core.google_spike import (
    build_google_spike_plan,
    evaluate_google_spike_gate,
    evaluate_google_spike_readiness_gate,
    select_google_spike_prompts,
)
from geno_core.graph import build_citation_graph
from geno_core.industry import build_au_dtc_ecommerce_profile
from geno_core.knowledge import (
    build_content_drafts,
    build_content_engine_audit_event,
    build_integration_connectors,
    build_localized_knowledge_facts,
    build_manual_distribution_records,
    search_knowledge_facts,
)
from geno_core.market import build_au_market_profile
from geno_core.models import (
    EntityAliasInput,
    RuntimeHumanReviewInput,
    ManualBackfillInput,
    RuntimeProjectBrandKitInput,
    RuntimeProjectBrandLogoUpload,
    RuntimeProjectMemberDeleteInput,
    RuntimeProjectMemberInput,
    RuntimePromptImportInput,
    RuntimeSavedViewInput,
    RuntimeScoreWeightConfigInput,
)
from geno_core.object_store import ObjectStoreError, archive_project_brand_logo
from geno_core.prompt_import import prompt_import_file_to_csv
from geno_core.report import MarkdownCsvReportExporter
from geno_core.runtime import (
    RuntimePersistenceError,
    build_runtime_diagnostics,
    build_object_store_from_env,
    build_repository_from_env,
    close_repository_connection,
    close_runtime_postgres_pool,
    runtime_database_diagnostic,
    runtime_postgres_pool_snapshot,
)
from geno_core.scoring import get_score_formula, list_score_formulas, normalize_score_weights
from geno_core.traceability import build_traceability_bundle

app = FastAPI(title="GENO SaaS AU API", version="0.1.0")


@app.on_event("shutdown")
def close_runtime_resources() -> None:
    close_runtime_postgres_pool()

RUNTIME_PROJECT_ACCESS_CONTROL_ENV = "GENO_RUNTIME_PROJECT_ACCESS_CONTROL"
RUNTIME_ACTOR_HEADER = "X-GENO-Actor-Id"
RUNTIME_AUTH_MODE_ENV = "GENO_RUNTIME_AUTH_MODE"
RUNTIME_AUTH_MODE_HEADER = "header"
RUNTIME_AUTH_MODE_JWT = "jwt"
RUNTIME_AUTH_MODES = {RUNTIME_AUTH_MODE_HEADER, RUNTIME_AUTH_MODE_JWT}
RUNTIME_JWT_SECRET_ENV = "GENO_RUNTIME_JWT_SECRET"
RUNTIME_JWT_ALGORITHM_ENV = "GENO_RUNTIME_JWT_ALGORITHM"
RUNTIME_JWT_ACTOR_CLAIM_ENV = "GENO_RUNTIME_JWT_ACTOR_CLAIM"
RUNTIME_JWT_ISSUER_ENV = "GENO_RUNTIME_JWT_ISSUER"
RUNTIME_JWT_AUDIENCE_ENV = "GENO_RUNTIME_JWT_AUDIENCE"
RUNTIME_JWT_CLOCK_SKEW_SECONDS_ENV = "GENO_RUNTIME_JWT_CLOCK_SKEW_SECONDS"
RUNTIME_PROJECT_ACCESS_CONTROL_ENABLED_VALUES = {"1", "true", "yes", "on"}
PROJECT_MANAGE_ROLES = ("owner", "admin")
PROJECT_ANALYZE_ROLES = ("owner", "admin", "analyst")
_RUNTIME_JWT_ACTOR_ID: ContextVar[str | None] = ContextVar("geno_runtime_jwt_actor_id", default=None)
METRICS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
REQUEST_ID_HEADER = "X-GENO-Request-Id"
REQUEST_DURATION_BUCKETS_SECONDS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
RUNTIME_ACCESS_LOGGER = logging.getLogger("geno_api.access")
_METRICS_LOCK = threading.Lock()
_REQUEST_TOTAL: defaultdict[tuple[str, str, str], int] = defaultdict(int)
_REQUEST_DURATION_BUCKET_TOTAL: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
_REQUEST_DURATION_SUM: defaultdict[tuple[str, str, str], float] = defaultdict(float)
_REQUEST_DURATION_COUNT: defaultdict[tuple[str, str, str], int] = defaultdict(int)


def runtime_project_access_control_enabled() -> bool:
    return (
        os.getenv(RUNTIME_PROJECT_ACCESS_CONTROL_ENV, "").strip().lower()
        in RUNTIME_PROJECT_ACCESS_CONTROL_ENABLED_VALUES
    )


def runtime_auth_mode() -> str:
    mode = os.getenv(RUNTIME_AUTH_MODE_ENV, RUNTIME_AUTH_MODE_HEADER).strip().lower() or RUNTIME_AUTH_MODE_HEADER
    if mode not in RUNTIME_AUTH_MODES:
        raise HTTPException(status_code=503, detail=f"{RUNTIME_AUTH_MODE_ENV} must be header or jwt")
    return mode


def _runtime_jwt_secret() -> str:
    secret = os.getenv(RUNTIME_JWT_SECRET_ENV, "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail=f"{RUNTIME_JWT_SECRET_ENV} is required when {RUNTIME_AUTH_MODE_ENV}=jwt")
    return secret


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _json_from_base64url(value: str) -> dict[str, object]:
    try:
        decoded = _base64url_decode(value)
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=401, detail="invalid runtime JWT payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="invalid runtime JWT payload")
    return payload


def _runtime_jwt_clock_skew_seconds() -> int:
    raw_value = os.getenv(RUNTIME_JWT_CLOCK_SKEW_SECONDS_ENV, "30").strip() or "30"
    try:
        return max(0, int(raw_value))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"{RUNTIME_JWT_CLOCK_SKEW_SECONDS_ENV} must be an integer") from exc


def decode_runtime_jwt_actor(authorization: str | None) -> str:
    if not authorization or not authorization.strip().lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization Bearer JWT is required when runtime auth mode is jwt")
    token = authorization.strip()[7:].strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="invalid runtime JWT")
    header = _json_from_base64url(parts[0])
    payload = _json_from_base64url(parts[1])
    algorithm = os.getenv(RUNTIME_JWT_ALGORITHM_ENV, "HS256").strip().upper() or "HS256"
    if algorithm != "HS256":
        raise HTTPException(status_code=503, detail="only HS256 runtime JWT verification is currently supported")
    if str(header.get("alg", "")).upper() != algorithm:
        raise HTTPException(status_code=401, detail="runtime JWT algorithm is not allowed")
    expected_signature = hmac.new(
        _runtime_jwt_secret().encode("utf-8"),
        f"{parts[0]}.{parts[1]}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual_signature = _base64url_decode(parts[2])
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid runtime JWT signature") from exc
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise HTTPException(status_code=401, detail="invalid runtime JWT signature")

    now = time.time()
    clock_skew = _runtime_jwt_clock_skew_seconds()
    exp = payload.get("exp")
    if exp is not None and now > float(exp) + clock_skew:
        raise HTTPException(status_code=401, detail="runtime JWT has expired")
    nbf = payload.get("nbf")
    if nbf is not None and now + clock_skew < float(nbf):
        raise HTTPException(status_code=401, detail="runtime JWT is not active yet")
    issuer = os.getenv(RUNTIME_JWT_ISSUER_ENV, "").strip()
    if issuer and payload.get("iss") != issuer:
        raise HTTPException(status_code=401, detail="runtime JWT issuer is not allowed")
    audience = os.getenv(RUNTIME_JWT_AUDIENCE_ENV, "").strip()
    if audience:
        token_audience = payload.get("aud")
        allowed = token_audience if isinstance(token_audience, list) else [token_audience]
        if audience not in allowed:
            raise HTTPException(status_code=401, detail="runtime JWT audience is not allowed")
    actor_claim = os.getenv(RUNTIME_JWT_ACTOR_CLAIM_ENV, "sub").strip() or "sub"
    actor_id = str(payload.get(actor_claim, "")).strip()
    if not actor_id:
        raise HTTPException(status_code=401, detail=f"runtime JWT claim {actor_claim} is required")
    return actor_id


@app.middleware("http")
async def runtime_jwt_actor_middleware(request: Request, call_next):
    actor_token = _RUNTIME_JWT_ACTOR_ID.set(None)
    try:
        if runtime_project_access_control_enabled() and runtime_auth_mode() == RUNTIME_AUTH_MODE_JWT:
            authorization = request.headers.get("authorization")
            if authorization:
                _RUNTIME_JWT_ACTOR_ID.set(decode_runtime_jwt_actor(authorization))
        return await call_next(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    finally:
        _RUNTIME_JWT_ACTOR_ID.reset(actor_token)


def _route_template_for_metrics(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", "")
    if route_path:
        return str(route_path)
    return "__unmatched__"


def _observe_api_request(*, method: str, path: str, status_code: int, duration_seconds: float) -> None:
    label_key = (method.upper(), path, str(status_code))
    with _METRICS_LOCK:
        _REQUEST_TOTAL[label_key] += 1
        _REQUEST_DURATION_SUM[label_key] += duration_seconds
        _REQUEST_DURATION_COUNT[label_key] += 1
        for bucket in REQUEST_DURATION_BUCKETS_SECONDS:
            if duration_seconds <= bucket:
                _REQUEST_DURATION_BUCKET_TOTAL[(*label_key, _format_bucket_label(bucket))] += 1
        _REQUEST_DURATION_BUCKET_TOTAL[(*label_key, "+Inf")] += 1


def _request_id_from_headers(request: Request) -> str:
    raw_request_id = request.headers.get(REQUEST_ID_HEADER) or request.headers.get("X-Request-Id") or ""
    request_id = raw_request_id.strip()
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
    if 1 <= len(request_id) <= 128 and all(char in allowed_chars for char in request_id):
        return request_id
    return uuid.uuid4().hex


def _emit_runtime_access_log(
    *,
    request_id: str,
    method: str,
    path: str,
    route: str,
    status_code: int,
    duration_seconds: float,
    client_host: str | None,
    error_type: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "event_type": "runtime_api_request",
        "log_version": "runtime_access_log_v1",
        "request_id": request_id,
        "method": method.upper(),
        "path": path,
        "route": route,
        "status_code": status_code,
        "duration_ms": round(duration_seconds * 1000, 3),
        "client_host": client_host or "",
    }
    if error_type:
        payload["error_type"] = error_type
    RUNTIME_ACCESS_LOGGER.info(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def reset_runtime_metrics() -> None:
    with _METRICS_LOCK:
        _REQUEST_TOTAL.clear()
        _REQUEST_DURATION_BUCKET_TOTAL.clear()
        _REQUEST_DURATION_SUM.clear()
        _REQUEST_DURATION_COUNT.clear()


def _format_bucket_label(bucket: float) -> str:
    return f"{bucket:g}"


def _format_metric_number(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.12g}"
    return "0"


def _escape_metric_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_labels(labels: Mapping[str, object]) -> str:
    return ",".join(f'{key}="{_escape_metric_label(value)}"' for key, value in labels.items())


def render_runtime_metrics() -> str:
    with _METRICS_LOCK:
        request_total = dict(_REQUEST_TOTAL)
        duration_buckets = dict(_REQUEST_DURATION_BUCKET_TOTAL)
        duration_sum = dict(_REQUEST_DURATION_SUM)
        duration_count = dict(_REQUEST_DURATION_COUNT)

    lines = [
        "# HELP geno_api_requests_total Total HTTP requests handled by the GENO API.",
        "# TYPE geno_api_requests_total counter",
    ]
    for (method, path, status), count in sorted(request_total.items()):
        lines.append(
            f'geno_api_requests_total{{{_metric_labels({"method": method, "path": path, "status": status})}}} {count}'
        )

    lines.extend(
        [
            "# HELP geno_api_request_duration_seconds HTTP request duration in seconds.",
            "# TYPE geno_api_request_duration_seconds histogram",
        ]
    )
    for (method, path, status, le), count in sorted(duration_buckets.items()):
        lines.append(
            "geno_api_request_duration_seconds_bucket"
            f'{{{_metric_labels({"method": method, "path": path, "status": status, "le": le})}}} {count}'
        )
    for (method, path, status), total_seconds in sorted(duration_sum.items()):
        lines.append(
            "geno_api_request_duration_seconds_sum"
            f'{{{_metric_labels({"method": method, "path": path, "status": status})}}} '
            f"{_format_metric_number(total_seconds)}"
        )
    for (method, path, status), count in sorted(duration_count.items()):
        lines.append(
            "geno_api_request_duration_seconds_count"
            f'{{{_metric_labels({"method": method, "path": path, "status": status})}}} {count}'
        )

    lines.extend(
        [
            "# HELP geno_runtime_postgres_pool_snapshot_ok Whether the runtime PostgreSQL pool snapshot could be read.",
            "# TYPE geno_runtime_postgres_pool_snapshot_ok gauge",
        ]
    )
    try:
        pool_snapshot = runtime_postgres_pool_snapshot()
    except RuntimePersistenceError:
        lines.append("geno_runtime_postgres_pool_snapshot_ok 0")
        pool_snapshot = {}
    else:
        lines.append("geno_runtime_postgres_pool_snapshot_ok 1")

    lines.extend(
        [
            "# HELP geno_runtime_postgres_pool_enabled Whether runtime PostgreSQL connection pooling is enabled.",
            "# TYPE geno_runtime_postgres_pool_enabled gauge",
            f"geno_runtime_postgres_pool_enabled {_format_metric_number(pool_snapshot.get('enabled', False))}",
            "# HELP geno_runtime_postgres_pool_max_size Configured runtime PostgreSQL pool maximum size.",
            "# TYPE geno_runtime_postgres_pool_max_size gauge",
            f"geno_runtime_postgres_pool_max_size {_format_metric_number(pool_snapshot.get('max_size', 0))}",
            "# HELP geno_runtime_postgres_pool_timeout_seconds Configured runtime PostgreSQL pool acquire timeout.",
            "# TYPE geno_runtime_postgres_pool_timeout_seconds gauge",
            f"geno_runtime_postgres_pool_timeout_seconds {_format_metric_number(pool_snapshot.get('timeout_seconds', 0.0))}",
            "# HELP geno_runtime_postgres_pool_connections_created Process-local PostgreSQL pool connections created.",
            "# TYPE geno_runtime_postgres_pool_connections_created gauge",
            f"geno_runtime_postgres_pool_connections_created {_format_metric_number(pool_snapshot.get('created', 0))}",
            "# HELP geno_runtime_postgres_pool_connections_available Process-local PostgreSQL pool connections available.",
            "# TYPE geno_runtime_postgres_pool_connections_available gauge",
            f"geno_runtime_postgres_pool_connections_available {_format_metric_number(pool_snapshot.get('available', 0))}",
        ]
    )
    return "\n".join(lines) + "\n"


@app.middleware("http")
async def runtime_metrics_middleware(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    request_id = _request_id_from_headers(request)
    start_time = time.perf_counter()
    status_code = 500
    error_type: str | None = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    except Exception as exc:
        error_type = type(exc).__name__
        raise
    finally:
        duration_seconds = max(0.0, time.perf_counter() - start_time)
        route_path = _route_template_for_metrics(request)
        _observe_api_request(
            method=request.method,
            path=route_path,
            status_code=status_code,
            duration_seconds=duration_seconds,
        )
        _emit_runtime_access_log(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            route=route_path,
            status_code=status_code,
            duration_seconds=duration_seconds,
            client_host=request.client.host if request.client else None,
            error_type=error_type,
        )


def require_runtime_actor_id(x_geno_actor_id: str | None = None) -> str | None:
    if runtime_project_access_control_enabled() and runtime_auth_mode() == RUNTIME_AUTH_MODE_JWT:
        _runtime_jwt_secret()
        actor_id = _RUNTIME_JWT_ACTOR_ID.get()
        if not actor_id:
            raise HTTPException(
                status_code=401,
                detail="Authorization Bearer JWT is required when runtime auth mode is jwt",
            )
        return actor_id
    actor_id = x_geno_actor_id.strip() if x_geno_actor_id else ""
    if runtime_project_access_control_enabled() and not actor_id:
        raise HTTPException(
            status_code=401,
            detail=f"{RUNTIME_ACTOR_HEADER} is required when runtime project access control is enabled",
        )
    return actor_id or None


def apply_runtime_project_db_context(
    repository: object,
    *,
    actor_id: str | None,
    project_id: str | None = None,
) -> None:
    if not runtime_project_access_control_enabled():
        return
    if not actor_id:
        raise HTTPException(
            status_code=401,
            detail=f"{RUNTIME_ACTOR_HEADER} is required when runtime project access control is enabled",
        )
    set_context = getattr(repository, "set_runtime_project_access_context", None)
    if callable(set_context):
        try:
            set_context(actor_id=actor_id, project_id=project_id.strip() if project_id else None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def assert_runtime_project_access(
    repository: object,
    *,
    project_id: str | None,
    actor_id: str | None,
    require_project_id: bool = True,
    allowed_roles: tuple[str, ...] | None = None,
) -> None:
    if not runtime_project_access_control_enabled():
        return
    normalized_project_id = project_id.strip() if project_id else ""
    if require_project_id and not normalized_project_id:
        raise HTTPException(
            status_code=400,
            detail="project_id is required when runtime project access control is enabled",
        )
    if not normalized_project_id:
        return
    if not actor_id:
        raise HTTPException(
            status_code=401,
            detail=f"{RUNTIME_ACTOR_HEADER} is required when runtime project access control is enabled",
        )
    get_project_member_role = getattr(repository, "get_project_member_role", None)
    if callable(get_project_member_role):
        role = get_project_member_role(project_id=normalized_project_id, actor_id=actor_id)
        if role is None:
            raise HTTPException(status_code=403, detail="actor does not have access to project")
        if allowed_roles and role not in allowed_roles:
            allowed = ", ".join(allowed_roles)
            raise HTTPException(status_code=403, detail=f"actor role {role} cannot perform this action; requires {allowed}")
        apply_runtime_project_db_context(
            repository,
            actor_id=actor_id,
            project_id=normalized_project_id,
        )
        return
    if allowed_roles:
        raise HTTPException(
            status_code=503,
            detail="runtime project role checks require repository.get_project_member_role",
        )
    user_can_access_project = getattr(repository, "user_can_access_project", None)
    if not callable(user_can_access_project):
        raise HTTPException(
            status_code=503,
            detail="runtime project access control requires repository.user_can_access_project",
        )
    if not user_can_access_project(project_id=normalized_project_id, actor_id=actor_id):
        raise HTTPException(status_code=403, detail="actor does not have access to project")
    apply_runtime_project_db_context(
        repository,
        actor_id=actor_id,
        project_id=normalized_project_id,
    )


class RuntimeSavedViewRequest(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    view_type: str = Field(default="runtime_evidence", min_length=1, max_length=80)
    filters: dict[str, object] = Field(default_factory=dict)
    sort: str = Field(default="collected_at_desc", max_length=80)
    query_path: str = Field(min_length=1, max_length=1000)
    export_path: str = Field(min_length=1, max_length=1000)
    created_by: str = Field(default="runtime-console", min_length=1, max_length=120)


class ProjectBrandKitRequest(BaseModel):
    project_id: str = Field(min_length=1)
    client_name: str = Field(min_length=1, max_length=160)
    prepared_by: str = Field(default="GENO SaaS AU", min_length=1, max_length=160)
    logo_url: str | None = Field(default=None, max_length=1000)
    primary_color: str | None = Field(default=None, max_length=40)
    secondary_color: str | None = Field(default=None, max_length=40)
    footer_text: str | None = Field(default=None, max_length=500)
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)


class ScoreWeightConfigRequest(BaseModel):
    project_id: str = Field(min_length=1)
    formula_version: str = Field(default="au_visibility_v1", min_length=1, max_length=80)
    weights: dict[str, float]
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=500)


class HumanReviewRequest(BaseModel):
    project_id: str = Field(min_length=1)
    target_type: str = Field(min_length=1, max_length=120)
    target_id: str = Field(min_length=1, max_length=240)
    review_status: str = Field(default="approved", min_length=1, max_length=80)
    decision: str = Field(min_length=1, max_length=240)
    reviewer_id: str = Field(default="runtime-console", min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    payload: dict[str, object] = Field(default_factory=dict)


class RuntimePromptImportRequest(BaseModel):
    project_id: str = Field(min_length=1)
    csv_content: str = Field(min_length=1, max_length=120000)
    imported_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    max_rows: int = Field(default=100, ge=1, le=200)


class ManualBackfillRequest(BaseModel):
    prompt_question_id: str = Field(min_length=1)
    platform: str = Field(default="google", min_length=1, max_length=80)
    surface: str = Field(default="google_ai_mode", min_length=1, max_length=120)
    answer_text: str = Field(min_length=1, max_length=20000)
    citation_urls: list[str] = Field(default_factory=list, max_length=20)
    screenshot_url: str | None = Field(default=None, max_length=1000)
    html_snapshot_url: str | None = Field(default=None, max_length=1000)
    answer_present: bool = True
    surface_triggered: bool = True
    sample_index: int = Field(default=1, ge=1, le=50)
    sample_size: int = Field(default=1, ge=1, le=50)
    device: str = Field(default="desktop", min_length=1, max_length=80)
    account_state: str | None = Field(default=None, max_length=120)
    submitted_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class EntityAliasConfirmRequest(BaseModel):
    entity_id: str = Field(min_length=1)
    entity_kind: str = Field(min_length=1, max_length=40)
    alias: str = Field(min_length=1, max_length=240)
    alias_type: str = Field(default="alias", min_length=1, max_length=80)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    confirmed_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class RuntimeProjectCreateRequest(BaseModel):
    tenant_name: str = Field(default="Design Partner AU", min_length=1, max_length=160)
    project_name: str = Field(default="AU DTC Evidence Pilot", min_length=1, max_length=160)
    target_brand: str = Field(default="ExampleBrand", min_length=1, max_length=160)
    category: str = Field(default="DTC ecommerce products", min_length=1, max_length=200)
    competitors: list[str] = Field(default_factory=list, max_length=5)
    brand_official_domains: list[str] = Field(default_factory=list, max_length=5)
    brand_parent_company: str | None = Field(default=None, max_length=160)
    brand_product_lines: list[str] = Field(default_factory=list, max_length=10)
    owner_user_id: str = Field(default="runtime-console", min_length=1, max_length=120)


class ProjectMemberRequest(BaseModel):
    project_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1, max_length=120)
    role: str = Field(default="viewer", min_length=1, max_length=40)
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class ProjectMemberDeleteRequest(BaseModel):
    project_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1, max_length=120)
    deleted_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class RuntimeFidelityCheckRequest(BaseModel):
    project_id: str = Field(min_length=1)
    report_export_id: str | None = Field(default=None, min_length=1)
    checked_by: str = Field(default="runtime-console", min_length=1, max_length=120)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "geno-saas-au-api"}


@app.get("/ready")
def readiness() -> JSONResponse:
    diagnostic = runtime_database_diagnostic()
    status_code = 200 if diagnostic.status == "pass" else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": diagnostic.status,
            "service": "geno-saas-au-api",
            "checks": [asdict(diagnostic)],
        },
    )


@app.get("/v1/runtime-diagnostics")
def runtime_diagnostics() -> dict[str, object]:
    return build_runtime_diagnostics().to_dict()


@app.get("/metrics")
def runtime_metrics() -> Response:
    return Response(content=render_runtime_metrics(), media_type=METRICS_CONTENT_TYPE)


@app.get("/v1/market-profiles/au")
def au_market_profile() -> dict[str, object]:
    return asdict(build_au_market_profile())


@app.get("/v1/industry-profiles/au/dtc-ecommerce")
def au_dtc_industry_profile() -> dict[str, object]:
    return asdict(build_au_dtc_ecommerce_profile())


@app.get("/v1/prompt-packs/au/dtc-ecommerce")
def au_dtc_prompt_pack() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    return {
        "prompt_version": bootstrap.project.prompt_version,
        "market_code": bootstrap.project.market_code,
        "industry_code": bootstrap.project.industry_code,
        "target_brand": bootstrap.project.target_brand,
        "category": bootstrap.project.category,
        "count": len(bootstrap.prompt_questions),
        "prompts": [asdict(prompt) for prompt in bootstrap.prompt_questions],
    }


@app.get("/v1/project-bootstraps/au/dtc-ecommerce")
def au_dtc_project_bootstrap() -> dict[str, object]:
    return asdict(build_au_project_bootstrap())


@app.post("/v1/projects/runtime/au/dtc-ecommerce")
def create_runtime_au_dtc_project(
    payload: RuntimeProjectCreateRequest | None = None,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    request = payload or RuntimeProjectCreateRequest()
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    owner_user_id = actor_id if runtime_project_access_control_enabled() and actor_id else request.owner_user_id.strip()
    competitors = tuple(item.strip() for item in request.competitors if item.strip())
    if not competitors:
        competitors = DEFAULT_AU_COMPETITORS
    brand_official_domains = tuple(item.strip() for item in request.brand_official_domains if item.strip())
    brand_product_lines = tuple(item.strip() for item in request.brand_product_lines if item.strip())
    try:
        bootstrap = build_au_project_bootstrap(
            tenant_name=request.tenant_name.strip(),
            project_name=request.project_name.strip(),
            target_brand=request.target_brand.strip(),
            category=request.category.strip(),
            competitors=competitors,
            brand_official_domains=brand_official_domains,
            brand_parent_company=request.brand_parent_company.strip() if request.brand_parent_company else None,
            brand_product_lines=brand_product_lines,
            owner_user_id=owner_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        apply_runtime_project_db_context(
            repository,
            actor_id=actor_id,
            project_id=bootstrap.project.id,
        )
        repository.save_project_bootstrap(bootstrap)
        return {
            "tenant_id": bootstrap.tenant.id,
            "project_id": bootstrap.project.id,
            "market_code": bootstrap.project.market_code,
            "industry_code": bootstrap.project.industry_code,
            "prompt_count": len(bootstrap.prompt_questions),
            "competitor_count": len(bootstrap.competitors),
            "audit_event_ids": [event.id for event in bootstrap.audit_events],
            "bootstrap": asdict(bootstrap),
        }
    finally:
        close_repository_connection(repository)


@app.get("/v1/projects/runtime")
def runtime_projects(
    project_id: str | None = None,
    market_code: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        apply_runtime_project_db_context(
            repository,
            actor_id=actor_id,
            project_id=project_id,
        )
        page = repository.list_runtime_projects(
            project_id=project_id,
            market_code=market_code,
            actor_id=actor_id if runtime_project_access_control_enabled() else None,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/project-members/runtime")
def runtime_project_members(
    project_id: str = Query(min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_project_members(project_id=project_id, limit=limit, offset=offset)
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/project-members/runtime")
def save_runtime_project_member(
    payload: ProjectMemberRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(
            repository,
            project_id=payload.project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        try:
            member = repository.save_runtime_project_member(
                RuntimeProjectMemberInput(
                    project_id=payload.project_id.strip(),
                    user_id=payload.user_id.strip(),
                    role=payload.role.strip().lower(),
                    updated_by=actor_id or payload.updated_by.strip(),
                    reason=payload.reason.strip() if payload.reason else None,
                )
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "project not found" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return asdict(member)
    finally:
        close_repository_connection(repository)


@app.delete("/v1/project-members/runtime")
def delete_runtime_project_member(
    payload: ProjectMemberDeleteRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(
            repository,
            project_id=payload.project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        try:
            member = repository.delete_runtime_project_member(
                RuntimeProjectMemberDeleteInput(
                    project_id=payload.project_id.strip(),
                    user_id=payload.user_id.strip(),
                    deleted_by=actor_id or payload.deleted_by.strip(),
                    reason=payload.reason.strip() if payload.reason else None,
                )
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "project member not found" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return asdict(member)
    finally:
        close_repository_connection(repository)


@app.get("/v1/entity-aliases/runtime")
def runtime_entity_aliases(
    project_id: str | None = None,
    entity_kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_entity_aliases(
            project_id=project_id,
            entity_kind=entity_kind,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/entity-aliases/runtime/candidates")
def runtime_entity_alias_candidates(
    project_id: str,
    entity_kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_entity_alias_candidates(
            project_id=project_id,
            entity_kind=entity_kind,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/entity-aliases/runtime/confirm")
def confirm_runtime_entity_alias(
    payload: EntityAliasConfirmRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        try:
            if runtime_project_access_control_enabled():
                apply_runtime_project_db_context(repository, actor_id=actor_id)
                project_id = repository.get_entity_project_id(
                    entity_id=payload.entity_id.strip(),
                    entity_kind=payload.entity_kind.strip(),
                )
                if project_id is None:
                    raise ValueError("entity not found")
                assert_runtime_project_access(
                    repository,
                    project_id=project_id,
                    actor_id=actor_id,
                    allowed_roles=PROJECT_ANALYZE_ROLES,
                )
            record = repository.confirm_entity_alias(
                EntityAliasInput(
                    entity_id=payload.entity_id.strip(),
                    entity_kind=payload.entity_kind.strip(),
                    alias=payload.alias.strip(),
                    alias_type=payload.alias_type.strip(),
                    confidence=payload.confidence,
                    confirmed_by=payload.confirmed_by.strip(),
                    notes=payload.notes.strip() if payload.notes else None,
                )
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "entity not found" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return asdict(record)
    finally:
        close_repository_connection(repository)


@app.get("/v1/prompts/runtime")
def runtime_prompts(
    project_id: str | None = None,
    market_code: str | None = None,
    intent_type: str | None = None,
    city: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_prompts(
            project_id=project_id,
            market_code=market_code,
            intent_type=intent_type,
            city=city,
            status=status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/prompts/runtime/imports")
def runtime_prompt_imports(
    project_id: str | None = None,
    source_format: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_prompt_imports(
            project_id=project_id,
            source_format=source_format,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/prompts/runtime/import.csv")
def import_runtime_prompts_csv(
    payload: RuntimePromptImportRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(
            repository,
            project_id=payload.project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        result = repository.import_runtime_prompts_csv(
            RuntimePromptImportInput(
                project_id=payload.project_id.strip(),
                csv_content=payload.csv_content,
                imported_by=payload.imported_by.strip(),
                max_rows=payload.max_rows,
            )
        )
        return asdict(result)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.post("/v1/prompts/runtime/import.file")
async def import_runtime_prompts_file(
    request: Request,
    project_id: str = Query(min_length=1),
    filename: str = Query(min_length=1, max_length=240),
    imported_by: str = Query(default="runtime-console", min_length=1, max_length=120),
    max_rows: int = Query(default=100, ge=1, le=200),
    content_type: str | None = Header(default=None),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    file_bytes = await request.body()
    try:
        csv_content, source_format = prompt_import_file_to_csv(file_bytes=file_bytes, filename=filename)
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="prompt import file must be UTF-8 encoded") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(
            repository,
            project_id=project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        result = repository.import_runtime_prompts_csv(
            RuntimePromptImportInput(
                project_id=project_id.strip(),
                csv_content=csv_content,
                imported_by=imported_by.strip(),
                max_rows=max_rows,
                source_filename=filename.strip(),
                source_format=source_format,
                source_content_type=content_type,
            )
        )
        return asdict(result)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/collection-plans/au/p0a")
def au_p0a_collection_plan() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    return asdict(
        build_p0a_collection_plan(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
        )
    )


@app.get("/v1/evidence-runs/au/p0a-fixture-slice")
def au_p0a_fixture_slice() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
    )
    return {
        "record_count": len(records),
        "answer_run_ids": [record.answer_run.id for record in records],
        "records": [asdict(record) for record in records],
    }


@app.get("/v1/evidence-runs/runtime")
def runtime_evidence_runs(
    project_id: str | None = None,
    platform: str | None = None,
    city: str | None = None,
    intent_type: str | None = None,
    status: str | None = None,
    sort: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_evidence_runs(
            project_id=project_id,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/collection-runs/runtime")
def runtime_collection_runs(
    project_id: str | None = None,
    run_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_collection_runs(
            project_id=project_id,
            run_type=run_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/evidence-runs/runtime/export.csv")
def runtime_evidence_export_csv(
    project_id: str | None = None,
    platform: str | None = None,
    city: str | None = None,
    intent_type: str | None = None,
    status: str | None = None,
    sort: str | None = None,
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> Response:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        export = repository.export_runtime_evidence_csv(
            project_id=project_id,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return Response(
            content=export.content,
            media_type=export.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{export.filename}"',
                "X-GENO-Evidence-Export-Hash": export.content_hash,
                "X-GENO-Evidence-Export-Row-Count": str(export.row_count),
                "X-GENO-Evidence-Export-Total-Count": str(export.total_count),
                "X-GENO-Evidence-Export-Sort": str(export.filters.get("sort", "collected_at_desc")),
            },
        )
    finally:
        close_repository_connection(repository)


@app.post("/v1/evidence-runs/runtime/manual-backfill")
def runtime_manual_backfill(
    payload: ManualBackfillRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        apply_runtime_project_db_context(repository, actor_id=actor_id)
        prompt = repository.get_runtime_prompt(payload.prompt_question_id)
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt question not found")
        assert_runtime_project_access(
            repository,
            project_id=str(prompt["project_id"]),
            actor_id=actor_id,
            allowed_roles=PROJECT_ANALYZE_ROLES,
        )
        citation_urls = tuple(url.strip() for url in payload.citation_urls if url.strip())
        record = build_manual_backfill_record(
            ManualBackfillInput(
                project_id=str(prompt["project_id"]),
                prompt_question_id=str(prompt["id"]),
                prompt_text=str(prompt["text"]),
                market_code=str(prompt["market_code"]),
                city=str(prompt["city"]),
                language=str(prompt["language"]),
                platform=payload.platform.strip(),
                surface=payload.surface.strip(),
                answer_text=payload.answer_text.strip(),
                citation_urls=citation_urls,
                screenshot_url=payload.screenshot_url.strip() if payload.screenshot_url else None,
                html_snapshot_url=payload.html_snapshot_url.strip() if payload.html_snapshot_url else None,
                answer_present=payload.answer_present,
                surface_triggered=payload.surface_triggered,
                sample_index=payload.sample_index,
                sample_size=payload.sample_size,
                device=payload.device.strip(),
                account_state=payload.account_state.strip() if payload.account_state else None,
                submitted_by=payload.submitted_by.strip(),
                notes=payload.notes.strip() if payload.notes else None,
            )
        )
        repository.save_raw_evidence_records((record,))
        return {
            "answer_run_id": record.answer_run.id,
            "raw_payload_hash": record.raw_answer.raw_payload_hash,
            "citation_count": len(record.citations),
            "evidence_asset_count": len(record.evidence_assets),
            "audit_event_ids": [event.id for event in record.audit_events],
            "record": asdict(record),
        }
    finally:
        close_repository_connection(repository)


@app.get("/v1/runtime-saved-views")
def runtime_saved_views(
    project_id: str | None = None,
    view_type: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_saved_views(
            project_id=project_id,
            view_type=view_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/runtime-saved-views")
def save_runtime_saved_view(
    payload: RuntimeSavedViewRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(
            repository,
            project_id=payload.project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        saved_view = repository.save_runtime_saved_view(
            RuntimeSavedViewInput(
                project_id=payload.project_id,
                name=payload.name.strip(),
                view_type=payload.view_type,
                filters=payload.filters,
                sort=payload.sort,
                query_path=payload.query_path,
                export_path=payload.export_path,
                created_by=payload.created_by,
            )
        )
        return asdict(saved_view)
    finally:
        close_repository_connection(repository)


@app.get("/v1/project-brand-kits/runtime")
def runtime_project_brand_kit(
    project_id: str = Query(min_length=1),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        brand_kit = repository.get_project_brand_kit(project_id=project_id)
        if brand_kit is None:
            raise HTTPException(status_code=404, detail="Project brand kit not found")
        return asdict(brand_kit)
    finally:
        close_repository_connection(repository)


@app.post("/v1/project-brand-kits/runtime")
def save_runtime_project_brand_kit(
    payload: ProjectBrandKitRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(
            repository,
            project_id=payload.project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        brand_kit = repository.save_project_brand_kit(
            RuntimeProjectBrandKitInput(
                project_id=payload.project_id.strip(),
                client_name=payload.client_name.strip(),
                prepared_by=payload.prepared_by.strip(),
                logo_url=payload.logo_url.strip() if payload.logo_url else None,
                primary_color=payload.primary_color.strip() if payload.primary_color else None,
                secondary_color=payload.secondary_color.strip() if payload.secondary_color else None,
                footer_text=payload.footer_text.strip() if payload.footer_text else None,
                updated_by=payload.updated_by.strip(),
            )
        )
        return asdict(brand_kit)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.post("/v1/project-brand-kits/runtime/logo")
async def upload_runtime_project_brand_logo(
    request: Request,
    project_id: str = Query(min_length=1),
    filename: str = Query(min_length=1, max_length=240),
    uploaded_by: str = Query(default="runtime-console", min_length=1, max_length=120),
    content_type: str | None = Header(default=None),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    file_bytes = await request.body()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="brand logo file is empty")
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(
            repository,
            project_id=project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        if repository.list_runtime_projects(project_id=project_id.strip(), limit=1, offset=0).total_count == 0:
            raise HTTPException(status_code=404, detail="project not found")
        try:
            store = build_object_store_from_env()
            stored = archive_project_brand_logo(
                project_id=project_id.strip(),
                filename=filename.strip(),
                content=file_bytes,
                content_type=content_type,
                store=store,
            )
        except ObjectStoreError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        brand_kit = repository.upload_project_brand_logo(
            RuntimeProjectBrandLogoUpload(
                project_id=project_id.strip(),
                logo_url=stored.uri,
                filename=filename.strip(),
                content_type=stored.content_type,
                content_hash=stored.content_hash,
                uploaded_by=uploaded_by.strip(),
            )
        )
        return asdict(brand_kit)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/score-weight-configs/runtime")
def runtime_score_weight_config(
    project_id: str = Query(min_length=1),
    formula_version: str = Query(default="au_visibility_v1", min_length=1),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        formula = get_score_formula(formula_version)
        config = repository.get_score_weight_config(project_id=project_id, formula_version=formula.formula_version)
        if config is None:
            return {
                "score_weight_config": {
                    "id": None,
                    "project_id": project_id,
                    "formula_version": formula.formula_version,
                    "weights": formula.weights,
                    "updated_by": "system-default",
                    "notes": f"Default {formula.formula_version} score weights",
                },
                "audit_events": [],
            }
        return asdict(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.post("/v1/score-weight-configs/runtime")
def save_runtime_score_weight_config(
    payload: ScoreWeightConfigRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        weights = normalize_score_weights(payload.weights, formula_version=payload.formula_version.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(
            repository,
            project_id=payload.project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        config = repository.save_score_weight_config(
            RuntimeScoreWeightConfigInput(
                project_id=payload.project_id.strip(),
                formula_version=payload.formula_version.strip(),
                weights=weights,
                updated_by=payload.updated_by.strip(),
                notes=payload.notes.strip() if payload.notes else None,
            )
        )
        return asdict(config)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/score-formulas/runtime")
def runtime_score_formulas() -> dict[str, object]:
    return {"formulas": list_score_formulas()}


@app.get("/v1/human-reviews/runtime")
def runtime_human_reviews(
    project_id: str | None = None,
    target_type: str | None = None,
    review_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_human_reviews(
            project_id=project_id,
            target_type=target_type,
            review_status=review_status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/human-reviews/runtime/queue")
def runtime_human_review_queue(
    project_id: str | None = None,
    target_type: str | None = None,
    queue_status: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_human_review_queue(
            project_id=project_id,
            target_type=target_type,
            queue_status=queue_status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/human-reviews/runtime")
def record_runtime_human_review(
    payload: HumanReviewRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(
            repository,
            project_id=payload.project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_ANALYZE_ROLES,
        )
        record = repository.save_human_review(
            RuntimeHumanReviewInput(
                project_id=payload.project_id.strip(),
                target_type=payload.target_type.strip(),
                target_id=payload.target_id.strip(),
                review_status=payload.review_status.strip(),
                decision=payload.decision.strip(),
                reviewer_id=payload.reviewer_id.strip(),
                notes=payload.notes.strip() if payload.notes else None,
                payload=payload.payload,
            )
        )
        return asdict(record)
    except ValueError as exc:
        status_code = 404 if str(exc) in {"project not found", "content draft not found"} else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/visibility-scores/runtime")
def runtime_visibility_scores(
    project_id: str | None = None,
    scope_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_score_snapshots(
            project_id=project_id,
            scope_type=scope_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/citation-graphs/runtime")
def runtime_citation_graphs(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_citation_graphs(
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/reports/runtime")
def runtime_reports(
    project_id: str | None = None,
    report_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_report_exports(
            project_id=project_id,
            report_type=report_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/fidelity-checks/runtime")
def runtime_fidelity_checks(
    project_id: str | None = None,
    report_export_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        if runtime_project_access_control_enabled() and report_export_id and not project_id:
            apply_runtime_project_db_context(repository, actor_id=actor_id)
            project_id = repository.get_report_export_project_id(report_export_id=report_export_id)
            if project_id is None:
                raise HTTPException(status_code=404, detail="report_export not found")
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_fidelity_checks(
            project_id=project_id,
            report_export_id=report_export_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/fidelity-checks/runtime/trend")
def runtime_fidelity_trend(
    project_id: str | None = None,
    report_export_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        if runtime_project_access_control_enabled() and report_export_id and not project_id:
            apply_runtime_project_db_context(repository, actor_id=actor_id)
            project_id = repository.get_report_export_project_id(report_export_id=report_export_id)
            if project_id is None:
                raise HTTPException(status_code=404, detail="report_export not found")
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        trend = repository.get_runtime_fidelity_trend(
            project_id=project_id,
            report_export_id=report_export_id,
            limit=limit,
        )
        return asdict(trend)
    finally:
        close_repository_connection(repository)


@app.post("/v1/fidelity-checks/runtime")
def create_runtime_fidelity_check(
    payload: RuntimeFidelityCheckRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(
            repository,
            project_id=payload.project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_ANALYZE_ROLES,
        )
        check = repository.create_runtime_fidelity_check(
            project_id=payload.project_id.strip(),
            report_export_id=payload.report_export_id.strip() if payload.report_export_id else None,
            checked_by=payload.checked_by.strip(),
        )
        return asdict(check)
    except ValueError as exc:
        status_code = 404 if str(exc) in {"project not found", "report_export not found"} else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/reports/runtime/{report_export_id}/artifact")
def runtime_report_artifact(
    report_export_id: str,
    artifact_type: str = Query(default="markdown", alias="type", pattern="^(markdown|csv|pdf)$"),
    template: str = Query(default="standard", pattern="^(standard|white_label)$"),
    client_name: str | None = None,
    prepared_by: str | None = None,
    platform: str | None = None,
    city: str | None = None,
    intent_type: str | None = None,
    status: str | None = None,
    sort: str | None = None,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> Response:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        if runtime_project_access_control_enabled():
            apply_runtime_project_db_context(repository, actor_id=actor_id)
            project_id = repository.get_report_export_project_id(report_export_id=report_export_id)
            assert_runtime_project_access(
                repository,
                project_id=project_id,
                actor_id=actor_id,
                require_project_id=project_id is not None,
            )
        artifact = repository.get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type=artifact_type,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
            template=template,
            client_name=client_name,
            prepared_by=prepared_by,
        )
        if artifact is None:
            raise HTTPException(status_code=404, detail="Runtime report artifact not found")
        return Response(
            content=artifact.content,
            media_type=artifact.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{artifact.filename}"',
                "X-GENO-Report-Artifact-Hash": artifact.content_hash,
                "X-GENO-Report-Artifact-Filter-Hash": artifact.filter_hash,
                "X-GENO-Report-Artifact-Template": artifact.template,
                "X-GENO-Report-Artifact-Template-Hash": artifact.template_hash,
                "X-GENO-Report-Artifact-Sort": artifact.sort,
                "X-GENO-Report-Artifact-Row-Count": str(artifact.row_count),
                "X-GENO-Report-Artifact-Total-Count": str(artifact.total_count),
            },
        )
    finally:
        close_repository_connection(repository)


@app.get("/v1/action-plans/runtime")
def runtime_action_plans(
    project_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_action_plans(
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/runtime-alerts")
def runtime_alerts(
    project_id: str | None = None,
    alert_type: str | None = None,
    severity: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_alerts(
            project_id=project_id,
            alert_type=alert_type,
            severity=severity,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/content-engines/runtime")
def runtime_content_engines(
    project_id: str | None = None,
    review_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_content_engines(
            project_id=project_id,
            review_status=review_status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/knowledge-facts/runtime/search")
def runtime_knowledge_fact_search(
    project_id: str = Query(min_length=1),
    query: str = Query(min_length=1),
    market_code: str = Query(default="AU", min_length=1, max_length=20),
    city: str | None = None,
    embedding_model: str = Query(default="fixture-knowledge-embedding-v1", min_length=1, max_length=120),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.search_runtime_knowledge_facts(
            project_id=project_id,
            query=query,
            market_code=market_code,
            city=city,
            embedding_model=embedding_model,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/traceability/runtime")
def runtime_traceability(
    project_id: str | None = None,
    report_export_id: str | None = None,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        if runtime_project_access_control_enabled() and report_export_id and not project_id:
            apply_runtime_project_db_context(repository, actor_id=actor_id)
            project_id = repository.get_report_export_project_id(report_export_id=report_export_id)
            if project_id is None:
                raise HTTPException(status_code=404, detail="report_export not found")
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        detail = repository.get_runtime_traceability_detail(
            project_id=project_id,
            report_export_id=report_export_id,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="Runtime traceability bundle not found")
        return asdict(detail)
    finally:
        close_repository_connection(repository)


@app.get("/v1/google-spikes/au/plan")
def au_google_spike_plan() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    return asdict(build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions))


@app.get("/v1/google-spikes/au/fixture-gate")
def au_google_spike_fixture_gate() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
    prompts = select_google_spike_prompts(bootstrap.prompt_questions)
    records = run_collection_slice(
        project_id=bootstrap.project.id,
        prompts=prompts,
        market_profile=bootstrap.market_profile,
        collectors=(FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector()),
        cities=plan.geo_cities,
        sample_size=plan.sample_size,
        prompt_limit=plan.prompt_count,
    )
    gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
    readiness_gate = evaluate_google_spike_readiness_gate(project_id=bootstrap.project.id, plan=plan, records=records)
    return {
        "plan": asdict(plan),
        "gate": asdict(gate),
        "readiness_gate": asdict(readiness_gate),
        "record_count": len(records),
    }


@app.get("/v1/visibility-scores/au/p0a-fixture")
def au_p0a_fixture_visibility_score() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
        scope_type="project",
        scope_value="p0a_fixture",
    )
    return {
        "analysis_count": len(result.analyses),
        "snapshot": asdict(result.snapshot),
        "contributions": [asdict(contribution) for contribution in result.contributions],
        "audit_event": asdict(result.audit_event),
    }


@app.get("/v1/citation-graphs/au/p0a-fixture")
def au_p0a_fixture_citation_graph() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.score_input_analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    return {
        "node_count": len(graph.nodes),
        "evidence_link_count": len(graph.evidence_links),
        "source_gap_count": len(graph.source_gaps),
        "competitor_count": len(graph.competitor_benchmarks),
        "nodes": [asdict(node) for node in graph.nodes],
        "source_gaps": [asdict(gap) for gap in graph.source_gaps],
        "competitor_benchmarks": [asdict(item) for item in graph.competitor_benchmarks],
    }


@app.get("/v1/reports/au/p0a-fixture")
def au_p0a_fixture_report() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.score_input_analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    google_plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
    google_gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=google_plan, records=())
    report = MarkdownCsvReportExporter().export(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        report_version="p0a-fixture-v1",
        report_type="design_partner_fixture",
        prompt_version=bootstrap.project.prompt_version,
        snapshot=analysis_result.snapshot,
        contributions=analysis_result.contributions,
        records=records,
        graph=graph,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
        google_spike_gate=google_gate,
        score_input_policy=analysis_result.score_input_policy,
    )
    return {
        "report_export": asdict(report.report_export),
        "markdown": report.markdown,
        "csv_content": report.csv_content,
        "pdf_content_hash": hashlib.sha256(report.pdf_content).hexdigest(),
        "pdf_size_bytes": len(report.pdf_content),
        "audit_event": asdict(report.audit_event),
        "report_evidence_answer_run_ids": list(report.report_evidence_answer_run_ids),
    }


@app.get("/v1/action-plans/au/p0a-fixture")
def au_p0a_fixture_action_plan() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.score_input_analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    actions = build_action_recommendations(
        project_id=bootstrap.project.id,
        graph=graph,
        snapshot=analysis_result.snapshot,
    )
    schedule = build_retest_schedule(
        project_id=bootstrap.project.id,
        prompt_version=bootstrap.project.prompt_version,
        sample_size=1,
        answer_run_ids=tuple(record.answer_run.id for record in records),
    )
    audit_event = build_action_plan_audit_event(
        project_id=bootstrap.project.id,
        actions=actions,
        schedule=schedule,
    )
    retest_snapshot = analysis_result.snapshot.__class__(
        **{
            **asdict(analysis_result.snapshot),
            "id": f"retest-{analysis_result.snapshot.id}",
            "final_score": round(analysis_result.snapshot.final_score + 2.5, 4),
        }
    )
    comparison = compare_retest_windows(
        project_id=bootstrap.project.id,
        baseline=analysis_result.snapshot,
        retest=retest_snapshot,
    )
    comparison_audit_event = build_retest_comparison_audit_event(
        project_id=bootstrap.project.id,
        comparison=comparison,
    )
    return {
        "action_count": len(actions),
        "actions": [asdict(action) for action in actions],
        "retest_schedule": asdict(schedule),
        "retest_comparison": asdict(comparison),
        "audit_event": asdict(audit_event),
        "comparison_audit_event": asdict(comparison_audit_event),
    }


@app.get("/v1/content-engines/au/p0a-fixture")
def au_p0a_fixture_content_engine() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.score_input_analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    actions = build_action_recommendations(
        project_id=bootstrap.project.id,
        graph=graph,
        snapshot=analysis_result.snapshot,
    )
    answer_run_ids = tuple(record.answer_run.id for record in records)
    facts = build_localized_knowledge_facts(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        brand=bootstrap.brand,
        category=bootstrap.project.category,
        answer_run_ids=answer_run_ids,
    )
    knowledge_results = search_knowledge_facts(
        facts=facts,
        query=f"{bootstrap.project.target_brand} {bootstrap.project.category} Australia shipping reviews",
        market_code=bootstrap.project.market_code,
        city="Sydney",
        limit=5,
    )
    drafts = build_content_drafts(
        project_id=bootstrap.project.id,
        target_brand=bootstrap.project.target_brand,
        category=bootstrap.project.category,
        actions=actions,
        prompts=bootstrap.prompt_questions,
        knowledge_results=knowledge_results,
    )
    connectors = build_integration_connectors(project_id=bootstrap.project.id)
    distribution_records = build_manual_distribution_records(project_id=bootstrap.project.id, drafts=drafts)
    audit_event = build_content_engine_audit_event(
        project_id=bootstrap.project.id,
        facts=facts,
        drafts=drafts,
        connectors=connectors,
        distribution_records=distribution_records,
    )
    return {
        "knowledge_fact_count": len(facts),
        "search_results": [asdict(result) for result in knowledge_results],
        "content_draft_count": len(drafts),
        "content_drafts": [asdict(draft) for draft in drafts],
        "integration_connectors": [asdict(connector) for connector in connectors],
        "manual_distribution_records": [asdict(record) for record in distribution_records],
        "audit_event": asdict(audit_event),
    }


@app.get("/v1/traceability/au/p0a-fixture")
def au_p0a_fixture_traceability() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.score_input_analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    report = MarkdownCsvReportExporter().export(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        report_version="p0a-fixture-v1",
        report_type="design_partner_fixture",
        prompt_version=bootstrap.project.prompt_version,
        snapshot=analysis_result.snapshot,
        contributions=analysis_result.contributions,
        records=records,
        graph=graph,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
        score_input_policy=analysis_result.score_input_policy,
    )
    actions = build_action_recommendations(
        project_id=bootstrap.project.id,
        graph=graph,
        snapshot=analysis_result.snapshot,
    )
    facts = build_localized_knowledge_facts(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        brand=bootstrap.brand,
        category=bootstrap.project.category,
        answer_run_ids=tuple(record.answer_run.id for record in records),
    )
    knowledge_results = search_knowledge_facts(
        facts=facts,
        query=f"{bootstrap.project.target_brand} {bootstrap.project.category} Australia shipping reviews",
        market_code=bootstrap.project.market_code,
        city="Sydney",
        limit=5,
    )
    drafts = build_content_drafts(
        project_id=bootstrap.project.id,
        target_brand=bootstrap.project.target_brand,
        category=bootstrap.project.category,
        actions=actions,
        prompts=bootstrap.prompt_questions,
        knowledge_results=knowledge_results,
    )
    bundle = build_traceability_bundle(
        project_id=bootstrap.project.id,
        report_export=report.report_export,
        snapshot=analysis_result.snapshot,
        contributions=analysis_result.contributions,
        records=records,
        graph=graph,
        actions=actions,
        content_drafts=drafts,
        audit_events=tuple(record.audit_events[0] for record in records)
        + (analysis_result.audit_event, report.audit_event),
    )
    return {
        "traceability_bundle": asdict(bundle),
        "report_export": asdict(report.report_export),
        "score_contribution_count": len(analysis_result.contributions),
        "answer_run_count": len(records),
    }


@app.get("/v1/contracts")
def contracts() -> dict[str, list[str]]:
    return {
        "interfaces": [
            "CollectorBackend",
            "LLMGateway",
            "ParserEngine",
            "VectorStore",
            "GraphStore",
            "GeoProvider",
            "ScoringFormula",
            "ReportExporter",
            "NotConfiguredCollectorBackend",
            "NotConfiguredParserEngine",
            "NotConfiguredScoringFormula",
            "NotConfiguredReportExporter",
            "RegistryScoringFormula",
        ],
        "auditability": [
            "AuditEvent",
            "EvidenceLink",
            "LLMCallLog",
            "ScoreContribution",
            "ReportExport",
            "RuntimeHumanReviewRecord",
            "RuntimeHumanReviewQueuePage",
            "RuntimeFidelityCheck",
            "RuntimeFidelityTrend",
            "RuntimeAlertItem",
            "RuntimeAlertPage",
            "TraceabilityBundle",
        ],
        "m1_bootstrap": [
            "Tenant",
            "Project",
            "ProjectMember",
            "BrandEntity",
            "CompetitorEntity",
            "EntityAlias",
            "EntityAliasInput",
            "RuntimeEntityAlias",
            "RuntimeEntityAliasCandidate",
            "RuntimeEntityAliasCandidatePage",
            "RuntimeEntityAliasPage",
            "IndustryProfile",
            "PromptQuestion",
            "ProjectBootstrap",
        ],
        "m2a_evidence": [
            "CollectionPlan",
            "BrowserFidelitySamplingPlan",
            "AnswerRun",
            "RawAnswer",
            "AnswerCitation",
            "EvidenceAsset",
            "CollectorLog",
            "CollectionCost",
            "CollectionRunSummary",
            "P0ACollectionReadinessGate",
            "evaluate_p0a_collection_readiness",
            "build_browser_fidelity_sampling_plan",
            "RuntimeFidelityCheck",
            "RuntimeFidelityCheckPage",
            "RuntimeFidelityTrend",
            "RuntimeFidelityTrendPoint",
            "RawEvidenceRecord",
            "CollectionFailureRecord",
            "ManualBackfillInput",
            "PerplexitySonarCollector",
            "OpenAIWebSearchCollector",
            "FixtureChatGPTSearchBrowserCollector",
            "PlaywrightChatGPTSearchCollector",
        ],
        "m2b_google_spike": [
            "GoogleSpikePlan",
            "GoogleSpikeGateResult",
            "GoogleSpikeReadinessGate",
            "evaluate_google_spike_readiness_gate",
            "PlaywrightGoogleAIOCollector",
            "PlaywrightAIModeCollector",
            "ThirdPartySerpCollector",
            "ManualBackfillCollector",
        ],
        "m3_analysis_scoring": [
            "RuleBasedAnswerParser",
            "LLMJudgeAnswerParser",
            "ComparativeAnswerParser",
            "parser_ab_compare_v1",
            "llm_judge_prompt_v1",
            "FixtureLLMGateway",
            "LiteLLMGateway",
            "LLMCallLog",
            "AnswerAnalysis",
            "VisibilityScoreSnapshot",
            "ScoreContribution",
            "RuntimeScoreWeightConfig",
            "RuntimeScoreWeightConfigInput",
            "ScoreWeightConfigRequest",
            "ScoreFormulaDefinition",
            "RegistryScoringFormula",
            "SCORE_FORMULA_REGISTRY",
            "list_score_formulas",
            "build_score_input_policy",
            "rescore_snapshot_with_formula",
            "RuntimeHumanReviewRecord",
            "RuntimeHumanReviewPage",
            "RuntimeHumanReviewQueueItem",
            "RuntimeHumanReviewQueuePage",
            "RuntimeHumanReviewInput",
            "HumanReviewRequest",
            "au_visibility_v1",
        ],
        "m4_graph_benchmark": [
            "SourceGraphNode",
            "SourceGraphEvidence",
            "SourceGap",
            "CompetitorBenchmark",
            "CitationGraphResult",
        ],
        "m5_report_export": [
            "ReportExport",
            "MarkdownCsvReportExporter",
            "EvidenceReport",
        ],
        "m6_action_retest": [
            "ActionRecommendation",
            "RetestSchedule",
            "RetestComparison",
        ],
        "m7_content_integrations": [
            "LocalizedKnowledgeFact",
            "KnowledgeSearchResult",
            "KnowledgeFactEmbedding",
            "RuntimeKnowledgeSearchResult",
            "RuntimeKnowledgeSearchPage",
            "ContentDraft",
            "IntegrationConnector",
            "ManualDistributionRecord",
        ],
        "traceability": [
            "EvidenceLink",
            "TraceabilityBundle",
            "build_traceability_bundle",
        ],
        "persistence": [
            "build_repository_from_env",
            "build_object_store_from_env",
            "build_runtime_diagnostics",
            "RuntimeComponentDiagnostic",
            "RuntimeDiagnostics",
            "connect_postgres_from_env",
            "close_repository_connection",
            "runtime_database_diagnostic",
            "runtime_object_store_diagnostic",
            "runtime_auth_diagnostic",
            "RuntimePersistenceError",
            "PostgresEvidenceRepository",
            "save_project_bootstrap",
            "archive_project_brand_logo",
            "RuntimeProject",
            "RuntimeProjectPage",
            "RuntimeProjectCreateRequest",
            "RuntimeProjectMember",
            "RuntimeProjectMemberPage",
            "RuntimeProjectMemberInput",
            "ProjectMemberRequest",
            "RuntimeProjectMemberDeleteInput",
            "ProjectMemberDeleteRequest",
            "RuntimeProjectBrandKit",
            "RuntimeProjectBrandKitInput",
            "RuntimeProjectBrandLogoUpload",
            "ProjectBrandKitRequest",
            "RuntimeScoreWeightConfig",
            "RuntimeScoreWeightConfigInput",
            "ScoreWeightConfigRequest",
            "ScoreFormulaDefinition",
            "RuntimeHumanReviewRecord",
            "RuntimeHumanReviewPage",
            "RuntimeHumanReviewQueueItem",
            "RuntimeHumanReviewQueuePage",
            "RuntimeHumanReviewInput",
            "HumanReviewRequest",
            "RuntimePromptPage",
            "RuntimePromptImportHistoryItem",
            "RuntimePromptImportHistoryPage",
            "RuntimePromptImportInput",
            "RuntimePromptImportResult",
            "RuntimePromptImportRequest",
            "EntityAliasInput",
            "RuntimeEntityAlias",
            "RuntimeEntityAliasCandidate",
            "RuntimeEntityAliasCandidatePage",
            "RuntimeEntityAliasPage",
            "RuntimeEvidenceRun",
            "RuntimeEvidencePage",
            "RuntimeEvidenceExport",
            "RuntimeCollectionRun",
            "RuntimeCollectionRunPage",
            "RuntimeFidelityCheck",
            "RuntimeFidelityCheckPage",
            "RuntimeFidelityTrend",
            "RuntimeFidelityTrendPoint",
            "RuntimeFidelityCheckRequest",
            "ManualBackfillInput",
            "RuntimeSavedView",
            "RuntimeSavedViewPage",
            "RuntimeSavedViewInput",
            "RuntimeScoreSnapshot",
            "RuntimeScoreSnapshotPage",
            "RuntimeCitationGraph",
            "RuntimeCitationGraphPage",
            "RuntimeReportArtifact",
            "RuntimeReportExport",
            "RuntimeReportExportPage",
            "RuntimeActionPlan",
            "RuntimeActionPlanPage",
            "RuntimeAlertItem",
            "RuntimeAlertPage",
            "RuntimeContentDraft",
            "RuntimeContentEngine",
            "RuntimeContentEnginePage",
            "RuntimeKnowledgeSearchResult",
            "RuntimeKnowledgeSearchPage",
            "RuntimeTraceabilityDetail",
            "ProjectBootstrap",
            "PromptQuestion",
            "RawEvidenceRecord",
            "CollectionFailureRecord",
            "VisibilityScoreSnapshot",
            "ReportExport",
            "TraceabilityBundle",
            "/v1/projects/runtime",
            "/v1/projects/runtime/au/dtc-ecommerce",
            "/v1/project-members/runtime",
            "/v1/entity-aliases/runtime",
            "/v1/entity-aliases/runtime/candidates",
            "/v1/entity-aliases/runtime/confirm",
            "/v1/prompts/runtime",
            "/v1/prompts/runtime/imports",
            "/v1/prompts/runtime/import.csv",
            "/v1/prompts/runtime/import.file",
            "/v1/evidence-runs/runtime",
            "/v1/collection-runs/runtime",
            "/v1/fidelity-checks/runtime",
            "/v1/fidelity-checks/runtime/trend",
            "/v1/evidence-runs/runtime/export.csv",
            "/v1/evidence-runs/runtime/manual-backfill",
            "/v1/runtime-saved-views",
            "/v1/project-brand-kits/runtime",
            "/v1/project-brand-kits/runtime/logo",
            "/v1/score-weight-configs/runtime",
            "/v1/score-formulas/runtime",
            "/v1/human-reviews/runtime",
            "/v1/human-reviews/runtime/queue",
            "worker --persist",
            "worker --persist-analysis",
            "/v1/visibility-scores/runtime",
            "/v1/citation-graphs/runtime",
            "/v1/reports/runtime",
            "/v1/reports/runtime/{report_export_id}/artifact",
            "/v1/action-plans/runtime",
            "/v1/runtime-alerts",
            "/v1/content-engines/runtime",
            "/v1/knowledge-facts/runtime/search",
            "/v1/traceability/runtime",
            "/ready",
            "/v1/runtime-diagnostics",
            "/metrics",
        ],
    }
