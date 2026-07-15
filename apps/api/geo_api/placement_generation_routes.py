"""Evidence, prompt, generation and immutable package routes."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Request, status

from geo_api.contracts import JobAccepted
from geo_api.placement_contracts import (
    AsyncResourceCreated,
    ClaimView,
    EvidenceAttemptView,
    ExportView,
    GenerationCreate,
    PackageEdit,
    PackageVersionView,
    PromptBundleCreate,
    PromptBundleView,
    PromptReleaseCreate,
    PromptReleaseView,
    PromptSkillCreate,
    PromptSkillView,
    ReviewCreate,
    ReviewView,
)
from geo_api.placement_routes_shared import IdempotencyHeader, placement_services
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.placements.domain import Review


def generation_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/geo",
        tags=["GEO evidence-led generation"], responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/brief-versions/{brief_version_id}/evidence-pack-attempts",
        response_model=AsyncResourceCreated, status_code=status.HTTP_202_ACCEPTED,
        operation_id="buildPlacementEvidencePack",
    )
    def create_evidence_attempt(
        project_id: UUID, brief_version_id: UUID, request: Request,
        idempotency_key: IdempotencyHeader,
    ) -> AsyncResourceCreated:
        attempt, job = placement_services(request).create_evidence_attempt(
            project_id=project_id, brief_version_id=brief_version_id,
            idempotency_key=idempotency_key,
        )
        return AsyncResourceCreated(
            resource=attempt, job_id=job.id, status=job.status,
            status_url=f"/v1/jobs/{job.id}",
        )

    @router.get(
        "/brief-versions/{brief_version_id}/evidence-pack-attempts",
        response_model=list[EvidenceAttemptView], operation_id="listPlacementEvidencePackAttempts",
    )
    def list_evidence_attempts(
        project_id: UUID, brief_version_id: UUID, request: Request
    ) -> tuple[object, ...]:
        return placement_services(request).list_evidence_attempts(
            project_id=project_id, brief_version_id=brief_version_id
        )

    @router.post(
        "/prompt-skills", response_model=PromptSkillView,
        status_code=status.HTTP_201_CREATED, operation_id="createPlacementPromptSkill",
    )
    def create_skill(project_id: UUID, payload: PromptSkillCreate, request: Request) -> object:
        return placement_services(request).create_prompt_skill(
            project_id=project_id, skill_key=payload.skill_key
        )

    @router.post(
        "/prompt-skills/{skill_id}/releases", response_model=PromptReleaseView,
        status_code=status.HTTP_201_CREATED, operation_id="publishPlacementPromptRelease",
    )
    def publish_release(
        project_id: UUID, skill_id: UUID, payload: PromptReleaseCreate, request: Request
    ) -> object:
        return placement_services(request).publish_skill_version(
            project_id=project_id, skill_id=skill_id, source=payload.source,
            actor_id=payload.actor_id, output_schema=payload.output_schema,
        )

    @router.post(
        "/brief-versions/{brief_version_id}/prompt-bundles",
        response_model=PromptBundleView, status_code=status.HTTP_201_CREATED,
        operation_id="createPlacementPromptBundle",
    )
    def create_bundle(
        project_id: UUID, brief_version_id: UUID, payload: PromptBundleCreate, request: Request
    ) -> object:
        return placement_services(request).create_prompt_bundle(
            project_id=project_id, brief_version_id=brief_version_id,
            evidence_pack_attempt_id=payload.evidence_pack_attempt_id,
            release_id=payload.template_release_id, variables=payload.variables,
            model_policy_hash=payload.model_policy_hash,
        )

    @router.post(
        "/prompt-bundles/{prompt_bundle_id}/generation-jobs",
        response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED,
        operation_id="requestPlacementGeneration",
    )
    def request_generation(
        project_id: UUID, prompt_bundle_id: UUID, payload: GenerationCreate,
        request: Request, idempotency_key: IdempotencyHeader,
    ) -> JobAccepted:
        job = placement_services(request).request_generation(
            project_id=project_id, prompt_bundle_id=prompt_bundle_id,
            configured_model=payload.configured_model,
            model_call_budget=payload.model_call_budget,
            idempotency_key=idempotency_key,
        )
        return JobAccepted(job_id=job.id, status=job.status, status_url=f"/v1/jobs/{job.id}")

    @router.get(
        "/opportunities/{opportunity_id}/package-versions",
        response_model=list[PackageVersionView], operation_id="listPlacementPackageVersions",
    )
    def list_versions(
        project_id: UUID, opportunity_id: UUID, request: Request
    ) -> tuple[object, ...]:
        return placement_services(request).list_package_versions(
            project_id=project_id, opportunity_id=opportunity_id
        )

    @router.post(
        "/packages/{package_id}/versions", response_model=PackageVersionView,
        status_code=status.HTTP_201_CREATED, operation_id="editPlacementPackageVersion",
    )
    def edit_version(
        project_id: UUID, package_id: UUID, payload: PackageEdit, request: Request
    ) -> object:
        return placement_services(request).edit_package_version(
            project_id=project_id, package_id=package_id,
            base_version_id=payload.base_version_id,
            base_content_hash=payload.base_content_hash, content_json=payload.content_json,
            rendered_text=payload.rendered_text, edited_by=payload.edited_by,
            reason=payload.reason,
        )

    @router.get(
        "/package-versions/{version_id}/claims", response_model=list[ClaimView],
        operation_id="listPlacementClaims",
    )
    def list_claims(project_id: UUID, version_id: UUID, request: Request) -> tuple[object, ...]:
        return placement_services(request).list_claims(project_id=project_id, version_id=version_id)

    @router.post(
        "/package-versions/{version_id}/reviews", response_model=ReviewView,
        status_code=status.HTTP_201_CREATED, operation_id="reviewPlacementPackageVersion",
    )
    def submit_review(
        project_id: UUID, version_id: UUID, payload: ReviewCreate, request: Request
    ) -> object:
        return placement_services(request).submit_review(
            review=Review(
                id=uuid4(), project_id=project_id, package_version_id=version_id,
                **payload.model_dump(),
            )
        )

    @router.post(
        "/package-versions/{version_id}/exports", response_model=ExportView,
        status_code=status.HTTP_201_CREATED, operation_id="exportPlacementPackageVersion",
    )
    def export_package(project_id: UUID, version_id: UUID, request: Request) -> object:
        return placement_services(request).export_package(project_id=project_id, version_id=version_id)

    return router
