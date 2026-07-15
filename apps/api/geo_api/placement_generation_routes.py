"""Evidence, prompt, generation and immutable package routes."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from geo_api.contracts import JobAccepted, JobState
from geo_api.placement_contracts import (
    AsyncResourceCreated,
    ClaimView,
    EvidenceAttemptView,
    EvidenceItemView,
    ExportView,
    GenerationCreate,
    PackageEdit,
    PackageVersionView,
    PromptBundleCreate,
    PromptBundleDetail,
    PromptBundleView,
    PromptReleaseCreate,
    PromptReleaseView,
    PromptSkillCreate,
    PromptSkillView,
    PromptTaskBindingCreate,
    PromptTaskBindingView,
    ReviewCreate,
    ReviewSubmissionView,
    ReviewView,
)
from geo_api.placement_access import PlacementApprover, PlacementEditor, PlacementViewer
from geo_api.placement_routes_shared import IdempotencyHeader, placement_services
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES


def generation_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo",
        tags=["GEO evidence-led generation"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/brief-versions/{brief_version_id}/evidence-pack-attempts",
        response_model=AsyncResourceCreated,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="buildPlacementEvidencePack",
    )
    def create_evidence_attempt(
        project_id: UUID,
        brief_version_id: UUID,
        request: Request,
        idempotency_key: IdempotencyHeader,
        principal: PlacementEditor,
    ) -> AsyncResourceCreated:
        del principal
        attempt, job = placement_services(request).create_evidence_attempt(
            project_id=project_id,
            brief_version_id=brief_version_id,
            idempotency_key=idempotency_key,
        )
        return AsyncResourceCreated(
            resource=EvidenceAttemptView.model_validate(attempt),
            job_id=job.id,
            status=JobState(job.status),
            status_url=f"/v1/jobs/{job.id}",
        )

    @router.get(
        "/brief-versions/{brief_version_id}/evidence-pack-attempts",
        response_model=list[EvidenceAttemptView],
        operation_id="listPlacementEvidencePackAttempts",
    )
    def list_evidence_attempts(
        project_id: UUID,
        brief_version_id: UUID,
        request: Request,
        principal: PlacementViewer,
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_evidence_attempts(
            project_id=project_id, brief_version_id=brief_version_id
        )

    @router.get(
        "/evidence-pack-attempts/{attempt_id}",
        response_model=EvidenceAttemptView,
        operation_id="getPlacementEvidencePackAttempt",
    )
    def get_evidence_attempt(
        project_id: UUID, attempt_id: UUID, request: Request, principal: PlacementViewer
    ) -> object:
        del principal
        attempt = placement_services(request).get_evidence_attempt(
            project_id=project_id, attempt_id=attempt_id
        )
        if attempt is None:
            raise ApiProblem(status=404, title="Not Found", detail="Evidence attempt not found.")
        return attempt

    @router.get(
        "/evidence-pack-attempts/{attempt_id}/items",
        response_model=list[EvidenceItemView],
        operation_id="listPlacementEvidencePackItems",
    )
    def list_evidence_items(
        project_id: UUID, attempt_id: UUID, request: Request, principal: PlacementViewer
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_evidence_attempt_items(
            project_id=project_id, attempt_id=attempt_id
        )

    @router.post(
        "/prompt-skills",
        response_model=PromptSkillView,
        status_code=status.HTTP_201_CREATED,
        operation_id="createPlacementPromptSkill",
    )
    def create_skill(
        project_id: UUID,
        payload: PromptSkillCreate,
        request: Request,
        principal: PlacementEditor,
    ) -> object:
        del principal
        return placement_services(request).create_prompt_skill(
            project_id=project_id, skill_key=payload.skill_key
        )

    @router.get(
        "/prompt-skills",
        response_model=list[PromptSkillView],
        operation_id="listPlacementPromptSkills",
    )
    def list_skills(
        project_id: UUID, request: Request, principal: PlacementViewer
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_prompt_skills(project_id=project_id)

    @router.post(
        "/prompt-skills/{skill_id}/releases",
        response_model=PromptReleaseView,
        status_code=status.HTTP_201_CREATED,
        operation_id="publishPlacementPromptRelease",
    )
    def publish_release(
        project_id: UUID,
        skill_id: UUID,
        payload: PromptReleaseCreate,
        request: Request,
        principal: PlacementEditor,
    ) -> object:
        return placement_services(request).publish_skill_version(
            project_id=project_id,
            skill_id=skill_id,
            source=payload.source,
            actor_id=principal.identity_id,
            output_schema=payload.output_schema,
            client_variable_names=tuple(payload.client_variable_names),
        )

    @router.get(
        "/prompt-skills/{skill_id}/releases",
        response_model=list[PromptReleaseView],
        operation_id="listPlacementPromptReleases",
    )
    def list_releases(
        project_id: UUID, skill_id: UUID, request: Request, principal: PlacementViewer
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_prompt_releases(
            project_id=project_id, skill_id=skill_id
        )

    @router.post(
        "/brief-versions/{brief_version_id}/prompt-bundles",
        response_model=PromptBundleView,
        status_code=status.HTTP_201_CREATED,
        operation_id="createPlacementPromptBundle",
    )
    def create_bundle(
        project_id: UUID,
        brief_version_id: UUID,
        payload: PromptBundleCreate,
        request: Request,
        principal: PlacementEditor,
    ) -> object:
        del principal
        return placement_services(request).create_prompt_bundle(
            project_id=project_id,
            brief_version_id=brief_version_id,
            evidence_pack_attempt_id=payload.evidence_pack_attempt_id,
            release_id=payload.template_release_id,
            variables=payload.variables,
            model_policy_hash=payload.model_policy_hash,
        )

    @router.get(
        "/brief-versions/{brief_version_id}/prompt-bundles",
        response_model=list[PromptBundleView],
        operation_id="listPlacementPromptBundles",
    )
    def list_bundles(
        project_id: UUID,
        brief_version_id: UUID,
        request: Request,
        principal: PlacementViewer,
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_prompt_bundles(
            project_id=project_id, brief_version_id=brief_version_id
        )

    @router.get(
        "/prompt-bundles/{bundle_id}",
        response_model=PromptBundleDetail,
        operation_id="getPlacementPromptBundle",
    )
    def get_bundle(
        project_id: UUID, bundle_id: UUID, request: Request, principal: PlacementViewer
    ) -> object:
        del principal
        bundle = placement_services(request).get_prompt_bundle(
            project_id=project_id, bundle_id=bundle_id
        )
        if bundle is None:
            raise ApiProblem(status=404, title="Not Found", detail="Prompt bundle not found.")
        return bundle

    @router.put(
        "/prompt-task-bindings/{task_key}",
        response_model=PromptTaskBindingView,
        operation_id="selectPlacementPromptRelease",
    )
    def select_prompt_release(
        project_id: UUID,
        task_key: Literal[
            "owned_site",
            "productreview",
            "youtube",
            "reddit",
            "amazon",
            "ozbargain",
            "tiktok",
            "instagram",
            "quora",
        ],
        payload: PromptTaskBindingCreate,
        request: Request,
        principal: PlacementEditor,
    ) -> object:
        return placement_services(request).select_prompt_release(
            project_id=project_id,
            task_key=task_key,
            release_id=payload.template_release_id,
            selected_by=principal.identity_id,
        )

    @router.get(
        "/prompt-task-bindings",
        response_model=list[PromptTaskBindingView],
        operation_id="listPlacementPromptReleaseSelections",
    )
    def list_prompt_release_selections(
        project_id: UUID, request: Request, principal: PlacementViewer
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_prompt_release_selections(project_id=project_id)

    @router.post(
        "/prompt-bundles/{prompt_bundle_id}/generation-jobs",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="requestPlacementGeneration",
    )
    def request_generation(
        project_id: UUID,
        prompt_bundle_id: UUID,
        payload: GenerationCreate,
        request: Request,
        idempotency_key: IdempotencyHeader,
        principal: PlacementEditor,
    ) -> JobAccepted:
        job = placement_services(request).request_generation(
            project_id=project_id,
            prompt_bundle_id=prompt_bundle_id,
            configured_model=payload.configured_model,
            model_call_budget=payload.model_call_budget,
            idempotency_key=idempotency_key,
            requested_by=principal.identity_id,
        )
        return JobAccepted(
            job_id=job.id,
            status=JobState(job.status),
            status_url=f"/v1/jobs/{job.id}",
        )

    @router.get(
        "/opportunities/{opportunity_id}/package-versions",
        response_model=list[PackageVersionView],
        operation_id="listPlacementPackageVersions",
    )
    def list_versions(
        project_id: UUID,
        opportunity_id: UUID,
        request: Request,
        principal: PlacementViewer,
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_package_versions(
            project_id=project_id, opportunity_id=opportunity_id
        )

    @router.get(
        "/package-versions/{version_id}",
        response_model=PackageVersionView,
        operation_id="getPlacementPackageVersion",
    )
    def get_version(
        project_id: UUID, version_id: UUID, request: Request, principal: PlacementViewer
    ) -> object:
        del principal
        version = placement_services(request).get_package_version(
            project_id=project_id, version_id=version_id
        )
        if version is None:
            raise ApiProblem(
                status=404, title="Not Found", detail="Package version does not exist."
            )
        return version

    @router.post(
        "/packages/{package_id}/versions",
        response_model=PackageVersionView,
        status_code=status.HTTP_201_CREATED,
        operation_id="editPlacementPackageVersion",
    )
    def edit_version(
        project_id: UUID,
        package_id: UUID,
        payload: PackageEdit,
        request: Request,
        principal: PlacementEditor,
    ) -> object:
        return placement_services(request).edit_package_version(
            project_id=project_id,
            package_id=package_id,
            base_version_id=payload.base_version_id,
            base_content_hash=payload.base_content_hash,
            content_json=payload.content_json,
            rendered_text=payload.rendered_text,
            edited_by=principal.identity_id,
            reason=payload.reason,
        )

    @router.get(
        "/package-versions/{version_id}/claims",
        response_model=list[ClaimView],
        operation_id="listPlacementClaims",
    )
    def list_claims(
        project_id: UUID, version_id: UUID, request: Request, principal: PlacementViewer
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_claims(project_id=project_id, version_id=version_id)

    @router.post(
        "/package-versions/{version_id}/submit-review",
        response_model=ReviewSubmissionView,
        status_code=status.HTTP_201_CREATED,
        operation_id="submitPlacementPackageVersionForReview",
    )
    def submit_for_review(
        project_id: UUID, version_id: UUID, request: Request, principal: PlacementEditor
    ) -> object:
        return placement_services(request).submit_for_review(
            project_id=project_id,
            version_id=version_id,
            submitted_by=principal.identity_id,
        )

    @router.post(
        "/package-versions/{version_id}/reviews",
        response_model=ReviewView,
        status_code=status.HTTP_201_CREATED,
        operation_id="reviewPlacementPackageVersion",
    )
    def submit_review(
        project_id: UUID,
        version_id: UUID,
        payload: ReviewCreate,
        request: Request,
        principal: PlacementApprover,
    ) -> object:
        return placement_services(request).submit_review(
            project_id=project_id,
            version_id=version_id,
            reviewer_id=principal.identity_id,
            **payload.model_dump(),
        )

    @router.get(
        "/package-versions/{version_id}/reviews",
        response_model=list[ReviewView],
        operation_id="listPlacementPackageReviews",
    )
    def list_reviews(
        project_id: UUID, version_id: UUID, request: Request, principal: PlacementViewer
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_reviews(
            project_id=project_id, version_id=version_id
        )

    @router.post(
        "/package-versions/{version_id}/exports",
        response_model=ExportView,
        status_code=status.HTTP_201_CREATED,
        operation_id="exportPlacementPackageVersion",
    )
    def export_package(
        project_id: UUID, version_id: UUID, request: Request, principal: PlacementEditor
    ) -> object:
        return placement_services(request).export_package(
            project_id=project_id,
            version_id=version_id,
            requested_by=principal.identity_id,
        )

    @router.get(
        "/package-versions/{version_id}/exports",
        response_model=list[ExportView],
        operation_id="listPlacementPackageExports",
    )
    def list_exports(
        project_id: UUID, version_id: UUID, request: Request, principal: PlacementViewer
    ) -> tuple[object, ...]:
        del principal
        return placement_services(request).list_exports(
            project_id=project_id, version_id=version_id
        )

    @router.get(
        "/package-versions/{version_id}/exports/{export_id}/download",
        response_class=Response,
        operation_id="downloadPlacementPackageExport",
    )
    def download_export(
        project_id: UUID,
        version_id: UUID,
        export_id: UUID,
        request: Request,
        principal: PlacementViewer,
    ) -> Response:
        del principal
        artifact = placement_services(request).download_export(
            project_id=project_id, version_id=version_id, export_id=export_id
        )
        return Response(
            content=artifact.content,
            media_type=artifact.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="geo-export-{export_id}.json"',
                "ETag": artifact.content_hash,
            },
        )

    return router
