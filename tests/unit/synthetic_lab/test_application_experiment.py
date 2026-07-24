from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from geo_core.jobs.lifecycle import JobStatus
from geo_core.synthetic_lab.application_support import JobWriteOwnership
from geo_core.synthetic_lab.corpus import (
    CorpusRole,
    FinalizationGuard,
    candidate_entry_from_resolution,
    freeze_corpus_version,
)
from geo_core.synthetic_lab.experiment_application import (
    OFFLINE_EXPERIMENT_RESULT_KIND,
    ExperimentApplication,
)
from geo_core.synthetic_lab.memory import (
    InMemorySyntheticLabStore,
    InMemorySyntheticLabUnitOfWorkFactory,
)
from geo_core.synthetic_lab.offline_experiment import (
    ExperimentArm,
    FrozenExperimentQuestion,
    create_offline_experiment_plan,
    make_slot_result,
    planned_experiment_slots,
)
from geo_core.synthetic_lab.offline_results import OfflineExperimentResult
from geo_core.synthetic_lab.ports import (
    DenyCustomerSyntheticProjection,
    LabPrincipal,
    LabRole,
    RuntimeInputSnapshot,
    StaticRuntimeInputPort,
    SyntheticCustomerProjectionDenied,
    SyntheticLabPersistenceError,
    SyntheticLabStaleInput,
    SyntheticJob,
)
from geo_core.synthetic_lab.review_application import ReviewApplication
from geo_core.synthetic_lab.revision import CandidateResolution, ReviewRunStatus


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


NOW = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)


def _principal(project_id: UUID, role: LabRole):
    return LabPrincipal(project_id=project_id, actor_id=uuid4(), roles=frozenset({role}))


def _guard(
    project_id: UUID,
    resource_id: UUID,
    fact_id: UUID,
    fact_hash: str,
) -> FinalizationGuard:
    lease = uuid4()
    return FinalizationGuard(
        project_id=project_id,
        resource_id=resource_id,
        expected_lease_id=lease,
        held_lease_id=lease,
        expected_fencing_token=1,
        held_fencing_token=1,
        fact_snapshot_id=fact_id,
        fact_snapshot_hash=fact_hash,
        facts_current_approved=True,
    )


def _plan_and_runtime(project_id: UUID):
    fact_id = uuid4()
    fact_hash = _hash("facts-v1")
    profile_id = uuid4()
    profile_hash = _hash("profile-v1")
    prompt_id = uuid4()
    prompt_hash = _hash("experiment-prompt-v1")
    candidate_id = uuid4()
    resolution = CandidateResolution(
        id=uuid4(),
        project_id=project_id,
        review_run_id=uuid4(),
        review_case_id=uuid4(),
        candidate_id=candidate_id,
        candidate_output_hash=_hash("candidate-output-v1"),
        evaluation_id=uuid4(),
        evaluation_evidence_hash=_hash("evaluation-v1"),
        channel="reddit",
        scenario_mode="autonomous_scenario",
        status=ReviewRunStatus.PASSED,
        warning_codes=(),
        failure_code=None,
    )
    entry = candidate_entry_from_resolution(
        resolution,
        competitor_scenario=True,
        model_key="generator-a",
        model_identity_hash=_hash("generator-a-v1"),
        question_cluster_key="comparison",
    )
    corpora = []
    for role in CorpusRole:
        corpus_id = uuid4()
        corpora.append(
            freeze_corpus_version(
                id=corpus_id,
                project_id=project_id,
                corpus_id=uuid4(),
                version_number=1,
                role=role,
                approved_fact_snapshot_id=fact_id,
                approved_fact_snapshot_hash=fact_hash,
                profile_version_id=profile_id,
                profile_hash=profile_hash,
                prompt_release_id=prompt_id,
                prompt_release_hash=prompt_hash,
                candidates=() if role == CorpusRole.NO_CORPUS_BASELINE else (entry,),
                guard=_guard(project_id, corpus_id, fact_id, fact_hash),
            )
        )
    question = FrozenExperimentQuestion(
        project_id=project_id,
        question_version_id=uuid5(NAMESPACE_URL, "synthetic-question-v1"),
        ordinal=1,
        question_hash=_hash("synthetic-question-v1"),
        question_cluster_key="comparison",
    )
    plan = create_offline_experiment_plan(
        id=uuid4(),
        project_id=project_id,
        question_set_id=uuid4(),
        question_set_hash=_hash("question-set-v1"),
        protocol_id=uuid4(),
        protocol_hash=_hash("protocol-v1"),
        prompt_release_id=prompt_id,
        prompt_release_hash=prompt_hash,
        approved_fact_snapshot_id=fact_id,
        approved_fact_snapshot_hash=fact_hash,
        profile_version_id=profile_id,
        profile_hash=profile_hash,
        model_policy_hash=_hash("model-policy-v1"),
        model_provider="test-provider",
        configured_model="test-model",
        reported_model="test-model-202607",
        model_identity_hash=_hash("test-model-202607"),
        metric_method_release="metric-v1",
        metric_method_hash=_hash("metric-v1"),
        seed_namespace_hash=_hash("seed-v1"),
        questions=(question,),
        corpora=tuple(corpora),
    )
    runtime = RuntimeInputSnapshot(
        project_id=project_id,
        fact_snapshot_id=fact_id,
        fact_snapshot_hash=fact_hash,
        profile_version_id=profile_id,
        profile_hash=profile_hash,
        prompt_release_id=prompt_id,
        prompt_release_hash=prompt_hash,
        facts_current_approved=True,
        profile_frozen=True,
        prompt_frozen=True,
    )
    return plan, runtime


def _slot_results(plan):
    metrics = {
        ExperimentArm.NO_CORPUS_BASELINE: 0.2,
        ExperimentArm.CURRENT_APPROVED_CORPUS: 0.5,
        ExperimentArm.NEW_CANDIDATE_CORPUS: 0.8,
    }
    return tuple(
        make_slot_result(
            slot,
            valid=True,
            metric_value=metrics[slot.arm],
            model_call_id=uuid5(NAMESPACE_URL, f"call-{slot.slot_id}"),
            request_hash=_hash(f"request-{slot.slot_id}"),
            response_hash=_hash(f"response-{slot.slot_id}"),
            answer_hash=_hash(f"answer-{slot.slot_id}"),
            citation_hash=_hash(f"citation-{slot.slot_id}"),
        )
        for slot in planned_experiment_slots(plan)
    )


def _enqueued_and_claimed():
    project_id = uuid4()
    operator = _principal(project_id, LabRole.OPERATOR)
    worker = _principal(project_id, LabRole.WORKER)
    plan, runtime = _plan_and_runtime(project_id)
    port = StaticRuntimeInputPort(runtime)
    store = InMemorySyntheticLabStore()
    factory = InMemorySyntheticLabUnitOfWorkFactory(store)
    experiments = ExperimentApplication(factory)
    reviews = ReviewApplication(factory)
    job = experiments.enqueue_offline_experiment(
        principal=operator,
        plan=plan,
        job_id=uuid4(),
        outbox_id=uuid4(),
        runtime_inputs=runtime,
        runtime_port=port,
        idempotency_key="enqueue-experiment",
    ).result
    assert isinstance(job, SyntheticJob)
    claimed = reviews.claim_job(
        principal=worker,
        job_id=job.id,
        expected_version=1,
        claimed_at=NOW,
        lease_for=timedelta(minutes=10),
        runtime_port=port,
        idempotency_key="claim-experiment",
    ).result
    assert isinstance(claimed, SyntheticJob)
    return worker, plan, runtime, port, store, experiments, claimed


def test_experiment_enqueue_and_finalize_are_atomic_and_exactly_replayable() -> None:
    worker, plan, _, port, store, app, claimed = _enqueued_and_claimed()
    ownership = JobWriteOwnership(
        lease_id=claimed.lease_id,  # type: ignore[arg-type]
        fencing_token=claimed.fencing_token,
    )
    result_id = uuid4()
    results = _slot_results(plan)
    receipt = app.finalize_offline_experiment(
        principal=worker,
        job_id=claimed.id,
        plan_id=plan.id,
        result_id=result_id,
        slot_results=results,
        ownership=ownership,
        expected_job_version=2,
        runtime_port=port,
        completed_at=NOW + timedelta(minutes=1),
        idempotency_key="finalize-experiment",
    )
    assert isinstance(receipt.result, OfflineExperimentResult)
    assert receipt.result.valid_pair_count == 10
    assert store.get_job(project_id=plan.project_id, job_id=claimed.id).status == (
        JobStatus.SUCCEEDED
    )
    assert (
        store.get_aggregate(
            project_id=plan.project_id,
            kind=OFFLINE_EXPERIMENT_RESULT_KIND,
            resource_id=result_id,
        )
        is not None
    )
    assert app.finalize_offline_experiment(
        principal=worker,
        job_id=claimed.id,
        plan_id=plan.id,
        result_id=result_id,
        slot_results=results,
        ownership=ownership,
        expected_job_version=2,
        runtime_port=port,
        completed_at=NOW + timedelta(minutes=1),
        idempotency_key="finalize-experiment",
    ).replayed


def test_experiment_stale_prompt_and_failed_commit_leave_no_terminal_projection() -> None:
    worker, plan, runtime, port, store, app, claimed = _enqueued_and_claimed()
    ownership = JobWriteOwnership(
        lease_id=claimed.lease_id,  # type: ignore[arg-type]
        fencing_token=claimed.fencing_token,
    )
    with pytest.raises(SyntheticLabStaleInput, match="identity or hash"):
        app.finalize_offline_experiment(
            principal=worker,
            job_id=claimed.id,
            plan_id=plan.id,
            result_id=uuid4(),
            slot_results=_slot_results(plan),
            ownership=ownership,
            expected_job_version=2,
            runtime_port=StaticRuntimeInputPort(
                replace(runtime, prompt_release_hash=_hash("prompt-v2"))
            ),
            completed_at=NOW + timedelta(minutes=1),
            idempotency_key="stale-prompt-finalize",
        )
    store.fail_next_commit()
    result_id = uuid4()
    with pytest.raises(SyntheticLabPersistenceError, match="simulated"):
        app.finalize_offline_experiment(
            principal=worker,
            job_id=claimed.id,
            plan_id=plan.id,
            result_id=result_id,
            slot_results=_slot_results(plan),
            ownership=ownership,
            expected_job_version=2,
            runtime_port=port,
            completed_at=NOW + timedelta(minutes=1),
            idempotency_key="failed-finalize-commit",
        )
    assert store.get_terminal_result(project_id=plan.project_id, job_id=claimed.id) is None
    assert (
        store.get_aggregate(
            project_id=plan.project_id,
            kind=OFFLINE_EXPERIMENT_RESULT_KIND,
            resource_id=result_id,
        )
        is None
    )
    assert store.get_job(project_id=plan.project_id, job_id=claimed.id).status == (
        JobStatus.RUNNING
    )


def test_customer_projection_port_always_rejects_synthetic_results() -> None:
    with pytest.raises(SyntheticCustomerProjectionDenied, match="Admin-only"):
        DenyCustomerSyntheticProjection().publish(project_id=uuid4(), result={"synthetic": True})
