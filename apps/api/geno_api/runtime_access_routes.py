from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from geno_core.models import (
    RuntimeCustomerPortalTokenActionInput,
    RuntimeCustomerPortalTokenInput,
    RuntimeProjectLaunchConfigInput,
    RuntimeProjectMemberInvitationAcceptInput,
)
from geno_core.runtime import RuntimePersistenceError, build_repository_from_env, close_repository_connection


class ProjectLaunchConfigRequest(BaseModel):
    project_id: str = Field(min_length=1)
    customer_email: str = Field(min_length=1, max_length=320)
    primary_domain: str = Field(min_length=1, max_length=320)
    competitor_domains: list[str] = Field(default_factory=list, max_length=5)
    locale: str = Field(default="en-AU", min_length=1, max_length=40)
    country_code: str = Field(default="AU", min_length=1, max_length=8)
    timezone: str = Field(default="Australia/Sydney", min_length=1, max_length=120)
    collection_mode: str = Field(default="api", min_length=1, max_length=40)
    schedule: dict[str, object] = Field(default_factory=dict)
    external_connectors: dict[str, object] = Field(default_factory=dict)
    scoring_profile: str = Field(default="au_visibility_v1", min_length=1, max_length=120)
    status: str = Field(default="draft", min_length=1, max_length=40)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    config_version: str = Field(default="au_launch_config_v1", min_length=1, max_length=120)
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
    portal_token: str | None = Field(default=None, max_length=200)
    invitation_id: str | None = Field(default=None, max_length=80)
    invite_token: str | None = Field(default=None, max_length=200)
    accepted_by: str | None = Field(default=None, max_length=320)


def register_runtime_access_routes(
    app: FastAPI,
    *,
    runtime_actor_header: str,
    project_manage_roles: tuple[str, ...],
    require_runtime_actor_id: Callable[[str | None], str | None],
    assert_runtime_project_access: Callable[..., None],
    runtime_project_access_control_enabled: Callable[[], bool],
) -> None:
    router = APIRouter()

    @router.get("/v1/project-launch-configs/runtime")
    def runtime_project_launch_config(
        project_id: str = Query(min_length=1),
        config_version: str = Query(default="au_launch_config_v1", min_length=1),
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
            if payload.portal_token:
                return _customer_portal_access_with_portal_token(
                    repository,
                    portal_token=payload.portal_token,
                    runtime_project_access_control_enabled=runtime_project_access_control_enabled,
                )
            if payload.invitation_id and payload.invite_token:
                return _customer_portal_access_with_invitation(
                    repository,
                    invitation_id=payload.invitation_id,
                    invite_token=payload.invite_token,
                    accepted_by=payload.accepted_by,
                    runtime_project_access_control_enabled=runtime_project_access_control_enabled,
                )
            raise HTTPException(status_code=400, detail="portal_token or invitation_id + invite_token is required")
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


def _customer_portal_access_with_invitation(
    repository: object,
    *,
    invitation_id: str,
    invite_token: str,
    accepted_by: str | None,
    runtime_project_access_control_enabled: Callable[[], bool],
) -> dict[str, object]:
    if runtime_project_access_control_enabled():
        set_invitation_context = getattr(repository, "set_runtime_project_invitation_accept_context", None)
        if not callable(set_invitation_context):
            raise HTTPException(
                status_code=503,
                detail="runtime invitation acceptance requires repository.set_runtime_project_invitation_accept_context",
            )
        set_invitation_context(invite_token_hash=hashlib.sha256(invite_token.strip().encode("utf-8")).hexdigest())
    try:
        accepted = repository.accept_runtime_project_member_invitation(
            RuntimeProjectMemberInvitationAcceptInput(
                invitation_id=invitation_id.strip(),
                invite_token=invite_token.strip(),
                accepted_by=accepted_by.strip() if accepted_by else None,
                reason="customer_portal_first_access",
            )
        )
        invitation = accepted.invitation
        member = invitation.get("member") if isinstance(invitation.get("member"), dict) else {}
        project_id = str(invitation["project_id"])
        member_user_id = str((member or {}).get("user_id") or invitation["email"]).strip().lower()
        if runtime_project_access_control_enabled():
            repository.set_runtime_project_access_context(actor_id=member_user_id, project_id=project_id)
        token = repository.create_customer_portal_token(
            RuntimeCustomerPortalTokenInput(
                project_id=project_id,
                member_user_id=member_user_id,
                invitation_id=str(invitation["id"]),
                issued_by=member_user_id,
                metadata={"created_from": "customer_portal_invitation_accept"},
                reason="customer_portal_first_access",
            )
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "project member invitation not found" else 409
        raise HTTPException(status_code=status_code, detail=message) from exc
    return {
        "portal_token": token.raw_token,
        "portal_token_record": asdict(token),
        "accepted_invitation": asdict(accepted),
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
