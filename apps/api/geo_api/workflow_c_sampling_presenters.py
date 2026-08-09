"""Sampling Core domain-to-transport projections."""

from __future__ import annotations

from typing import cast

from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyPageResponse,
    AdmissionPolicyResponse,
    AdmissionRuntimeOptionPageResponse,
    AdmissionRuntimeOptionResponse,
    CancelSamplingRunResponse,
    EnqueueReadySamplingRunResponse,
    ManualEvidenceImportPageResponse,
    ManualEvidenceImportResponse,
    ObservationEvidenceSummaryResponse,
    SamplingAssessmentResponse,
    SamplingAttemptResponse,
    SamplingActualLocationResponse,
    SamplingObservationResponse,
    SamplingQuestionContract,
    SamplingRunDetailResponse,
    SamplingRunResponse,
    SamplingRunPageResponse,
    SamplingCaptureMethod,
    SamplingSourceStratumContract,
    SamplingSuiteResponse,
    SamplingSuitePageResponse,
    SamplingSuiteInputOptionPageResponse,
    SamplingSuiteInputOptionResponse,
    SamplingTaskResponse,
    SurfaceParseSummaryResponse,
    SurfaceParserReleasePageResponse,
    SurfaceParserReleaseResponse,
)
from geo_api.workflow_c_sampling_catalog import ResolvedSamplingSuiteInputs
from geo_api.workflow_c_sampling_runtime import (
    BulkSamplingEnqueueView,
    BulkSamplingCancelView,
    SamplingAdmissionPolicyView,
)
from geo_api.workflow_c_sampling_policy_runtime import SamplingAdmissionRuntimeOption
from geo_core.sampling import (
    SamplingAttempt,
    SamplingActualLocationLineage,
    ManualEvidenceImport,
    SamplingObservation,
    SamplingRun,
    SamplingRunAssessment,
    SamplingSuite,
    SamplingTask,
    SurfaceParseSummary,
    SurfaceParserRelease,
)


def admission_policy_response(
    view: SamplingAdmissionPolicyView,
) -> AdmissionPolicyResponse:
    item = view.record
    return AdmissionPolicyResponse(
        id=item.id,
        project_id=item.project_id,
        revision=item.revision,
        supersedes_policy_id=item.supersedes_policy_id,
        platform=item.platform,
        capture_method=cast(SamplingCaptureMethod, item.capture_method.value),
        adapter_release=item.adapter_release,
        location_control=item.location_control.value,
        location_evidence_hash=item.location_evidence_hash,
        authorization_reference=item.authorization_reference,
        authorized_purposes=list(item.authorized_purposes),
        valid_until=item.valid_until,
        quota_remaining=item.quota_remaining,
        daily_task_limit=item.daily_task_limit,
        minimum_request_interval_seconds=item.minimum_request_interval_seconds,
        max_concurrency=item.max_concurrency,
        next_allowed_at=item.next_allowed_at,
        status=item.status.value,
        effective_authorization_state=view.effective_authorization_state.value,
        definition_hash=item.definition_hash,
        policy_version=item.policy_version,
        created_by=item.created_by,
        created_at=item.created_at,
        submitted_by=item.submitted_by,
        submitted_at=item.submitted_at,
        decided_by=item.decided_by,
        decided_at=item.decided_at,
        decision_reason=item.decision_reason,
        revoked_by=item.revoked_by,
        revoked_at=item.revoked_at,
        revocation_reason=item.revocation_reason,
        aggregate_version=item.aggregate_version,
    )


def admission_policy_page_response(
    views: tuple[SamplingAdmissionPolicyView, ...],
) -> AdmissionPolicyPageResponse:
    return AdmissionPolicyPageResponse(
        items=[admission_policy_response(item) for item in views],
        total=len(views),
    )


def admission_runtime_option_page_response(
    items: tuple[SamplingAdmissionRuntimeOption, ...],
) -> AdmissionRuntimeOptionPageResponse:
    return AdmissionRuntimeOptionPageResponse(
        items=[
            AdmissionRuntimeOptionResponse(
                option_key=item.option_key,
                display_name=item.display_name,
                platform=item.platform,
                capture_method=cast(SamplingCaptureMethod, item.capture_method.value),
                adapter_release=item.adapter_release,
                location_control=item.location_control.value,
                location_evidence_hash=item.location_evidence_hash,
                authorization_reference=item.authorization_reference,
                allowed_purposes=list(item.allowed_purposes),
            )
            for item in items
        ],
        total=len(items),
    )


def bulk_enqueue_response(
    view: BulkSamplingEnqueueView,
) -> EnqueueReadySamplingRunResponse:
    return EnqueueReadySamplingRunResponse(
        run_id=view.run_id,
        planned_task_count=view.planned_task_count,
        enqueued_count=view.enqueued_count,
        replayed_count=view.replayed_count,
        skipped_count=view.skipped_count,
        attempt_ids=list(view.attempt_ids),
        first_not_before=view.first_not_before,
        last_not_before=view.last_not_before,
        replayed=view.replayed,
    )


def bulk_cancel_response(view: BulkSamplingCancelView) -> CancelSamplingRunResponse:
    return CancelSamplingRunResponse(
        run_id=view.run_id,
        cancel_requested_count=view.cancel_requested_count,
        replayed_count=view.replayed_count,
        skipped_count=view.skipped_count,
        attempt_ids=list(view.attempt_ids),
        replayed=view.replayed,
    )


def manual_evidence_response(
    item: ManualEvidenceImport,
) -> ManualEvidenceImportResponse:
    return ManualEvidenceImportResponse(
        id=item.id,
        project_id=item.project_id,
        run_id=item.run_id,
        task_id=item.task_id,
        task_key=item.task_key,
        attempt_id=item.attempt_id,
        expected_task_version=item.expected_task_version,
        artifact_manifest_id=item.artifact_manifest_id,
        artifact_manifest_hash=item.artifact_manifest_hash,
        artifact_content_hash=item.artifact_content_hash,
        governance_policy_hash=item.governance_policy_hash,
        capture_session_id=item.capture_session_id,
        evidence_kind=item.evidence_kind.value,
        device=item.device.value,
        locale=item.locale,
        captured_at=item.captured_at,
        submitted_by=item.submitted_by,
        submitted_at=item.submitted_at,
        status=item.status.value,
        reviewed_by=item.reviewed_by,
        reviewed_at=item.reviewed_at,
        review_reason=item.review_reason,
        committed_at=item.committed_at,
        aggregate_version=item.aggregate_version,
        definition_hash=item.definition_hash,
        surface_parse=(
            surface_parse_summary_response(item.surface_parse)
            if item.surface_parse is not None
            else None
        ),
    )


def manual_evidence_page_response(
    items: tuple[ManualEvidenceImport, ...],
) -> ManualEvidenceImportPageResponse:
    return ManualEvidenceImportPageResponse(
        items=[manual_evidence_response(item) for item in items],
        total=len(items),
    )


def surface_parser_release_page_response(
    items: tuple[SurfaceParserRelease, ...],
) -> SurfaceParserReleasePageResponse:
    return SurfaceParserReleasePageResponse(
        items=[
            SurfaceParserReleaseResponse(
                id=item.id,
                release_key=item.release_key,
                release_version=item.release_version,
                release_hash=item.release_hash,
                platform=item.platform,
                surface=item.surface.value,
                artifact_schema_version=item.artifact_schema_version,
                parser_engine_version=item.parser_engine_version,
                status=item.status.value,
                automated_capture_eligible=False,
                evidence_scope="fixture_or_manual_non_live",
            )
            for item in items
        ],
        total=len(items),
    )


def surface_parse_summary_response(
    item: SurfaceParseSummary,
) -> SurfaceParseSummaryResponse:
    return SurfaceParseSummaryResponse(
        parser_release_id=item.parser_release_id,
        parser_release_hash=item.parser_release_hash,
        platform=item.platform,
        surface=item.surface.value,
        capture_kind="manual_ui",
        outcome=item.outcome.value,
        block_reason=item.block_reason.value if item.block_reason is not None else None,
        content_eligible=item.content_eligible,
        automated_capture=False,
        live_capture_eligible=False,
        answer_text_hash=item.answer_text_hash,
        answer_character_count=item.answer_character_count,
        citation_count=item.citation_count,
        citation_set_hash=item.citation_set_hash,
        locator_set_hash=item.locator_set_hash,
        parser_result_hash=item.parser_result_hash,
        summary_hash=item.summary_hash,
    )


def suite_response(item: SamplingSuite) -> SamplingSuiteResponse:
    source = item.source_stratum
    return SamplingSuiteResponse(
        id=item.id,
        project_id=item.project_id,
        question_set_id=item.question_set_id,
        question_set_version=item.question_set_version,
        question_set_hash=item.question_set_hash,
        adapter_release_id=item.adapter_release_id,
        adapter_release_hash=item.adapter_release_hash,
        model_release_id=item.model_release_id,
        model_release_hash=item.model_release_hash,
        route_policy_id=item.route_policy_id,
        route_policy_hash=item.route_policy_hash,
        runtime_manifest_id=item.runtime_manifest_id,
        runtime_manifest_hash=item.runtime_manifest_hash,
        runtime_option_id=item.runtime_option_id,
        runtime_option_hash=item.runtime_option_hash,
        admission_policy_id=item.admission_policy_id,
        admission_policy_hash=item.admission_policy_hash,
        questions=[
            SamplingQuestionContract(
                question_id=question.question_id,
                question_version=question.question_version,
                text_hash=question.text_hash,
            )
            for question in item.questions
        ],
        question_set_item_ids=[question.question_id for question in item.questions],
        source_stratum=SamplingSourceStratumContract.model_validate(
            {**source.canonical_value(), "stratum_hash": source.stratum_hash}
        ),
        repetitions=item.repetitions,
        statistics_method_version=item.statistics_method_version,
        max_planned_tasks=item.max_planned_tasks,
        max_daily_tasks=item.max_daily_tasks,
        minimum_request_interval_seconds=item.minimum_request_interval_seconds,
        max_concurrency=item.max_concurrency,
        minimum_valid_repeats=item.minimum_valid_repeats,
        planned_task_count=item.planned_task_count,
        frozen_by=item.frozen_by,
        frozen_at=item.frozen_at,
        suite_hash=item.suite_hash,
    )


def suite_page_response(items: tuple[SamplingSuite, ...]) -> SamplingSuitePageResponse:
    return SamplingSuitePageResponse(
        items=[suite_response(item) for item in items],
        total=len(items),
    )


def suite_input_option_page_response(
    items: tuple[ResolvedSamplingSuiteInputs, ...],
) -> SamplingSuiteInputOptionPageResponse:
    return SamplingSuiteInputOptionPageResponse(
        items=[
            SamplingSuiteInputOptionResponse(
                option_key=item.option_key,
                display_name=item.display_name,
                question_set_id=item.question_set_id,
                question_set_version=item.question_set_version,
                question_set_hash=item.question_set_hash,
                question_count=len(item.questions),
                question_set_item_ids=[question.question_id for question in item.questions],
                adapter_release_id=item.adapter_release_id,
                adapter_release_hash=item.adapter_release_hash,
                model_release_id=item.model_release_id,
                model_release_hash=item.model_release_hash,
                route_policy_id=item.route_policy_id,
                route_policy_hash=item.route_policy_hash,
                runtime_manifest_id=item.runtime_manifest_id,
                runtime_manifest_hash=item.runtime_manifest_hash,
                runtime_option_id=item.runtime_option_id,
                runtime_option_hash=item.runtime_option_hash,
                admission_policy_id=item.admission_policy_id,
                admission_policy_hash=item.admission_policy_hash,
                source_stratum=SamplingSourceStratumContract.model_validate(
                    {
                        **item.source_stratum.canonical_value(),
                        "stratum_hash": item.source_stratum.stratum_hash,
                    }
                ),
            )
            for item in items
        ],
        total=len(items),
    )


def run_response(item: SamplingRun) -> SamplingRunResponse:
    return SamplingRunResponse(
        id=item.id,
        project_id=item.project_id,
        suite_id=item.suite_id,
        suite_hash=item.suite_hash,
        admission_policy_id=item.admission_policy_id,
        admission_policy_hash=item.admission_policy_hash,
        admission_grant_hash=item.admission_grant_hash,
        purpose=item.purpose,
        authorization_reference=item.authorization_reference,
        authorization_valid_until=item.authorization_valid_until,
        admission_policy_version=item.admission_policy_version,
        reserved_task_count=item.reserved_task_count,
        planned_task_keys=list(item.planned_task_keys),
        status=item.status.value,
        admitted_not_before=item.admitted_not_before,
        created_at=item.created_at,
        version=item.version,
    )


def run_page_response(items: tuple[SamplingRun, ...]) -> SamplingRunPageResponse:
    return SamplingRunPageResponse(
        items=[run_response(item) for item in items],
        total=len(items),
    )


def task_response(item: SamplingTask) -> SamplingTaskResponse:
    identity = item.identity
    return SamplingTaskResponse(
        id=item.id,
        project_id=item.project_id,
        run_id=item.run_id,
        task_key=identity.task_key,
        question_id=identity.question_id,
        question_version=identity.question_version,
        repetition=identity.repetition,
        capture_method=cast(SamplingCaptureMethod, identity.capture_method.value),
        source_stratum_hash=identity.source_stratum_hash,
        status=item.status.value,
        attempt_ids=list(item.attempt_ids),
        max_attempts=item.max_attempts,
        version=item.version,
    )


def attempt_response(item: SamplingAttempt) -> SamplingAttemptResponse:
    job = item.job
    return SamplingAttemptResponse(
        id=item.id,
        project_id=item.project_id,
        run_id=item.run_id,
        task_id=item.task_id,
        task_key=item.task_key,
        ordinal=item.ordinal,
        job_status=job.status.value,
        record_version=item.record_version,
        attempt_count=job.attempt_count,
        provider_response_id=item.provider_response_id,
        egress_verification_id=item.egress_verification_id,
        raw_artifact_hash=item.raw_artifact_hash,
        actual_location=_actual_location_response(item.actual_location),
        terminal_status=(item.terminal_status.value if item.terminal_status else None),
    )


def observation_response(item: SamplingObservation) -> SamplingObservationResponse:
    evidence = item.evidence
    return SamplingObservationResponse(
        id=item.id,
        project_id=item.project_id,
        run_id=item.run_id,
        task_id=item.task_id,
        task_key=item.task_key,
        winning_attempt_id=item.winning_attempt_id,
        source_stratum_hash=item.source_stratum_hash,
        actual_location=_actual_location_response(item.actual_location),
        evidence_status=item.evidence_status.value,
        ineligible_reasons=list(item.ineligible_reasons),
        evidence=ObservationEvidenceSummaryResponse(
            raw_manifest_hash=evidence.raw_artifact.manifest_hash,
            derived_manifest_hash=evidence.derived_artifact.manifest_hash,
            derived_content_hash=evidence.derived_artifact.content_hash,
            governance_policy_hash=evidence.derived_artifact.governance_policy_hash,
            derived_summary=evidence.derived_summary,
            evidence_locator=evidence.evidence_locator,
            provider_response_id=evidence.provider_response_id,
            egress_verification_id=evidence.egress_verification_id,
            result_parameters_hash=evidence.result_parameters_hash,
        ),
        observed_at=item.observed_at,
        observation_hash=item.observation_hash,
    )


def _actual_location_response(
    item: SamplingActualLocationLineage | None,
) -> SamplingActualLocationResponse | None:
    if item is None:
        return None
    return SamplingActualLocationResponse.model_validate(item.canonical_value())


def assessment_response(item: SamplingRunAssessment) -> SamplingAssessmentResponse:
    return SamplingAssessmentResponse(
        run_id=item.run_id,
        planned_task_count=item.planned_task_count,
        valid_task_count=item.valid_task_count,
        invalid_task_count=item.invalid_task_count,
        missing_task_count=item.missing_task_count,
        valid_completion_ratio=str(item.valid_completion_ratio),
        sufficient_question_count=item.sufficient_question_count,
        question_count=item.question_count,
        status=item.status.value,
        denominator_hash=item.denominator_hash,
    )


def run_detail_response(
    *,
    suite: SamplingSuite,
    run: SamplingRun,
    tasks: tuple[SamplingTask, ...],
    attempts: tuple[SamplingAttempt, ...],
    observations: tuple[SamplingObservation, ...],
    assessment: SamplingRunAssessment,
) -> SamplingRunDetailResponse:
    return SamplingRunDetailResponse(
        suite=suite_response(suite),
        run=run_response(run),
        tasks=[task_response(item) for item in tasks],
        attempts=[attempt_response(item) for item in attempts],
        observations=[observation_response(item) for item in observations],
        assessment=assessment_response(assessment),
    )
