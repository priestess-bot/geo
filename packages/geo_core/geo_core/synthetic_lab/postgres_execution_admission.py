"""Server-resolved admission for executable Synthetic Lab tasks."""

from __future__ import annotations

from typing import Any
from uuid import UUID


from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.corpus import (
    CorpusRole,
)
from geo_core.synthetic_lab.domain import (
    StyleProfileStatus,
    SyntheticLabContractError,
    style_sample_manifest_hash,
)
from geo_core.synthetic_lab.execution_application import SyntheticExecutionApplication
from geo_core.synthetic_lab.execution_contracts import (
    CorpusFinalizeOutput,
    CorpusFinalizeTask,
    FrozenEvidence,
    ReviewCaseRunOutput,
    ReviewCaseRunTask,
    StyleProfileBuildTask,
)
from geo_core.synthetic_lab.execution_gateway import PromptProgramExecutionResolver
from geo_core.synthetic_lab.execution_admission_support import (
    _corpus_entry,
    _resolved_candidate_text,
    _same_runtime,
)
from geo_core.synthetic_lab.ports import (
    CommandReceipt,
    LabPrincipal,
    RuntimeInputSnapshot,
    SyntheticLabIdempotencyConflict,
    SyntheticLabPersistenceError,
    SyntheticJob,
)
from geo_core.synthetic_lab.postgres_api_reads import PostgresSyntheticApiReads
from geo_core.synthetic_lab.postgres_api_support import stable_id
from geo_core.synthetic_lab.postgres_execution_admission_tail import (
    _PostgresSyntheticExecutionAdmissionTail,
)
from geo_core.synthetic_lab.postgres_execution_runtime import (
    PostgresRuntimePromptApplication,
    PostgresSyntheticRuntimeInputPort,
)
from geo_core.synthetic_lab.postgres_manual_import import PostgresManualImportService
from geo_core.synthetic_lab.postgres_uow import PostgresSyntheticLabUnitOfWorkFactory
from geo_core.synthetic_lab.review_cases import ReviewSuiteStatus


_REVIEW_PROMPTS = (
    ProgramKind.GENERATION,
    ProgramKind.CLAIM_EXTRACTION,
    ProgramKind.CONFLICT_CHECK,
    ProgramKind.REVISION,
    ProgramKind.STYLE_JUDGE,
    ProgramKind.ARBITER,
)


class PostgresSyntheticExecutionAdmission(_PostgresSyntheticExecutionAdmissionTail):
    """Freeze selectors into typed tasks before the Durable Job transaction commits."""

    def __init__(
        self,
        database_url: str,
        *,
        connection_factory: Any,
        uow_factory: PostgresSyntheticLabUnitOfWorkFactory,
        reads: PostgresSyntheticApiReads,
        manual_imports: PostgresManualImportService | None,
    ) -> None:
        self._database_url = database_url
        self._connect = connection_factory
        self._reads = reads
        self._manual_imports = manual_imports
        self._application = SyntheticExecutionApplication(uow_factory)
        self._runtime_inputs = PostgresSyntheticRuntimeInputPort(connection_factory)
        self._prompt_application = PostgresRuntimePromptApplication(connection_factory)
        self._prompt_resolver = PromptProgramExecutionResolver(self._prompt_application)
        self._runtime_catalog = PostgresRuntimeCatalog(database_url)

    def enqueue_profile_build(
        self,
        *,
        principal: LabPrincipal,
        profile_version_id: UUID,
        fact_snapshot_id: UUID,
        approved_sample_ids: tuple[UUID, ...],
        runtime_selection_id: UUID,
        recovery_of_attempt_id: UUID | None = None,
        dify_reconciliation_token: str | None = None,
        idempotency_key: str,
    ) -> CommandReceipt | SyntheticJob:
        project_id = principal.project_id
        job_id = stable_id(project_id, idempotency_key, "style-profile-build-job")
        existing = self._reads.execution_task_or_none(project_id, job_id)
        if existing is not None:
            if not isinstance(existing, StyleProfileBuildTask) or (
                existing.profile_version_id != profile_version_id
                or existing.runtime_inputs.fact_snapshot_id != fact_snapshot_id
                or existing.prompt.runtime_option_id != runtime_selection_id
            ):
                raise SyntheticLabIdempotencyConflict(
                    "Style Profile build Idempotency-Key was reused"
                )
            return self._application.enqueue(
                principal=principal,
                task=existing,
                outbox_id=stable_id(
                    project_id, idempotency_key, "style-profile-build-outbox"
                ),
                runtime_inputs=self._runtime_inputs,
                prompts=self._prompt_resolver,
                idempotency_key=idempotency_key,
                recovery_of_attempt_id=recovery_of_attempt_id,
                dify_reconciliation_token=dify_reconciliation_token,
            )

        profile = self._profile(project_id, profile_version_id)
        if profile.status is not StyleProfileStatus.DRAFT:
            raise SyntheticLabContractError("only a draft Style Profile can be built")
        approved_sample_ids = self._reads.profile_sample_ids(
            project_id,
            profile_version_id=profile.id,
            corpus_hash=profile.corpus_hash,
            legacy_sample_ids=approved_sample_ids,
        )
        samples = self._reads.approved_style_samples(
            project_id,
            channel=profile.channel,
            sample_ids=approved_sample_ids,
        )
        if (
            len(samples) != profile.approved_sample_count
            or style_sample_manifest_hash(samples) != profile.corpus_hash
        ):
            raise SyntheticLabContractError(
                "Style Profile build samples differ from the draft manifest"
            )
        if self._manual_imports is None:
            raise SyntheticLabPersistenceError(
                "Style Profile example decryption or object storage is unavailable"
            )
        examples = self._manual_imports.load_profile_examples(
            project_id=project_id,
            sample_ids=approved_sample_ids,
        )
        prompt = self._prompt(
            project_id=project_id,
            kind=ProgramKind.STYLE_PROFILE,
            runtime_selection_id=runtime_selection_id,
        )
        if (
            prompt.release_id != profile.prompt_release_id
            or prompt.release_hash != profile.prompt_release_hash
        ):
            raise SyntheticLabContractError(
                "Style Profile draft no longer matches the current frozen Prompt binding"
            )
        fact_hash, _subject_id = self._fact_snapshot(project_id, fact_snapshot_id)
        runtime = RuntimeInputSnapshot(
            project_id=project_id,
            fact_snapshot_id=fact_snapshot_id,
            fact_snapshot_hash=fact_hash,
            profile_version_id=profile.id,
            profile_hash=profile.profile_hash,
            prompt_release_id=prompt.release_id,
            prompt_release_hash=prompt.release_hash,
            facts_current_approved=True,
            profile_frozen=False,
            prompt_frozen=True,
        )
        task = StyleProfileBuildTask(
            project_id=project_id,
            job_id=job_id,
            model_job_version=1,
            requested_by=principal.actor_id,
            profile_version_id=profile.id,
            profile_id=profile.profile_id,
            version_number=profile.version_number,
            channel=profile.channel,
            locale=profile.locale,
            corpus_hash=profile.corpus_hash,
            approved_sample_count=profile.approved_sample_count,
            sample_manifest_hash=profile.corpus_hash,
            sample_style_evidence=tuple(
                FrozenEvidence(
                    ref=f"sample:{sample_id}",
                    subject_id=f"style:{profile.channel}",
                    summary=text,
                )
                for sample_id, text in examples
            ),
            runtime_inputs=runtime,
            prompt=prompt,
        )
        return self._application.enqueue(
            principal=principal,
            task=task,
            outbox_id=stable_id(project_id, idempotency_key, "style-profile-build-outbox"),
            runtime_inputs=self._runtime_inputs,
            prompts=self._prompt_resolver,
            idempotency_key=idempotency_key,
            recovery_of_attempt_id=recovery_of_attempt_id,
            dify_reconciliation_token=dify_reconciliation_token,
        )

    def enqueue_review_case(
        self,
        *,
        principal: LabPrincipal,
        suite_version_id: UUID,
        case_id: UUID,
        runtime_selection_id: UUID,
        style_pass_threshold: float,
        idempotency_key: str,
    ) -> CommandReceipt | SyntheticJob:
        project_id = principal.project_id
        job_id = stable_id(project_id, idempotency_key, "review-case-run-job")
        existing = self._reads.execution_task_or_none(project_id, job_id)
        if existing is not None:
            if not isinstance(existing, ReviewCaseRunTask) or (
                existing.case.id != case_id
                or existing.case.review_suite_version_id != suite_version_id
                or existing.style_pass_threshold != style_pass_threshold
                or any(
                    prompt.runtime_option_id != runtime_selection_id
                    for prompt in existing.prompts.values()
                )
            ):
                raise SyntheticLabIdempotencyConflict("Review Case run Idempotency-Key was reused")
            return self._reads.job(project_id, job_id)

        suite = self._suite(project_id, suite_version_id)
        if suite.status is not ReviewSuiteStatus.FROZEN:
            raise SyntheticLabContractError("Review Case execution requires a frozen Suite")
        case = self._case(project_id, case_id)
        if case.review_suite_version_id != suite.id or case.channel != suite.channel:
            raise SyntheticLabContractError("Review Case is outside the selected frozen Suite")
        profile = self._profile(project_id, case.profile_version_id)
        if (
            profile.status is not StyleProfileStatus.FROZEN
            or profile.profile_hash != case.profile_hash
        ):
            raise SyntheticLabContractError("Review Case Style Profile is stale or not frozen")
        build = self._reads.profile_build_output(
            project_id,
            profile_version_id=profile.id,
            profile_hash=profile.profile_hash,
        )
        if build is None or not build.profile_summary:
            raise SyntheticLabContractError(
                "Review Case requires a completed governed Style Profile build"
            )
        fact_hash, subject_id = self._fact_snapshot(project_id, case.fact_snapshot_id)
        if fact_hash != case.fact_snapshot_hash:
            raise SyntheticLabContractError("Review Case Fact snapshot changed")
        evidence = self._review_evidence(
            project_id=project_id,
            fact_snapshot_id=case.fact_snapshot_id,
            primary_subject_id=subject_id,
        )
        prompts = {
            kind: self._prompt(
                project_id=project_id,
                kind=kind,
                runtime_selection_id=runtime_selection_id,
            )
            for kind in _REVIEW_PROMPTS
        }
        primary = prompts[ProgramKind.GENERATION]
        runtime = RuntimeInputSnapshot(
            project_id=project_id,
            fact_snapshot_id=case.fact_snapshot_id,
            fact_snapshot_hash=case.fact_snapshot_hash,
            profile_version_id=profile.id,
            profile_hash=profile.profile_hash,
            prompt_release_id=primary.release_id,
            prompt_release_hash=primary.release_hash,
            facts_current_approved=True,
            profile_frozen=True,
            prompt_frozen=True,
        )
        task = ReviewCaseRunTask(
            project_id=project_id,
            job_id=job_id,
            model_job_version=1,
            requested_by=principal.actor_id,
            review_run_id=stable_id(project_id, idempotency_key, "review-case-run"),
            review_suite_hash=suite.case_set_hash,
            case=case,
            subject_id=subject_id,
            evidence=evidence,
            style_profile_summary=build.profile_summary,
            style_pass_threshold=style_pass_threshold,
            runtime_inputs=runtime,
            prompts=prompts,
        )
        return self._application.enqueue(
            principal=principal,
            task=task,
            outbox_id=stable_id(project_id, idempotency_key, "review-case-run-outbox"),
            runtime_inputs=self._runtime_inputs,
            prompts=self._prompt_resolver,
            idempotency_key=idempotency_key,
        )

    def enqueue_corpus_finalize(
        self,
        *,
        principal: LabPrincipal,
        role: CorpusRole,
        review_job_ids: tuple[UUID, ...],
        source_corpus_job_id: UUID | None,
        idempotency_key: str,
    ) -> CommandReceipt | SyntheticJob:
        project_id = principal.project_id
        normalized_role = CorpusRole(role)
        normalized_review_jobs = tuple(sorted(set(review_job_ids), key=str))
        job_id = stable_id(project_id, idempotency_key, "corpus-finalize-job")
        existing = self._reads.execution_task_or_none(project_id, job_id)
        if existing is not None:
            if not isinstance(existing, CorpusFinalizeTask) or (
                existing.role is not normalized_role
                or existing.source_review_job_ids != normalized_review_jobs
                or existing.source_corpus_job_id != source_corpus_job_id
            ):
                raise SyntheticLabIdempotencyConflict(
                    "Corpus finalization Idempotency-Key was reused"
                )
            return self._reads.job(project_id, job_id)

        if normalized_role is CorpusRole.NEW_CANDIDATE:
            if not normalized_review_jobs or source_corpus_job_id is not None:
                raise SyntheticLabContractError(
                    "candidate Corpus requires completed Review Job selectors"
                )
            sources = tuple(
                self._reads.completed_execution(project_id, source_job_id)
                for source_job_id in normalized_review_jobs
            )
            if any(
                not isinstance(task, ReviewCaseRunTask)
                or not isinstance(output, ReviewCaseRunOutput)
                for task, output in sources
            ):
                raise SyntheticLabContractError(
                    "candidate Corpus accepts only completed Review Case Jobs"
                )
            review_sources = tuple(
                (task, output)
                for task, output in sources
                if isinstance(task, ReviewCaseRunTask) and isinstance(output, ReviewCaseRunOutput)
            )
            runtime = _same_runtime(tuple(task.runtime_inputs for task, _ in review_sources))
            candidates = tuple(_corpus_entry(task, output) for task, output in review_sources)
            if len({item.candidate_output_hash for item in candidates}) != len(candidates):
                raise SyntheticLabContractError(
                    "candidate Corpus Review Jobs resolve duplicate Candidate outputs"
                )
            texts = {
                output.resolution.candidate_id: _resolved_candidate_text(output)
                for _, output in review_sources
            }
            corpus_id = stable_id(project_id, idempotency_key, "corpus-identity")
            version_number = 1
        elif normalized_role is CorpusRole.CURRENT_APPROVED:
            if normalized_review_jobs or source_corpus_job_id is None:
                raise SyntheticLabContractError(
                    "approved Corpus requires one candidate Corpus selector"
                )
            source_task, source_output = self._reads.completed_execution(
                project_id, source_corpus_job_id
            )
            if (
                not isinstance(source_task, CorpusFinalizeTask)
                or not isinstance(source_output, CorpusFinalizeOutput)
                or source_output.corpus.role is not CorpusRole.NEW_CANDIDATE
            ):
                raise SyntheticLabContractError(
                    "approved Corpus source must be a completed candidate Corpus"
                )
            if source_task.requested_by == principal.actor_id:
                raise SyntheticLabContractError(
                    "Corpus maker cannot approve the same candidate Corpus"
                )
            runtime = source_task.runtime_inputs
            candidates = source_output.corpus.candidates
            texts = dict(source_output.candidate_text)
            corpus_id = source_output.corpus.corpus_id
            version_number = source_output.corpus.version_number + 1
        else:
            raise SyntheticLabContractError(
                "no-corpus baseline is created only with an Offline Experiment"
            )

        task = CorpusFinalizeTask(
            project_id=project_id,
            job_id=job_id,
            model_job_version=1,
            requested_by=principal.actor_id,
            corpus_version_id=stable_id(project_id, idempotency_key, "corpus-version"),
            corpus_id=corpus_id,
            version_number=version_number,
            role=normalized_role,
            candidates=candidates,
            candidate_text=texts,
            source_review_job_ids=normalized_review_jobs,
            source_corpus_job_id=source_corpus_job_id,
            runtime_inputs=runtime,
        )
        return self._application.enqueue(
            principal=principal,
            task=task,
            outbox_id=stable_id(project_id, idempotency_key, "corpus-finalize-outbox"),
            runtime_inputs=self._runtime_inputs,
            prompts=self._prompt_resolver,
            idempotency_key=idempotency_key,
        )


__all__ = ["PostgresSyntheticExecutionAdmission"]
