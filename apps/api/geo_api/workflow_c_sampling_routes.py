"""Internal-only Sampling Suite/Run/Task/Attempt/Observation routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.workflow_c_routes import (
    AuthorizationHeader,
    IdempotencyHeader,
    MANAGE_ROLES,
    READ_ROLES,
    WRITE_ROLES,
    authorize_workflow_c,
    workflow_c_api,
    workflow_c_call,
)
from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicyPageResponse,
    AdmissionPolicyResponse,
    AdmissionPolicySubmitRequest,
    AdmissionRuntimeOptionPageResponse,
    CancelSamplingAttemptRequest,
    CancelSamplingRunResponse,
    CreateAdmissionPolicyRequest,
    EnqueueSamplingAttemptRequest,
    EnqueueReadySamplingRunRequest,
    EnqueueReadySamplingRunResponse,
    ManualEvidenceImportPageResponse,
    ManualEvidenceImportResponse,
    ReviewManualEvidenceRequest,
    SamplingAttemptResponse,
    SamplingRunDetailResponse,
    SubmitManualEvidenceRequest,
    SurfaceParserReleasePageResponse,
)
from geo_api.workflow_c_sampling_presenters import (
    admission_policy_page_response,
    admission_policy_response,
    admission_runtime_option_page_response,
    attempt_response,
    bulk_enqueue_response,
    bulk_cancel_response,
    manual_evidence_page_response,
    manual_evidence_response,
    run_detail_response,
    surface_parser_release_page_response,
)
from geo_api.workflow_c_sampling_suite_routes import workflow_c_sampling_suite_router
from geo_core.sampling import SURFACE_PARSER_RELEASES


def workflow_c_sampling_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/sampling",
        tags=["workflow C sampling"],
        responses=PROBLEM_RESPONSES,
    )
    router.include_router(workflow_c_sampling_suite_router())

    @router.get(
        "/surface-parser-releases",
        response_model=SurfaceParserReleasePageResponse,
        operation_id="listConsumerSurfaceParserReleases",
    )
    def list_surface_parser_releases(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SurfaceParserReleasePageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        return surface_parser_release_page_response(SURFACE_PARSER_RELEASES)

    @router.get(
        "/admission-options",
        response_model=AdmissionRuntimeOptionPageResponse,
        operation_id="listSamplingAdmissionRuntimeOptions",
    )
    def list_admission_runtime_options(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AdmissionRuntimeOptionPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        items = workflow_c_call(
            lambda: workflow_c_api(request).sampling.policies.list_runtime_options(
                project_id=project_id
            )
        )
        return admission_runtime_option_page_response(items)

    @router.post(
        "/admission-policies",
        response_model=AdmissionPolicyResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSamplingAdmissionPolicy",
    )
    def create_admission_policy(
        project_id: UUID,
        payload: CreateAdmissionPolicyRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AdmissionPolicyResponse:
        principal = authorize_workflow_c(request, authorization, project_id, MANAGE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.create_admission_policy(
                project_id=project_id,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        return admission_policy_response(result)

    @router.get(
        "/admission-policies",
        response_model=AdmissionPolicyPageResponse,
        operation_id="listSamplingAdmissionPolicies",
    )
    def list_admission_policies(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AdmissionPolicyPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.list_admission_policies(project_id=project_id)
        )
        return admission_policy_page_response(result)

    @router.get(
        "/admission-policies/{policy_id}",
        response_model=AdmissionPolicyResponse,
        operation_id="getSamplingAdmissionPolicy",
    )
    def get_admission_policy(
        project_id: UUID,
        policy_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> AdmissionPolicyResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.get_admission_policy(
                project_id=project_id, policy_id=policy_id
            )
        )
        return admission_policy_response(result)

    def change_admission_policy(
        *,
        project_id: UUID,
        policy_id: UUID,
        request: Request,
        idempotency_key: str,
        payload: AdmissionPolicySubmitRequest | AdmissionPolicyDecisionRequest,
        operation: str,
        authorization: str | None,
    ) -> AdmissionPolicyResponse:
        principal = authorize_workflow_c(request, authorization, project_id, MANAGE_ROLES)
        runtime = workflow_c_api(request).sampling
        if operation == "submit":
            assert isinstance(payload, AdmissionPolicySubmitRequest)
            result = workflow_c_call(
                lambda: runtime.submit_admission_policy(
                    project_id=project_id,
                    policy_id=policy_id,
                    actor_id=principal.actor_id,
                    idempotency_key=idempotency_key,
                    payload=payload,
                )
            )
        elif operation == "revoke":
            assert isinstance(payload, AdmissionPolicyDecisionRequest)
            result = workflow_c_call(
                lambda: runtime.revoke_admission_policy(
                    project_id=project_id,
                    policy_id=policy_id,
                    actor_id=principal.actor_id,
                    idempotency_key=idempotency_key,
                    payload=payload,
                )
            )
        else:
            assert isinstance(payload, AdmissionPolicyDecisionRequest)
            result = workflow_c_call(
                lambda: runtime.decide_admission_policy(
                    project_id=project_id,
                    policy_id=policy_id,
                    actor_id=principal.actor_id,
                    idempotency_key=idempotency_key,
                    payload=payload,
                    approved=operation == "approve",
                )
            )
        return admission_policy_response(result)

    @router.post(
        "/admission-policies/{policy_id}/submit",
        response_model=AdmissionPolicyResponse,
        operation_id="submitSamplingAdmissionPolicy",
    )
    def submit_admission_policy_route(
        project_id: UUID,
        policy_id: UUID,
        payload: AdmissionPolicySubmitRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AdmissionPolicyResponse:
        return change_admission_policy(
            project_id=project_id,
            policy_id=policy_id,
            request=request,
            idempotency_key=idempotency_key,
            payload=payload,
            operation="submit",
            authorization=authorization,
        )

    def decision_route(
        project_id: UUID,
        policy_id: UUID,
        payload: AdmissionPolicyDecisionRequest,
        request: Request,
        idempotency_key: str,
        authorization: str | None,
        operation: str,
    ) -> AdmissionPolicyResponse:
        return change_admission_policy(
            project_id=project_id,
            policy_id=policy_id,
            request=request,
            idempotency_key=idempotency_key,
            payload=payload,
            operation=operation,
            authorization=authorization,
        )

    @router.post(
        "/admission-policies/{policy_id}/approve",
        response_model=AdmissionPolicyResponse,
        operation_id="approveSamplingAdmissionPolicy",
    )
    def approve_admission_policy(
        project_id: UUID,
        policy_id: UUID,
        payload: AdmissionPolicyDecisionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AdmissionPolicyResponse:
        return decision_route(
            project_id, policy_id, payload, request, idempotency_key, authorization, "approve"
        )

    @router.post(
        "/admission-policies/{policy_id}/assess-no-basis",
        response_model=AdmissionPolicyResponse,
        operation_id="assessSamplingAdmissionPolicyNoBasis",
    )
    def assess_admission_policy_no_basis(
        project_id: UUID,
        policy_id: UUID,
        payload: AdmissionPolicyDecisionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AdmissionPolicyResponse:
        return decision_route(
            project_id,
            policy_id,
            payload,
            request,
            idempotency_key,
            authorization,
            "assess-no-basis",
        )

    @router.post(
        "/admission-policies/{policy_id}/revoke",
        response_model=AdmissionPolicyResponse,
        operation_id="revokeSamplingAdmissionPolicy",
    )
    def revoke_admission_policy_route(
        project_id: UUID,
        policy_id: UUID,
        payload: AdmissionPolicyDecisionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AdmissionPolicyResponse:
        return decision_route(
            project_id, policy_id, payload, request, idempotency_key, authorization, "revoke"
        )

    @router.get(
        "/runs/{run_id}",
        response_model=SamplingRunDetailResponse,
        operation_id="getSamplingRun",
    )
    def get_run(
        project_id: UUID,
        run_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SamplingRunDetailResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        return _run_detail(request, project_id, run_id)

    @router.post(
        "/runs/{run_id}/cancel",
        response_model=CancelSamplingRunResponse,
        operation_id="cancelSamplingRun",
    )
    def cancel_run(
        project_id: UUID,
        run_id: UUID,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> CancelSamplingRunResponse:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.cancel_run(
                project_id=project_id,
                run_id=run_id,
                idempotency_key=idempotency_key,
            )
        )
        return bulk_cancel_response(result)

    @router.post(
        "/runs/{run_id}/tasks/{task_id}/manual-evidence",
        response_model=ManualEvidenceImportResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="submitManualSamplingEvidence",
    )
    def submit_manual_evidence(
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        payload: SubmitManualEvidenceRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ManualEvidenceImportResponse:
        principal = authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.submit_manual_evidence(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        return manual_evidence_response(result)

    @router.get(
        "/manual-evidence-imports",
        response_model=ManualEvidenceImportPageResponse,
        operation_id="listManualSamplingEvidence",
    )
    def list_manual_evidence(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ManualEvidenceImportPageResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.list_manual_evidence(project_id=project_id)
        )
        return manual_evidence_page_response(result)

    @router.get(
        "/manual-evidence-imports/{import_id}",
        response_model=ManualEvidenceImportResponse,
        operation_id="getManualSamplingEvidence",
    )
    def get_manual_evidence(
        project_id: UUID,
        import_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> ManualEvidenceImportResponse:
        authorize_workflow_c(request, authorization, project_id, READ_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.get_manual_evidence(
                project_id=project_id, import_id=import_id
            )
        )
        return manual_evidence_response(result)

    def review_manual_evidence(
        *,
        project_id: UUID,
        import_id: UUID,
        payload: ReviewManualEvidenceRequest,
        request: Request,
        idempotency_key: str,
        authorization: str | None,
        approved: bool,
    ) -> ManualEvidenceImportResponse:
        principal = authorize_workflow_c(request, authorization, project_id, MANAGE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.review_manual_evidence(
                project_id=project_id,
                import_id=import_id,
                actor_id=principal.actor_id,
                idempotency_key=idempotency_key,
                payload=payload,
                approved=approved,
            )
        )
        return manual_evidence_response(result)

    @router.post(
        "/manual-evidence-imports/{import_id}/approve",
        response_model=ManualEvidenceImportResponse,
        operation_id="approveManualSamplingEvidence",
    )
    def approve_manual_evidence(
        project_id: UUID,
        import_id: UUID,
        payload: ReviewManualEvidenceRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ManualEvidenceImportResponse:
        return review_manual_evidence(
            project_id=project_id,
            import_id=import_id,
            payload=payload,
            request=request,
            idempotency_key=idempotency_key,
            authorization=authorization,
            approved=True,
        )

    @router.post(
        "/manual-evidence-imports/{import_id}/reject",
        response_model=ManualEvidenceImportResponse,
        operation_id="rejectManualSamplingEvidence",
    )
    def reject_manual_evidence(
        project_id: UUID,
        import_id: UUID,
        payload: ReviewManualEvidenceRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ManualEvidenceImportResponse:
        return review_manual_evidence(
            project_id=project_id,
            import_id=import_id,
            payload=payload,
            request=request,
            idempotency_key=idempotency_key,
            authorization=authorization,
            approved=False,
        )

    @router.post(
        "/runs/{run_id}/enqueue-ready",
        response_model=EnqueueReadySamplingRunResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="enqueueReadySamplingRun",
    )
    def enqueue_ready_attempts(
        project_id: UUID,
        run_id: UUID,
        payload: EnqueueReadySamplingRunRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> EnqueueReadySamplingRunResponse:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.enqueue_ready_attempts(
                project_id=project_id,
                run_id=run_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        return bulk_enqueue_response(result)

    @router.post(
        "/runs/{run_id}/tasks/{task_id}/attempts",
        response_model=SamplingAttemptResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="enqueueSamplingAttempt",
    )
    def enqueue_attempt(
        project_id: UUID,
        run_id: UUID,
        task_id: UUID,
        payload: EnqueueSamplingAttemptRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> SamplingAttemptResponse:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.enqueue_attempt(
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
        )
        return attempt_response(result.attempt)

    @router.post(
        "/attempts/{attempt_id}/cancel",
        response_model=SamplingAttemptResponse,
        operation_id="cancelSamplingAttempt",
    )
    def cancel_attempt(
        project_id: UUID,
        attempt_id: UUID,
        payload: CancelSamplingAttemptRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SamplingAttemptResponse:
        authorize_workflow_c(request, authorization, project_id, WRITE_ROLES)
        result = workflow_c_call(
            lambda: workflow_c_api(request).sampling.cancel_attempt(
                project_id=project_id, attempt_id=attempt_id, payload=payload
            )
        )
        return attempt_response(result.attempt)

    return router


def _run_detail(request: Request, project_id: UUID, run_id: UUID) -> SamplingRunDetailResponse:
    view = workflow_c_call(
        lambda: workflow_c_api(request).sampling.get_run_view(project_id=project_id, run_id=run_id)
    )
    return run_detail_response(
        suite=view.suite,
        run=view.run,
        tasks=view.tasks,
        attempts=view.attempts,
        observations=view.observations,
        assessment=view.assessment,
    )
