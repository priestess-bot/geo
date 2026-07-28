from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from geo_core.model_gateway.contracts import StructuredOutputValidationError
from geo_core.recommendations.generation_application import (
    RecommendationGenerationApplication,
)
from geo_core.recommendations.generation_contracts import (
    GenerationJobOwnership,
    GenerationJobStatus,
    RecommendationGenerationConflict,
    RecommendationGenerationJob,
    RecommendationGenerationSpec,
)
from geo_core.recommendations.generation_memory import (
    InMemoryRecommendationGenerationRepository,
)
from geo_core.recommendations.models import (
    DownstreamDraftKind,
    RecommendationStatus,
    RecommendationType,
)
from tests.unit.recommendations.generation_test_support import (
    NOW,
    PROJECT_ID,
    FactResolverStub,
    GatewayApplicationStub,
    MutableClock,
    PromptResolverStub,
    arbiter_output,
    generation_spec,
    model_output,
)


def test_insufficient_evidence_short_circuits_model_and_creates_sampling_draft() -> None:
    gateway = GatewayApplicationStub()
    app, repository, prompts, facts, clock = _application(gateway)
    spec = generation_spec(real_observations=2, minimum_real_observations=3)
    job, ownership = _enqueue_claim(app, spec)

    execution = app.run(project_id=PROJECT_ID, job_id=job.id, ownership=ownership)

    assert execution.job.status == GenerationJobStatus.SUCCEEDED
    assert execution.job.consumed_model_calls == 0
    assert execution.result is not None
    recommendation = execution.result.recommendation
    assert recommendation.recommendation_type == RecommendationType.INSUFFICIENT_EVIDENCE
    assert recommendation.status == RecommendationStatus.DRAFT
    assert recommendation.approval is None
    assert recommendation.proposed_draft_kind == DownstreamDraftKind.SAMPLING_PLAN
    assert recommendation.evidence.model_calls == ()
    assert execution.result.insufficient_reasons == ("insufficient_real_observation_count",)
    assert gateway.commands == []
    assert len(prompts.calls) == facts.calls == 2
    assert repository.result(project_id=PROJECT_ID, job_id=job.id) == execution.result
    assert clock() == NOW


@pytest.mark.parametrize(
    ("recommendation_type", "draft_kind"),
    (
        ("hard_blocker", DownstreamDraftKind.CONTENT_BRIEF),
        ("gap", DownstreamDraftKind.QUESTION_SET),
        ("experiment", DownstreamDraftKind.EXPERIMENT_PLAN),
        ("optional", DownstreamDraftKind.CONTENT_BRIEF),
        ("no_change", None),
    ),
)
def test_model_generation_creates_only_unapproved_recommendation_drafts(
    recommendation_type: str,
    draft_kind: DownstreamDraftKind | None,
) -> None:
    spec = generation_spec(recommendation_type=recommendation_type)
    gateway = GatewayApplicationStub(
        model_output(recommendation_type, evidence=spec.evidence)
    )
    app, _, _, _, _ = _application(gateway)
    job, ownership = _enqueue_claim(app, spec)

    execution = app.run(project_id=PROJECT_ID, job_id=job.id, ownership=ownership)

    assert execution.job.status == GenerationJobStatus.SUCCEEDED
    assert execution.result is not None
    recommendation = execution.result.recommendation
    assert recommendation.recommendation_type.value == recommendation_type
    assert recommendation.status == RecommendationStatus.DRAFT
    assert recommendation.approval is None
    assert recommendation.proposed_draft_kind == draft_kind
    assert execution.job.consumed_model_calls == 1
    assert len(recommendation.evidence.model_calls) == 1
    command = gateway.commands[0]
    assert command.route == spec.route
    assert command.prompt_release_hash == spec.prompt_binding.release_hash
    assert command.request.output_schema is not None
    assert command.request.capture_method is spec.capture_method
    assert command.request.search_mode == spec.search_mode


@pytest.mark.parametrize("failure", ("invalid_json", "hallucinated_ref", "numeric_claim"))
def test_invalid_model_outputs_fail_without_persisting_recommendation(failure: str) -> None:
    output = deepcopy(model_output())
    if failure == "invalid_json":
        gateway = GatewayApplicationStub(
            StructuredOutputValidationError("provider returned invalid JSON")
        )
    else:
        if failure == "hallucinated_ref":
            output["evidence_refs"].append({"kind": "fact", "resource_id": "fact:invented"})
        else:
            output["decision"]["risk"] = "Risk increased by 40 percent"
        gateway = GatewayApplicationStub(output)
    app, repository, _, _, _ = _application(gateway)
    job, ownership = _enqueue_claim(app, generation_spec())

    execution = app.run(project_id=PROJECT_ID, job_id=job.id, ownership=ownership)

    assert execution.job.status == GenerationJobStatus.FAILED
    assert execution.job.consumed_model_calls == 1
    assert execution.result is None
    assert repository.result(project_id=PROJECT_ID, job_id=job.id) is None


@pytest.mark.parametrize("stale_source", ("prompt", "fact"))
def test_prompt_or_fact_change_after_model_call_rejects_terminal_result(
    stale_source: str,
) -> None:
    prompts = PromptResolverStub(stale_at=2 if stale_source == "prompt" else None)
    facts = FactResolverStub(stale_at=2 if stale_source == "fact" else None)
    gateway = GatewayApplicationStub(model_output())
    app, repository, _, _, _ = _application(gateway, prompts=prompts, facts=facts)
    job, ownership = _enqueue_claim(app, generation_spec())

    execution = app.run(project_id=PROJECT_ID, job_id=job.id, ownership=ownership)

    assert execution.job.status == GenerationJobStatus.REJECTED_STALE_INPUT
    assert execution.job.consumed_model_calls == 1
    assert execution.result is None
    assert repository.result(project_id=PROJECT_ID, job_id=job.id) is None


def test_search_mode_tampering_after_model_call_rejects_terminal_result() -> None:
    prompts = PromptResolverStub(search_mode_tamper_at=2)
    gateway = GatewayApplicationStub(model_output())
    app, repository, _, _, _ = _application(gateway, prompts=prompts)
    job, ownership = _enqueue_claim(app, generation_spec())

    execution = app.run(project_id=PROJECT_ID, job_id=job.id, ownership=ownership)

    assert execution.job.status == GenerationJobStatus.REJECTED_STALE_INPUT
    assert execution.job.consumed_model_calls == 1
    assert len(gateway.commands) == 1
    assert repository.result(project_id=PROJECT_ID, job_id=job.id) is None


def test_cancelled_job_never_calls_model_or_writes_result() -> None:
    gateway = GatewayApplicationStub(model_output())
    app, repository, _, _, _ = _application(gateway)
    job, ownership = _enqueue_claim(app, generation_spec())
    app.cancel(project_id=PROJECT_ID, job_id=job.id)

    execution = app.run(project_id=PROJECT_ID, job_id=job.id, ownership=ownership)

    assert execution.job.status == GenerationJobStatus.CANCELLED
    assert gateway.commands == []
    assert repository.result(project_id=PROJECT_ID, job_id=job.id) is None


def test_expired_lease_reclaim_fences_old_worker() -> None:
    gateway = GatewayApplicationStub(model_output())
    app, _, _, _, clock = _application(gateway)
    queued = app.enqueue(generation_spec(), idempotency_key="generation:fence").job
    first = app.claim(
        project_id=PROJECT_ID,
        job_id=queued.id,
        worker_id="worker-one",
        lease_for=timedelta(seconds=1),
    )
    assert first.lease_id is not None
    first_owner = GenerationJobOwnership(first.lease_id, first.fencing_token)
    clock.now += timedelta(seconds=2)
    second = app.claim(
        project_id=PROJECT_ID,
        job_id=queued.id,
        worker_id="worker-two",
        lease_for=timedelta(hours=1),
    )

    with pytest.raises(RecommendationGenerationConflict, match="fenced"):
        app.run(project_id=PROJECT_ID, job_id=queued.id, ownership=first_owner)
    assert second.fencing_token == first.fencing_token + 1
    assert gateway.commands == []


def test_enqueue_idempotency_and_changed_input_conflict() -> None:
    app, _, _, _, _ = _application(GatewayApplicationStub())
    spec = generation_spec()
    first = app.enqueue(spec, idempotency_key="generation:same")
    replay = app.enqueue(spec, idempotency_key="generation:same")

    assert replay.replayed is True
    assert replay.job.id == first.job.id
    changed = generation_spec(minimum_real_observations=4)
    with pytest.raises(RecommendationGenerationConflict, match="another input hash"):
        app.enqueue(changed, idempotency_key="generation:same")


def test_distinct_arbiter_consumes_second_call_and_same_model_was_rejected_by_spec() -> None:
    candidate = model_output()
    gateway = GatewayApplicationStub(candidate, arbiter_output(candidate))
    app, repository, _, _, _ = _application(gateway)
    spec = generation_spec(with_arbiter=True)
    job, ownership = _enqueue_claim(app, spec)

    execution = app.run(project_id=PROJECT_ID, job_id=job.id, ownership=ownership)

    assert execution.job.status == GenerationJobStatus.SUCCEEDED
    assert execution.job.consumed_model_calls == 2
    assert execution.result is not None
    assert len(execution.result.model_call_ids) == 2
    assert gateway.commands[0].route.model_release_id != gateway.commands[1].route.model_release_id
    assert gateway.commands[0].request.capture_method is spec.capture_method
    assert gateway.commands[0].request.search_mode == spec.search_mode
    assert gateway.commands[1].request.capture_method is spec.arbiter_capture_method
    assert gateway.commands[1].request.search_mode == spec.arbiter_search_mode
    assert repository.result(project_id=PROJECT_ID, job_id=job.id) == execution.result


def _application(
    gateway: GatewayApplicationStub,
    *,
    prompts: PromptResolverStub | None = None,
    facts: FactResolverStub | None = None,
) -> tuple[
    RecommendationGenerationApplication,
    InMemoryRecommendationGenerationRepository,
    PromptResolverStub,
    FactResolverStub,
    MutableClock,
]:
    repository = InMemoryRecommendationGenerationRepository()
    prompt_port = prompts or PromptResolverStub()
    fact_port = facts or FactResolverStub()
    clock = MutableClock()
    application = RecommendationGenerationApplication(
        repository=repository,
        prompts=prompt_port,
        facts=fact_port,
        model_gateway=gateway,
        clock=clock,
    )
    return application, repository, prompt_port, fact_port, clock


def _enqueue_claim(
    app: RecommendationGenerationApplication,
    spec: RecommendationGenerationSpec,
) -> tuple[RecommendationGenerationJob, GenerationJobOwnership]:
    queued = app.enqueue(spec, idempotency_key=f"generation:{id(spec)}").job
    claimed = app.claim(
        project_id=PROJECT_ID,
        job_id=queued.id,
        worker_id="generation-worker",
        lease_for=timedelta(hours=1),
    )
    assert claimed.lease_id is not None
    return claimed, GenerationJobOwnership(claimed.lease_id, claimed.fencing_token)
