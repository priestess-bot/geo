"""Internal-only project-scoped Secret Store metadata and lifecycle routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, TypeVar, cast
from uuid import UUID, uuid5

from fastapi import APIRouter, Header, Path, Query, Request, status

from geo_api.foundation_services import AuthenticationInput, FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.secret_store_contracts import (
    CreateSecretRequest,
    SecretAuditEventPage,
    SecretReferencePage,
    SecretReferenceResponse,
    SecretVersionResponse,
    SecretVersionTransitionRequest,
    StageSecretRotationRequest,
)
from geo_api.secret_store_presenters import (
    audit_page_response,
    reference_page_response,
    reference_response,
    version_response,
)
from geo_api.secret_store_runtime import SecretStoreApi
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.access.models import AccessPrincipal
from geo_core.secrets import (
    SecretAuthorizationError,
    SecretConcurrencyConflict,
    SecretContractError,
    SecretIdempotencyConflict,
    SecretLifecycleError,
    SecretNotFound,
    SecretScopeViolation,
    SecretStateConflict,
    SecretStoreError,
    SecretValue,
    SecretVersionUnavailable,
)


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=256),
]
VersionPath = Annotated[int, Path(ge=1)]
_ADMIN_ROLES = frozenset({"owner", "admin"})
T = TypeVar("T")
_REFERENCE_NAMESPACE = UUID("cda9062f-a60d-5f31-891d-779d3a56aa11")


def secret_store_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/secrets",
        tags=["secret store"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "",
        response_model=SecretVersionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSecretReference",
    )
    def create_secret(
        project_id: UUID,
        payload: CreateSecretRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SecretVersionResponse:
        principal = _principal(request, authorization, project_id)
        reference_id = payload.reference_id or _generated_reference_id(
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        return version_response(
            _call(
                lambda: _api(request).create(
                    principal,
                    project_id=project_id,
                    reference_id=reference_id,
                    purpose=payload.purpose.value,
                    value=SecretValue(payload.secret_value.get_secret_value()),
                    expected_version=payload.expected_version,
                    idempotency_key=idempotency_key,
                )
            )
        )

    @router.get(
        "",
        response_model=SecretReferencePage,
        operation_id="listSecretReferences",
    )
    def list_secrets(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SecretReferencePage:
        principal = _principal(request, authorization, project_id)
        return reference_page_response(
            _call(
                lambda: _api(request).list_references(
                    principal,
                    project_id=project_id,
                    limit=limit,
                    offset=offset,
                )
            )
        )

    @router.get(
        "/audit-events",
        response_model=SecretAuditEventPage,
        operation_id="listSecretAuditEvents",
    )
    def list_audits(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SecretAuditEventPage:
        principal = _principal(request, authorization, project_id)
        return audit_page_response(
            _call(
                lambda: _api(request).list_audits(
                    principal,
                    project_id=project_id,
                    limit=limit,
                    offset=offset,
                )
            )
        )

    @router.get(
        "/{reference_id}",
        response_model=SecretReferenceResponse,
        operation_id="getSecretReference",
    )
    def get_secret(
        project_id: UUID,
        reference_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SecretReferenceResponse:
        principal = _principal(request, authorization, project_id)
        return reference_response(
            _call(
                lambda: _api(request).get_reference(
                    principal,
                    project_id=project_id,
                    reference_id=reference_id,
                )
            )
        )

    @router.post(
        "/{reference_id}/versions/{version}/verify",
        response_model=SecretVersionResponse,
        operation_id="verifySecretVersionCanary",
    )
    def verify_secret(
        project_id: UUID,
        reference_id: UUID,
        version: VersionPath,
        payload: SecretVersionTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SecretVersionResponse:
        principal = _principal(request, authorization, project_id)
        return version_response(
            _call(
                lambda: _api(request).verify(
                    principal,
                    project_id=project_id,
                    reference_id=reference_id,
                    version=version,
                    expected_version=payload.expected_version,
                    idempotency_key=idempotency_key,
                )
            )
        )

    @router.post(
        "/{reference_id}/versions",
        response_model=SecretVersionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="stageSecretRotation",
    )
    def stage_rotation(
        project_id: UUID,
        reference_id: UUID,
        payload: StageSecretRotationRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SecretVersionResponse:
        principal = _principal(request, authorization, project_id)
        return version_response(
            _call(
                lambda: _api(request).stage_rotation(
                    principal,
                    project_id=project_id,
                    reference_id=reference_id,
                    value=SecretValue(payload.secret_value.get_secret_value()),
                    expected_version=payload.expected_version,
                    idempotency_key=idempotency_key,
                )
            )
        )

    @router.post(
        "/{reference_id}/versions/{version}/activate",
        response_model=SecretVersionResponse,
        operation_id="activateSecretVersion",
    )
    def activate_secret(
        project_id: UUID,
        reference_id: UUID,
        version: VersionPath,
        payload: SecretVersionTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SecretVersionResponse:
        principal = _principal(request, authorization, project_id)
        return version_response(
            _call(
                lambda: _api(request).activate(
                    principal,
                    project_id=project_id,
                    reference_id=reference_id,
                    version=version,
                    expected_version=payload.expected_version,
                    idempotency_key=idempotency_key,
                )
            )
        )

    @router.post(
        "/{reference_id}/versions/{version}/revoke",
        response_model=SecretVersionResponse,
        operation_id="revokeSecretVersion",
    )
    def revoke_secret(
        project_id: UUID,
        reference_id: UUID,
        version: VersionPath,
        payload: SecretVersionTransitionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SecretVersionResponse:
        principal = _principal(request, authorization, project_id)
        return version_response(
            _call(
                lambda: _api(request).revoke(
                    principal,
                    project_id=project_id,
                    reference_id=reference_id,
                    version=version,
                    expected_version=payload.expected_version,
                    idempotency_key=idempotency_key,
                )
            )
        )

    return router


def _generated_reference_id(*, project_id: UUID, idempotency_key: str) -> UUID:
    """Generate a stable opaque ID so retries preserve the command fingerprint."""

    return uuid5(_REFERENCE_NAMESPACE, f"{project_id}:{idempotency_key}")


def _principal(
    request: Request,
    authorization: str | None,
    project_id: UUID,
) -> AccessPrincipal:
    authentication = AuthenticationInput(
        authorization=authorization,
        customer_session=request.cookies.get(request.app.state.customer_session_cookie_name),
        development_actor_id=request.headers.get("X-GEO-Actor-ID"),
        development_tenant_id=request.headers.get("X-GEO-Tenant-ID"),
    )
    operation = getattr(request.app.state.services, "require_project_role", None)
    if not callable(operation):
        raise FoundationServiceUnavailable("Project authorization is not connected.")
    return cast(
        AccessPrincipal,
        operation(authentication, project_id=project_id, allowed_roles=_ADMIN_ROLES),
    )


def _api(request: Request) -> SecretStoreApi:
    application = getattr(request.app.state, "secret_store_application", None)
    if application is None:
        raise FoundationServiceUnavailable(
            "Secret Store persistence is unavailable until its migration-backed adapter is installed."
        )
    return cast(SecretStoreApi, application)


def _call(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except SecretContractError as error:
        raise _problem(422, "Unprocessable Content", error, "contract") from error
    except (SecretAuthorizationError, SecretScopeViolation) as error:
        raise _problem(403, "Forbidden", error, "forbidden") from error
    except SecretNotFound as error:
        raise _problem(404, "Not Found", error, "not-found") from error
    except (
        SecretIdempotencyConflict,
        SecretConcurrencyConflict,
        SecretLifecycleError,
        SecretStateConflict,
        SecretVersionUnavailable,
    ) as error:
        raise _problem(409, "Conflict", error, "conflict") from error
    except SecretStoreError as error:
        raise _problem(503, "Service Unavailable", error, "unavailable") from error


def _problem(status_code: int, title: str, error: Exception, suffix: str) -> ApiProblem:
    return ApiProblem(
        status=status_code,
        title=title,
        detail=str(error),
        type_uri=f"urn:geo:problem:secret-store-{suffix}",
        headers={"Retry-After": "30"} if status_code == 503 else None,
    )
