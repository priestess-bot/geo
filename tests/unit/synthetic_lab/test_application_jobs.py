from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.lifecycle import JobStatus
from geo_core.synthetic_lab.application_support import JobWriteOwnership
from geo_core.synthetic_lab.domain import (
    StyleProfileStatus,
    StyleProfileVersion,
    StyleSample,
    StyleSampleReviewStatus,
    style_sample_manifest_hash,
)
from geo_core.synthetic_lab.memory import (
    InMemorySyntheticLabStore,
    InMemorySyntheticLabUnitOfWorkFactory,
)
from geo_core.synthetic_lab.ports import (
    JobTerminalResult,
    LabPrincipal,
    LabRole,
    RuntimeInputSnapshot,
    StaticRuntimeInputPort,
    SyntheticLabJobOwnershipLost,
    SyntheticLabPermissionDenied,
    SyntheticLabPersistenceError,
    SyntheticLabStaleInput,
    SyntheticLabVersionConflict,
    SyntheticJob,
    VersionedAggregate,
)
from geo_core.synthetic_lab.review_application import (
    REVIEW_SUITE_KIND,
    STYLE_PROFILE_KIND,
    JobEnqueueRequest,
    ReviewApplication,
)
from geo_core.synthetic_lab.review_cases import (
    ReviewCase,
    ReviewSuite,
    ReviewSuiteStatus,
    ScenarioMode,
    review_case_content_hash,
    review_case_set_hash,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _principal(project_id: UUID, role: LabRole, *, actor_id: UUID | None = None):
    return LabPrincipal(
        project_id=project_id,
        actor_id=actor_id or uuid4(),
        roles=frozenset({role}),
    )


def _runtime(project_id: UUID, **changes: object) -> RuntimeInputSnapshot:
    values: dict[str, object] = {
        "project_id": project_id,
        "fact_snapshot_id": uuid4(),
        "fact_snapshot_hash": _hash("facts-v1"),
        "profile_version_id": uuid4(),
        "profile_hash": _hash("profile-v1"),
        "prompt_release_id": uuid4(),
        "prompt_release_hash": _hash("prompt-v1"),
        "facts_current_approved": True,
        "profile_frozen": True,
        "prompt_frozen": True,
    }
    values.update(changes)
    return RuntimeInputSnapshot(**values)  # type: ignore[arg-type]


def _samples(project_id: UUID) -> tuple[StyleSample, ...]:
    source_id = uuid4()
    run_id = uuid4()
    reviewer = uuid4()
    return tuple(
        StyleSample(
            id=uuid4(),
            project_id=project_id,
            collection_run_id=run_id,
            style_source_revision_id=source_id,
            source_revision_number=1,
            channel="reddit",
            locale="en-AU",
            content_hash=_hash(f"sample-{index}"),
            is_anonymized=True,
            is_au_english=True,
            review_status=StyleSampleReviewStatus.APPROVED,
            reviewed_by=reviewer,
            reviewed_at=NOW,
        )
        for index in range(200)
    )


def _profile(project_id: UUID, samples: tuple[StyleSample, ...]):
    return StyleProfileVersion(
        id=uuid4(),
        project_id=project_id,
        profile_id=uuid4(),
        version_number=1,
        channel="reddit",
        locale="en-AU",
        corpus_hash=style_sample_manifest_hash(samples),
        profile_hash=_hash("profile-v1"),
        prompt_release_id=uuid4(),
        prompt_release_hash=_hash("profile-prompt-v1"),
        approved_sample_count=200,
        status=StyleProfileStatus.APPROVED,
        reviewed_by=uuid4(),
        reviewed_at=NOW,
    )


def _case(project_id: UUID, suite_id: UUID) -> ReviewCase:
    fields: dict[str, object] = {
        "case_key": "reddit-case-1",
        "ordinal": 1,
        "mode": ScenarioMode.AUTONOMOUS,
        "channel": "reddit",
        "persona": "Australian home owner",
        "use_case": "compare pressure washers",
        "subject": "Acme PW-20",
        "question_set_version_id": uuid4(),
        "question_set_hash": _hash("questions-v1"),
        "fact_snapshot_id": uuid4(),
        "fact_snapshot_hash": _hash("facts-v1"),
        "profile_version_id": uuid4(),
        "profile_hash": _hash("profile-v1"),
        "competitor_scenario": True,
        "expected_risks": ("subject_mix",),
        "creative_reference": None,
    }
    return ReviewCase(
        id=uuid4(),
        project_id=project_id,
        review_suite_version_id=suite_id,
        review_suite_version_number=1,
        content_hash=review_case_content_hash(**fields),  # type: ignore[arg-type]
        **fields,  # type: ignore[arg-type]
    )


def _suite(project_id: UUID):
    version_id = uuid4()
    case = _case(project_id, version_id)
    suite = ReviewSuite(
        id=version_id,
        project_id=project_id,
        suite_id=uuid4(),
        version_number=1,
        channel="reddit",
        case_count=1,
        case_set_hash=review_case_set_hash((case,)),
        status=ReviewSuiteStatus.DRAFT,
    )
    return suite, (case,)


def test_profile_and_suite_freeze_require_independent_reviewer_and_cas() -> None:
    project_id = uuid4()
    submitter = _principal(project_id, LabRole.OPERATOR)
    self_reviewer = _principal(project_id, LabRole.REVIEWER, actor_id=submitter.actor_id)
    reviewer = _principal(project_id, LabRole.REVIEWER)
    store = InMemorySyntheticLabStore()
    app = ReviewApplication(InMemorySyntheticLabUnitOfWorkFactory(store))
    samples = _samples(project_id)
    profile = _profile(project_id, samples)
    suite, cases = _suite(project_id)
    store.seed_aggregate(
        VersionedAggregate(
            project_id=project_id,
            kind=STYLE_PROFILE_KIND,
            resource_id=profile.id,
            version=1,
            submitted_by=submitter.actor_id,
            payload=profile,
        )
    )
    store.seed_aggregate(
        VersionedAggregate(
            project_id=project_id,
            kind=REVIEW_SUITE_KIND,
            resource_id=suite.id,
            version=1,
            submitted_by=submitter.actor_id,
            payload=suite,
        )
    )

    with pytest.raises(SyntheticLabPermissionDenied, match="own resource"):
        app.freeze_profile(
            principal=self_reviewer,
            profile=profile,
            samples=samples,
            expected_version=1,
            idempotency_key="self-freeze-profile",
        )
    frozen_profile = app.freeze_profile(
        principal=reviewer,
        profile=profile,
        samples=samples,
        expected_version=1,
        idempotency_key="freeze-profile",
    )
    assert frozen_profile.result.status == StyleProfileStatus.FROZEN
    assert app.freeze_profile(
        principal=reviewer,
        profile=profile,
        samples=samples,
        expected_version=1,
        idempotency_key="freeze-profile",
    ).replayed

    frozen_suite = app.freeze_suite(
        principal=reviewer,
        suite=suite,
        cases=cases,
        expected_version=1,
        idempotency_key="freeze-suite",
    )
    assert frozen_suite.result.status == ReviewSuiteStatus.FROZEN


def _enqueue_request(project_id: UUID, runtime: RuntimeInputSnapshot):
    return JobEnqueueRequest(
        project_id=project_id,
        job_id=uuid4(),
        outbox_id=uuid4(),
        resource_id=uuid4(),
        resource_hash=_hash("resource-v1"),
        runtime_inputs=runtime,
    )


def test_generation_revision_and_corpus_enqueue_only_identifier_payloads() -> None:
    project_id = uuid4()
    operator = _principal(project_id, LabRole.OPERATOR)
    runtime = _runtime(project_id)
    port = StaticRuntimeInputPort(runtime)
    store = InMemorySyntheticLabStore()
    app = ReviewApplication(InMemorySyntheticLabUnitOfWorkFactory(store))

    jobs = (
        app.enqueue_generation(
            principal=operator,
            request=_enqueue_request(project_id, runtime),
            runtime_port=port,
            idempotency_key="generation",
        ).result,
        app.enqueue_revision(
            principal=operator,
            request=_enqueue_request(project_id, runtime),
            runtime_port=port,
            idempotency_key="revision",
        ).result,
        app.enqueue_corpus(
            principal=operator,
            request=_enqueue_request(project_id, runtime),
            runtime_port=port,
            idempotency_key="corpus",
        ).result,
    )
    assert all(isinstance(job, SyntheticJob) for job in jobs)
    assert {job.kind for job in jobs} == {
        "candidate_generation",
        "candidate_revision",
        "corpus_finalize",
    }
    assert all(all(key.endswith(("_id", "_hash")) for key in job.payload) for job in jobs)
    assert store.job_count(project_id) == store.outbox_count(project_id) == 3

    stale = replace(runtime, prompt_frozen=False)
    with pytest.raises(SyntheticLabStaleInput, match="Prompt"):
        app.enqueue_generation(
            principal=operator,
            request=_enqueue_request(project_id, runtime),
            runtime_port=StaticRuntimeInputPort(stale),
            idempotency_key="stale-generation",
        )
    assert store.job_count(project_id) == 3


def _queued_and_claimed():
    project_id = uuid4()
    operator = _principal(project_id, LabRole.OPERATOR)
    worker = _principal(project_id, LabRole.WORKER)
    runtime = _runtime(project_id)
    port = StaticRuntimeInputPort(runtime)
    store = InMemorySyntheticLabStore()
    app = ReviewApplication(InMemorySyntheticLabUnitOfWorkFactory(store))
    request = _enqueue_request(project_id, runtime)
    app.enqueue_generation(
        principal=operator,
        request=request,
        runtime_port=port,
        idempotency_key="enqueue-for-worker",
    )
    claimed = app.claim_job(
        principal=worker,
        job_id=request.job_id,
        expected_version=1,
        claimed_at=NOW,
        lease_for=timedelta(minutes=10),
        runtime_port=port,
        idempotency_key="claim-for-worker",
    ).result
    assert isinstance(claimed, SyntheticJob)
    return project_id, operator, worker, runtime, port, store, app, claimed


def test_terminal_write_rechecks_lease_fence_cancel_and_all_runtime_inputs() -> None:
    project_id, _, worker, runtime, port, store, app, claimed = _queued_and_claimed()
    wrong = JobWriteOwnership(lease_id=claimed.lease_id, fencing_token=2)  # type: ignore[arg-type]
    with pytest.raises(SyntheticLabJobOwnershipLost, match="fencing"):
        app.finalize_result(
            principal=worker,
            job_id=claimed.id,
            ownership=wrong,
            expected_version=2,
            result={"result_hash": _hash("result")},
            runtime_port=port,
            completed_at=NOW + timedelta(minutes=1),
            idempotency_key="wrong-fence",
        )

    ownership = JobWriteOwnership(
        lease_id=claimed.lease_id,  # type: ignore[arg-type]
        fencing_token=claimed.fencing_token,
    )
    with pytest.raises(SyntheticLabJobOwnershipLost, match="expired"):
        app.finalize_result(
            principal=worker,
            job_id=claimed.id,
            ownership=ownership,
            expected_version=2,
            result={"result_hash": _hash("result")},
            runtime_port=port,
            completed_at=NOW + timedelta(minutes=11),
            idempotency_key="expired-lease",
        )

    stale_port = StaticRuntimeInputPort(replace(runtime, facts_current_approved=False))
    with pytest.raises(SyntheticLabStaleInput, match="Fact"):
        app.finalize_result(
            principal=worker,
            job_id=claimed.id,
            ownership=ownership,
            expected_version=2,
            result={"result_hash": _hash("result")},
            runtime_port=stale_port,
            completed_at=NOW + timedelta(minutes=1),
            idempotency_key="stale-facts",
        )
    assert store.get_terminal_result(project_id=project_id, job_id=claimed.id) is None

    receipt = app.finalize_result(
        principal=worker,
        job_id=claimed.id,
        ownership=ownership,
        expected_version=2,
        result={"result_hash": _hash("result")},
        runtime_port=port,
        completed_at=NOW + timedelta(minutes=1),
        idempotency_key="finalize-result",
    )
    assert isinstance(receipt.result, JobTerminalResult)
    assert store.get_job(project_id=project_id, job_id=claimed.id).status == (JobStatus.SUCCEEDED)


def test_cancelled_running_job_cannot_publish_and_uow_detects_concurrent_cas() -> None:
    project_id, operator, worker, _, port, _, app, claimed = _queued_and_claimed()
    cancelled = app.cancel_job(
        principal=operator,
        job_id=claimed.id,
        expected_version=2,
        cancelled_at=NOW + timedelta(seconds=30),
        idempotency_key="cancel-running",
    ).result
    assert cancelled.cancel_requested
    with pytest.raises(SyntheticLabJobOwnershipLost, match="cancelled"):
        app.finalize_result(
            principal=worker,
            job_id=claimed.id,
            ownership=JobWriteOwnership(
                lease_id=claimed.lease_id,  # type: ignore[arg-type]
                fencing_token=claimed.fencing_token,
            ),
            expected_version=3,
            result={"result_hash": _hash("late-result")},
            runtime_port=port,
            completed_at=NOW + timedelta(minutes=1),
            idempotency_key="late-finalize",
        )

    store = InMemorySyntheticLabStore()
    factory = InMemorySyntheticLabUnitOfWorkFactory(store)
    suite, _ = _suite(project_id)
    first = factory(project_id=project_id)
    second = factory(project_id=project_id)
    with first, second:
        for uow, actor in ((first, uuid4()), (second, uuid4())):
            uow.aggregates.stage(
                VersionedAggregate(
                    project_id=project_id,
                    kind="concurrency_probe",
                    resource_id=suite.id,
                    version=1,
                    submitted_by=actor,
                    payload=suite,
                ),
                expected_version=0,
            )
        first.commit()
        with pytest.raises(SyntheticLabVersionConflict, match="concurrent"):
            second.commit()

    with factory(project_id=project_id) as scoped:
        with pytest.raises(SyntheticLabPersistenceError, match="scope mismatch"):
            scoped.jobs.get(project_id=uuid4(), job_id=uuid4())
