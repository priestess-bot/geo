"""Deterministic four-candidate, two-revision, one-regeneration orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid5

from geo_core.jobs.postgres import WorkerLease
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_validation import (
    validate_bootstrap_input,
    validate_bootstrap_output,
)
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.evaluation import CandidateEvaluation, EvaluationDisposition
from geo_core.synthetic_lab.execution_contracts import (
    ExecutionCheckpoint,
    ReviewCaseRunOutput,
    ReviewExecutionTask,
    SyntheticExecutionError,
    SyntheticExecutionResult,
    SyntheticModelCallPort,
    SyntheticModelInvocation,
    SyntheticModelResult,
    SyntheticPromptResolverPort,
    SyntheticWorkflowResult,
)
from geo_core.synthetic_lab.generation import GeneratedCandidate, GenerationBatch, GenerationBatchKind
from geo_core.synthetic_lab.review_execution_support import (
    claim_assessments as _claim_assessments,
    common_review_input as _common_input,
    conflict_check_claims as _conflict_check_claims,
    conflict_issue_codes as _conflict_issue_codes,
    evidence_refs as _evidence_refs,
    frozen_call_lineage as _lineage,
    mapping_items as _mapping_items,
    required_string as _string,
    string_tuple as _string_tuple,
)
from geo_core.synthetic_lab.revision import (
    CandidateRevision,
    RevisedCandidate,
    WorkflowAction,
    decide_next_step,
    resolution_from_decision,
    revision_issue_set_hash,
)


@dataclass(frozen=True)
class _CandidateWork:
    initial: GeneratedCandidate
    current: GeneratedCandidate | RevisedCandidate
    text: str
    evaluation: CandidateEvaluation
    revisions: tuple[CandidateRevision, ...] = ()


class ReviewCaseExecutor:
    def __init__(
        self,
        *,
        prompts: SyntheticPromptResolverPort,
        model_gateway: SyntheticModelCallPort,
    ) -> None:
        self._prompts = prompts
        self._models = model_gateway

    def run(
        self,
        *,
        lease: WorkerLease,
        task: ReviewExecutionTask,
        checkpoint: ExecutionCheckpoint,
    ) -> ReviewCaseRunOutput:
        model_calls: list[SyntheticExecutionResult] = []
        evaluations: list[CandidateEvaluation] = []
        revisions: list[CandidateRevision] = []
        initial_batch, initial_text = self._generate_batch(
            lease=lease,
            task=task,
            batch_number=1,
            checkpoint=checkpoint,
            model_calls=model_calls,
        )
        initial_work = self._evaluate_batch(
            lease=lease,
            task=task,
            batch=initial_batch,
            texts=initial_text,
            checkpoint=checkpoint,
            model_calls=model_calls,
        )
        evaluations.extend(item.evaluation for item in initial_work)
        complete = _best_complete(initial_work)
        if complete is not None:
            resolution = _resolution(task, initial_batch, complete)
            return _output(
                task,
                (initial_batch,),
                revisions,
                evaluations,
                resolution,
                model_calls,
                complete.text,
            )

        selected = min(
            initial_work,
            key=lambda item: (len(item.evaluation.correctable_issue_codes), item.initial.ordinal),
        )
        current = selected
        for round_number in (1, 2):
            current = self._revise(
                lease=lease,
                task=task,
                batch=initial_batch,
                work=current,
                round_number=round_number,
                checkpoint=checkpoint,
                model_calls=model_calls,
            )
            revisions.append(current.revisions[-1])
            evaluations.append(current.evaluation)
            decision = decide_next_step(
                initial_batch,
                current.initial,
                current.revisions,
                current.evaluation,
            )
            if decision.action is WorkflowAction.COMPLETE:
                resolution = resolution_from_decision(
                    resolution_id=_id(lease, f"resolution:{task.case.id}"),
                    decision=decision,
                    evaluation=current.evaluation,
                    channel=task.case.channel,
                    scenario_mode=task.case.mode,
                )
                return _output(
                    task,
                    (initial_batch,),
                    revisions,
                    evaluations,
                    resolution,
                    model_calls,
                    current.text,
                )
        decision = decide_next_step(
            initial_batch,
            current.initial,
            current.revisions,
            current.evaluation,
        )
        if decision.action is not WorkflowAction.REGENERATE:
            raise SyntheticExecutionError("two failed revisions must request regeneration")

        regenerated, regenerated_text = self._generate_batch(
            lease=lease,
            task=task,
            batch_number=2,
            checkpoint=checkpoint,
            model_calls=model_calls,
        )
        regenerated_work = self._evaluate_batch(
            lease=lease,
            task=task,
            batch=regenerated,
            texts=regenerated_text,
            checkpoint=checkpoint,
            model_calls=model_calls,
        )
        evaluations.extend(item.evaluation for item in regenerated_work)
        selected = _best_complete(regenerated_work) or min(
            regenerated_work, key=lambda item: item.initial.ordinal
        )
        resolution = _resolution(task, regenerated, selected)
        return _output(
            task,
            (initial_batch, regenerated),
            revisions,
            evaluations,
            resolution,
            model_calls,
            selected.text,
        )

    def _generate_batch(
        self,
        *,
        lease: WorkerLease,
        task: ReviewExecutionTask,
        batch_number: int,
        checkpoint: ExecutionCheckpoint,
        model_calls: list[SyntheticExecutionResult],
    ) -> tuple[GenerationBatch, dict[UUID, str]]:
        kind = GenerationBatchKind.INITIAL if batch_number == 1 else GenerationBatchKind.REGENERATED
        scenario = "; ".join((task.case.persona, task.case.use_case, task.case.subject))
        if batch_number == 2:
            scenario += "; previous batch exhausted two frozen revision rounds; produce distinct options"
        structured_input = {
            **_common_input(task),
            "scenario_mode": task.case.mode.value,
            "guided_idea": task.case.creative_reference or "",
            "channel": task.case.channel,
            "scenario": scenario,
            "style_profile": task.style_profile_summary,
            "approved_facts": [item.summary for item in task.evidence if item.fact_id is not None],
        }
        result = self._call(
            lease=lease,
            task=task,
            kind=ProgramKind.GENERATION,
            structured_input=structured_input,
            step_key=f"generation:batch:{batch_number}",
            checkpoint=checkpoint,
        )
        model_calls.append(result)
        candidates_output = _mapping_items(result.output.get("candidates"), "generation candidates")
        batch_id = _id(lease, f"batch:{task.case.id}:{batch_number}")
        candidates: list[GeneratedCandidate] = []
        texts: dict[UUID, str] = {}
        for ordinal, item in enumerate(candidates_output, start=1):
            text = _string(item.get("text"), "Candidate text")
            output_hash = canonical_hash(text)
            candidate_id = _id(lease, f"candidate:{batch_number}:{ordinal}:{output_hash}")
            candidate = GeneratedCandidate(
                id=candidate_id,
                project_id=task.project_id,
                review_run_id=task.review_run_id,
                review_case_id=task.case.id,
                generation_batch_id=batch_id,
                batch_number=batch_number,
                ordinal=ordinal,
                output_hash=output_hash,
                artifact_hash=canonical_hash(
                    {**_call_identity(result), "ordinal": ordinal, "output": item}
                ),
            )
            candidates.append(candidate)
            texts[candidate.id] = text
        batch = GenerationBatch(
            id=batch_id,
            project_id=task.project_id,
            review_run_id=task.review_run_id,
            review_case_id=task.case.id,
            batch_number=batch_number,
            kind=kind,
            scenario_mode=task.case.mode,
            creative_reference=task.case.creative_reference,
            call_lineage=_lineage(task, result, ProgramKind.GENERATION),
            candidates=tuple(candidates),
        )
        return batch, texts

    def _evaluate_batch(
        self,
        *,
        lease: WorkerLease,
        task: ReviewExecutionTask,
        batch: GenerationBatch,
        texts: Mapping[UUID, str],
        checkpoint: ExecutionCheckpoint,
        model_calls: list[SyntheticExecutionResult],
    ) -> tuple[_CandidateWork, ...]:
        return tuple(
            _CandidateWork(
                initial=candidate,
                current=candidate,
                text=texts[candidate.id],
                evaluation=self._evaluate(
                    lease=lease,
                    task=task,
                    batch=batch,
                    candidate=candidate,
                    text=texts[candidate.id],
                    label=f"b{batch.batch_number}:c{candidate.ordinal}",
                    checkpoint=checkpoint,
                    model_calls=model_calls,
                ),
            )
            for candidate in batch.candidates
        )

    def _revise(
        self,
        *,
        lease: WorkerLease,
        task: ReviewExecutionTask,
        batch: GenerationBatch,
        work: _CandidateWork,
        round_number: int,
        checkpoint: ExecutionCheckpoint,
        model_calls: list[SyntheticExecutionResult],
    ) -> _CandidateWork:
        issues = work.evaluation.correctable_issue_codes
        if not issues:
            raise SyntheticExecutionError("revision-required Candidate has no frozen issue codes")
        structured_input = {
            **_common_input(task),
            "candidate_text": work.text,
            "issue_codes": list(issues),
            "scenario_mode": task.case.mode.value,
            "guided_idea": task.case.creative_reference or "",
        }
        result = self._call(
            lease=lease,
            task=task,
            kind=ProgramKind.REVISION,
            structured_input=structured_input,
            step_key=f"revision:c{work.initial.ordinal}:r{round_number}:{work.current.output_hash}",
            checkpoint=checkpoint,
        )
        model_calls.append(result)
        text = _string(result.output.get("revised_text"), "revised Candidate text")
        revision_id = _id(lease, f"revision:{work.initial.id}:{round_number}")
        revised_id = _id(lease, f"revised-candidate:{revision_id}:{canonical_hash(text)}")
        revised = RevisedCandidate(
            id=revised_id,
            project_id=task.project_id,
            review_run_id=task.review_run_id,
            review_case_id=task.case.id,
            generation_batch_id=batch.id,
            batch_number=1,
            revision_id=revision_id,
            revision_round=round_number,
            parent_candidate_id=work.current.id,
            parent_output_hash=work.current.output_hash,
            output_hash=canonical_hash(text),
            artifact_hash=canonical_hash(result.output),
        )
        revision = CandidateRevision(
            id=revision_id,
            project_id=task.project_id,
            review_run_id=task.review_run_id,
            review_case_id=task.case.id,
            generation_batch_id=batch.id,
            round_number=round_number,
            parent_candidate_id=work.current.id,
            parent_output_hash=work.current.output_hash,
            issue_codes=issues,
            issue_set_hash=revision_issue_set_hash(issues),
            call_lineage=_lineage(task, result, ProgramKind.REVISION),
            revised_candidate=revised,
        )
        evaluation = self._evaluate(
            lease=lease,
            task=task,
            batch=batch,
            candidate=revised,
            text=text,
            label=f"c{work.initial.ordinal}:r{round_number}",
            checkpoint=checkpoint,
            model_calls=model_calls,
        )
        return _CandidateWork(
            initial=work.initial,
            current=revised,
            text=text,
            evaluation=evaluation,
            revisions=(*work.revisions, revision),
        )

    def _evaluate(
        self,
        *,
        lease: WorkerLease,
        task: ReviewExecutionTask,
        batch: GenerationBatch,
        candidate: GeneratedCandidate | RevisedCandidate,
        text: str,
        label: str,
        checkpoint: ExecutionCheckpoint,
        model_calls: list[SyntheticExecutionResult],
    ) -> CandidateEvaluation:
        common = _common_input(task)
        claims = self._call(
            lease=lease,
            task=task,
            kind=ProgramKind.CLAIM_EXTRACTION,
            structured_input={**common, "candidate_text": text},
            step_key=f"evaluate:{label}:claims:{candidate.output_hash}",
            checkpoint=checkpoint,
        )
        claim_values = _mapping_items(claims.output.get("claims"), "extracted claims")
        conflict = self._call(
            lease=lease,
            task=task,
            kind=ProgramKind.CONFLICT_CHECK,
            structured_input={**common, "claims": _conflict_check_claims(claim_values)},
            step_key=f"evaluate:{label}:conflicts:{candidate.output_hash}",
            checkpoint=checkpoint,
        )
        style = self._call(
            lease=lease,
            task=task,
            kind=ProgramKind.STYLE_JUDGE,
            structured_input={
                **common,
                "candidate_text": text,
                "style_profile": task.style_profile_summary,
                "pass_threshold": task.style_pass_threshold,
            },
            step_key=f"evaluate:{label}:style:{candidate.output_hash}",
            checkpoint=checkpoint,
        )
        conflict_issues = _conflict_issue_codes(conflict.output)
        style_issues = _string_tuple(style.output.get("issue_codes"), "style issue codes")
        conflict_disposition = "revise" if conflict.output.get("requires_revision") is True else "pass"
        style_disposition = "pass" if style.output.get("passed") is True else "revise"
        arbiter = self._call(
            lease=lease,
            task=task,
            kind=ProgramKind.ARBITER,
            structured_input={
                **common,
                "candidate_ids": [str(candidate.id)],
                "evaluator_results": [
                    {
                        "candidate_id": str(candidate.id),
                        "evaluator": "conflict_check",
                        "disposition": conflict_disposition,
                        "issue_codes": list(conflict_issues),
                        "evidence_refs": _evidence_refs(conflict.output),
                    },
                    {
                        "candidate_id": str(candidate.id),
                        "evaluator": "style_judge",
                        "disposition": style_disposition,
                        "issue_codes": list(style_issues),
                        "evidence_refs": _evidence_refs(style.output),
                    },
                ],
            },
            step_key=f"evaluate:{label}:arbiter:{candidate.output_hash}",
            checkpoint=checkpoint,
        )
        model_calls.extend((claims, conflict, style, arbiter))
        disposition = _string(arbiter.output.get("disposition"), "arbiter disposition")
        hard_revision = conflict_disposition == "revise" or style_disposition == "revise"
        if hard_revision and disposition != "revise":
            raise SyntheticExecutionError("arbiter attempted to bypass a hard revision requirement")
        arbiter_issues = _string_tuple(arbiter.output.get("issue_codes"), "arbiter issues")
        correctable = tuple(sorted(set((*conflict_issues, *style_issues, *arbiter_issues))))
        if disposition == "revise" and not correctable:
            correctable = ("arbiter_revision_required",)
        soft = arbiter_issues if disposition == "warning" else ()
        assessments = _claim_assessments(task, claim_values, conflict.output)
        score = style.output.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise SyntheticExecutionError("style score is not numeric")
        evaluator_hash = canonical_hash(
            [claims.response_hash, conflict.response_hash, style.response_hash, arbiter.response_hash]
        )
        return CandidateEvaluation(
            id=_id(lease, f"evaluation:{label}:{candidate.output_hash}"),
            project_id=task.project_id,
            review_run_id=task.review_run_id,
            review_case_id=task.case.id,
            generation_batch_id=batch.id,
            candidate_id=candidate.id,
            candidate_output_hash=candidate.output_hash,
            call_lineage=_lineage(task, arbiter, ProgramKind.ARBITER),
            evaluator_release="synthetic-prompt-evaluator-v1",
            evaluator_hash=evaluator_hash,
            evidence_artifact_hash=canonical_hash(
                {"claims": claims.output, "conflict": conflict.output, "style": style.output, "arbiter": arbiter.output}
            ),
            claim_assessments=assessments,
            style_score=float(score),
            style_passed=style.output.get("passed") is True,
            correctable_issue_codes=correctable if disposition == "revise" else (),
            soft_issue_codes=soft,
        )

    def _call(
        self,
        *,
        lease: WorkerLease,
        task: ReviewExecutionTask,
        kind: ProgramKind,
        structured_input: Mapping[str, object],
        step_key: str,
        checkpoint: ExecutionCheckpoint,
    ) -> SyntheticExecutionResult:
        checkpoint()
        spec = default_prompt_bootstrap_spec(kind)
        output_schema = spec.schemas.output_schema
        application_output_schema = spec.schemas.application_output_schema
        frozen = task.prompts[kind]
        validate_bootstrap_input(spec, structured_input)
        resolved = self._prompts.resolve(
            frozen=frozen,
            structured_input=structured_input,
            output_schema=output_schema,
            application_output_schema=application_output_schema,
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
            )
        )
        checkpoint()
        validate_bootstrap_output(spec, input_value=structured_input, output=result.output)
        if result.configured_model != frozen.configured_model:
            raise SyntheticExecutionError("model result changed the configured model")
        return result


def _best_complete(items: tuple[_CandidateWork, ...]) -> _CandidateWork | None:
    complete = tuple(
        item for item in items if item.evaluation.disposition is not EvaluationDisposition.REVISE
    )
    if not complete:
        return None
    rank = {EvaluationDisposition.PASS: 0, EvaluationDisposition.WARNING: 1}
    return min(complete, key=lambda item: (rank[item.evaluation.disposition], item.initial.ordinal))


def _resolution(
    task: ReviewExecutionTask,
    batch: GenerationBatch,
    work: _CandidateWork,
):
    decision = decide_next_step(batch, work.initial, work.revisions, work.evaluation)
    return resolution_from_decision(
        resolution_id=_id_from_values(task.job_id, f"resolution:{task.case.id}"),
        decision=decision,
        evaluation=work.evaluation,
        channel=task.case.channel,
        scenario_mode=task.case.mode,
    )


def _output(
    task,
    batches,
    revisions,
    evaluations,
    resolution,
    model_calls,
    resolved_candidate_text,
):
    return ReviewCaseRunOutput(
        project_id=task.project_id,
        review_run_id=task.review_run_id,
        review_case_id=task.case.id,
        batches=tuple(batches),
        revisions=tuple(revisions),
        evaluations=tuple(evaluations),
        resolution=resolution,
        model_call_ids=tuple(
            result.model_call_id
            for result in model_calls
            if isinstance(result, SyntheticModelResult)
        ),
        workflow_attempt_ids=tuple(
            result.workflow_attempt_id
            for result in model_calls
            if isinstance(result, SyntheticWorkflowResult)
        ),
        resolved_candidate_text=resolved_candidate_text,
    )


def _call_identity(result: SyntheticExecutionResult) -> dict[str, UUID]:
    if isinstance(result, SyntheticModelResult):
        return {"model_call_id": result.model_call_id}
    return {"workflow_attempt_id": result.workflow_attempt_id}


def _id(lease: WorkerLease, name: str) -> UUID:
    return _id_from_values(lease.job_id, name)


def _id_from_values(namespace: UUID, name: str) -> UUID:
    return uuid5(namespace, name)


__all__ = ["ReviewCaseExecutor"]
