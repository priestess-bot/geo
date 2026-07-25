"""Pure frozen-material helpers shared by Synthetic execution admission paths."""

from __future__ import annotations

import json
from typing import Any

from geo_core.prompts.application_models import RuntimePromptProgram
from geo_core.synthetic_lab.corpus import (
    CorpusCandidateEntry,
    candidate_entry_from_resolution,
)
from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.execution_contracts import (
    CorpusFinalizeOutput,
    FrozenPromptRef,
    ReviewCaseRunOutput,
    ReviewCaseRunTask,
)
from geo_core.synthetic_lab.ports import RuntimeInputSnapshot


def _same_runtime(values: tuple[RuntimeInputSnapshot, ...]) -> RuntimeInputSnapshot:
    if not values or any(value != values[0] for value in values[1:]):
        raise SyntheticLabContractError(
            "Corpus Review Jobs do not share exact frozen runtime inputs"
        )
    return values[0]


def _resolved_candidate_text(output: ReviewCaseRunOutput) -> str:
    if output.resolved_candidate_text is None:
        raise SyntheticLabContractError(
            "Review Job predates governed Candidate text lineage; rerun the Case"
        )
    return output.resolved_candidate_text


def _corpus_entry(task: ReviewCaseRunTask, output: ReviewCaseRunOutput) -> CorpusCandidateEntry:
    resolution = output.resolution
    if not resolution.offline_experiment_eligible:
        raise SyntheticLabContractError("failed Review Candidate cannot enter a Corpus")
    generation_batch_id = next(
        (
            batch.id
            for batch in output.batches
            if any(candidate.id == resolution.candidate_id for candidate in batch.candidates)
        ),
        None,
    )
    if generation_batch_id is None:
        generation_batch_id = next(
            (
                revision.generation_batch_id
                for revision in output.revisions
                if revision.revised_candidate.id == resolution.candidate_id
            ),
            None,
        )
    batch = next(
        (item for item in output.batches if item.id == generation_batch_id),
        None,
    )
    if batch is None:
        raise SyntheticLabContractError("resolved Candidate generation lineage is incomplete")
    _resolved_candidate_text(output)
    lineage = batch.call_lineage
    return candidate_entry_from_resolution(
        resolution,
        competitor_scenario=task.case.competitor_scenario,
        model_key=f"{lineage.provider}:{lineage.configured_model}",
        model_identity_hash=lineage.model_identity_hash,
        question_cluster_key=task.case.case_key,
    )


def _retrieved_corpus_context(
    output: CorpusFinalizeOutput,
    question_cluster_key: str,
) -> str:
    ordered = sorted(
        output.corpus.candidates,
        key=lambda item: (
            item.question_cluster_key != question_cluster_key,
            str(item.candidate_id),
        ),
    )
    chunks: list[str] = []
    size = 0
    for item in ordered:
        header = json.dumps(
            {
                "candidate_id": str(item.candidate_id),
                "candidate_output_hash": item.candidate_output_hash,
                "question_cluster_key": item.question_cluster_key,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        chunk = f"{header}\n{output.candidate_text[item.candidate_id]}"
        added = len(chunk) + (5 if chunks else 0)
        if chunks and size + added > 95_000:
            break
        if added > 95_000:
            raise SyntheticLabContractError(
                "one Corpus Candidate exceeds the Offline Experiment context limit"
            )
        chunks.append(chunk)
        size += added
    if not chunks:
        raise SyntheticLabContractError("Corpus produced no retrievable Candidate context")
    return "\n\n---\n\n".join(chunks)


def _frozen_prompt(runtime: RuntimePromptProgram, selection: Any) -> FrozenPromptRef:
    release, state, binding = runtime.release, runtime.state, runtime.binding
    return FrozenPromptRef(
        project_id=release.project_id,
        binding_id=binding.id,
        binding_version=binding.binding_version,
        frozen_state_id=state.id,
        frozen_state_version=state.version,
        release_id=release.id,
        release_version=release.version,
        release_hash=release.release_hash,
        program_kind=release.program_kind,
        purpose=release.purpose,
        route=selection.route,
        configured_model=selection.configured_model,
        runtime_manifest_id=selection.runtime_manifest_id,
        runtime_manifest_hash=selection.runtime_manifest_hash,
        runtime_option_id=selection.runtime_option_id,
        runtime_option_hash=selection.runtime_option_hash,
        model_policy=selection.policy,
        model_policy_hash=release.model_policy.policy_hash,
    )


__all__ = [
    "_corpus_entry",
    "_frozen_prompt",
    "_resolved_candidate_text",
    "_retrieved_corpus_context",
    "_same_runtime",
]
