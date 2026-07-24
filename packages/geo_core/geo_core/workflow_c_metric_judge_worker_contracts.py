"""Frozen encrypted-task contracts for Workflow C metric model children."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from uuid import UUID

from geo_core.secrets import (
    EncryptedSecretVersion,
    EnvelopeCipher,
    SecretReference,
    SecretValue,
    SecretVersionHandle,
)
from geo_core.semantic_metrics import (
    EvidenceLocator,
    EvidenceLocatorKind,
    JudgeKind,
    MetricJudgeCandidate,
    MetricJudgeCandidateResolution,
    MetricJudgePlan,
    MetricJudgePlanBatch,
    MetricJudgeKind,
    MetricInputSet,
    MetricObservation,
    StructuredJudgeOutput,
)
from geo_core.semantic_metrics.program_output import ParsedMetricJudgeProgramOutput
from geo_core.workflow_c_job_specs import WorkflowCJobSpec
from geo_core.workflow_c_metric_judge_worker_types import (
    MetricArbiterTask,
    MetricChild,
    MetricChildReference,
    MetricJudgeTask,
    MetricTask,
    ModelRequestTask,
    WorkflowCMetricJudgeWorkerContractError,
)


_TASK_SECRET_PURPOSE = "workflow_c.metric_model_task"


@dataclass(frozen=True)
class FrozenMetricTask:
    """Canonical plaintext identity plus the envelope stored on one child row."""

    task: MetricTask
    task_hash: str
    envelope: EncryptedSecretVersion

    def __post_init__(self) -> None:
        if self.envelope.handle.purpose != _TASK_SECRET_PURPOSE:
            raise WorkflowCMetricJudgeWorkerContractError("metric task envelope purpose changed")
        if self.envelope.handle.reference_id.int == 0 or self.envelope.handle.project_id.int == 0:
            raise WorkflowCMetricJudgeWorkerContractError("metric task envelope identity is invalid")
        hash_value(self.task_hash, "metric task hash")


def metric_child_reference(
    spec: WorkflowCJobSpec, *, expected_role: str
) -> MetricChildReference:
    payload = object_value(spec.payload, "metric child Job spec")
    exact_keys(payload, {"schema_version", "kind", "metric_model_child"}, "metric child Job spec")
    if payload.get("schema_version") != 1 or payload.get("kind") != spec.kind:
        raise WorkflowCMetricJudgeWorkerContractError("metric child Job spec identity changed")
    value = object_value(payload.get("metric_model_child"), "metric child reference")
    exact_keys(
        value,
        {"child_job_id", "parent_job_id", "batch_id", "role", "parent_input_hash", "task_hash"},
        "metric child reference",
    )
    role = text(value.get("role"), "metric child role")
    if role != expected_role:
        raise WorkflowCMetricJudgeWorkerContractError("metric child Job spec role is invalid")
    result = MetricChildReference(
        child_job_id=uuid(value.get("child_job_id"), "metric child Job ID"),
        parent_job_id=uuid(value.get("parent_job_id"), "metric parent Job ID"),
        batch_id=uuid(value.get("batch_id"), "metric batch ID"),
        role=role,
        parent_input_hash=hash_value(value.get("parent_input_hash"), "metric parent input hash"),
        task_hash=hash_value(value.get("task_hash"), "metric task hash"),
    )
    if result.child_job_id != spec.job_id or spec.project_id.int == 0:
        raise WorkflowCMetricJudgeWorkerContractError("metric child Job spec does not bind this Job")
    return result


def metric_child(row: Mapping[str, object]) -> MetricChild:
    return MetricChild(
        project_id=uuid(row.get("project_id"), "metric child project ID"),
        parent_job_id=uuid(row.get("parent_job_id"), "metric parent Job ID"),
        child_job_id=uuid(row.get("child_job_id"), "metric child Job ID"),
        batch_id=uuid(row.get("batch_id"), "metric batch ID"),
        role=text(row.get("role"), "metric child role"),
        evaluator_id=text(row.get("evaluator_id"), "metric evaluator ID"),
        candidate_id=uuid(row.get("candidate_id"), "metric candidate ID"),
        parent_input_hash=hash_value(row.get("parent_input_hash"), "metric parent input hash"),
        runtime_selection_id=uuid(row.get("runtime_selection_id"), "metric runtime selection"),
        runtime_manifest_id=uuid(row.get("runtime_manifest_id"), "metric runtime manifest"),
        runtime_manifest_hash=hash_value(row.get("runtime_manifest_hash"), "metric runtime manifest hash"),
        runtime_option_id=uuid(row.get("runtime_option_id"), "metric runtime option"),
        runtime_option_hash=hash_value(row.get("runtime_option_hash"), "metric runtime option hash"),
        prompt_binding_id=uuid(row.get("prompt_binding_id"), "metric Prompt binding"),
        prompt_binding_version=positive(row.get("prompt_binding_version"), "metric Prompt binding version"),
        prompt_frozen_state_id=uuid(row.get("prompt_frozen_state_id"), "metric Prompt state"),
        prompt_state_version=positive(row.get("prompt_state_version"), "metric Prompt state version"),
        prompt_release_id=uuid(row.get("prompt_release_id"), "metric Prompt Release"),
        prompt_release_version=positive(row.get("prompt_release_version"), "metric Prompt Release version"),
        prompt_release_hash=hash_value(row.get("prompt_release_hash"), "metric Prompt Release hash"),
        prompt_purpose=text(row.get("prompt_purpose"), "metric Prompt purpose"),
        prompt_bundle_hash=hash_value(row.get("prompt_bundle_hash"), "metric Prompt bundle hash"),
        portable_output_schema_hash=hash_value(row.get("portable_output_schema_hash"), "metric portable output schema hash"),
        application_output_schema_hash=hash_value(row.get("application_output_schema_hash"), "metric application output schema hash"),
        task_ciphertext=bytes_value(row.get("task_ciphertext"), "metric task ciphertext"),
        task_data_nonce=bytes_value(row.get("task_data_nonce"), "metric task data nonce", 12),
        task_wrapped_data_key=bytes_value(row.get("task_wrapped_data_key"), "metric task wrapped key"),
        task_wrap_nonce=bytes_value(row.get("task_wrap_nonce"), "metric task wrap nonce", 12),
        task_master_key_version=positive(row.get("task_master_key_version"), "metric task master key version"),
        task_algorithm=text(row.get("task_algorithm"), "metric task algorithm"),
        task_hash=hash_value(row.get("task_hash"), "metric task hash"),
        task_created_at=aware_datetime(row.get("created_at"), "metric task creation time"),
    )


def decrypt_task(cipher: EnvelopeCipher, child: MetricChild) -> MetricTask:
    envelope = EncryptedSecretVersion(
        handle=SecretVersionHandle(
            reference_id=child.child_job_id,
            project_id=child.project_id,
            purpose=_TASK_SECRET_PURPOSE,
            version=1,
        ),
        ciphertext=child.task_ciphertext,
        data_nonce=child.task_data_nonce,
        wrapped_data_key=child.task_wrapped_data_key,
        wrap_nonce=child.task_wrap_nonce,
        master_key_version=child.task_master_key_version,
        algorithm=child.task_algorithm,
        created_at=child.task_created_at,
    )
    plaintext = bytearray(cipher.decrypt(envelope).reveal_bytes())
    try:
        if hashlib.sha256(plaintext).hexdigest() != child.task_hash:
            raise WorkflowCMetricJudgeWorkerContractError("metric task plaintext hash changed")
        try:
            decoded = json.loads(plaintext)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WorkflowCMetricJudgeWorkerContractError("metric task plaintext is not JSON") from error
    finally:
        wipe(plaintext)
    return parse_task(object_value(decoded, "metric task"), expected_role=child.role)


def build_metric_judge_task(
    *,
    admitted_by: UUID,
    admitted_at: datetime,
    request: ModelRequestTask,
    input_set: MetricInputSet,
    batch: MetricJudgePlanBatch,
    schema_version: str,
) -> MetricTask:
    """Freeze the exact judge evaluation payload for one planned batch."""

    evaluation = {
        "subject_id": input_set.subjects.primary_subject_key,
        "output_locale": "en-AU",
        "schema_version": schema_version,
        "observation": _observation_value(batch.observation),
        "plans": [_plan_value(plan) for plan in batch.plans],
    }
    return parse_task(
        {
            "schema_version": 1,
            "role": "metric_judge",
            "admitted_by": str(admitted_by),
            "admitted_at": admitted_at.isoformat(),
            "request": _request_value(
                _request_with_program_input(
                    request,
                    {
                        "program": "metric_judge",
                        "schema_version": schema_version,
                        "input": batch.program_input(input_set=input_set),
                    },
                )
            ),
            "evaluation": evaluation,
        },
        expected_role="metric_judge",
    )


def build_metric_arbiter_task(
    *,
    admitted_by: UUID,
    admitted_at: datetime,
    request: ModelRequestTask,
    input_set: MetricInputSet,
    batch: MetricJudgePlanBatch,
    resolution: MetricJudgeCandidateResolution,
) -> MetricTask:
    """Freeze an Arbiter only for an exact, already-disagreeing Judge set."""

    if not resolution.arbiter_required:
        raise WorkflowCMetricJudgeWorkerContractError(
            "metric arbiter task is forbidden when judges agree"
        )
    candidate_ids = tuple(item.candidate_id for item in resolution.candidates)
    evaluator_ids = tuple(item.evaluator_id for item in resolution.candidates)
    allowed_evidence_refs = sorted(
        {
            reference
            for plan in batch.plans
            for reference in plan.allowed_evidence_refs
        }
    )
    allowed_citation_refs = sorted(item.id for item in batch.observation.citations)
    return parse_task(
        {
            "schema_version": 1,
            "role": "arbiter",
            "admitted_by": str(admitted_by),
            "admitted_at": admitted_at.isoformat(),
            "request": _request_value(
                _request_with_program_input(
                    request,
                    {
                        "program": "metric_arbiter",
                        "input": batch.program_input(input_set=input_set),
                        "candidates": [
                            {
                                "candidate_id": candidate.candidate_id,
                                "evaluator_id": candidate.evaluator_id,
                                "output_hash": candidate.output_hash,
                                "output": {
                                    "results": [
                                        item.canonical_value()
                                        for item in candidate.output.results
                                    ],
                                    "overall_status": candidate.output.overall_status,
                                    "output_locale": candidate.output.output_locale,
                                },
                            }
                            for candidate in resolution.candidates
                        ],
                        "allowed_evidence_refs": allowed_evidence_refs,
                        "allowed_citation_refs": allowed_citation_refs,
                    },
                )
            ),
            "evaluation": {
                "subject_id": input_set.subjects.primary_subject_key,
                "output_locale": "en-AU",
                "candidate_ids": list(candidate_ids),
                "evaluator_ids": list(evaluator_ids),
                "allowed_evidence_refs": allowed_evidence_refs,
                "allowed_citation_refs": allowed_citation_refs,
            },
        },
        expected_role="arbiter",
    )


def freeze_metric_task(
    *,
    cipher: EnvelopeCipher,
    project_id: UUID,
    child_job_id: UUID,
    task: MetricTask,
    created_at: datetime,
) -> FrozenMetricTask:
    """Canonicalize, hash and envelope a validated child task for persistence."""

    if project_id.int == 0 or child_job_id.int == 0:
        raise WorkflowCMetricJudgeWorkerContractError("metric task identity is invalid")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise WorkflowCMetricJudgeWorkerContractError("metric task creation time must be timezone-aware")
    expected_role = task.role
    if expected_role not in {"metric_judge", "arbiter"}:
        raise WorkflowCMetricJudgeWorkerContractError("metric task role is invalid")
    value = metric_task_value(task)
    parsed = parse_task(value, expected_role=expected_role)
    plaintext = bytearray(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )
    try:
        task_hash = hashlib.sha256(plaintext).hexdigest()
        envelope = cipher.encrypt(
            reference=SecretReference(
                id=child_job_id,
                project_id=project_id,
                purpose=_TASK_SECRET_PURPOSE,
                created_at=created_at,
            ),
            version=1,
            value=SecretValue(plaintext),
            created_at=created_at,
        )
    finally:
        wipe(plaintext)
    return FrozenMetricTask(task=parsed, task_hash=task_hash, envelope=envelope)


def metric_task_value(task: MetricTask) -> dict[str, object]:
    """Return the one canonical JSON form accepted by ``parse_task``."""

    role = text(task.role, "metric task role")
    if role not in {"metric_judge", "arbiter"}:
        raise WorkflowCMetricJudgeWorkerContractError("metric task role is invalid")
    if task.admitted_at.tzinfo is None or task.admitted_at.utcoffset() is None:
        raise WorkflowCMetricJudgeWorkerContractError("metric task admission time must be timezone-aware")
    if (role == "metric_judge") != (task.judge is not None):
        raise WorkflowCMetricJudgeWorkerContractError("metric judge task shape is invalid")
    if (role == "arbiter") != (task.arbiter is not None):
        raise WorkflowCMetricJudgeWorkerContractError("metric arbiter task shape is invalid")
    evaluation: dict[str, object]
    if task.judge is not None:
        evaluation = {
            "subject_id": task.judge.subject_id,
            "output_locale": task.judge.output_locale,
            "schema_version": task.judge.schema_version,
            "observation": _observation_value(task.judge.observation),
            "plans": [_plan_value(plan) for plan in task.judge.plans],
        }
    else:
        assert task.arbiter is not None
        evaluation = {
            "subject_id": task.arbiter.subject_id,
            "output_locale": task.arbiter.output_locale,
            "candidate_ids": list(task.arbiter.candidate_ids),
            "evaluator_ids": list(task.arbiter.evaluator_ids),
            "allowed_evidence_refs": sorted(task.arbiter.allowed_evidence_refs),
            "allowed_citation_refs": sorted(task.arbiter.allowed_citation_refs),
        }
    return {
        "schema_version": 1,
        "role": role,
        "admitted_by": str(task.admitted_by),
        "admitted_at": task.admitted_at.isoformat(),
        "request": _request_value(task.request),
        "evaluation": evaluation,
    }


def metric_judge_candidate_from_projection(
    *,
    candidate_id: UUID,
    evaluator_id: str,
    output_hash: str,
    projection: Mapping[str, object],
) -> MetricJudgeCandidate:
    """Rehydrate only a hash-bound, selected Judge output for parent merging."""

    hash_value(output_hash, "metric judge output hash")
    exact_keys(
        projection,
        {"results", "overall_status", "output_locale"},
        "metric judge output projection",
    )
    results_value = projection.get("results")
    if not isinstance(results_value, list) or not results_value:
        raise WorkflowCMetricJudgeWorkerContractError("metric judge projection results are invalid")
    results = tuple(
        _projection_result(object_value(item, "metric judge projection result"))
        for item in results_value
    )
    metric_ids = {item.metric_id for item in results}
    if None in metric_ids or len(metric_ids) != len(results):
        raise WorkflowCMetricJudgeWorkerContractError("metric judge projection metric IDs changed")
    overall_status = text(projection.get("overall_status"), "metric judge overall status")
    if overall_status not in {"pass", "warning", "fail"}:
        raise WorkflowCMetricJudgeWorkerContractError("metric judge overall status is invalid")
    output_locale = text(projection.get("output_locale"), "metric judge output locale")
    if output_locale != "en-AU":
        raise WorkflowCMetricJudgeWorkerContractError("metric judge output locale is invalid")
    parsed = ParsedMetricJudgeProgramOutput(
        results=results,
        overall_status=overall_status,
        output_locale=output_locale,
    )
    candidate = MetricJudgeCandidate.create(
        candidate_id=str(candidate_id), evaluator_id=evaluator_id, output=parsed
    )
    if candidate.output_hash != output_hash:
        raise WorkflowCMetricJudgeWorkerContractError("metric judge projection hash changed")
    return candidate


def _request_value(request: ModelRequestTask) -> dict[str, object]:
    if request.deadline_at is not None and (
        request.deadline_at.tzinfo is None or request.deadline_at.utcoffset() is None
    ):
        raise WorkflowCMetricJudgeWorkerContractError("metric deadline must be timezone-aware")
    return {
        "messages": [dict(message) for message in request.messages],
        "configured_model": request.configured_model,
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
        "output_schema": dict(request.output_schema),
        "application_output_schema": dict(request.application_output_schema),
        "seed": request.seed,
        "tool_mode": request.tool_mode,
        "search_mode": request.search_mode,
        "deadline_at": (
            request.deadline_at.isoformat() if request.deadline_at is not None else None
        ),
    }


def _request_with_program_input(
    request: ModelRequestTask, program_input: Mapping[str, object]
) -> ModelRequestTask:
    """Append the exact frozen evaluation input as one canonical user message.

    A task's ``evaluation`` fields are for application-side validation.  They
    are not implicitly visible to a provider.  Keeping a canonical copy in
    the encrypted request prevents a child from making a formally valid model
    call that lacks the Observation, allowed evidence, or Arbiter candidates
    it is required to evaluate.
    """

    try:
        content = json.dumps(
            {"metric_evaluation": program_input},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise WorkflowCMetricJudgeWorkerContractError(
            "metric program input is not canonical JSON"
        ) from error
    return ModelRequestTask(
        messages=(*request.messages, {"role": "user", "content": content}),
        configured_model=request.configured_model,
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        output_schema=request.output_schema,
        application_output_schema=request.application_output_schema,
        seed=request.seed,
        tool_mode=request.tool_mode,
        search_mode=request.search_mode,
        deadline_at=request.deadline_at,
    )


def _observation_value(observation: MetricObservation) -> dict[str, object]:
    return {
        "id": str(observation.id),
        "slot_id": observation.slot_id,
        "payload_hash": observation.payload_hash,
        "question_id": observation.question_id,
        "question_cluster": observation.question_cluster,
        "answer_text": observation.answer_text,
        "artifact_version": observation.artifact_version,
        "citations": [
            {
                "id": citation.id,
                "ordinal": citation.ordinal,
                "url": citation.url,
                "visible_title": citation.visible_title,
                "source_type": citation.source_type,
            }
            for citation in observation.citations
        ],
    }


def _plan_value(plan: MetricJudgePlan) -> dict[str, object]:
    return {
        "metric_id": plan.metric_id,
        "metric_kind": plan.metric_kind.value,
        "definition": plan.definition,
        "allowed_evidence_refs": list(plan.allowed_evidence_refs),
    }


def _projection_result(value: Mapping[str, object]) -> StructuredJudgeOutput:
    exact_keys(
        value,
        {"kind", "label", "score", "reason_codes", "locators", "schema_version", "metric_id"},
        "metric judge projection result",
    )
    raw_score = value.get("score")
    if raw_score is None:
        score = None
    elif isinstance(raw_score, str):
        try:
            score = Decimal(raw_score)
        except InvalidOperation as error:
            raise WorkflowCMetricJudgeWorkerContractError(
                "metric judge projection score is invalid"
            ) from error
    else:
        raise WorkflowCMetricJudgeWorkerContractError("metric judge projection score is invalid")
    raw_locators = value.get("locators")
    if not isinstance(raw_locators, list) or not raw_locators:
        raise WorkflowCMetricJudgeWorkerContractError("metric judge projection locators are invalid")
    try:
        kind = JudgeKind(
            MetricJudgeKind(
                text(value.get("kind"), "metric judge projection kind")
            ).value
        )
    except ValueError as error:
        raise WorkflowCMetricJudgeWorkerContractError(
            "metric judge projection kind is invalid"
        ) from error
    return StructuredJudgeOutput(
        kind=kind,
        label=text(value.get("label"), "metric judge projection label"),
        score=score,
        reason_codes=text_array(value.get("reason_codes"), "metric judge projection reasons"),
        locators=tuple(
            _projection_locator(object_value(item, "metric judge projection locator"))
            for item in raw_locators
        ),
        schema_version=text(value.get("schema_version"), "metric judge projection schema version"),
        metric_id=text(value.get("metric_id"), "metric judge projection metric ID"),
    )


def _projection_locator(value: Mapping[str, object]) -> EvidenceLocator:
    exact_keys(
        value,
        {"kind", "reference_id", "version", "content_hash", "start", "end", "redacted_quote_hash"},
        "metric judge projection locator",
    )
    start = value.get("start")
    end = value.get("end")
    if start is not None and (not isinstance(start, int) or isinstance(start, bool)):
        raise WorkflowCMetricJudgeWorkerContractError("metric judge projection locator start is invalid")
    if end is not None and (not isinstance(end, int) or isinstance(end, bool)):
        raise WorkflowCMetricJudgeWorkerContractError("metric judge projection locator end is invalid")
    content_hash = value.get("content_hash")
    redacted_quote_hash = value.get("redacted_quote_hash")
    if content_hash is not None:
        content_hash = hash_value(content_hash, "metric judge projection locator content hash")
    if redacted_quote_hash is not None:
        redacted_quote_hash = hash_value(
            redacted_quote_hash, "metric judge projection locator quote hash"
        )
    return EvidenceLocator(
        kind=EvidenceLocatorKind(text(value.get("kind"), "metric judge projection locator kind")),
        reference_id=text(value.get("reference_id"), "metric judge projection locator reference"),
        version=optional_text(value.get("version"), "metric judge projection locator version"),
        content_hash=content_hash,
        start=start,
        end=end,
        redacted_quote_hash=redacted_quote_hash,
    )


from geo_core.workflow_c_metric_judge_worker_values import (  # noqa: E402, F401
    arbiter_hash,
    assert_task_schema_hashes,
    aware_datetime,
    bytes_value,
    candidate_hash,
    exact_keys,
    hash_value,
    object_value,
    optional_text,
    parse_task,
    positive,
    row_mapping,
    text,
    text_array,
    uuid,
    wipe,
)


__all__ = [
    "FrozenMetricTask", "MetricArbiterTask", "MetricChild", "MetricChildReference",
    "MetricJudgeTask", "MetricTask", "ModelRequestTask",
    "WorkflowCMetricJudgeWorkerContractError", "arbiter_hash", "assert_task_schema_hashes",
    "build_metric_arbiter_task", "build_metric_judge_task", "candidate_hash", "decrypt_task",
    "freeze_metric_task", "hash_value", "metric_child", "metric_child_reference",
    "metric_judge_candidate_from_projection", "metric_task_value", "row_mapping", "text",
]
