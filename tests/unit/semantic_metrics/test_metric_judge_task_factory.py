from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from uuid import UUID, uuid4

import pytest

from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.semantic_metrics import (
    MetricJudgeCandidate,
    plan_metric_judge_batches,
    resolve_metric_judge_candidates,
)
from geo_core.semantic_metrics.program_output import ParsedMetricJudgeProgramOutput
from geo_core.workflow_c_metric_judge_worker_contracts import (
    MetricChild,
    ModelRequestTask,
    WorkflowCMetricJudgeWorkerContractError,
    build_metric_arbiter_task,
    build_metric_judge_task,
    decrypt_task,
    freeze_metric_task,
    metric_judge_candidate_from_projection,
    metric_task_value,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def test_metric_judge_task_factory_freezes_and_encrypts_the_exact_batch(
    metric_input_set, metric_suite
) -> None:
    batch = plan_metric_judge_batches(
        input_set=metric_input_set,
        suite=metric_suite,
        observation=metric_input_set.observations[0],
    )[0]
    project_id, child_job_id = uuid4(), uuid4()
    task = build_metric_judge_task(
        admitted_by=uuid4(),
        admitted_at=NOW,
        request=_request(),
        input_set=metric_input_set,
        batch=batch,
        schema_version=metric_suite.judge_version.schema_version,
    )
    frozen = freeze_metric_task(
        cipher=_cipher(),
        project_id=project_id,
        child_job_id=child_job_id,
        task=task,
        created_at=NOW,
    )

    assert frozen.task.judge is not None
    assert frozen.task.judge.observation.judge_outputs == ()
    assert [item.metric_id for item in frozen.task.judge.plans] == [
        item.metric_id for item in batch.plans
    ]
    context = json.loads(frozen.task.request.messages[-1]["content"])
    assert frozen.task.request.messages[-1]["role"] == "user"
    assert context == {
        "metric_evaluation": {
            "program": "metric_judge",
            "schema_version": metric_suite.judge_version.schema_version,
            "input": batch.program_input(input_set=metric_input_set),
        }
    }
    assert frozen.task_hash == _hash(metric_task_value(task))
    decrypted = decrypt_task(_cipher(), _child(project_id, child_job_id, frozen))
    assert metric_task_value(decrypted) == metric_task_value(task)


def test_metric_arbiter_factory_requires_disagreement_and_exact_uuid_candidates(
    metric_input_set, metric_suite
) -> None:
    batch = plan_metric_judge_batches(
        input_set=metric_input_set,
        suite=metric_suite,
        observation=metric_input_set.observations[0],
    )[0]
    output = replace(
        metric_input_set.observations[0].judge_outputs[0], metric_id=batch.plans[0].metric_id
    )
    matching = ParsedMetricJudgeProgramOutput(
        results=(output,), overall_status="pass", output_locale="en-AU"
    )
    disagreeing = ParsedMetricJudgeProgramOutput(
        results=(replace(output, label="no"),),
        overall_status="warning",
        output_locale="en-AU",
    )
    first = MetricJudgeCandidate.create(
        candidate_id=str(uuid4()),
        evaluator_id="judge-a",
        output=matching,
    )
    second = MetricJudgeCandidate.create(
        candidate_id=str(uuid4()),
        evaluator_id="judge-b",
        output=disagreeing,
    )
    resolution = resolve_metric_judge_candidates((first, second))
    task = build_metric_arbiter_task(
        admitted_by=uuid4(),
        admitted_at=NOW,
        request=_request(),
        input_set=metric_input_set,
        batch=batch,
        resolution=resolution,
    )

    assert task.arbiter is not None
    assert task.arbiter.candidate_ids == tuple(sorted((first.candidate_id, second.candidate_id)))
    assert task.arbiter.allowed_citation_refs == frozenset(
        item.id for item in batch.observation.citations
    )
    context = json.loads(task.request.messages[-1]["content"])["metric_evaluation"]
    assert context["program"] == "metric_arbiter"
    assert context["input"] == batch.program_input(input_set=metric_input_set)
    assert context["allowed_evidence_refs"] == sorted(
        {
            reference
            for plan in batch.plans
            for reference in plan.allowed_evidence_refs
        }
    )
    assert context["candidates"] == [
        {
            "candidate_id": candidate.candidate_id,
            "evaluator_id": candidate.evaluator_id,
            "output_hash": candidate.output_hash,
            "output": {
                "results": [item.canonical_value() for item in candidate.output.results],
                "overall_status": candidate.output.overall_status,
                "output_locale": candidate.output.output_locale,
            },
        }
        for candidate in resolution.candidates
    ]
    agreed_second = MetricJudgeCandidate.create(
        candidate_id=str(uuid4()),
        evaluator_id="judge-b",
        output=matching,
    )
    agreement = resolve_metric_judge_candidates((first, agreed_second))
    with pytest.raises(WorkflowCMetricJudgeWorkerContractError, match="forbidden"):
        build_metric_arbiter_task(
            admitted_by=uuid4(),
            admitted_at=NOW,
            request=_request(),
            input_set=metric_input_set,
            batch=batch,
            resolution=agreement,
        )


def test_selected_metric_projection_is_rehydrated_only_when_hash_bound(metric_input_set) -> None:
    output = replace(metric_input_set.observations[0].judge_outputs[0], metric_id="recommendation")
    projection = {
        "results": [output.canonical_value()],
        "overall_status": "pass",
        "output_locale": "en-AU",
    }
    candidate = metric_judge_candidate_from_projection(
        candidate_id=uuid4(),
        evaluator_id="judge-a",
        output_hash=_hash(projection),
        projection=projection,
    )

    assert candidate.output.results == (output,)
    tampered = {**projection, "overall_status": "warning"}
    with pytest.raises(WorkflowCMetricJudgeWorkerContractError, match="hash changed"):
        metric_judge_candidate_from_projection(
            candidate_id=uuid4(),
            evaluator_id="judge-a",
            output_hash=_hash(projection),
            projection=tampered,
        )
    invalid_kind = {
        **projection,
        "results": [{**output.canonical_value(), "kind": "unapproved_kind"}],
    }
    with pytest.raises(WorkflowCMetricJudgeWorkerContractError, match="kind is invalid"):
        metric_judge_candidate_from_projection(
            candidate_id=uuid4(),
            evaluator_id="judge-a",
            output_hash=_hash(invalid_kind),
            projection=invalid_kind,
        )


def _request() -> ModelRequestTask:
    return ModelRequestTask(
        messages=({"role": "system", "content": "Return JSON."},),
        configured_model="fixture-model",
        temperature=0.2,
        max_output_tokens=256,
        output_schema={},
        application_output_schema={},
        seed=1,
        tool_mode=None,
        search_mode=None,
        deadline_at=None,
    )


def _cipher() -> EnvelopeCipher:
    return EnvelopeCipher(MasterKeyring(keys={1: b"k" * 32}, active_version=1))


def _child(project_id: UUID, child_job_id: UUID, frozen) -> MetricChild:
    envelope = frozen.envelope
    return MetricChild(
        project_id=project_id,
        parent_job_id=uuid4(),
        child_job_id=child_job_id,
        batch_id=uuid4(),
        role=frozen.task.role,
        evaluator_id="judge-a",
        candidate_id=uuid4(),
        parent_input_hash="a" * 64,
        runtime_selection_id=uuid4(),
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash="b" * 64,
        runtime_option_id=uuid4(),
        runtime_option_hash="c" * 64,
        prompt_binding_id=uuid4(),
        prompt_binding_version=1,
        prompt_frozen_state_id=uuid4(),
        prompt_state_version=1,
        prompt_release_id=uuid4(),
        prompt_release_version=1,
        prompt_release_hash="d" * 64,
        prompt_purpose="monitoring.metric_judge",
        prompt_bundle_hash="e" * 64,
        portable_output_schema_hash="f" * 64,
        application_output_schema_hash="0" * 64,
        task_ciphertext=envelope.ciphertext,
        task_data_nonce=envelope.data_nonce,
        task_wrapped_data_key=envelope.wrapped_data_key,
        task_wrap_nonce=envelope.wrap_nonce,
        task_master_key_version=envelope.master_key_version,
        task_algorithm=envelope.algorithm,
        task_hash=frozen.task_hash,
        task_created_at=NOW,
    )


def _hash(value: object) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
