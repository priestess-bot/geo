from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable
from dataclasses import asdict
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from psycopg.errors import InsufficientPrivilege

from geo_api.auth_context import AuthContext
from geo_api.auth_contracts import (
    AuthErrorResponse,
    AuthInvitationPreflightRequest,
    AuthInvitationPreflightResponse,
    AuthInvitationRedeemRequest,
    AuthInvitationRedeemResponse,
    AuthLogoutResponse,
    AuthMeResponse,
    RuntimeSessionScopeV2,
)
from geo_core.auth import (
    AUTH_SURFACE_POLICY_VERSION,
    RUNTIME_SESSION_SCOPE_VERSION,
    AuthContractError,
    AuthWritesDisabledError,
)
from geo_core.auth_delivery import AuthDeliveryError
from geo_core.models import RuntimeSessionRevokeInput
from geo_core.runtime import RuntimePersistenceError


def register_auth_routes(
    app: FastAPI,
    *,
    build_repository: Callable[[], object],
    close_repository: Callable[[object], None],
    resolve_auth_context: Callable[[str | None], AuthContext],
    runtime_actor_header: str,
    session_cookie_name: str,
    csrf_cookie_name: str,
    csrf_header_name: str,
    cookie_secure: Callable[[], bool],
) -> None:
    router = APIRouter()

    @app.exception_handler(AuthContractError)
    async def auth_contract_error_handler(_request: object, exc: AuthContractError) -> JSONResponse:
        payload: dict[str, object] = {
            "code": exc.code,
            "detail": exc.detail,
            "correlation_id": exc.correlation_id,
        }
        if exc.recommended_surface:
            payload["recommended_surface"] = exc.recommended_surface
        if exc.code == "invitation_surface_mismatch":
            payload["invitation_consumed"] = False
        headers = {"Cache-Control": "no-store"}
        if exc.http_status == 503:
            headers["Retry-After"] = "60"
        elif exc.http_status == 429:
            headers["Retry-After"] = "600"
        return JSONResponse(status_code=exc.http_status, content=payload, headers=headers)

    @app.exception_handler(InsufficientPrivilege)
    async def auth_db_write_guard_handler(_request: object, exc: InsufficientPrivilege) -> JSONResponse:
        primary_message = str(getattr(getattr(exc, "diag", None), "message_primary", "") or "")
        if exc.sqlstate != "42501" or primary_message != "auth_writes_temporarily_disabled":
            raise exc
        error = AuthWritesDisabledError()
        return JSONResponse(
            status_code=error.http_status,
            content={
                "code": error.code,
                "detail": error.detail,
                "correlation_id": error.correlation_id,
            },
            headers={"Cache-Control": "no-store", "Retry-After": "60"},
        )

    @router.post(
        "/v1/auth/invitations/preflight",
        response_model=AuthInvitationPreflightResponse,
        responses={400: {"model": AuthErrorResponse}, 404: {"model": AuthErrorResponse}},
    )
    def preflight_auth_invitation(
        payload: AuthInvitationPreflightRequest,
        request: Request,
        response: Response,
    ) -> AuthInvitationPreflightResponse:
        response.headers["Cache-Control"] = "no-store"
        repository = _build_repository(build_repository)
        try:
            _consume_preflight_rate_limit(repository, payload=payload, request=request)
            method = getattr(repository, "preflight_auth_invitation", None)
            if not callable(method):
                raise AuthContractError(
                    "auth_writes_temporarily_disabled",
                    "Authentication preflight is unavailable.",
                    http_status=503,
                )
            result = method(
                invitation_id=str(payload.invitation_id),
                invite_token=payload.invite_token,
                requested_surface=payload.requested_surface,
            )
            return AuthInvitationPreflightResponse(**asdict(result))
        except AuthDeliveryError as exc:
            raise AuthContractError(
                "auth_writes_temporarily_disabled",
                "Authentication delivery configuration is unavailable.",
                http_status=503,
            ) from exc
        finally:
            close_repository(repository)

    @router.post(
        "/v1/auth/invitations/redeem",
        response_model=AuthInvitationRedeemResponse,
        responses={
            409: {"model": AuthErrorResponse},
            410: {"model": AuthErrorResponse},
            429: {"model": AuthErrorResponse},
            503: {"model": AuthErrorResponse},
        },
    )
    def redeem_auth_invitation(
        payload: AuthInvitationRedeemRequest,
        response: Response,
        idempotency_key: str = Header(min_length=16, max_length=512, alias="Idempotency-Key"),
    ) -> AuthInvitationRedeemResponse:
        response.headers["Cache-Control"] = "no-store"
        repository = _build_repository(build_repository)
        try:
            method = getattr(repository, "redeem_auth_invitation_v2", None)
            if not callable(method):
                raise AuthContractError(
                    "auth_writes_temporarily_disabled",
                    "Authentication redemption is unavailable.",
                    http_status=503,
                )
            result = method(
                invitation_id=str(payload.invitation_id),
                invite_token=payload.invite_token,
                requested_surface=payload.requested_surface,
                idempotency_key=idempotency_key,
            )
            for cookie_header in result.cookie_delivery.cookie_headers:
                response.headers.append("Set-Cookie", cookie_header)
            return AuthInvitationRedeemResponse(
                recovery_status=result.recovery_status,
                session=RuntimeSessionScopeV2(**asdict(result.session)),
                correlation_id=result.correlation_id,
            )
        except AuthDeliveryError as exc:
            raise AuthContractError(
                "auth_writes_temporarily_disabled",
                "Authentication delivery configuration is unavailable.",
                http_status=503,
            ) from exc
        finally:
            close_repository(repository)

    @router.get("/v1/auth/me", response_model=AuthMeResponse)
    def runtime_auth_me(
        request: Request,
        x_geo_actor_id: str | None = Header(default=None, alias=runtime_actor_header),
        x_geo_csrf_token: str | None = Header(default=None, alias=csrf_header_name),
    ) -> AuthMeResponse:
        context = resolve_auth_context(x_geo_actor_id)
        scope = _scope_from_context(context)
        csrf_cookie = request.cookies.get(csrf_cookie_name, "").strip()
        csrf_header = (x_geo_csrf_token or "").strip()
        should_confirm_delivery = bool(
            csrf_header
            and csrf_cookie
            and hmac.compare_digest(csrf_header, csrf_cookie)
        )
        if should_confirm_delivery and context.session_id and context.tenant_id:
            repository = _build_repository(build_repository)
            try:
                confirm = getattr(repository, "confirm_auth_invitation_delivery", None)
                if callable(confirm):
                    confirm(
                        session_id=context.session_id,
                        actor_id=context.actor_id or "",
                        tenant_id=context.tenant_id,
                    )
            finally:
                close_repository(repository)
        return AuthMeResponse(session=scope)

    @router.post("/v1/auth/logout", response_model=AuthLogoutResponse)
    def runtime_auth_logout(
        response: Response,
        x_geo_actor_id: str | None = Header(default=None, alias=runtime_actor_header),
    ) -> AuthLogoutResponse:
        context = resolve_auth_context(x_geo_actor_id)
        if context.session_id:
            repository = _build_repository(build_repository)
            try:
                repository.revoke_runtime_session(
                    RuntimeSessionRevokeInput(
                        session_id=context.session_id,
                        revoked_by=context.actor_id or "runtime-auth",
                        reason="auth_logout",
                    )
                )
            finally:
                close_repository(repository)
        response.delete_cookie(
            key=session_cookie_name,
            httponly=True,
            secure=cookie_secure(),
            samesite="lax",
            path="/",
        )
        response.delete_cookie(
            key=csrf_cookie_name,
            httponly=False,
            secure=cookie_secure(),
            samesite="lax",
            path="/",
        )
        return AuthLogoutResponse()

    app.include_router(router)


def _build_repository(builder: Callable[[], object]) -> object:
    try:
        return builder()
    except RuntimePersistenceError as exc:
        raise AuthContractError(
            "auth_writes_temporarily_disabled",
            "Authentication persistence is unavailable.",
            http_status=503,
        ) from exc


def _consume_preflight_rate_limit(
    repository: object,
    *,
    payload: AuthInvitationPreflightRequest,
    request: Request,
) -> None:
    method = getattr(repository, "consume_auth_preflight_rate_limit", None)
    if not callable(method):
        raise AuthContractError(
            "auth_writes_temporarily_disabled",
            "Authentication preflight rate limiting is unavailable.",
            http_status=503,
        )
    limit = _bounded_env_int("GEO_AUTH_PREFLIGHT_RATE_LIMIT", default=20, minimum=1, maximum=1000)
    window_seconds = _bounded_env_int(
        "GEO_AUTH_PREFLIGHT_RATE_WINDOW_SECONDS",
        default=600,
        minimum=1,
        maximum=3600,
    )
    bucket_key = hashlib.sha256(
        f"invitation\0{str(payload.invitation_id)}".encode("utf-8")
    ).hexdigest()
    count = int(method(bucket_key=bucket_key, limit=limit, window_seconds=window_seconds))
    if count > limit:
        raise AuthContractError(
            "auth_preflight_rate_limited",
            "Too many authentication preflight requests.",
            http_status=429,
        )
    trusted_source_header = os.getenv("GEO_AUTH_PREFLIGHT_TRUSTED_SOURCE_HEADER", "").strip()
    trusted_source = request.headers.get(trusted_source_header, "").strip() if trusted_source_header else ""
    if not trusted_source:
        return
    source_limit = _bounded_env_int(
        "GEO_AUTH_PREFLIGHT_SOURCE_RATE_LIMIT",
        default=100,
        minimum=1,
        maximum=5000,
    )
    source_bucket_key = hashlib.sha256(f"source\0{trusted_source}".encode("utf-8")).hexdigest()
    source_count = int(method(bucket_key=source_bucket_key, limit=source_limit, window_seconds=window_seconds))
    if source_count > source_limit:
        raise AuthContractError(
            "auth_preflight_rate_limited",
            "Too many authentication preflight requests.",
            http_status=429,
        )


def _bounded_env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except ValueError as exc:
        raise AuthContractError(
            "auth_writes_temporarily_disabled",
            f"{name} configuration is invalid.",
            http_status=503,
        ) from exc
    if value < minimum or value > maximum:
        raise AuthContractError(
            "auth_writes_temporarily_disabled",
            f"{name} must be between {minimum} and {maximum}.",
            http_status=503,
        )
    return value


def _scope_from_context(context: AuthContext) -> RuntimeSessionScopeV2:
    if (
        not context.is_authenticated
        or context.scope_version != RUNTIME_SESSION_SCOPE_VERSION
        or context.authz_policy_version != AUTH_SURFACE_POLICY_VERSION
        or not context.actor_id
        or not context.tenant_id
    ):
        raise HTTPException(status_code=401, detail="runtime session scope-v2 authentication is required")
    return RuntimeSessionScopeV2(
        scope_version=RUNTIME_SESSION_SCOPE_VERSION,
        authz_policy_version=AUTH_SURFACE_POLICY_VERSION,
        actor_id=context.actor_id,
        tenant_id=context.tenant_id,
        tenant_roles=list(context.tenant_roles),
        project_scopes=[dict(scope) for scope in context.project_scopes],
        project_ids=list(context.project_ids),
    )
