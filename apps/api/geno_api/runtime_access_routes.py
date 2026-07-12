from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from geno_core.models import (
    RuntimeCustomerPortalTokenActionInput,
    RuntimeCustomerPortalTokenInput,
    RuntimeProjectLaunchConfigInput,
)
from geno_core.runtime import RuntimePersistenceError, build_repository_from_env, close_repository_connection
from geno_core.auth import AUTH_SURFACE_POLICY_VERSION, RUNTIME_SESSION_SCOPE_VERSION, InvitationSurface


class ProjectLaunchConfigRequest(BaseModel):
    project_id: str = Field(min_length=1)
    customer_email: str = Field(min_length=1, max_length=320)
    primary_domain: str = Field(min_length=1, max_length=320)
    competitor_domains: list[str] = Field(default_factory=list, max_length=5)
    locale: str = Field(default="en", min_length=1, max_length=40)
    country_code: str = Field(default="GLOBAL", min_length=1, max_length=12)
    timezone: str = Field(default="UTC", min_length=1, max_length=120)
    collection_mode: str = Field(default="api", min_length=1, max_length=40)
    schedule: dict[str, object] = Field(default_factory=dict)
    external_connectors: dict[str, object] = Field(default_factory=dict)
    scoring_profile: str = Field(default="visibility_v1.0", min_length=1, max_length=120)
    status: str = Field(default="draft", min_length=1, max_length=40)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    config_version: str = Field(default="project_launch_config_v1", min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class CustomerPortalTokenCreateRequest(BaseModel):
    project_id: str = Field(min_length=1)
    member_user_id: str = Field(min_length=1, max_length=320)
    invitation_id: str | None = Field(default=None, max_length=80)
    issued_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    metadata: dict[str, object] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=500)


class CustomerPortalTokenRevokeRequest(BaseModel):
    project_id: str = Field(min_length=1)
    token_id: str = Field(min_length=1, max_length=80)
    revoked_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class CustomerPortalAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portal_token: str = Field(min_length=1, max_length=200)


def register_runtime_access_routes(
    app: FastAPI,
    *,
    runtime_actor_header: str,
    project_manage_roles: tuple[str, ...],
    require_runtime_actor_id: Callable[[str | None], str | None],
    assert_runtime_project_access: Callable[..., None],
    runtime_project_access_control_enabled: Callable[[], bool],
    resolve_auth_context: Callable[[str | None], object] | None = None,
    apply_runtime_project_db_context: Callable[..., None] | None = None,
    build_repository: Callable[[], object] = build_repository_from_env,
    close_repository: Callable[[object], None] = close_repository_connection,
) -> None:
    router = APIRouter()

    @router.get("/v1/projects/runtime")
    def runtime_projects_with_surface_projection(
        surface: InvitationSurface | None = Query(default=None),
        project_id: str | None = None,
        market_code: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        x_geno_actor_id: str | None = Header(default=None, alias=runtime_actor_header),
    ) -> dict[str, object]:
        actor_id = require_runtime_actor_id(x_geno_actor_id)
        context = resolve_auth_context(x_geno_actor_id) if callable(resolve_auth_context) else None
        try:
            repository = build_repository()
        except RuntimePersistenceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            project_ids: tuple[str, ...] = tuple(getattr(context, "project_ids", ()) or ())
            tenant_id = getattr(context, "tenant_id", None)
            if surface is not None:
                if (
                    getattr(context, "scope_version", None) != RUNTIME_SESSION_SCOPE_VERSION
                    or getattr(context, "authz_policy_version", None) != AUTH_SURFACE_POLICY_VERSION
                ):
                    raise HTTPException(status_code=401, detail="surface projection requires a scope-v2 session")
                scopes = tuple(getattr(context, "project_scopes", ()) or ())
                capability = "portal.admin.access" if surface is InvitationSurface.ADMIN else "portal.customer.access"
                project_ids = tuple(
                    str(scope.get("project_id"))
                    for scope in scopes
                    if isinstance(scope, dict)
                    and capability in tuple(scope.get("portal_capabilities") or ())
                    and scope.get("project_id")
                )
                if not project_ids:
                    return {
                        "total_count": 0,
                        "limit": limit,
                        "offset": offset,
                        "records": [],
                    }
            if callable(apply_runtime_project_db_context):
                apply_runtime_project_db_context(
                    repository,
                    actor_id=getattr(context, "actor_id", actor_id),
                    project_id=project_id,
                    tenant_id=tenant_id,
                    project_ids=project_ids,
                )
            if surface is not None:
                records: list[dict[str, object]] = []
                for scoped_project_id in project_ids:
                    if project_id and scoped_project_id != project_id:
                        continue
                    scoped_page = repository.list_runtime_projects(
                        project_id=scoped_project_id,
                        market_code=market_code,
                        status=status,
                        include_archived=include_archived,
                        actor_id=None,
                        limit=1,
                        offset=0,
                    )
                    records.extend(asdict(record) for record in scoped_page.records)
                records.sort(
                    key=lambda record: (
                        str((record.get("project") or {}).get("created_at") or ""),
                        str((record.get("project") or {}).get("id") or ""),
                    ),
                    reverse=True,
                )
                return {
                    "total_count": len(records),
                    "limit": limit,
                    "offset": offset,
                    "records": records[offset : offset + limit],
                }
            page = repository.list_runtime_projects(
                project_id=project_id,
                market_code=market_code,
                status=status,
                include_archived=include_archived,
                actor_id=None if project_ids else actor_id,
                limit=limit,
                offset=offset,
            )
            payload = asdict(page)
            return payload
        finally:
            close_repository(repository)

    @router.get("/v1/project-launch-configs/runtime")
    def runtime_project_launch_config(
        project_id: str = Query(min_length=1),
        config_version: str | None = Query(default=None, min_length=1),
        x_geno_actor_id: str | None = Header(default=None, alias=runtime_actor_header),
    ) -> dict[str, object]:
        actor_id = require_runtime_actor_id(x_geno_actor_id)
        try:
            repository = build_repository_from_env()
        except RuntimePersistenceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            assert_runtime_project_access(repository, project_id=project_id, actor_id=actor_id)
            launch_config = repository.get_project_launch_config(project_id=project_id, config_version=config_version)
            if launch_config is None:
                raise HTTPException(status_code=404, detail="project launch config not found")
            return asdict(launch_config)
        finally:
            close_repository_connection(repository)

    @router.post("/v1/project-launch-configs/runtime")
    def save_runtime_project_launch_config(
        payload: ProjectLaunchConfigRequest,
        x_geno_actor_id: str | None = Header(default=None, alias=runtime_actor_header),
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
                allowed_roles=project_manage_roles,
            )
            launch_config = repository.save_project_launch_config(
                RuntimeProjectLaunchConfigInput(
                    project_id=payload.project_id.strip(),
                    customer_email=payload.customer_email.strip(),
                    primary_domain=payload.primary_domain.strip(),
                    competitor_domains=tuple(payload.competitor_domains),
                    locale=payload.locale.strip(),
                    country_code=payload.country_code.strip(),
                    timezone=payload.timezone.strip(),
                    collection_mode=payload.collection_mode.strip(),
                    schedule=payload.schedule,
                    external_connectors=payload.external_connectors,
                    scoring_profile=payload.scoring_profile.strip(),
                    status=payload.status.strip(),
                    metadata=payload.metadata,
                    created_by=actor_id or payload.created_by.strip(),
                    updated_by=actor_id or payload.updated_by.strip(),
                    config_version=payload.config_version.strip(),
                    reason=payload.reason.strip() if payload.reason else None,
                )
            )
            return asdict(launch_config)
        except ValueError as exc:
            status_code = 404 if str(exc) == "project not found" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        finally:
            close_repository_connection(repository)

    @router.post("/v1/customer-portal/tokens/runtime")
    def create_runtime_customer_portal_token(
        payload: CustomerPortalTokenCreateRequest,
        x_geno_actor_id: str | None = Header(default=None, alias=runtime_actor_header),
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
                allowed_roles=project_manage_roles,
            )
            token = repository.create_customer_portal_token(
                RuntimeCustomerPortalTokenInput(
                    project_id=payload.project_id.strip(),
                    member_user_id=payload.member_user_id.strip(),
                    invitation_id=payload.invitation_id.strip() if payload.invitation_id else None,
                    issued_by=actor_id or payload.issued_by.strip(),
                    metadata=payload.metadata,
                    reason=payload.reason.strip() if payload.reason else None,
                )
            )
            return asdict(token)
        except ValueError as exc:
            message = str(exc)
            status_code = 404 if message in {"project not found", "project member not found"} else 400
            raise HTTPException(status_code=status_code, detail=message) from exc
        finally:
            close_repository_connection(repository)

    @router.get("/v1/customer-portal/tokens/runtime")
    def runtime_customer_portal_tokens(
        project_id: str = Query(min_length=1),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        x_geno_actor_id: str | None = Header(default=None, alias=runtime_actor_header),
    ) -> dict[str, object]:
        actor_id = require_runtime_actor_id(x_geno_actor_id)
        try:
            repository = build_repository_from_env()
        except RuntimePersistenceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            assert_runtime_project_access(
                repository,
                project_id=project_id,
                actor_id=actor_id,
                allowed_roles=project_manage_roles,
            )
            list_tokens = getattr(repository, "list_customer_portal_tokens", None)
            if not callable(list_tokens):
                raise HTTPException(status_code=503, detail="runtime customer portal token listing is unavailable")
            page = dict(list_tokens(project_id=project_id, limit=limit, offset=offset))
            page["records"] = [
                {key: value for key, value in dict(record).items() if key not in {"token_hash", "raw_token"}}
                for record in page.get("records", [])
            ]
            return page
        finally:
            close_repository_connection(repository)

    @router.post("/v1/customer-portal/tokens/runtime/revoke")
    def revoke_runtime_customer_portal_token(
        payload: CustomerPortalTokenRevokeRequest,
        x_geno_actor_id: str | None = Header(default=None, alias=runtime_actor_header),
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
                allowed_roles=project_manage_roles,
            )
            token = repository.revoke_customer_portal_token(
                RuntimeCustomerPortalTokenActionInput(
                    token_id=payload.token_id.strip(),
                    project_id=payload.project_id.strip(),
                    revoked_by=actor_id or payload.revoked_by.strip(),
                    reason=payload.reason.strip() if payload.reason else None,
                )
            )
            return asdict(token)
        except ValueError as exc:
            status_code = 404 if str(exc) == "customer portal token not found" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        finally:
            close_repository_connection(repository)

    @router.post("/v1/customer-portal/access")
    def customer_portal_access(payload: CustomerPortalAccessRequest) -> dict[str, object]:
        try:
            repository = build_repository_from_env()
        except RuntimePersistenceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            return _customer_portal_access_with_portal_token(
                repository,
                portal_token=payload.portal_token,
                runtime_project_access_control_enabled=runtime_project_access_control_enabled,
            )
        finally:
            close_repository_connection(repository)

    app.include_router(router)


def _customer_portal_access_with_portal_token(
    repository: object,
    *,
    portal_token: str,
    runtime_project_access_control_enabled: Callable[[], bool],
) -> dict[str, object]:
    portal_token_hash = hashlib.sha256(portal_token.strip().encode("utf-8")).hexdigest()
    if runtime_project_access_control_enabled():
        set_portal_context = getattr(repository, "set_runtime_project_portal_token_context", None)
        if not callable(set_portal_context):
            raise HTTPException(
                status_code=503,
                detail="runtime customer portal requires repository.set_runtime_project_portal_token_context",
            )
        set_portal_context(portal_token_hash=portal_token_hash)
    try:
        token = repository.validate_customer_portal_token(portal_token.strip())
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    project_id = str(token.portal_token["project_id"])
    member_user_id = str(token.portal_token["member_user_id"])
    if runtime_project_access_control_enabled():
        repository.set_runtime_project_access_context(actor_id=member_user_id, project_id=project_id)
    return {
        "portal_token": None,
        "portal_token_record": asdict(token),
        "bundle": _customer_portal_bundle(repository, project_id=project_id, member_user_id=member_user_id),
    }


def _customer_portal_bundle(repository: object, *, project_id: str, member_user_id: str) -> dict[str, object]:
    page = repository.list_runtime_projects(project_id=project_id, limit=1, offset=0)
    if page.total_count == 0:
        raise HTTPException(status_code=404, detail="project not found")
    project_record = asdict(page.records[0])
    launch_config = repository.get_project_launch_config(project_id=project_id)
    brand_kit = repository.get_project_brand_kit(project_id=project_id)
    lifecycle_events = repository.list_runtime_project_lifecycle_events(project_id=project_id, limit=20, offset=0)
    audit_events = repository.list_runtime_audit_events(project_id=project_id, limit=20, offset=0)
    score_config = repository.get_score_weight_config(project_id=project_id)
    return {
        "access": {
            "mode": "customer_portal",
            "project_id": project_id,
            "member_user_id": member_user_id,
            "allowed_scope": "single_project",
        },
        "project": project_record,
        "launch_config": asdict(launch_config) if launch_config else None,
        "brand_kit": asdict(brand_kit) if brand_kit else None,
        "score_weight_config": asdict(score_config) if score_config else None,
        "lifecycle_events": asdict(lifecycle_events),
        "audit_events": asdict(audit_events),
    }
