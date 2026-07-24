from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets import EnvelopeCipher, MasterKeyring, SecretReference, SecretValue
from geo_core.workflow_c_job_specs import WorkflowCJobSpec
from geo_core.workflow_c_metric_judge_worker import (
    METRIC_ARBITER_KIND,
    METRIC_JUDGE_KIND,
    PostgresWorkflowCMetricArbiterOperation,
    PostgresWorkflowCMetricJudgeOperation,
    WorkflowCMetricJudgeWorkerError,
)
from geo_core.workflow_c_metric_judge_worker_contracts import (
    MetricChild,
    WorkflowCMetricJudgeWorkerContractError,
    decrypt_task,
    metric_child_reference,
    parse_task,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def test_metric_child_spec_binds_the_current_child_job_and_role() -> None:
    job_id = uuid4()
    payload = {
        "schema_version": 1,
        "kind": METRIC_JUDGE_KIND,
        "metric_model_child": {
            "child_job_id": str(job_id),
            "parent_job_id": str(uuid4()),
            "batch_id": str(uuid4()),
            "role": "metric_judge",
            "parent_input_hash": "a" * 64,
            "task_hash": "b" * 64,
        },
    }
    spec = WorkflowCJobSpec(
        project_id=uuid4(),
        job_id=job_id,
        kind=METRIC_JUDGE_KIND,
        spec_hash=_hash(payload),
        payload=payload,
        created_at=NOW,
    )

    reference = metric_child_reference(spec, expected_role="metric_judge")

    assert reference.child_job_id == job_id
    with pytest.raises(WorkflowCMetricJudgeWorkerContractError, match="role"):
        metric_child_reference(spec, expected_role="arbiter")


def test_metric_judge_task_rejects_unknown_fields_before_model_admission() -> None:
    task = _judge_task()
    parsed = parse_task(task, expected_role="metric_judge")

    assert parsed.judge is not None
    assert parsed.judge.plans[0].metric_id == "recommendation"
    task["evaluation"]["unexpected"] = True  # type: ignore[index]
    with pytest.raises(WorkflowCMetricJudgeWorkerContractError, match="unexpected schema"):
        parse_task(task, expected_role="metric_judge")


def test_metric_task_decryption_binds_child_project_key_version_and_hash() -> None:
    task = _judge_task()
    plaintext = json.dumps(task, sort_keys=True, separators=(",", ":")).encode("utf-8")
    project_id, child_job_id = uuid4(), uuid4()
    cipher = EnvelopeCipher(MasterKeyring(keys={1: b"k" * 32}, active_version=1))
    envelope = cipher.encrypt(
        reference=SecretReference(
            id=child_job_id,
            project_id=project_id,
            purpose="workflow_c.metric_model_task",
            created_at=NOW,
        ),
        version=1,
        value=SecretValue(bytearray(plaintext)),
        created_at=NOW,
    )
    child = _child_from_envelope(project_id, child_job_id, envelope, plaintext)

    decrypted = decrypt_task(cipher, child)

    assert decrypted.role == "metric_judge"
    assert decrypted.judge is not None
    tampered = MetricChild(**{**child.__dict__, "task_hash": "c" * 64})
    with pytest.raises(WorkflowCMetricJudgeWorkerContractError, match="plaintext hash"):
        decrypt_task(cipher, tampered)


@pytest.mark.parametrize(
    "operation_type,expected_kind",
    (
        (PostgresWorkflowCMetricJudgeOperation, METRIC_JUDGE_KIND),
        (PostgresWorkflowCMetricArbiterOperation, METRIC_ARBITER_KIND),
    ),
)
def test_metric_operations_reject_the_other_child_kind_before_any_read(
    operation_type, expected_kind: str
) -> None:
    operation = operation_type(
        store=None,
        specs=None,
        repository=None,
        model_runtime=None,
        cipher=None,
        lease_for=timedelta(seconds=30),
    )
    wrong_kind = METRIC_ARBITER_KIND if expected_kind == METRIC_JUDGE_KIND else METRIC_JUDGE_KIND
    lease = WorkerLease(
        job_id=uuid4(),
        project_id=uuid4(),
        kind=wrong_kind,
        worker_id="test-worker",
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )

    with pytest.raises(WorkflowCMetricJudgeWorkerError, match="kind is invalid"):
        operation.execute(lease)


def _judge_task() -> dict[str, object]:
    observation_id = UUID("cb000000-0000-0000-0000-000000000001")
    answer = "Advinsys is recommended."
    return {
        "schema_version": 1,
        "role": "metric_judge",
        "admitted_by": str(uuid4()),
        "admitted_at": NOW.isoformat(),
        "request": {
            "messages": [{"role": "system", "content": "Return JSON."}],
            "configured_model": "fixture-model",
            "temperature": 0.2,
            "max_output_tokens": 256,
            "output_schema": {},
            "application_output_schema": {},
            "seed": 1,
            "tool_mode": None,
            "search_mode": None,
            "deadline_at": None,
        },
        "evaluation": {
            "subject_id": "advinsys",
            "output_locale": "en-AU",
            "schema_version": "metric-judge-output-v1",
            "observation": {
                "id": str(observation_id),
                "slot_id": "slot-1",
                "payload_hash": hashlib.sha256(answer.encode()).hexdigest(),
                "question_id": "question-1",
                "question_cluster": "brand",
                "answer_text": answer,
                "artifact_version": "observation-artifact-v1",
                "citations": [],
            },
            "plans": [
                {
                    "metric_id": "recommendation",
                    "metric_kind": "recommendation",
                    "definition": "Whether the answer recommends the governed subject.",
                    "allowed_evidence_refs": [str(observation_id)],
                }
            ],
        },
    }


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _child_from_envelope(
    project_id, child_job_id, envelope, plaintext: bytes
) -> MetricChild:
    return MetricChild(
        project_id=project_id,
        parent_job_id=uuid4(),
        child_job_id=child_job_id,
        batch_id=uuid4(),
        role="metric_judge",
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
        task_hash=hashlib.sha256(plaintext).hexdigest(),
        task_created_at=NOW,
    )
