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
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, Response
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes

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
    RuntimeAlertEventInput,
    RuntimeHumanReviewInput,
    ManualBackfillInput,
    RuntimeProjectBrandAssetInput,
    RuntimeProjectBrandAssetScanInput,
    RuntimeProjectBrandKitInput,
    RuntimeProjectBrandAssetActivationInput,
    RuntimeProjectBrandLogoUpload,
    RuntimeProjectMemberDeleteInput,
    RuntimeProjectMemberInput,
    RuntimePromptImportInput,
    RuntimeNotificationSubscriptionInput,
    RuntimeNotificationStatusInput,
    RuntimeReportExportJobInput,
    RuntimeReportExportJobStatusInput,
    RuntimeReportManagementInput,
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
from scripts.build_au_launch_status import (
    DEFAULT_OUTPUT_PATH as DEFAULT_AU_LAUNCH_STATUS_OUTPUT_PATH,
    DEFAULT_P0A_STATUS_PATH,
    DEFAULT_P0B_GOOGLE_EXECUTION_PATH,
    DEFAULT_P0B_GOOGLE_PACKAGE_PATH,
    DEFAULT_P0B_GOOGLE_RUNBOOK_PATH,
    DEFAULT_P0B_GOOGLE_STATUS_PATH,
    DEFAULT_P0C_REPORT_PACKAGE_PATH,
    build_au_launch_status,
)
from scripts.build_au_launch_remediation_plan import (
    DEFAULT_OUTPUT_PATH as DEFAULT_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH,
    build_au_launch_remediation_plan,
)
from scripts.build_au_handoff_dossier import (
    DEFAULT_MARKDOWN_OUTPUT_PATH as DEFAULT_AU_HANDOFF_DOSSIER_MARKDOWN_OUTPUT_PATH,
    DEFAULT_OUTPUT_PATH as DEFAULT_AU_HANDOFF_DOSSIER_OUTPUT_PATH,
    build_au_handoff_dossier,
)
from scripts.build_au_p0a_environment_checklist import (
    DEFAULT_OUTPUT_PATH as DEFAULT_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH,
    build_au_p0a_environment_checklist,
)
from scripts.build_au_p0a_env_report import (
    DEFAULT_ENV_FILE as DEFAULT_AU_P0A_ENV_FILE,
    DEFAULT_OUTPUT_PATH as DEFAULT_AU_P0A_ENV_OUTPUT_PATH,
)
from scripts.build_au_p0a_runbook import DEFAULT_OUTPUT_PATH as DEFAULT_AU_P0A_RUNBOOK_OUTPUT_PATH
from scripts.build_au_p0b_google_execution_checklist import (
    DEFAULT_OUTPUT_PATH as DEFAULT_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH,
    build_au_p0b_google_execution_checklist,
)
from scripts.build_au_p0b_google_playwright_env_report import (
    DEFAULT_ENV_FILE as DEFAULT_AU_P0B_GOOGLE_ENV_FILE,
    DEFAULT_OUTPUT_PATH as DEFAULT_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH,
)

app = FastAPI(title="GENO SaaS AU API", version="0.1.0")


@app.on_event("shutdown")
def close_runtime_resources() -> None:
    close_runtime_postgres_pool()

RUNTIME_PROJECT_ACCESS_CONTROL_ENV = "GENO_RUNTIME_PROJECT_ACCESS_CONTROL"
RUNTIME_ACTOR_HEADER = "X-GENO-Actor-Id"
RUNTIME_AUTH_MODE_ENV = "GENO_RUNTIME_AUTH_MODE"
RUNTIME_AUTH_MODE_HEADER = "header"
RUNTIME_AUTH_MODE_JWT = "jwt"
RUNTIME_AUTH_MODE_JWKS = "jwks"
RUNTIME_AUTH_MODES = {RUNTIME_AUTH_MODE_HEADER, RUNTIME_AUTH_MODE_JWT, RUNTIME_AUTH_MODE_JWKS}
RUNTIME_JWT_SECRET_ENV = "GENO_RUNTIME_JWT_SECRET"
RUNTIME_JWKS_JSON_ENV = "GENO_RUNTIME_JWKS_JSON"
RUNTIME_JWKS_URL_ENV = "GENO_RUNTIME_JWKS_URL"
RUNTIME_OIDC_DISCOVERY_URL_ENV = "GENO_RUNTIME_OIDC_DISCOVERY_URL"
RUNTIME_JWKS_CACHE_TTL_SECONDS_ENV = "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS"
RUNTIME_JWKS_STALE_IF_ERROR_SECONDS_ENV = "GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS"
RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS_ENV = "GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS"
RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS_ENV = "GENO_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS"
RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS_ENV = "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS"
DEFAULT_RUNTIME_JWKS_CACHE_TTL_SECONDS = 300.0
DEFAULT_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS = 0.0
DEFAULT_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS = 300.0
DEFAULT_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS = 0.0
DEFAULT_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS = 2.0
RUNTIME_JWT_ALGORITHM_ENV = "GENO_RUNTIME_JWT_ALGORITHM"
RUNTIME_JWT_ACTOR_CLAIM_ENV = "GENO_RUNTIME_JWT_ACTOR_CLAIM"
RUNTIME_JWT_ISSUER_ENV = "GENO_RUNTIME_JWT_ISSUER"
RUNTIME_JWT_AUDIENCE_ENV = "GENO_RUNTIME_JWT_AUDIENCE"
RUNTIME_JWT_CLOCK_SKEW_SECONDS_ENV = "GENO_RUNTIME_JWT_CLOCK_SKEW_SECONDS"
RUNTIME_PROJECT_ACCESS_CONTROL_ENABLED_VALUES = {"1", "true", "yes", "on"}
REPORT_ARTIFACT_SIGNING_SECRET_ENV = "GENO_REPORT_ARTIFACT_SIGNING_SECRET"
REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS_ENV = "GENO_REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS"
DEFAULT_REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS = 900.0
MAX_REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS = 86400.0
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
_RUNTIME_JWKS_CACHE_LOCK = threading.Lock()
_RUNTIME_JWKS_CACHE_URL: str | None = None
_RUNTIME_JWKS_CACHE: dict[str, Any] | None = None
_RUNTIME_JWKS_CACHE_EXPIRES_AT = 0.0
_RUNTIME_OIDC_DISCOVERY_CACHE_LOCK = threading.Lock()
_RUNTIME_OIDC_DISCOVERY_CACHE_URL: str | None = None
_RUNTIME_OIDC_DISCOVERY_CACHE: dict[str, Any] | None = None
_RUNTIME_OIDC_DISCOVERY_CACHE_EXPIRES_AT = 0.0


def runtime_project_access_control_enabled() -> bool:
    return (
        os.getenv(RUNTIME_PROJECT_ACCESS_CONTROL_ENV, "").strip().lower()
        in RUNTIME_PROJECT_ACCESS_CONTROL_ENABLED_VALUES
    )


def runtime_auth_mode() -> str:
    mode = os.getenv(RUNTIME_AUTH_MODE_ENV, RUNTIME_AUTH_MODE_HEADER).strip().lower() or RUNTIME_AUTH_MODE_HEADER
    if mode not in RUNTIME_AUTH_MODES:
        raise HTTPException(status_code=503, detail=f"{RUNTIME_AUTH_MODE_ENV} must be header, jwt, or jwks")
    return mode


def _runtime_jwt_secret() -> str:
    secret = os.getenv(RUNTIME_JWT_SECRET_ENV, "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail=f"{RUNTIME_JWT_SECRET_ENV} is required when {RUNTIME_AUTH_MODE_ENV}=jwt")
    return secret


def _validate_runtime_jwks(jwks: object, *, source: str) -> dict[str, Any]:
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise HTTPException(status_code=503, detail=f"{source} must contain a JWKS keys array")
    if not jwks["keys"]:
        raise HTTPException(status_code=503, detail=f"{source} must contain at least one JWKS key")
    return jwks


def _validate_runtime_http_url(value: str, *, source: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=503, detail=f"{source} must be an http or https URL")
    return value


def _runtime_jwks_url() -> str:
    jwks_url = os.getenv(RUNTIME_JWKS_URL_ENV, "").strip()
    if not jwks_url:
        return ""
    return _validate_runtime_http_url(jwks_url, source=RUNTIME_JWKS_URL_ENV)


def _runtime_oidc_discovery_url() -> str:
    discovery_url = os.getenv(RUNTIME_OIDC_DISCOVERY_URL_ENV, "").strip()
    if discovery_url:
        return _validate_runtime_http_url(discovery_url, source=RUNTIME_OIDC_DISCOVERY_URL_ENV)
    issuer = os.getenv(RUNTIME_JWT_ISSUER_ENV, "").strip()
    if not issuer:
        return ""
    _validate_runtime_http_url(
        issuer,
        source=f"{RUNTIME_JWT_ISSUER_ENV} when used for OIDC discovery",
    )
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


def _non_negative_float_env(key: str, default: float) -> float:
    raw_value = os.getenv(key, str(default)).strip() or str(default)
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"{key} must be a non-negative number") from exc
    if value < 0:
        raise HTTPException(status_code=503, detail=f"{key} must be a non-negative number")
    return value


def _positive_float_env(key: str, default: float) -> float:
    raw_value = os.getenv(key, str(default)).strip() or str(default)
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"{key} must be a positive number") from exc
    if value <= 0:
        raise HTTPException(status_code=503, detail=f"{key} must be a positive number")
    return value


def _runtime_jwks_cache_ttl_seconds() -> float:
    return _non_negative_float_env(RUNTIME_JWKS_CACHE_TTL_SECONDS_ENV, DEFAULT_RUNTIME_JWKS_CACHE_TTL_SECONDS)


def _runtime_jwks_stale_if_error_seconds() -> float:
    return _non_negative_float_env(
        RUNTIME_JWKS_STALE_IF_ERROR_SECONDS_ENV,
        DEFAULT_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS,
    )


def _runtime_oidc_discovery_cache_ttl_seconds() -> float:
    return _non_negative_float_env(
        RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS_ENV,
        DEFAULT_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS,
    )


def _runtime_oidc_discovery_stale_if_error_seconds() -> float:
    return _non_negative_float_env(
        RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS_ENV,
        DEFAULT_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS,
    )


def _runtime_jwks_fetch_timeout_seconds() -> float:
    return _positive_float_env(RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS_ENV, DEFAULT_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS)


def _report_artifact_signing_secret() -> str:
    secret = os.getenv(REPORT_ARTIFACT_SIGNING_SECRET_ENV, "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail=f"{REPORT_ARTIFACT_SIGNING_SECRET_ENV} is required")
    return secret


def _report_artifact_signed_url_ttl_seconds() -> int:
    ttl = _positive_float_env(
        REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS_ENV,
        DEFAULT_REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS,
    )
    if ttl > MAX_REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS:
        raise HTTPException(
            status_code=503,
            detail=f"{REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS_ENV} must be <= {int(MAX_REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS)}",
        )
    return int(ttl)


def _report_artifact_signature_payload(
    *,
    report_export_id: str,
    artifact_type: str,
    template: str,
    client_name: str | None,
    prepared_by: str | None,
    platform: str | None,
    city: str | None,
    intent_type: str | None,
    status: str | None,
    sort: str | None,
    expires_at: int,
    actor_id: str | None,
) -> dict[str, object]:
    return {
        "actor_id": actor_id or "",
        "city": city or "",
        "client_name": client_name or "",
        "expires_at": expires_at,
        "intent_type": intent_type or "",
        "platform": platform or "",
        "prepared_by": prepared_by or "",
        "report_export_id": report_export_id.strip(),
        "sort": sort or "",
        "status": status or "",
        "template": template,
        "type": artifact_type,
    }


def _canonical_report_artifact_signature_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign_report_artifact_payload(payload: dict[str, object]) -> str:
    digest = hmac.new(
        _report_artifact_signing_secret().encode("utf-8"),
        _canonical_report_artifact_signature_payload(payload),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_report_artifact_signature(payload: dict[str, object], signature: str | None) -> None:
    if not signature:
        raise HTTPException(status_code=401, detail="report artifact signature is required")
    try:
        expires_at = int(payload["expires_at"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="report artifact signed URL is invalid") from exc
    if expires_at < int(time.time()):
        raise HTTPException(status_code=401, detail="report artifact signed URL has expired")
    expected = _sign_report_artifact_payload(payload)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="report artifact signature is invalid")


def _absolute_url_for_request(request: Request, path: str, query: dict[str, object]) -> str:
    base_url = str(request.base_url).rstrip("/")
    query_string = urlencode(
        {
            key: str(value)
            for key, value in query.items()
            if value is not None and str(value) != ""
        }
    )
    return f"{base_url}{path}?{query_string}" if query_string else f"{base_url}{path}"


def _runtime_jwks_from_json(raw_value: str) -> dict[str, Any]:
    try:
        jwks = json.loads(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"{RUNTIME_JWKS_JSON_ENV} must be valid JWKS JSON") from exc
    return _validate_runtime_jwks(jwks, source=RUNTIME_JWKS_JSON_ENV)


def _runtime_stale_jwks_if_allowed(jwks_url: str) -> dict[str, Any] | None:
    stale_seconds = _runtime_jwks_stale_if_error_seconds()
    if stale_seconds <= 0:
        return None
    now = time.time()
    with _RUNTIME_JWKS_CACHE_LOCK:
        if (
            _RUNTIME_JWKS_CACHE_URL == jwks_url
            and _RUNTIME_JWKS_CACHE is not None
            and now < _RUNTIME_JWKS_CACHE_EXPIRES_AT + stale_seconds
        ):
            return _RUNTIME_JWKS_CACHE
    return None


def _runtime_jwks_from_url(jwks_url: str) -> dict[str, Any]:
    global _RUNTIME_JWKS_CACHE_URL, _RUNTIME_JWKS_CACHE, _RUNTIME_JWKS_CACHE_EXPIRES_AT
    now = time.time()
    with _RUNTIME_JWKS_CACHE_LOCK:
        if _RUNTIME_JWKS_CACHE_URL == jwks_url and _RUNTIME_JWKS_CACHE is not None and now < _RUNTIME_JWKS_CACHE_EXPIRES_AT:
            return _RUNTIME_JWKS_CACHE
    try:
        response = httpx.get(
            jwks_url,
            timeout=_runtime_jwks_fetch_timeout_seconds(),
            follow_redirects=True,
        )
        response.raise_for_status()
        jwks = response.json()
    except httpx.TimeoutException as exc:
        stale_jwks = _runtime_stale_jwks_if_allowed(jwks_url)
        if stale_jwks is not None:
            return stale_jwks
        raise HTTPException(status_code=503, detail="runtime JWKS URL fetch timed out") from exc
    except httpx.HTTPStatusError as exc:
        stale_jwks = _runtime_stale_jwks_if_allowed(jwks_url)
        if stale_jwks is not None:
            return stale_jwks
        raise HTTPException(status_code=503, detail=f"runtime JWKS URL returned status {exc.response.status_code}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        stale_jwks = _runtime_stale_jwks_if_allowed(jwks_url)
        if stale_jwks is not None:
            return stale_jwks
        raise HTTPException(status_code=503, detail="runtime JWKS URL fetch failed") from exc

    try:
        validated_jwks = _validate_runtime_jwks(jwks, source=RUNTIME_JWKS_URL_ENV)
    except HTTPException:
        stale_jwks = _runtime_stale_jwks_if_allowed(jwks_url)
        if stale_jwks is not None:
            return stale_jwks
        raise
    cache_expires_at = time.time() + _runtime_jwks_cache_ttl_seconds()
    with _RUNTIME_JWKS_CACHE_LOCK:
        _RUNTIME_JWKS_CACHE_URL = jwks_url
        _RUNTIME_JWKS_CACHE = validated_jwks
        _RUNTIME_JWKS_CACHE_EXPIRES_AT = cache_expires_at
    return validated_jwks


def _runtime_stale_oidc_discovery_document_if_allowed(discovery_url: str) -> dict[str, Any] | None:
    stale_seconds = _runtime_oidc_discovery_stale_if_error_seconds()
    if stale_seconds <= 0:
        return None
    now = time.time()
    with _RUNTIME_OIDC_DISCOVERY_CACHE_LOCK:
        if (
            _RUNTIME_OIDC_DISCOVERY_CACHE_URL == discovery_url
            and _RUNTIME_OIDC_DISCOVERY_CACHE is not None
            and now < _RUNTIME_OIDC_DISCOVERY_CACHE_EXPIRES_AT + stale_seconds
        ):
            return _RUNTIME_OIDC_DISCOVERY_CACHE
    return None


def _runtime_oidc_discovery_document(discovery_url: str) -> dict[str, Any]:
    global _RUNTIME_OIDC_DISCOVERY_CACHE_URL, _RUNTIME_OIDC_DISCOVERY_CACHE, _RUNTIME_OIDC_DISCOVERY_CACHE_EXPIRES_AT
    now = time.time()
    with _RUNTIME_OIDC_DISCOVERY_CACHE_LOCK:
        if (
            _RUNTIME_OIDC_DISCOVERY_CACHE_URL == discovery_url
            and _RUNTIME_OIDC_DISCOVERY_CACHE is not None
            and now < _RUNTIME_OIDC_DISCOVERY_CACHE_EXPIRES_AT
        ):
            return _RUNTIME_OIDC_DISCOVERY_CACHE
    try:
        response = httpx.get(
            discovery_url,
            timeout=_runtime_jwks_fetch_timeout_seconds(),
            follow_redirects=True,
        )
        response.raise_for_status()
        document = response.json()
    except httpx.TimeoutException as exc:
        stale_document = _runtime_stale_oidc_discovery_document_if_allowed(discovery_url)
        if stale_document is not None:
            return stale_document
        raise HTTPException(status_code=503, detail="runtime OIDC discovery fetch timed out") from exc
    except httpx.HTTPStatusError as exc:
        stale_document = _runtime_stale_oidc_discovery_document_if_allowed(discovery_url)
        if stale_document is not None:
            return stale_document
        raise HTTPException(
            status_code=503,
            detail=f"runtime OIDC discovery returned status {exc.response.status_code}",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        stale_document = _runtime_stale_oidc_discovery_document_if_allowed(discovery_url)
        if stale_document is not None:
            return stale_document
        raise HTTPException(status_code=503, detail="runtime OIDC discovery fetch failed") from exc

    if not isinstance(document, dict):
        stale_document = _runtime_stale_oidc_discovery_document_if_allowed(discovery_url)
        if stale_document is not None:
            return stale_document
        raise HTTPException(status_code=503, detail="runtime OIDC discovery document must be a JSON object")
    jwks_uri = document.get("jwks_uri")
    if not isinstance(jwks_uri, str) or not jwks_uri.strip():
        stale_document = _runtime_stale_oidc_discovery_document_if_allowed(discovery_url)
        if stale_document is not None:
            return stale_document
        raise HTTPException(status_code=503, detail="runtime OIDC discovery document must contain jwks_uri")
    validated_document = dict(document)
    try:
        validated_document["jwks_uri"] = _validate_runtime_http_url(
            jwks_uri.strip(),
            source="runtime OIDC discovery jwks_uri",
        )
    except HTTPException:
        stale_document = _runtime_stale_oidc_discovery_document_if_allowed(discovery_url)
        if stale_document is not None:
            return stale_document
        raise
    cache_expires_at = time.time() + _runtime_oidc_discovery_cache_ttl_seconds()
    with _RUNTIME_OIDC_DISCOVERY_CACHE_LOCK:
        _RUNTIME_OIDC_DISCOVERY_CACHE_URL = discovery_url
        _RUNTIME_OIDC_DISCOVERY_CACHE = validated_document
        _RUNTIME_OIDC_DISCOVERY_CACHE_EXPIRES_AT = cache_expires_at
    return validated_document


def _runtime_jwks_from_oidc_discovery() -> dict[str, Any]:
    discovery_url = _runtime_oidc_discovery_url()
    if not discovery_url:
        return {}
    discovery_document = _runtime_oidc_discovery_document(discovery_url)
    return _runtime_jwks_from_url(str(discovery_document["jwks_uri"]))


def _ensure_runtime_jwks_configured() -> None:
    raw_value = os.getenv(RUNTIME_JWKS_JSON_ENV, "").strip()
    if raw_value:
        _runtime_jwks_from_json(raw_value)
        return
    if _runtime_jwks_url():
        _runtime_jwks_cache_ttl_seconds()
        _runtime_jwks_stale_if_error_seconds()
        _runtime_jwks_fetch_timeout_seconds()
        return
    if _runtime_oidc_discovery_url():
        _runtime_jwks_cache_ttl_seconds()
        _runtime_jwks_stale_if_error_seconds()
        _runtime_oidc_discovery_cache_ttl_seconds()
        _runtime_oidc_discovery_stale_if_error_seconds()
        _runtime_jwks_fetch_timeout_seconds()
        return
    raise HTTPException(
        status_code=503,
        detail=(
            f"{RUNTIME_JWKS_JSON_ENV}, {RUNTIME_JWKS_URL_ENV}, {RUNTIME_OIDC_DISCOVERY_URL_ENV}, "
            f"or URL-form {RUNTIME_JWT_ISSUER_ENV} is required when {RUNTIME_AUTH_MODE_ENV}=jwks"
        ),
    )


def _runtime_jwks() -> dict[str, Any]:
    raw_value = os.getenv(RUNTIME_JWKS_JSON_ENV, "").strip()
    if raw_value:
        return _runtime_jwks_from_json(raw_value)
    jwks_url = _runtime_jwks_url()
    if jwks_url:
        return _runtime_jwks_from_url(jwks_url)
    oidc_jwks = _runtime_jwks_from_oidc_discovery()
    if oidc_jwks:
        return oidc_jwks
    raise HTTPException(
        status_code=503,
        detail=(
            f"{RUNTIME_JWKS_JSON_ENV}, {RUNTIME_JWKS_URL_ENV}, {RUNTIME_OIDC_DISCOVERY_URL_ENV}, "
            f"or URL-form {RUNTIME_JWT_ISSUER_ENV} is required when {RUNTIME_AUTH_MODE_ENV}=jwks"
        ),
    )


def reset_runtime_auth_caches() -> None:
    global _RUNTIME_JWKS_CACHE_URL, _RUNTIME_JWKS_CACHE, _RUNTIME_JWKS_CACHE_EXPIRES_AT
    global _RUNTIME_OIDC_DISCOVERY_CACHE_URL, _RUNTIME_OIDC_DISCOVERY_CACHE, _RUNTIME_OIDC_DISCOVERY_CACHE_EXPIRES_AT
    with _RUNTIME_JWKS_CACHE_LOCK:
        _RUNTIME_JWKS_CACHE_URL = None
        _RUNTIME_JWKS_CACHE = None
        _RUNTIME_JWKS_CACHE_EXPIRES_AT = 0.0
    with _RUNTIME_OIDC_DISCOVERY_CACHE_LOCK:
        _RUNTIME_OIDC_DISCOVERY_CACHE_URL = None
        _RUNTIME_OIDC_DISCOVERY_CACHE = None
        _RUNTIME_OIDC_DISCOVERY_CACHE_EXPIRES_AT = 0.0


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


def _int_from_base64url(value: object, *, field: str) -> int:
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=503, detail=f"runtime JWKS RSA key is missing {field}")
    try:
        return int.from_bytes(_base64url_decode(value), "big")
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"runtime JWKS RSA key has invalid {field}") from exc


def _runtime_jwt_clock_skew_seconds() -> int:
    raw_value = os.getenv(RUNTIME_JWT_CLOCK_SKEW_SECONDS_ENV, "30").strip() or "30"
    try:
        return max(0, int(raw_value))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"{RUNTIME_JWT_CLOCK_SKEW_SECONDS_ENV} must be an integer") from exc


def _validate_runtime_jwt_claims(payload: dict[str, object]) -> str:
    try:
        now = time.time()
        clock_skew = _runtime_jwt_clock_skew_seconds()
        exp = payload.get("exp")
        if exp is not None and now > float(exp) + clock_skew:
            raise HTTPException(status_code=401, detail="runtime JWT has expired")
        nbf = payload.get("nbf")
        if nbf is not None and now + clock_skew < float(nbf):
            raise HTTPException(status_code=401, detail="runtime JWT is not active yet")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="invalid runtime JWT temporal claim") from exc
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


def _verify_runtime_hs256_jwt(parts: list[str], header: dict[str, object]) -> dict[str, object]:
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
    return _json_from_base64url(parts[1])


def _select_runtime_jwks_key(header: dict[str, object]) -> dict[str, object]:
    kid = str(header.get("kid", "")).strip()
    keys = _runtime_jwks()["keys"]
    matches: list[dict[str, object]] = []
    for key in keys:
        if not isinstance(key, dict):
            continue
        if key.get("kty") != "RSA":
            continue
        if key.get("use") not in {None, "sig"}:
            continue
        if kid and key.get("kid") != kid:
            continue
        if key.get("alg") not in {None, "RS256"}:
            continue
        matches.append(key)
    if not matches:
        raise HTTPException(status_code=401, detail="runtime JWT signing key is not trusted")
    if not kid and len(matches) > 1:
        raise HTTPException(status_code=401, detail="runtime JWT kid is required when JWKS has multiple RSA signing keys")
    return matches[0]


def _verify_runtime_jwks_jwt(parts: list[str], header: dict[str, object]) -> dict[str, object]:
    if str(header.get("alg", "")).upper() != "RS256":
        raise HTTPException(status_code=401, detail="runtime JWT algorithm is not allowed")
    key = _select_runtime_jwks_key(header)
    try:
        public_key = rsa.RSAPublicNumbers(
            e=_int_from_base64url(key.get("e"), field="e"),
            n=_int_from_base64url(key.get("n"), field="n"),
        ).public_key()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="runtime JWKS RSA key is invalid") from exc
    try:
        signature = _base64url_decode(parts[2])
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid runtime JWT signature") from exc
    try:
        public_key.verify(
            signature,
            f"{parts[0]}.{parts[1]}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise HTTPException(status_code=401, detail="invalid runtime JWT signature") from exc
    return _json_from_base64url(parts[1])


def decode_runtime_jwt_actor(authorization: str | None) -> str:
    auth_mode = runtime_auth_mode()
    if not authorization or not authorization.strip().lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail=f"Authorization Bearer JWT is required when runtime auth mode is {auth_mode}",
        )
    token = authorization.strip()[7:].strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="invalid runtime JWT")
    header = _json_from_base64url(parts[0])
    if auth_mode == RUNTIME_AUTH_MODE_JWKS:
        payload = _verify_runtime_jwks_jwt(parts, header)
    else:
        payload = _verify_runtime_hs256_jwt(parts, header)
    return _validate_runtime_jwt_claims(payload)


@app.middleware("http")
async def runtime_jwt_actor_middleware(request: Request, call_next):
    actor_token = _RUNTIME_JWT_ACTOR_ID.set(None)
    try:
        if runtime_project_access_control_enabled() and runtime_auth_mode() in {RUNTIME_AUTH_MODE_JWT, RUNTIME_AUTH_MODE_JWKS}:
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
    auth_mode = runtime_auth_mode()
    if runtime_project_access_control_enabled() and auth_mode in {RUNTIME_AUTH_MODE_JWT, RUNTIME_AUTH_MODE_JWKS}:
        if auth_mode == RUNTIME_AUTH_MODE_JWT:
            _runtime_jwt_secret()
        else:
            _ensure_runtime_jwks_configured()
        actor_id = _RUNTIME_JWT_ACTOR_ID.get()
        if not actor_id:
            raise HTTPException(
                status_code=401,
                detail=f"Authorization Bearer JWT is required when runtime auth mode is {auth_mode}",
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


class ProjectBrandAssetActivationRequest(BaseModel):
    project_id: str = Field(min_length=1)
    asset_url: str = Field(min_length=1, max_length=1000)
    activated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class ProjectBrandAssetRequest(BaseModel):
    project_id: str = Field(min_length=1)
    asset_type: str = Field(default="image", min_length=1, max_length=80)
    asset_url: str = Field(min_length=1, max_length=1000)
    category: str = Field(default="uncategorized", min_length=1, max_length=120)
    preview_url: str | None = Field(default=None, max_length=1000)
    source_filename: str | None = Field(default=None, max_length=240)
    source_content_type: str | None = Field(default=None, max_length=160)
    content_hash: str | None = Field(default=None, max_length=160)
    storage_version: str | None = Field(default=None, max_length=240)
    status: str = Field(default="active", min_length=1, max_length=40)
    uploaded_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    metadata: dict[str, object] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=500)


class ProjectBrandAssetScanRequest(BaseModel):
    scan_status: str = Field(default="pending", min_length=1, max_length=40)
    scanned_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    scan_method_version: str = Field(default="manual_asset_scan_v1", min_length=1, max_length=120)
    scan_notes: str | None = Field(default=None, max_length=1000)
    reason: str | None = Field(default=None, max_length=500)


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


class RuntimeReportManagementEventRequest(BaseModel):
    status: str = Field(min_length=1, max_length=80)
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=500)


class RuntimeAlertEventRequest(BaseModel):
    project_id: str = Field(min_length=1)
    alert_type: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=120)
    source_id: str = Field(min_length=1, max_length=240)
    status: str = Field(default="acknowledged", min_length=1, max_length=80)
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=500)
    metadata: dict[str, object] = Field(default_factory=dict)


class RuntimeAlertNotificationRequest(BaseModel):
    project_id: str = Field(min_length=1)
    alert_type: str | None = Field(default=None, min_length=1, max_length=120)
    severity: str | None = Field(default=None, min_length=1, max_length=80)
    created_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)
    include_resolved: bool = False


class RuntimeReportExportJobRequest(BaseModel):
    project_id: str = Field(min_length=1)
    report_export_id: str | None = Field(default=None, min_length=1)
    artifact_type: str = Field(default="pdf", min_length=1, max_length=40)
    template: str = Field(default="standard", min_length=1, max_length=40)
    filters: dict[str, object] = Field(default_factory=dict)
    sort: str = Field(default="collected_at_desc", min_length=1, max_length=80)
    requested_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class RuntimeReportExportJobStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=80)
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    report_export_id: str | None = Field(default=None, min_length=1)
    artifact_url: str | None = Field(default=None, max_length=1000)
    error_message: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=500)


class RuntimeNotificationStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=40)
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class RuntimeNotificationSubscriptionRequest(BaseModel):
    project_id: str = Field(min_length=1)
    endpoint_url: str = Field(min_length=1, max_length=1000)
    channel: str = Field(default="webhook", min_length=1, max_length=40)
    event_types: list[str] = Field(default_factory=lambda: ["report_export_job"])
    severity_threshold: str = Field(default="info", min_length=1, max_length=40)
    status: str = Field(default="active", min_length=1, max_length=40)
    metadata: dict[str, object] = Field(default_factory=dict)
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


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


@app.get("/v1/launch-status/au")
def au_launch_status() -> dict[str, object]:
    return _build_au_launch_status_from_env()


def _build_au_launch_status_from_env() -> dict[str, object]:
    return build_au_launch_status(
        p0a_status_path=Path(os.getenv("GENO_AU_P0A_STATUS_OUTPUT_PATH", DEFAULT_P0A_STATUS_PATH)),
        p0b_google_status_path=Path(
            os.getenv("GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_STATUS_PATH)
        ),
        p0b_google_package_path=Path(
            os.getenv("GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_PACKAGE_PATH)
        ),
        p0b_google_runbook_path=Path(
            os.getenv("GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_RUNBOOK_PATH)
        ),
        p0b_google_execution_path=Path(
            os.getenv("GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_EXECUTION_PATH)
        ),
        p0c_report_package_path=Path(
            os.getenv("GENO_AU_P0C_REPORT_PACKAGE_OUTPUT_PATH", DEFAULT_P0C_REPORT_PACKAGE_PATH)
        ),
        output_path=Path(os.getenv("GENO_AU_LAUNCH_STATUS_OUTPUT_PATH", DEFAULT_AU_LAUNCH_STATUS_OUTPUT_PATH)),
    )


@app.get("/v1/launch-remediation-plan/au")
def au_launch_remediation_plan() -> dict[str, object]:
    return _build_au_launch_remediation_plan_from_env()


@app.get("/v1/p0a-environment-checklist/au")
def au_p0a_environment_checklist() -> dict[str, object]:
    return build_au_p0a_environment_checklist(
        runbook_path=Path(os.getenv("GENO_AU_P0A_RUNBOOK_OUTPUT_PATH", DEFAULT_AU_P0A_RUNBOOK_OUTPUT_PATH)),
        environment_path=Path(os.getenv("GENO_AU_P0A_ENV_OUTPUT_PATH", DEFAULT_AU_P0A_ENV_OUTPUT_PATH)),
        status_path=Path(os.getenv("GENO_AU_P0A_STATUS_OUTPUT_PATH", DEFAULT_P0A_STATUS_PATH)),
        env_file_path=Path(os.getenv("GENO_AU_P0A_ENV_FILE", DEFAULT_AU_P0A_ENV_FILE)),
        output_path=Path(
            os.getenv(
                "GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH",
                DEFAULT_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH,
            )
        ),
    )


@app.get("/v1/p0b-google-execution-checklist/au")
def au_p0b_google_execution_checklist() -> dict[str, object]:
    return build_au_p0b_google_execution_checklist(
        runbook_path=Path(os.getenv("GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_RUNBOOK_PATH)),
        execution_path=Path(
            os.getenv("GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_EXECUTION_PATH)
        ),
        playwright_env_path=Path(
            os.getenv("GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH", DEFAULT_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH)
        ),
        status_report_path=Path(os.getenv("GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_STATUS_PATH)),
        package_path=Path(os.getenv("GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH", DEFAULT_P0B_GOOGLE_PACKAGE_PATH)),
        env_file_path=Path(os.getenv("GENO_AU_P0B_GOOGLE_ENV_FILE", DEFAULT_AU_P0B_GOOGLE_ENV_FILE)),
        output_path=Path(
            os.getenv(
                "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH",
                DEFAULT_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH,
            )
        ),
    )


def _build_au_launch_remediation_plan_from_env() -> dict[str, object]:
    launch_status_path = Path(os.getenv("GENO_AU_LAUNCH_STATUS_OUTPUT_PATH", DEFAULT_AU_LAUNCH_STATUS_OUTPUT_PATH))
    launch_status = _build_au_launch_status_from_env()
    return build_au_launch_remediation_plan(
        launch_status=launch_status,
        launch_status_path=launch_status_path,
        output_path=Path(
            os.getenv(
                "GENO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH",
                DEFAULT_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH,
            )
        ),
    )


@app.get("/v1/handoff-dossier/au")
def au_handoff_dossier() -> dict[str, object]:
    launch_status_path = Path(os.getenv("GENO_AU_LAUNCH_STATUS_OUTPUT_PATH", DEFAULT_AU_LAUNCH_STATUS_OUTPUT_PATH))
    remediation_plan_path = Path(
        os.getenv(
            "GENO_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH",
            DEFAULT_AU_LAUNCH_REMEDIATION_PLAN_OUTPUT_PATH,
        )
    )
    p0a_environment_checklist_path = Path(
        os.getenv(
            "GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH",
            DEFAULT_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH,
        )
    )
    p0b_google_execution_checklist_path = Path(
        os.getenv(
            "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH",
            DEFAULT_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH,
        )
    )
    launch_status = _build_au_launch_status_from_env()
    remediation_plan = build_au_launch_remediation_plan(
        launch_status=launch_status,
        launch_status_path=launch_status_path,
        output_path=remediation_plan_path,
    )
    p0a_environment_checklist = au_p0a_environment_checklist()
    p0b_google_execution_checklist = au_p0b_google_execution_checklist()
    return build_au_handoff_dossier(
        launch_status_path=launch_status_path,
        remediation_plan_path=remediation_plan_path,
        p0a_environment_checklist_path=p0a_environment_checklist_path,
        p0b_google_execution_checklist_path=p0b_google_execution_checklist_path,
        launch_status=launch_status,
        remediation_plan=remediation_plan,
        p0a_environment_checklist=p0a_environment_checklist,
        p0b_google_execution_checklist=p0b_google_execution_checklist,
        output_path=Path(os.getenv("GENO_AU_HANDOFF_DOSSIER_OUTPUT_PATH", DEFAULT_AU_HANDOFF_DOSSIER_OUTPUT_PATH)),
        markdown_output_path=Path(
            os.getenv("GENO_AU_HANDOFF_DOSSIER_MARKDOWN_PATH", DEFAULT_AU_HANDOFF_DOSSIER_MARKDOWN_OUTPUT_PATH)
        ),
    )


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


@app.get("/v1/project-brand-kits/runtime/assets")
def runtime_project_brand_asset_versions(
    project_id: str = Query(min_length=1),
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
        page = repository.list_project_brand_asset_versions(
            project_id=project_id.strip(),
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/project-brand-assets/runtime")
def runtime_project_brand_assets(
    project_id: str = Query(min_length=1),
    asset_type: str | None = Query(default=None, min_length=1, max_length=80),
    category: str | None = Query(default=None, min_length=1, max_length=120),
    status: str | None = Query(default=None, min_length=1, max_length=40),
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
        page = repository.list_project_brand_assets(
            project_id=project_id.strip(),
            asset_type=asset_type.strip() if asset_type else None,
            category=category.strip() if category else None,
            status=status.strip() if status else None,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.post("/v1/project-brand-assets/runtime")
def save_runtime_project_brand_asset(
    payload: ProjectBrandAssetRequest,
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
        record = repository.save_project_brand_asset(
            RuntimeProjectBrandAssetInput(
                project_id=payload.project_id.strip(),
                asset_type=payload.asset_type.strip(),
                asset_url=payload.asset_url.strip(),
                category=payload.category.strip(),
                preview_url=payload.preview_url.strip() if payload.preview_url else None,
                source_filename=payload.source_filename.strip() if payload.source_filename else None,
                source_content_type=payload.source_content_type.strip() if payload.source_content_type else None,
                content_hash=payload.content_hash.strip() if payload.content_hash else None,
                storage_version=payload.storage_version.strip() if payload.storage_version else None,
                status=payload.status.strip(),
                uploaded_by=actor_id or payload.uploaded_by.strip(),
                metadata=payload.metadata,
                reason=payload.reason.strip() if payload.reason else None,
            )
        )
        return asdict(record)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.post("/v1/project-brand-assets/runtime/{asset_id}/scan-status")
def update_runtime_project_brand_asset_scan_status(
    asset_id: str,
    payload: ProjectBrandAssetScanRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        project_id = repository.get_project_brand_asset_project_id(asset_id=asset_id.strip())
        if project_id is None:
            raise HTTPException(status_code=404, detail="project brand asset not found")
        assert_runtime_project_access(
            repository,
            project_id=project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        record = repository.update_project_brand_asset_scan_status(
            RuntimeProjectBrandAssetScanInput(
                asset_id=asset_id.strip(),
                scan_status=payload.scan_status.strip(),
                scanned_by=actor_id or payload.scanned_by.strip(),
                scan_method_version=payload.scan_method_version.strip(),
                scan_notes=payload.scan_notes.strip() if payload.scan_notes else None,
                reason=payload.reason.strip() if payload.reason else None,
            )
        )
        return asdict(record)
    except HTTPException:
        raise
    except ValueError as exc:
        status_code = 404 if str(exc) == "project brand asset not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.post("/v1/project-brand-kits/runtime/assets/activate")
def activate_runtime_project_brand_asset_version(
    payload: ProjectBrandAssetActivationRequest,
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
        brand_kit = repository.activate_project_brand_logo_version(
            RuntimeProjectBrandAssetActivationInput(
                project_id=payload.project_id.strip(),
                asset_url=payload.asset_url.strip(),
                activated_by=actor_id or payload.activated_by.strip(),
                reason=payload.reason.strip() if payload.reason else None,
            )
        )
        return asdict(brand_kit)
    except ValueError as exc:
        status_code = 404 if str(exc) in {"project not found", "brand asset version not found"} else 400
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


@app.post("/v1/reports/runtime/{report_export_id}/management-events")
def record_runtime_report_management_event(
    report_export_id: str,
    payload: RuntimeReportManagementEventRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        project_id: str | None = None
        if runtime_project_access_control_enabled():
            apply_runtime_project_db_context(repository, actor_id=actor_id)
            project_id = repository.get_report_export_project_id(report_export_id=report_export_id)
            if project_id is None:
                raise HTTPException(status_code=404, detail="report_export not found")
        assert_runtime_project_access(
            repository,
            project_id=project_id,
            actor_id=actor_id,
            require_project_id=project_id is not None,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        try:
            report = repository.record_runtime_report_management_event(
                RuntimeReportManagementInput(
                    report_export_id=report_export_id,
                    status=payload.status.strip(),
                    updated_by=actor_id or payload.updated_by.strip(),
                    note=payload.note.strip() if payload.note else None,
                )
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "report_export not found" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return asdict(report)
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
    request: Request,
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
    expires_at: int | None = None,
    signature: str | None = None,
    signed_actor_id: str | None = None,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> Response:
    signed_download = expires_at is not None or signature is not None
    if signed_download:
        payload = _report_artifact_signature_payload(
            report_export_id=report_export_id,
            artifact_type=artifact_type,
            template=template,
            client_name=client_name,
            prepared_by=prepared_by,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
            expires_at=expires_at or 0,
            actor_id=signed_actor_id,
        )
        _verify_report_artifact_signature(payload, signature)
        actor_id = signed_actor_id.strip() if signed_actor_id else None
    else:
        actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        if runtime_project_access_control_enabled():
            if signed_download and not actor_id:
                raise HTTPException(status_code=401, detail="signed_actor_id is required when runtime project access control is enabled")
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
                "X-GENO-Report-Artifact-Signed": "true" if signed_download else "false",
            },
        )
    finally:
        close_repository_connection(repository)


@app.get("/v1/reports/runtime/{report_export_id}/artifact/signed-url")
def runtime_report_artifact_signed_url(
    request: Request,
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
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    ttl_seconds = _report_artifact_signed_url_ttl_seconds()
    expires_at = int(time.time()) + ttl_seconds
    payload = _report_artifact_signature_payload(
        report_export_id=report_export_id,
        artifact_type=artifact_type,
        template=template,
        client_name=client_name,
        prepared_by=prepared_by,
        platform=platform,
        city=city,
        intent_type=intent_type,
        status=status,
        sort=sort,
        expires_at=expires_at,
        actor_id=actor_id,
    )
    signature = _sign_report_artifact_payload(payload)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        if runtime_project_access_control_enabled():
            apply_runtime_project_db_context(repository, actor_id=actor_id)
        project_id = repository.get_report_export_project_id(report_export_id=report_export_id)
        if project_id is None:
            raise HTTPException(status_code=404, detail="report_export not found")
        assert_runtime_project_access(
            repository,
            project_id=project_id,
            actor_id=actor_id,
            require_project_id=True,
        )
    finally:
        close_repository_connection(repository)

    artifact_path = f"/v1/reports/runtime/{report_export_id}/artifact"
    signed_query = {
        "type": artifact_type,
        "template": template,
        "client_name": client_name,
        "prepared_by": prepared_by,
        "platform": platform,
        "city": city,
        "intent_type": intent_type,
        "status": status,
        "sort": sort,
        "expires_at": expires_at,
        "signed_actor_id": actor_id,
        "signature": signature,
    }
    download_url = _absolute_url_for_request(request, artifact_path, signed_query)
    return {
        "report_export_id": report_export_id,
        "artifact_type": artifact_type,
        "template": template,
        "expires_at": expires_at,
        "ttl_seconds": ttl_seconds,
        "download_url": download_url,
        "signed_url_hash": hashlib.sha256(download_url.encode("utf-8")).hexdigest(),
        "signature_payload_hash": hashlib.sha256(
            _canonical_report_artifact_signature_payload(payload)
        ).hexdigest(),
        "signature_version": "report_artifact_hmac_sha256_v1",
    }


@app.get("/v1/report-export-jobs/runtime")
def runtime_report_export_jobs(
    project_id: str | None = None,
    status: str | None = None,
    report_export_id: str | None = None,
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
        page = repository.list_runtime_report_export_jobs(
            project_id=project_id,
            status=status,
            report_export_id=report_export_id,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/report-export-jobs/runtime/stats")
def runtime_report_export_job_stats(
    project_id: str | None = None,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        stats = repository.get_runtime_report_export_job_queue_stats(project_id=project_id)
        return asdict(stats)
    finally:
        close_repository_connection(repository)


@app.get("/v1/runtime-notifications")
def runtime_notifications(
    project_id: str | None = None,
    status: str | None = None,
    notification_type: str | None = None,
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
        page = repository.list_runtime_notifications(
            project_id=project_id,
            status=status,
            notification_type=notification_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/runtime-notification-subscriptions")
def runtime_notification_subscriptions(
    project_id: str | None = None,
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
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_notification_subscriptions(
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/runtime-notification-subscriptions")
def save_runtime_notification_subscription(
    payload: RuntimeNotificationSubscriptionRequest,
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
        record = repository.save_runtime_notification_subscription(
            RuntimeNotificationSubscriptionInput(
                project_id=payload.project_id.strip(),
                endpoint_url=payload.endpoint_url.strip(),
                channel=payload.channel.strip(),
                event_types=tuple(payload.event_types),
                severity_threshold=payload.severity_threshold.strip(),
                status=payload.status.strip(),
                metadata=payload.metadata,
                updated_by=actor_id or payload.updated_by.strip(),
                reason=payload.reason.strip() if payload.reason else None,
            )
        )
        return asdict(record)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/runtime-notification-deliveries")
def runtime_notification_deliveries(
    project_id: str | None = None,
    notification_id: str | None = None,
    subscription_id: str | None = None,
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
        assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
        page = repository.list_runtime_notification_deliveries(
            project_id=project_id,
            notification_id=notification_id,
            subscription_id=subscription_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/runtime-notifications/{notification_id}/status")
def update_runtime_notification_status(
    notification_id: str,
    payload: RuntimeNotificationStatusRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        project_id = repository.get_runtime_notification_project_id(notification_id=notification_id)
        if project_id is None:
            raise HTTPException(status_code=404, detail="runtime notification not found")
        assert_runtime_project_access(
            repository,
            project_id=project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        record = repository.update_runtime_notification_status(
            RuntimeNotificationStatusInput(
                notification_id=notification_id,
                status=payload.status,
                updated_by=actor_id or payload.updated_by,
                reason=payload.reason,
            )
        )
        return asdict(record)
    except ValueError as exc:
        status_code = 404 if str(exc) == "runtime notification not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.post("/v1/report-export-jobs/runtime")
def enqueue_runtime_report_export_job(
    payload: RuntimeReportExportJobRequest,
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
        job = repository.enqueue_runtime_report_export_job(
            RuntimeReportExportJobInput(
                project_id=payload.project_id,
                report_export_id=payload.report_export_id,
                artifact_type=payload.artifact_type,
                template=payload.template,
                filters=payload.filters,
                sort=payload.sort,
                requested_by=actor_id or payload.requested_by,
                reason=payload.reason,
            )
        )
        return asdict(job)
    except ValueError as exc:
        status_code = 404 if str(exc) in {"project not found", "report_export not found"} else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.post("/v1/report-export-jobs/runtime/{job_id}/status")
def update_runtime_report_export_job_status(
    job_id: str,
    payload: RuntimeReportExportJobStatusRequest,
    x_geno_actor_id: str | None = Header(default=None, alias=RUNTIME_ACTOR_HEADER),
) -> dict[str, object]:
    actor_id = require_runtime_actor_id(x_geno_actor_id)
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        project_id = repository.get_report_export_job_project_id(job_id=job_id)
        if project_id is None:
            raise HTTPException(status_code=404, detail="report_export_job not found")
        assert_runtime_project_access(
            repository,
            project_id=project_id,
            actor_id=actor_id,
            allowed_roles=PROJECT_MANAGE_ROLES,
        )
        job = repository.update_runtime_report_export_job_status(
            RuntimeReportExportJobStatusInput(
                job_id=job_id,
                status=payload.status,
                updated_by=actor_id or payload.updated_by,
                report_export_id=payload.report_export_id,
                artifact_url=payload.artifact_url,
                error_message=payload.error_message,
                reason=payload.reason,
            )
        )
        return asdict(job)
    except ValueError as exc:
        status_code = 404 if str(exc) in {"report_export_job not found", "report_export not found"} else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
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


@app.post("/v1/runtime-alerts/notifications")
def enqueue_runtime_alert_notifications(
    payload: RuntimeAlertNotificationRequest,
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
        try:
            record = repository.enqueue_runtime_alert_notifications(
                project_id=payload.project_id.strip(),
                alert_type=payload.alert_type.strip() if payload.alert_type else None,
                severity=payload.severity.strip() if payload.severity else None,
                created_by=actor_id or payload.created_by.strip(),
                reason=payload.reason.strip() if payload.reason else None,
                include_resolved=payload.include_resolved,
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "project not found" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return asdict(record)
    finally:
        close_repository_connection(repository)


@app.post("/v1/runtime-alerts/{alert_id}/events")
def record_runtime_alert_event(
    alert_id: str,
    payload: RuntimeAlertEventRequest,
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
        try:
            record = repository.record_runtime_alert_event(
                RuntimeAlertEventInput(
                    project_id=payload.project_id.strip(),
                    alert_id=alert_id.strip(),
                    alert_type=payload.alert_type.strip(),
                    source=payload.source.strip(),
                    source_id=payload.source_id.strip(),
                    status=payload.status.strip(),
                    updated_by=actor_id or payload.updated_by.strip(),
                    note=payload.note.strip() if payload.note else None,
                    metadata=payload.metadata,
                )
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "project not found" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return asdict(record)
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
        audit_events=(analysis_result.audit_event,),
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
        audit_events=(analysis_result.audit_event,),
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
            "RuntimeAlertEvent",
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
            "InMemoryPostgresAdjacencyGraphStore",
            "InMemoryNeo4jCitationGraphStore",
            "summarize_citation_graph_store",
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
            "InMemoryPgVectorStore",
            "InMemoryQdrantVectorStore",
            "summarize_vector_search",
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
            "RuntimeProjectBrandAsset",
            "RuntimeProjectBrandAssetPage",
            "RuntimeProjectBrandAssetInput",
            "RuntimeProjectBrandAssetScanInput",
            "RuntimeProjectBrandAssetVersion",
            "RuntimeProjectBrandAssetVersionPage",
            "RuntimeProjectBrandAssetActivationInput",
            "RuntimeProjectBrandLogoUpload",
            "ProjectBrandKitRequest",
            "ProjectBrandAssetRequest",
            "ProjectBrandAssetScanRequest",
            "ProjectBrandAssetActivationRequest",
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
            "RuntimeReportExportJob",
            "RuntimeReportExportJobPage",
            "RuntimeReportExportJobQueueStats",
            "RuntimeReportExportJobInput",
            "RuntimeReportExportJobStatusInput",
            "RuntimeReportExportJobRequest",
            "RuntimeReportExportJobStatusRequest",
            "RuntimeNotification",
            "RuntimeNotificationDelivery",
            "RuntimeNotificationDeliveryPage",
            "RuntimeNotificationDeliveryStatusInput",
            "RuntimeNotificationPage",
            "RuntimeNotificationSubscription",
            "RuntimeNotificationSubscriptionInput",
            "RuntimeNotificationSubscriptionPage",
            "RuntimeNotificationSubscriptionRequest",
            "RuntimeNotificationStatusInput",
            "RuntimeNotificationStatusRequest",
            "RuntimeReportManagementInput",
            "RuntimeReportManagementEventRequest",
            "RuntimeActionPlan",
            "RuntimeActionPlanPage",
            "RuntimeAlertItem",
            "RuntimeAlertPage",
            "RuntimeAlertEvent",
            "RuntimeAlertEventInput",
            "RuntimeAlertEventRequest",
            "RuntimeAlertNotificationRequest",
            "RuntimeAlertNotificationResult",
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
            "/v1/project-brand-kits/runtime/assets",
            "/v1/project-brand-kits/runtime/assets/activate",
            "/v1/project-brand-assets/runtime",
            "/v1/score-weight-configs/runtime",
            "/v1/score-formulas/runtime",
            "/v1/human-reviews/runtime",
            "/v1/human-reviews/runtime/queue",
            "worker --persist",
            "worker --persist-analysis",
            "/v1/visibility-scores/runtime",
            "/v1/citation-graphs/runtime",
            "/v1/reports/runtime",
            "/v1/report-export-jobs/runtime",
            "/v1/report-export-jobs/runtime/stats",
            "/v1/report-export-jobs/runtime/{job_id}/status",
            "/v1/runtime-notifications",
            "/v1/runtime-notification-subscriptions",
            "/v1/runtime-notification-deliveries",
            "/v1/runtime-notifications/{notification_id}/status",
            "/v1/reports/runtime/{report_export_id}/management-events",
            "/v1/reports/runtime/{report_export_id}/artifact",
            "/v1/reports/runtime/{report_export_id}/artifact/signed-url",
            "/v1/action-plans/runtime",
            "/v1/runtime-alerts",
            "/v1/runtime-alerts/notifications",
            "/v1/runtime-alerts/{alert_id}/events",
            "/v1/content-engines/runtime",
            "/v1/knowledge-facts/runtime/search",
            "/v1/traceability/runtime",
            "/ready",
            "/v1/runtime-diagnostics",
            "/v1/launch-status/au",
            "/v1/launch-remediation-plan/au",
            "/v1/p0a-environment-checklist/au",
            "/v1/p0b-google-execution-checklist/au",
            "/v1/handoff-dossier/au",
            "/metrics",
        ],
    }
