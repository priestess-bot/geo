"""Deterministic Sampling Core test object factories."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID, uuid4, uuid5

from geo_core.sampling import (
    AuthorizationState,
    CaptureMethod,
    EvidenceStatus,
    LocationControl,
    ObservationArtifactKind,
    ObservationArtifactManifest,
    ObservationEvidence,
    SamplingAdmissionCommand,
    SamplingAdmissionPolicy,
    SamplingObservation,
    SamplingQuestion,
    SamplingSourceStratum,
    SamplingSuite,
    SamplingTask,
    admit_sampling_suite,
    materialize_sampling_run,
)
from geo_core.sampling.execution import observation_id


NOW = datetime(2026, 7, 23, 4, 0, tzinfo=UTC)
ATTEMPT_NAMESPACE = UUID("f70805af-a15d-50cb-a917-e8a545496404")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_source(
    capture_method: CaptureMethod = CaptureMethod.PROVIDER_API,
    *,
    adapter_release: str = "openai-web-search@2026-07-23",
) -> SamplingSourceStratum:
    is_api = capture_method in {
        CaptureMethod.PROVIDER_API,
        CaptureMethod.PROXY_GROUNDED_API,
    }
    return SamplingSourceStratum(
        platform="openai" if is_api else "consumer-ui-manual",
        surface="web_search" if is_api else "manual-search-result",
        configured_model="gpt-5-mini",
        reported_model="gpt-5-mini-2026-07-01",
        capture_method=capture_method,
        adapter_release=adapter_release,
        locale="en-AU",
        region="AU",
        language="en",
        search_mode="enabled",
        account_cohort="not_applicable" if is_api else "au-clean-account-v1",
        egress_policy_category=("not_applicable" if is_api else "operator_verified_manual_au"),
        location_control=LocationControl.COUNTRY,
        location_evidence_hash=digest("location-evidence:au-country"),
        requested_country="AU",
        requested_region=None,
        requested_locale="en-AU",
        requested_language="en",
        effective_country="AU",
        effective_region=None,
        effective_locale=None,
        effective_language=None,
    )


def make_suite(
    capture_method: CaptureMethod = CaptureMethod.PROVIDER_API,
    *,
    repetitions: int | None = None,
    question_count: int = 1,
    project_id: UUID | None = None,
    suite_id: UUID | None = None,
) -> SamplingSuite:
    repeats = repetitions
    if repeats is None:
        repeats = 10 if capture_method is not CaptureMethod.MANUAL_UI else 3
    source = make_source(capture_method)
    questions = tuple(
        SamplingQuestion(f"q-{index}", "v1", digest(f"question-{index}"))
        for index in range(1, question_count + 1)
    )
    planned_count = len(questions) * repeats
    return SamplingSuite(
        id=suite_id or uuid4(),
        project_id=project_id or uuid4(),
        question_set_id=uuid4(),
        question_set_version="question-set-v1",
        question_set_hash=digest("question-set"),
        adapter_release_id=UUID("54000000-0000-4000-8000-000000000001"),
        adapter_release_hash=digest("adapter-release"),
        model_release_id=UUID("54000000-0000-4000-8000-000000000002"),
        model_release_hash=digest("model-release"),
        route_policy_id=UUID("54000000-0000-4000-8000-000000000003"),
        route_policy_hash=digest("route-policy"),
        runtime_manifest_id=UUID("54000000-0000-4000-8000-000000000004"),
        runtime_manifest_hash=digest("runtime-manifest"),
        runtime_option_id=UUID("54000000-0000-4000-8000-000000000005"),
        runtime_option_hash=digest("runtime-option"),
        admission_policy_id=UUID("53000000-0000-4000-8000-000000000001"),
        admission_policy_hash=digest("admission-policy-definition"),
        questions=questions,
        source_stratum=source,
        repetitions=repeats,
        statistics_method_version="sampling-statistics-v1",
        max_planned_tasks=planned_count,
        max_daily_tasks=planned_count,
        minimum_request_interval_seconds=2,
        max_concurrency=2,
        frozen_by="sampling-test",
        frozen_at=NOW,
    )


def make_policy(suite: SamplingSuite) -> SamplingAdmissionPolicy:
    return SamplingAdmissionPolicy(
        id=UUID("53000000-0000-4000-8000-000000000001"),
        project_id=suite.project_id,
        platform=suite.source_stratum.platform,
        capture_method=suite.source_stratum.capture_method,
        adapter_release=suite.source_stratum.adapter_release,
        location_control=suite.source_stratum.location_control,
        location_evidence_hash=suite.source_stratum.location_evidence_hash,
        authorization_state=AuthorizationState.APPROVED,
        authorization_reference="authorization:terms-review:42",
        authorized_purposes=("geo_measurement",),
        valid_until=NOW + timedelta(days=30),
        quota_remaining=suite.planned_task_count,
        daily_task_limit=suite.max_daily_tasks,
        minimum_request_interval_seconds=suite.minimum_request_interval_seconds,
        max_concurrency=suite.max_concurrency,
        next_allowed_at=NOW + timedelta(minutes=1),
        policy_version="sampling-admission-v1",
    )


def make_run(suite: SamplingSuite):
    policy = make_policy(suite)
    command = SamplingAdmissionCommand(
        idempotency_key=f"admit:{suite.id}",
        purpose="geo_measurement",
        requested_at=NOW,
        requested_not_before=NOW,
    )
    grant = admit_sampling_suite(suite, policy=policy, command=command)
    run, tasks = materialize_sampling_run(suite, grant=grant, run_id=uuid4(), created_at=NOW)
    return grant, run, tasks


def make_evidence(
    task: SamplingTask,
    *,
    provider_response_id: str | None = None,
    egress_verification_id: str | None = None,
) -> ObservationEvidence:
    raw_hash = digest(f"raw:{task.identity.task_key}")
    derived_hash = digest(f"derived:{task.identity.task_key}")
    return ObservationEvidence(
        raw_artifact=ObservationArtifactManifest(
            kind=ObservationArtifactKind.RAW,
            manifest_reference=f"artifact-manifest://raw/{task.identity.task_key}",
            manifest_hash=digest(f"raw-manifest:{task.identity.task_key}"),
            content_hash=raw_hash,
            governance_policy_hash=digest("sampling-artifact-policy-v1"),
        ),
        derived_artifact=ObservationArtifactManifest(
            kind=ObservationArtifactKind.DERIVED,
            manifest_reference=f"artifact-manifest://derived/{task.identity.task_key}",
            manifest_hash=digest(f"derived-manifest:{task.identity.task_key}"),
            content_hash=derived_hash,
            governance_policy_hash=digest("sampling-artifact-policy-v1"),
        ),
        derived_summary="Anonymous governed answer evidence.",
        evidence_locator="json-pointer:/answer",
        provider_response_id=provider_response_id,
        egress_verification_id=egress_verification_id,
        result_parameters_hash=digest(f"parameters:{task.identity.task_key}"),
        storage_decision="allowed",
        cache_decision="allowed",
        display_decision="allowed",
        redistribution_decision="prohibited",
        usage_purpose="geo_measurement",
        usage_audience="internal_worker",
    )


def make_observation(
    suite: SamplingSuite,
    task: SamplingTask,
    *,
    eligible: bool = True,
    source: SamplingSourceStratum | None = None,
) -> SamplingObservation:
    evidence = make_evidence(task)
    attempt_id = uuid5(ATTEMPT_NAMESPACE, task.identity.task_key)
    selected_source = source or suite.source_stratum
    return SamplingObservation(
        id=observation_id(task.identity, attempt_id=attempt_id, evidence=evidence),
        project_id=task.project_id,
        run_id=task.run_id,
        task_id=task.id,
        task_key=task.identity.task_key,
        winning_attempt_id=attempt_id,
        source_stratum=selected_source,
        source_stratum_hash=selected_source.stratum_hash,
        evidence_status=EvidenceStatus.COMPLETE if eligible else EvidenceStatus.INELIGIBLE,
        ineligible_reasons=() if eligible else ("provider_response_invalid",),
        evidence=evidence,
        observed_at=NOW,
    )
