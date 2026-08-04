"""Canonical input material for immutable Synthetic execution tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from geo_core.synthetic_lab.application_support import canonical_hash

if TYPE_CHECKING:
    from geo_core.synthetic_lab.execution_contracts import (
        CorpusFinalizeTask,
        DirectGenerationTask,
        OfflineExperimentRunTask,
        ReviewCaseRunTask,
        StyleProfileBuildTask,
    )


def style_task_value(task: StyleProfileBuildTask) -> dict[str, object]:
    return {
        "project_id": task.project_id,
        "job_id": task.job_id,
        "requested_by": task.requested_by,
        "profile_version_id": task.profile_version_id,
        "profile_id": task.profile_id,
        "version_number": task.version_number,
        "channel": task.channel,
        "locale": task.locale,
        "corpus_hash": task.corpus_hash,
        "approved_sample_count": task.approved_sample_count,
        "sample_manifest_hash": task.sample_manifest_hash,
        "evidence": task.sample_style_evidence,
        "runtime": task.runtime_inputs,
        "prompt": task.prompt.identity_hash,
    }


def review_task_value(task: ReviewCaseRunTask) -> dict[str, object]:
    return {
        "project_id": task.project_id,
        "job_id": task.job_id,
        "requested_by": task.requested_by,
        "review_run_id": task.review_run_id,
        "review_suite_hash": task.review_suite_hash,
        "case": task.case,
        "subject_id": task.subject_id,
        "evidence": task.evidence,
        "style_profile_summary": task.style_profile_summary,
        "style_pass_threshold": task.style_pass_threshold,
        "runtime": task.runtime_inputs,
        "prompts": {kind.value: ref.identity_hash for kind, ref in task.prompts.items()},
    }


def direct_task_value(task: DirectGenerationTask) -> dict[str, object]:
    return {
        "project_id": task.project_id,
        "job_id": task.job_id,
        "requested_by": task.requested_by,
        "review_run_id": task.review_run_id,
        "case": task.case,
        "subject_id": task.subject_id,
        "evidence": task.evidence,
        "knowledge_snapshot": task.knowledge_snapshot,
        "channel_style": task.channel_style,
        "style_profile_summary": task.style_profile_summary,
        "style_pass_threshold": task.style_pass_threshold,
        "runtime": task.runtime_inputs,
        "prompts": {kind.value: ref.identity_hash for kind, ref in task.prompts.items()},
    }


def corpus_task_value(task: CorpusFinalizeTask) -> dict[str, object]:
    return {
        "project_id": task.project_id,
        "job_id": task.job_id,
        "requested_by": task.requested_by,
        "corpus_version_id": task.corpus_version_id,
        "corpus_id": task.corpus_id,
        "version_number": task.version_number,
        "role": task.role.value,
        "candidates": task.candidates,
        "candidate_text_hashes": {
            str(key): canonical_hash(value) for key, value in task.candidate_text.items()
        },
        "source_review_job_ids": task.source_review_job_ids,
        "source_corpus_job_id": task.source_corpus_job_id,
        "runtime": task.runtime_inputs,
    }


def offline_task_value(task: OfflineExperimentRunTask) -> dict[str, object]:
    value: dict[str, object] = {
        "project_id": task.project_id,
        "job_id": task.job_id,
        "requested_by": task.requested_by,
        "result_id": task.result_id,
        "plan_input_hash": task.plan.input_hash,
        "question_text_hashes": {
            str(key): canonical_hash(value) for key, value in task.question_text.items()
        },
        "corpus_context_hashes": {
            str(key): canonical_hash(value) for key, value in task.corpus_context.items()
        },
        "runtime": task.runtime_inputs,
        "prompt": task.prompt.identity_hash,
    }
    if task.question_corpus_context:
        value["question_corpus_context_hashes"] = {
            f"{corpus_id}:{question_id}": canonical_hash(context)
            for (corpus_id, question_id), context in task.question_corpus_context.items()
        }
    return value


__all__ = [
    "corpus_task_value",
    "direct_task_value",
    "offline_task_value",
    "review_task_value",
    "style_task_value",
]
