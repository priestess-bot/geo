"""Internal-only project routes for Synthetic Lab authorization and composition."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.catalog_routes import _principal
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.synthetic_lab_contracts import (
    AuthorizationPageResponse,
    AuthorizationResponse,
    CreateAuthorizationRequest,
    DecideAuthorizationRequest,
    ReassessAuthorizationRequest,
    RevokeAuthorizationRequest,
)
from geo_api.synthetic_lab_presenters import authorization_page, authorization_response
from geo_api.synthetic_lab_resource_routes import synthetic_lab_resource_router
from geo_api.synthetic_lab_route_support import (
    AuthorizationHeader,
    IdempotencyHeader,
    LimitQuery,
    OffsetQuery,
    run,
    run_write,
)


def synthetic_lab_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/synthetic-lab",
        tags=["synthetic lab"],
        responses=PROBLEM_RESPONSES,
    )

    @router.get(
        "/authorizations",
        response_model=AuthorizationPageResponse,
        operation_id="listSyntheticCollectionAuthorizations",
    )
    def list_authorizations(
        project_id: UUID,
        request: Request,
        limit: LimitQuery = 50,
        offset: OffsetQuery = 0,
        authorization: AuthorizationHeader = None,
    ) -> AuthorizationPageResponse:
        return authorization_page(
            run(
                request,
                "list_authorizations",
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )

    @router.post(
        "/authorizations",
        response_model=AuthorizationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSyntheticCollectionAuthorization",
    )
    def create_authorization(
        project_id: UUID,
        payload: CreateAuthorizationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AuthorizationResponse:
        return authorization_response(
            run_write(
                request,
                "create_authorization",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                payload=payload,
            )
        )

    @router.post(
        "/authorizations/{authorization_id}/decision",
        response_model=AuthorizationResponse,
        operation_id="decideSyntheticCollectionAuthorization",
    )
    def decide_authorization(
        project_id: UUID,
        authorization_id: UUID,
        payload: DecideAuthorizationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AuthorizationResponse:
        return authorization_response(
            run_write(
                request,
                "decide_authorization",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                authorization_id=authorization_id,
                payload=payload,
            )
        )

    @router.post(
        "/authorizations/{authorization_id}/revoke",
        response_model=AuthorizationResponse,
        operation_id="revokeSyntheticCollectionAuthorization",
    )
    def revoke_authorization(
        project_id: UUID,
        authorization_id: UUID,
        payload: RevokeAuthorizationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AuthorizationResponse:
        return authorization_response(
            run_write(
                request,
                "revoke_authorization",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                authorization_id=authorization_id,
                payload=payload,
            )
        )

    @router.post(
        "/authorizations/{authorization_id}/reassess",
        response_model=AuthorizationResponse,
        operation_id="reassessSyntheticCollectionAuthorization",
    )
    def reassess_authorization(
        project_id: UUID,
        authorization_id: UUID,
        payload: ReassessAuthorizationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AuthorizationResponse:
        return authorization_response(
            run_write(
                request,
                "reassess_authorization",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                authorization_id=authorization_id,
                payload=payload,
            )
        )

    router.include_router(synthetic_lab_resource_router())
    from geo_api.synthetic_lab_job_routes import synthetic_lab_job_router

    router.include_router(synthetic_lab_job_router())
    return router


__all__ = ["synthetic_lab_router"]
