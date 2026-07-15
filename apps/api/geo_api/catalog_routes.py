"""Internal-only stable API routes for Project Catalog and Evidence."""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, status

from geo_api.catalog_contracts import (
    CatalogProjectResponse,
    CreateEntityRequest,
    CreateEvidenceRequest,
    CreateMarketProfileRequest,
    CreateProjectRequest,
    DevelopmentBootstrapRequest,
    DevelopmentBootstrapResponse,
    EntityResponse,
    EvidenceResponse,
    EvidenceSnapshotResponse,
    MarketProfileResponse,
    PublicCitationResponse,
    SourceRevisionResponse,
    TextEvidenceSnapshot,
    UpdateProjectRequest,
)
from geo_api.foundation_services import AuthenticationInput, FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.access.models import AccessPrincipal
from geo_core.catalog.application import CatalogApplication
from geo_core.catalog.domain import (
    CatalogConflict,
    CatalogForbidden,
    CatalogNotFound,
    CatalogPersistenceUnavailable,
    CatalogRuleViolation,
    Confidentiality,
    EntityType,
    EvidenceDraft,
    EvidenceItem,
    EvidenceItemType,
    EvidenceSnapshot,
    MarketProfile,
    ProductEntity,
    Project,
    PublicCitation,
    SubjectRole,
    UsageRights,
)


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


def catalog_router() -> APIRouter:
    router = APIRouter(prefix="/v1/projects", tags=["project catalog"], responses=PROBLEM_RESPONSES)

    @router.post(
        "",
        response_model=CatalogProjectResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createProject",
    )
    def create_project(
        payload: CreateProjectRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> CatalogProjectResponse:
        return _project(
            _call(
                lambda: _catalog(request).create_project(
                    _principal(request, authorization), name=payload.name
                )
            )
        )

    @router.get(
        "/{project_id}", response_model=CatalogProjectResponse, operation_id="getProject"
    )
    def get_project(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> CatalogProjectResponse:
        return _project(
            _call(
                lambda: _catalog(request).get_project(
                    _principal(request, authorization), project_id=project_id
                )
            )
        )

    @router.patch(
        "/{project_id}", response_model=CatalogProjectResponse, operation_id="updateProject"
    )
    def update_project(
        project_id: UUID,
        payload: UpdateProjectRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> CatalogProjectResponse:
        return _project(
            _call(
                lambda: _catalog(request).update_project(
                    _principal(request, authorization),
                    project_id=project_id,
                    name=payload.name,
                    status=payload.status,
                )
            )
        )

    @router.post(
        "/{project_id}/entities",
        response_model=EntityResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createProductEntity",
    )
    def create_entity(
        project_id: UUID,
        payload: CreateEntityRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> EntityResponse:
        entity = _call(
            lambda: _catalog(request).create_entity(
                _principal(request, authorization),
                project_id=project_id,
                entity_type=EntityType(payload.entity_type),
                canonical_name=payload.canonical_name,
                canonical_url=payload.canonical_url,
                attributes=payload.attributes,
            )
        )
        return _entity(entity)

    @router.get(
        "/{project_id}/entities",
        response_model=list[EntityResponse],
        operation_id="listProductEntities",
    )
    def list_entities(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[EntityResponse]:
        items = _call(
            lambda: _catalog(request).list_entities(
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )
        return [_entity(item) for item in items]

    @router.post(
        "/{project_id}/market-profiles",
        response_model=MarketProfileResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createMarketProfile",
    )
    def create_market_profile(
        project_id: UUID,
        payload: CreateMarketProfileRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> MarketProfileResponse:
        profile = _call(
            lambda: _catalog(request).create_market_profile(
                _principal(request, authorization),
                project_id=project_id,
                market_code=payload.market_code,
                locale=payload.locale,
                timezone=payload.timezone,
                rules=payload.rules,
            )
        )
        return _market(profile)

    @router.get(
        "/{project_id}/market-profiles",
        response_model=list[MarketProfileResponse],
        operation_id="listMarketProfiles",
    )
    def list_market_profiles(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[MarketProfileResponse]:
        items = _call(
            lambda: _catalog(request).list_market_profiles(
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )
        return [_market(item) for item in items]

    @router.post(
        "/{project_id}/evidence-items",
        response_model=EvidenceResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createEvidenceItem",
    )
    def create_evidence(
        project_id: UUID,
        payload: CreateEvidenceRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> EvidenceResponse:
        item = _call(
            lambda: _catalog(request).create_evidence(
                _principal(request, authorization),
                project_id=project_id,
                draft=_draft(payload),
            )
        )
        return _evidence(item)

    @router.get(
        "/{project_id}/evidence-items",
        response_model=list[EvidenceResponse],
        operation_id="listEvidenceItems",
    )
    def list_evidence(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[EvidenceResponse]:
        items = _call(
            lambda: _catalog(request).list_evidence(
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )
        return [_evidence(item) for item in items]

    return router


def catalog_bootstrap_router() -> APIRouter:
    router = APIRouter(prefix="/v1/dev-tools", tags=["development tools"])

    @router.post(
        "/catalog-bootstrap",
        response_model=DevelopmentBootstrapResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="bootstrapDevelopmentCatalog",
    )
    def bootstrap(
        payload: DevelopmentBootstrapRequest, request: Request
    ) -> DevelopmentBootstrapResponse:
        result = _call(
            lambda: _catalog(request).bootstrap_development(
                tenant_name=payload.tenant_name,
                identity_subject=payload.identity_subject,
                identity_email=payload.identity_email,
                project_name=payload.project_name,
            )
        )
        return DevelopmentBootstrapResponse(
            tenant_id=result.tenant_id,
            identity_id=result.identity_id,
            project=_project(result.project),
        )

    return router


def _principal(request: Request, authorization: str | None) -> AccessPrincipal:
    authentication = AuthenticationInput(
        authorization=authorization,
        customer_session=request.cookies.get(request.app.state.customer_session_cookie_name),
        development_actor_id=request.headers.get("X-GEO-Actor-ID"),
        development_tenant_id=request.headers.get("X-GEO-Tenant-ID"),
    )
    service = request.app.state.services
    authenticate = getattr(service, "authenticate", None)
    if not callable(authenticate):
        raise FoundationServiceUnavailable("Principal authentication is not connected.")
    return cast(AccessPrincipal, authenticate(authentication))


def _catalog(request: Request) -> CatalogApplication:
    application = request.app.state.catalog_application
    if not isinstance(application, CatalogApplication):
        raise FoundationServiceUnavailable("The Catalog application service is not configured.")
    return application


def _call(operation: Any) -> Any:
    try:
        return operation()
    except CatalogRuleViolation as error:
        raise ApiProblem(
            status=422,
            title="Unprocessable Content",
            detail=str(error),
            type_uri="urn:geo:problem:catalog-rule-violation",
        ) from error
    except CatalogForbidden as error:
        raise ApiProblem(
            status=403,
            title="Forbidden",
            detail=str(error),
            type_uri="urn:geo:problem:catalog-forbidden",
        ) from error
    except CatalogNotFound as error:
        raise ApiProblem(
            status=404,
            title="Not Found",
            detail=str(error),
            type_uri="urn:geo:problem:catalog-not-found",
        ) from error
    except CatalogConflict as error:
        raise ApiProblem(
            status=409,
            title="Conflict",
            detail=str(error),
            type_uri="urn:geo:problem:catalog-conflict",
        ) from error
    except CatalogPersistenceUnavailable as error:
        raise ApiProblem(
            status=503,
            title="Service Unavailable",
            detail=str(error),
            type_uri="urn:geo:problem:catalog-persistence-unavailable",
        ) from error


def _project(item: Project) -> CatalogProjectResponse:
    return CatalogProjectResponse(**item.__dict__)


def _entity(item: ProductEntity) -> EntityResponse:
    return EntityResponse(
        id=item.id,
        project_id=item.project_id,
        entity_type=item.entity_type.value,
        canonical_name=item.canonical_name,
        canonical_url=item.canonical_url,
        attributes=dict(item.attributes),
        status=item.status,
        created_at=item.created_at,
    )


def _market(item: MarketProfile) -> MarketProfileResponse:
    return MarketProfileResponse(
        id=item.id,
        project_id=item.project_id,
        market_code=item.market_code,
        locale=item.locale,
        timezone=item.timezone,
        rules=dict(item.rules),
        status=item.status,
        created_at=item.created_at,
    )


def _draft(payload: CreateEvidenceRequest) -> EvidenceDraft:
    snapshot = (
        EvidenceSnapshot(text=payload.snapshot.text, uri=None, sha256=payload.snapshot.sha256)
        if isinstance(payload.snapshot, TextEvidenceSnapshot)
        else EvidenceSnapshot(text=None, uri=payload.snapshot.uri, sha256=payload.snapshot.sha256)
    )
    return EvidenceDraft(
        item_type=EvidenceItemType(payload.item_type),
        source_id=payload.source_id,
        subject_entity_id=payload.subject_entity_id,
        subject_role=SubjectRole(payload.subject_role),
        locator=payload.locator,
        snapshot=snapshot,
        source_revision_kind=payload.source_revision.kind,
        source_revision_value=payload.source_revision.value,
        usage_rights=UsageRights(payload.usage_rights),
        confidentiality=Confidentiality(payload.confidentiality),
        public_citation=PublicCitation(**payload.public_citation.model_dump()),
    )


def _evidence(item: EvidenceItem) -> EvidenceResponse:
    draft = item.draft
    snapshot = draft.snapshot
    return EvidenceResponse(
        id=item.id,
        project_id=item.project_id,
        item_type=draft.item_type.value,
        source_id=draft.source_id,
        subject_entity_id=draft.subject_entity_id,
        subject_role=draft.subject_role.value,
        locator=dict(draft.locator),
        snapshot=EvidenceSnapshotResponse(
            kind="text" if snapshot.text is not None else "minio",
            text=snapshot.text,
            uri=snapshot.uri,
            sha256=snapshot.sha256,
        ),
        source_revision=SourceRevisionResponse(
            kind=draft.source_revision_kind, value=draft.source_revision_value
        ),
        usage_rights=draft.usage_rights.value,
        confidentiality=draft.confidentiality.value,
        public_citation=PublicCitationResponse(**draft.public_citation.__dict__),
        eligible_for_generation=item.eligible_for_generation,
        eligible_for_publication=item.eligible_for_publication,
        created_at=item.created_at,
    )
