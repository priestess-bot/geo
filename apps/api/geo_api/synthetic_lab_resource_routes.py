"""Internal Synthetic Lab resource, review and manual import routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.catalog_routes import _principal
from geo_api.synthetic_lab_contracts import (
    ApproveManualImportPreviewRequest,
    CreateManualImportPreviewRequest,
    CreateReviewCaseRequest,
    CreateReviewSuiteRequest,
    CreateStyleProfileRequest,
    CreateStyleSourceRequest,
    DecideStyleProfileRequest,
    FreezeReviewSuiteRequest,
    FreezeStyleProfileRequest,
    ImportedSampleOptionPageResponse,
    ManualImportPreviewPageResponse,
    ManualImportPreviewResponse,
    ManualImportPreviewSummaryResponse,
    ManualSampleImportResponse,
    RejectManualImportPreviewRequest,
    ReviewCasePageResponse,
    ReviewCaseResponse,
    ReviewSuitePageResponse,
    ReviewSuiteResponse,
    StyleProfilePageResponse,
    StyleProfileResponse,
    StyleSourcePageResponse,
    StyleSourceResponse,
    SubmitStyleProfileRequest,
    SyntheticResourceInventoryResponse,
)
from geo_api.synthetic_lab_direct_routes import synthetic_lab_direct_resource_router
from geo_api.synthetic_lab_presenters import (
    case_page,
    case_response,
    imported_sample_option_page,
    manual_import_preview_page,
    manual_import_preview_response,
    manual_import_preview_summary,
    manual_import_response,
    profile_page,
    profile_response,
    resource_inventory_response,
    style_source_page,
    style_source_response,
    suite_page,
    suite_response,
)
from geo_api.synthetic_lab_route_support import (
    AuthorizationHeader,
    IdempotencyHeader,
    LimitQuery,
    OffsetQuery,
    run,
    run_write,
)


def synthetic_lab_resource_router() -> APIRouter:
    router = APIRouter()
    router.include_router(synthetic_lab_direct_resource_router())

    @router.get(
        "/resource-inventory",
        response_model=SyntheticResourceInventoryResponse,
        operation_id="getSyntheticResourceInventory",
    )
    def resource_inventory(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SyntheticResourceInventoryResponse:
        return resource_inventory_response(
            run(
                request,
                "resource_inventory",
                _principal(request, authorization),
                project_id=project_id,
            )
        )

    @router.get(
        "/style-sources",
        response_model=StyleSourcePageResponse,
        operation_id="listSyntheticStyleSources",
    )
    def list_style_sources(
        project_id: UUID,
        request: Request,
        limit: LimitQuery = 50,
        offset: OffsetQuery = 0,
        authorization: AuthorizationHeader = None,
    ) -> StyleSourcePageResponse:
        return style_source_page(
            run(
                request,
                "list_style_sources",
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )

    @router.post(
        "/style-sources",
        response_model=StyleSourceResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSyntheticStyleSource",
    )
    def create_style_source(
        project_id: UUID,
        payload: CreateStyleSourceRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StyleSourceResponse:
        return style_source_response(
            run_write(
                request,
                "create_style_source",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                payload=payload,
            )
        )

    @router.get(
        "/sample-import-previews",
        response_model=ManualImportPreviewPageResponse,
        operation_id="listSyntheticManualImportPreviews",
    )
    def list_import_previews(
        project_id: UUID,
        request: Request,
        limit: LimitQuery = 50,
        offset: OffsetQuery = 0,
        authorization: AuthorizationHeader = None,
    ) -> ManualImportPreviewPageResponse:
        return manual_import_preview_page(
            run(
                request,
                "list_import_previews",
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )

    @router.post(
        "/sample-import-previews",
        response_model=ManualImportPreviewResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSyntheticManualImportPreview",
    )
    def create_import_preview(
        project_id: UUID,
        payload: CreateManualImportPreviewRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ManualImportPreviewResponse:
        return manual_import_preview_response(
            run_write(
                request,
                "create_import_preview",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                payload=payload,
            )
        )

    @router.get(
        "/sample-import-previews/{preview_id}",
        response_model=ManualImportPreviewResponse,
        operation_id="getSyntheticManualImportPreview",
    )
    def get_import_preview(
        project_id: UUID,
        preview_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ManualImportPreviewResponse:
        return manual_import_preview_response(
            run(
                request,
                "get_import_preview",
                _principal(request, authorization),
                project_id=project_id,
                preview_id=preview_id,
            )
        )

    @router.post(
        "/sample-import-previews/{preview_id}/approve",
        response_model=ManualSampleImportResponse,
        operation_id="approveSyntheticManualImportPreview",
    )
    def approve_import_preview(
        project_id: UUID,
        preview_id: UUID,
        payload: ApproveManualImportPreviewRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ManualSampleImportResponse:
        return manual_import_response(
            run_write(
                request,
                "approve_import_preview",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                preview_id=preview_id,
                payload=payload,
            )
        )

    @router.post(
        "/sample-import-previews/{preview_id}/reject",
        response_model=ManualImportPreviewSummaryResponse,
        operation_id="rejectSyntheticManualImportPreview",
    )
    def reject_import_preview(
        project_id: UUID,
        preview_id: UUID,
        payload: RejectManualImportPreviewRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ManualImportPreviewSummaryResponse:
        return manual_import_preview_summary(
            run_write(
                request,
                "reject_import_preview",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                preview_id=preview_id,
                payload=payload,
            )
        )

    @router.get(
        "/sample-options",
        response_model=ImportedSampleOptionPageResponse,
        operation_id="listSyntheticImportedSampleOptions",
    )
    def list_imported_sample_options(
        project_id: UUID,
        request: Request,
        limit: LimitQuery = 50,
        offset: OffsetQuery = 0,
        authorization: AuthorizationHeader = None,
    ) -> ImportedSampleOptionPageResponse:
        return imported_sample_option_page(
            run(
                request,
                "list_imported_sample_options",
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )

    @router.get(
        "/style-profiles",
        response_model=StyleProfilePageResponse,
        operation_id="listSyntheticStyleProfiles",
    )
    def list_profiles(
        project_id: UUID,
        request: Request,
        limit: LimitQuery = 50,
        offset: OffsetQuery = 0,
        authorization: AuthorizationHeader = None,
    ) -> StyleProfilePageResponse:
        return profile_page(
            run(
                request,
                "list_profiles",
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )

    @router.post(
        "/style-profiles",
        response_model=StyleProfileResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSyntheticStyleProfile",
    )
    def create_profile(
        project_id: UUID,
        payload: CreateStyleProfileRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StyleProfileResponse:
        return profile_response(
            run_write(
                request,
                "create_profile",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                payload=payload,
            )
        )

    _mount_profile_transitions(router)
    _mount_review_suites(router)
    return router


def _mount_profile_transitions(router: APIRouter) -> None:
    @router.post(
        "/style-profiles/{profile_version_id}/submit",
        response_model=StyleProfileResponse,
        operation_id="submitSyntheticStyleProfile",
    )
    def submit_profile(
        project_id: UUID,
        profile_version_id: UUID,
        payload: SubmitStyleProfileRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StyleProfileResponse:
        return _profile_command(
            request, principal=_principal(request, authorization), method="submit_profile",
            project_id=project_id, profile_version_id=profile_version_id,
            payload=payload, idempotency_key=idempotency_key,
        )

    @router.post(
        "/style-profiles/{profile_version_id}/decision",
        response_model=StyleProfileResponse,
        operation_id="decideSyntheticStyleProfile",
    )
    def decide_profile(
        project_id: UUID,
        profile_version_id: UUID,
        payload: DecideStyleProfileRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StyleProfileResponse:
        return _profile_command(
            request, principal=_principal(request, authorization), method="decide_profile",
            project_id=project_id, profile_version_id=profile_version_id,
            payload=payload, idempotency_key=idempotency_key,
        )

    @router.post(
        "/style-profiles/{profile_version_id}/freeze",
        response_model=StyleProfileResponse,
        operation_id="freezeSyntheticStyleProfile",
    )
    def freeze_profile(
        project_id: UUID,
        profile_version_id: UUID,
        payload: FreezeStyleProfileRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> StyleProfileResponse:
        return _profile_command(
            request, principal=_principal(request, authorization), method="freeze_profile",
            project_id=project_id, profile_version_id=profile_version_id,
            payload=payload, idempotency_key=idempotency_key,
        )


def _profile_command(
    request: Request,
    *,
    principal: object,
    method: str,
    project_id: UUID,
    profile_version_id: UUID,
    payload: object,
    idempotency_key: str,
) -> StyleProfileResponse:
    return profile_response(
        run_write(
            request, method, principal, idempotency_key,
            project_id=project_id, profile_version_id=profile_version_id, payload=payload,
        )
    )


def _mount_review_suites(router: APIRouter) -> None:
    @router.get(
        "/review-suites",
        response_model=ReviewSuitePageResponse,
        operation_id="listSyntheticReviewSuites",
    )
    def list_suites(
        project_id: UUID,
        request: Request,
        limit: LimitQuery = 50,
        offset: OffsetQuery = 0,
        authorization: AuthorizationHeader = None,
    ) -> ReviewSuitePageResponse:
        return suite_page(
            run(
                request,
                "list_suites",
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
            )
        )

    @router.post(
        "/review-suites",
        response_model=ReviewSuiteResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSyntheticReviewSuite",
    )
    def create_suite(
        project_id: UUID,
        payload: CreateReviewSuiteRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ReviewSuiteResponse:
        return suite_response(
            run_write(
                request,
                "create_suite",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                payload=payload,
            )
        )

    @router.get(
        "/review-suites/{suite_version_id}/cases",
        response_model=ReviewCasePageResponse,
        operation_id="listSyntheticReviewCases",
    )
    def list_cases(
        project_id: UUID,
        suite_version_id: UUID,
        request: Request,
        limit: LimitQuery = 50,
        offset: OffsetQuery = 0,
        authorization: AuthorizationHeader = None,
    ) -> ReviewCasePageResponse:
        return case_page(
            run(
                request,
                "list_cases",
                _principal(request, authorization),
                project_id=project_id,
                suite_version_id=suite_version_id,
                limit=limit,
                offset=offset,
            )
        )

    @router.post(
        "/review-suites/{suite_version_id}/cases",
        response_model=ReviewCaseResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSyntheticReviewCase",
    )
    def create_case(
        project_id: UUID,
        suite_version_id: UUID,
        payload: CreateReviewCaseRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ReviewCaseResponse:
        return case_response(
            run_write(
                request,
                "create_case",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                suite_version_id=suite_version_id,
                payload=payload,
            )
        )

    @router.post(
        "/review-suites/{suite_version_id}/freeze",
        response_model=ReviewSuiteResponse,
        operation_id="freezeSyntheticReviewSuite",
    )
    def freeze_suite(
        project_id: UUID,
        suite_version_id: UUID,
        payload: FreezeReviewSuiteRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ReviewSuiteResponse:
        return suite_response(
            run_write(
                request,
                "freeze_suite",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                suite_version_id=suite_version_id,
                payload=payload,
            )
        )


__all__ = ["synthetic_lab_resource_router"]
