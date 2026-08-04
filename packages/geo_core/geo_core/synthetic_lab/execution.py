"""Deterministic Style Profile and three-arm offline task orchestration."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import cast
from uuid import UUID

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.contracts import ModelGatewayError, RetryableModelGatewayError
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_validation import (
    validate_bootstrap_input,
    validate_bootstrap_output,
)
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.execution_contracts import (
    CorpusFinalizeOutput,
    CorpusFinalizeTask,
    DirectGenerationTask,
    ExecutionCheckpoint,
    OfflineExperimentRunOutput,
    OfflineExperimentRunTask,
    ResolvedSyntheticPrompt,
    ReviewCaseRunTask,
    StyleProfileBuildOutput,
    StyleProfileBuildTask,
    SyntheticExecutionError,
    SyntheticExecutionResult,
    SyntheticExecutionOutput,
    SyntheticExecutionTask,
    SyntheticModelCallPort,
    SyntheticModelInvocation,
    SyntheticModelResult,
    SyntheticPromptResolverPort,
    SyntheticWorkflowResult,
)
from geo_core.synthetic_lab.corpus import FinalizationGuard, freeze_corpus_version
from geo_core.synthetic_lab.offline_experiment import (
    OfflineSlotResult,
    PlannedExperimentSlot,
    make_slot_result,
    planned_experiment_slots,
)
from geo_core.synthetic_lab.offline_results import finalize_offline_experiment
from geo_core.synthetic_lab.review_executor import ReviewCaseExecutor


_STYLE_PROFILE_SPEC = default_prompt_bootstrap_spec(ProgramKind.STYLE_PROFILE)
_OFFLINE_ANSWER_SPEC = default_prompt_bootstrap_spec(ProgramKind.OFFLINE_ANSWER)
STYLE_PROFILE_OUTPUT_SCHEMA: Mapping[str, object] = _STYLE_PROFILE_SPEC.schemas.output_schema
OFFLINE_SLOT_OUTPUT_SCHEMA: Mapping[str, object] = _OFFLINE_ANSWER_SPEC.schemas.output_schema


class SyntheticTaskExecutor:
    def __init__(
        self,
        *,
        prompts: SyntheticPromptResolverPort,
        model_gateway: SyntheticModelCallPort,
    ) -> None:
        self._prompts = prompts
        self._models = model_gateway
        self._reviews = ReviewCaseExecutor(prompts=prompts, model_gateway=model_gateway)

    def run(
        self,
        *,
        lease: WorkerLease,
        task: SyntheticExecutionTask,
        checkpoint: ExecutionCheckpoint,
    ) -> SyntheticExecutionOutput:
        if task.project_id != lease.project_id or task.job_id != lease.job_id:
            raise SyntheticExecutionError("execution task does not match the claimed Job")
        if isinstance(task, StyleProfileBuildTask):
            return self._build_profile(lease=lease, task=task, checkpoint=checkpoint)
        if isinstance(task, CorpusFinalizeTask):
            return self._finalize_corpus(lease=lease, task=task, checkpoint=checkpoint)
        if isinstance(task, OfflineExperimentRunTask):
            return self._run_offline(lease=lease, task=task, checkpoint=checkpoint)
        if isinstance(task, (ReviewCaseRunTask, DirectGenerationTask)):
            return self._reviews.run(lease=lease, task=task, checkpoint=checkpoint)
        raise SyntheticExecutionError("unsupported Synthetic execution task")

    def _finalize_corpus(
        self,
        *,
        lease: WorkerLease,
        task: CorpusFinalizeTask,
        checkpoint: ExecutionCheckpoint,
    ) -> CorpusFinalizeOutput:
        runtime = checkpoint()
        corpus = freeze_corpus_version(
            id=task.corpus_version_id,
            project_id=task.project_id,
            corpus_id=task.corpus_id,
            version_number=task.version_number,
            role=task.role,
            approved_fact_snapshot_id=runtime.fact_snapshot_id,
            approved_fact_snapshot_hash=runtime.fact_snapshot_hash,
            profile_version_id=runtime.profile_version_id,
            profile_hash=runtime.profile_hash,
            prompt_release_id=runtime.prompt_release_id,
            prompt_release_hash=runtime.prompt_release_hash,
            candidates=task.candidates,
            guard=FinalizationGuard(
                project_id=task.project_id,
                resource_id=task.corpus_version_id,
                expected_lease_id=lease.lease_token,
                held_lease_id=lease.lease_token,
                expected_fencing_token=lease.fencing_generation,
                held_fencing_token=lease.fencing_generation,
                fact_snapshot_id=runtime.fact_snapshot_id,
                fact_snapshot_hash=runtime.fact_snapshot_hash,
                facts_current_approved=runtime.facts_current_approved,
                cancelled=False,
            ),
        )
        checkpoint()
        return CorpusFinalizeOutput(
            project_id=task.project_id,
            corpus=corpus,
            candidate_text=task.candidate_text,
        )

    def _build_profile(
        self,
        *,
        lease: WorkerLease,
        task: StyleProfileBuildTask,
        checkpoint: ExecutionCheckpoint,
    ) -> StyleProfileBuildOutput:
        subject_id = f"style:{task.channel}"
        structured_input = {
            "subject_id": subject_id,
            "allowed_subject_ids": list(
                dict.fromkeys(
                    (subject_id, *(item.subject_id for item in task.sample_style_evidence))
                )
            ),
            "evidence": [
                {
                    **item.prompt_value(),
                    "evidence_scope": (
                        "primary_subject"
                        if item.subject_id == subject_id
                        else "competitor_subject"
                    ),
                }
                for item in task.sample_style_evidence
            ],
            "output_locale": task.locale,
            "untrusted_text": "",
            "prompt_injection_present": False,
            "channel": task.channel,
            "locale": task.locale,
            "corpus_hash": task.corpus_hash,
            "approved_sample_count": task.approved_sample_count,
            "sample_manifest_hash": task.sample_manifest_hash,
        }
        result = self._invoke(
            lease=lease,
            task=task,
            prompt=task.prompt,
            structured_input=structured_input,
            kind=ProgramKind.STYLE_PROFILE,
            step_key="style-profile:build:v1",
            checkpoint=checkpoint,
        )
        if result.output.get("sample_manifest_hash") != task.sample_manifest_hash:
            raise SyntheticExecutionError("Style Profile output changed the sample manifest")
        for field_name in (
            "voice_traits",
            "lexical_patterns",
            "structure_patterns",
            "avoid_patterns",
        ):
            _string_list(result.output.get(field_name), field_name)
        profile_summary = json.dumps(
            dict(result.output),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return StyleProfileBuildOutput(
            project_id=task.project_id,
            profile_version_id=task.profile_version_id,
            profile_hash=task.runtime_inputs.profile_hash,
            artifact_hash=canonical_hash(result.output),
            model_call_ids=(
                (result.model_call_id,)
                if isinstance(result, SyntheticModelResult)
                else ()
            ),
            workflow_attempt_ids=(
                (result.workflow_attempt_id,)
                if isinstance(result, SyntheticWorkflowResult)
                else ()
            ),
            profile_summary=profile_summary,
        )

    def _run_offline(
        self,
        *,
        lease: WorkerLease,
        task: OfflineExperimentRunTask,
        checkpoint: ExecutionCheckpoint,
    ) -> OfflineExperimentRunOutput:
        slots = planned_experiment_slots(task.plan)
        by_pair: dict[str, list[PlannedExperimentSlot]] = {}
        for slot in slots:
            by_pair.setdefault(slot.pair_id, []).append(slot)
        slot_results: list[OfflineSlotResult] = []
        model_call_ids: list[UUID] = []
        for pair_id in sorted(by_pair):
            pair_slots = sorted(by_pair[pair_id], key=lambda item: item.arm.value)
            completed: list[tuple[PlannedExperimentSlot, SyntheticModelResult]] = []
            try:
                for slot in pair_slots:
                    result = self._offline_call(
                        lease=lease,
                        task=task,
                        slot=slot,
                        checkpoint=checkpoint,
                    )
                    completed.append((slot, result))
                    model_call_ids.append(result.model_call_id)
            except RetryableModelGatewayError:
                raise
            except ModelGatewayError as error:
                checkpoint()
                reason = f"model_{error.code.value}"
                slot_results.extend(
                    make_slot_result(slot, valid=False, invalid_reason=reason)
                    for slot in pair_slots
                )
                continue
            for slot, result in completed:
                answer = result.output.get("answer_text")
                citations = result.output.get("citation_refs")
                metric = result.output.get("metric_value")
                if not isinstance(answer, str) or not answer.strip():
                    raise SyntheticExecutionError("offline slot answer is empty")
                citation_values = _string_list(citations, "citation_refs")
                if isinstance(metric, bool) or not isinstance(metric, (int, float)):
                    raise SyntheticExecutionError("offline slot metric is not numeric")
                metric_value = float(metric)
                if not 0 <= metric_value <= 1:
                    raise SyntheticExecutionError("offline slot metric is outside [0, 1]")
                slot_results.append(
                    make_slot_result(
                        slot,
                        valid=True,
                        metric_value=metric_value,
                        model_call_id=result.model_call_id,
                        request_hash=result.request_hash,
                        response_hash=result.response_hash,
                        answer_hash=canonical_hash(answer),
                        citation_hash=canonical_hash(citation_values),
                    )
                )
        ordered = tuple(sorted(slot_results, key=lambda item: item.slot_id))
        if len(ordered) != len(slots):
            raise SyntheticExecutionError("Offline Experiment did not resolve every slot")
        runtime = checkpoint()
        summary = finalize_offline_experiment(
            result_id=task.result_id,
            plan=task.plan,
            slot_results=ordered,
            guard=FinalizationGuard(
                project_id=task.project_id,
                resource_id=task.plan.id,
                expected_lease_id=lease.lease_token,
                held_lease_id=lease.lease_token,
                expected_fencing_token=lease.fencing_generation,
                held_fencing_token=lease.fencing_generation,
                fact_snapshot_id=runtime.fact_snapshot_id,
                fact_snapshot_hash=runtime.fact_snapshot_hash,
                facts_current_approved=runtime.facts_current_approved,
                cancelled=False,
            ),
        )
        checkpoint()
        return OfflineExperimentRunOutput(
            project_id=task.project_id,
            experiment_id=task.plan.id,
            result_id=task.result_id,
            slot_results=ordered,
            model_call_ids=tuple(model_call_ids),
            summary=summary,
        )

    def _offline_call(
        self,
        *,
        lease: WorkerLease,
        task: OfflineExperimentRunTask,
        slot: PlannedExperimentSlot,
        checkpoint: ExecutionCheckpoint,
    ) -> SyntheticModelResult:
        context = task.question_corpus_context.get(
            (slot.corpus_version_id, slot.question_version_id),
            task.corpus_context[slot.corpus_version_id],
        )
        structured_input = {
            "subject_id": slot.question_cluster_key,
            "allowed_subject_ids": [slot.question_cluster_key],
            "evidence": [
                {
                    "ref": f"corpus:{slot.corpus_version_id}:{slot.corpus_hash}",
                    "subject_id": slot.question_cluster_key,
                    "evidence_scope": "primary_subject",
                    "summary": (
                        "Frozen synthetic Corpus context; content hash "
                        f"{canonical_hash(context)}."
                    ),
                }
            ],
            "output_locale": "en-AU",
            "untrusted_text": task.question_text[slot.question_version_id],
            "prompt_injection_present": False,
            "experiment_input_hash": task.plan.input_hash,
            "slot_id": slot.slot_id,
            "pair_id": slot.pair_id,
            "question_version_id": str(slot.question_version_id),
            "question_hash": slot.question_hash,
            "question_text": task.question_text[slot.question_version_id],
            "question_cluster_key": slot.question_cluster_key,
            "repetition": slot.repetition,
            "arm": slot.arm.value,
            "corpus_version_id": str(slot.corpus_version_id),
            "corpus_hash": slot.corpus_hash,
            "corpus_context": context,
        }
        result = self._invoke(
            lease=lease,
            task=task,
            prompt=task.prompt,
            structured_input=structured_input,
            kind=ProgramKind.OFFLINE_ANSWER,
            step_key=f"offline-slot:{slot.slot_id}",
            checkpoint=checkpoint,
            seed=slot.deterministic_seed,
        )
        if not isinstance(result, SyntheticModelResult):
            raise SyntheticExecutionError("Offline Answer must remain on the native Model Gateway")
        return result

    def _invoke(
        self,
        *,
        lease: WorkerLease,
        task: StyleProfileBuildTask | OfflineExperimentRunTask,
        prompt,
        structured_input: Mapping[str, object],
        kind: ProgramKind,
        step_key: str,
        checkpoint: ExecutionCheckpoint,
        seed: int | None = None,
    ) -> SyntheticExecutionResult:
        checkpoint()
        spec = default_prompt_bootstrap_spec(kind)
        validate_bootstrap_input(spec, structured_input)
        resolved: ResolvedSyntheticPrompt = self._prompts.resolve(
            frozen=prompt,
            structured_input=structured_input,
            output_schema=spec.schemas.output_schema,
            application_output_schema=spec.schemas.application_output_schema,
        )
        result = self._models.execute(
            SyntheticModelInvocation(
                lease=lease,
                expected_job_version=task.model_job_version,
                parent_task_input_hash=task.input_hash,
                runtime_inputs=task.runtime_inputs,
                prompt=resolved,
                admitted_by=task.requested_by,
                step_key=step_key,
                structured_input=structured_input,
                deterministic_seed=seed,
            )
        )
        checkpoint()
        validate_bootstrap_output(spec, input_value=structured_input, output=result.output)
        if result.configured_model != prompt.configured_model:
            raise SyntheticExecutionError("model result changed the configured model")
        return result


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise SyntheticExecutionError(f"{label} must be a list of non-empty strings")
    return tuple(cast(str, item).strip() for item in value)


__all__ = [
    "OFFLINE_SLOT_OUTPUT_SCHEMA",
    "STYLE_PROFILE_OUTPUT_SCHEMA",
    "SyntheticTaskExecutor",
]
