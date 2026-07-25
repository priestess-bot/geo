"""Server-resolved admission for executable Synthetic Lab tasks."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

import psycopg

from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelRouteError
from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.placements.execution_eligibility import approved_fact_evidence_is_current
from geo_core.prompts.bootstrap_templates import bootstrap_template
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.corpus import (
    CorpusRole,
    create_no_corpus_baseline,
)
from geo_core.synthetic_lab.domain import (
    StyleProfileVersion,
    SyntheticLabContractError,
)
from geo_core.synthetic_lab.execution_application import SyntheticExecutionApplication
from geo_core.synthetic_lab.execution_contracts import (
    CorpusFinalizeOutput,
    FrozenEvidence,
    FrozenPromptRef,
    OfflineExperimentRunTask,
)
from geo_core.synthetic_lab.execution_gateway import PromptProgramExecutionResolver
from geo_core.synthetic_lab.execution_admission_support import (
    _frozen_prompt,
    _retrieved_corpus_context,
)
from geo_core.synthetic_lab.ports import (
    CommandReceipt,
    LabPrincipal,
    RuntimeInputSnapshot,
    SyntheticLabIdempotencyConflict,
    SyntheticLabNotFound,
    SyntheticJob,
)
from geo_core.synthetic_lab.postgres_api_reads import PostgresSyntheticApiReads
from geo_core.synthetic_lab.postgres_api_support import stable_id
from geo_core.synthetic_lab.postgres_execution_runtime import (
    PostgresRuntimePromptApplication,
    PostgresSyntheticRuntimeInputPort,
)
from geo_core.synthetic_lab.postgres_manual_import import PostgresManualImportService
from geo_core.synthetic_lab.offline_experiment import (
    FrozenExperimentQuestion,
    create_offline_experiment_plan,
)
from geo_core.synthetic_lab.review_cases import ReviewCase, ReviewSuite


_REVIEW_PROMPTS = (
    ProgramKind.GENERATION,
    ProgramKind.CLAIM_EXTRACTION,
    ProgramKind.CONFLICT_CHECK,
    ProgramKind.REVISION,
    ProgramKind.STYLE_JUDGE,
    ProgramKind.ARBITER,
)


class _PostgresSyntheticExecutionAdmissionTail:
    _database_url: str
    _connect: Any
    _reads: PostgresSyntheticApiReads
    _manual_imports: PostgresManualImportService | None
    _application: SyntheticExecutionApplication
    _runtime_inputs: PostgresSyntheticRuntimeInputPort
    _prompt_application: PostgresRuntimePromptApplication
    _prompt_resolver: PromptProgramExecutionResolver
    _runtime_catalog: PostgresRuntimeCatalog

    def enqueue_offline_experiment(
        self,
        *,
        principal: LabPrincipal,
        question_set_id: UUID,
        current_corpus_job_id: UUID,
        candidate_corpus_job_id: UUID,
        runtime_selection_id: UUID,
        minimum_valid_pair_ratio: float,
        idempotency_key: str,
    ) -> CommandReceipt | SyntheticJob:
        project_id = principal.project_id
        job_id = stable_id(project_id, idempotency_key, "offline-experiment-job")
        existing = self._reads.execution_task_or_none(project_id, job_id)
        if existing is not None:
            if not isinstance(existing, OfflineExperimentRunTask) or (
                existing.plan.question_set_id != question_set_id
                or existing.prompt.runtime_option_id != runtime_selection_id
                or existing.plan.minimum_valid_pair_ratio != minimum_valid_pair_ratio
                or {item.id for item in existing.plan.corpora}
                != {
                    stable_id(project_id, idempotency_key, "offline-baseline-corpus"),
                    self._corpus_output(project_id, current_corpus_job_id).corpus.id,
                    self._corpus_output(project_id, candidate_corpus_job_id).corpus.id,
                }
            ):
                raise SyntheticLabIdempotencyConflict(
                    "Offline Experiment Idempotency-Key was reused"
                )
            return self._reads.job(project_id, job_id)

        current = self._corpus_output(project_id, current_corpus_job_id)
        candidate = self._corpus_output(project_id, candidate_corpus_job_id)
        if current.corpus.role is not CorpusRole.CURRENT_APPROVED:
            raise SyntheticLabContractError("current Corpus selector is not approved")
        if candidate.corpus.role is not CorpusRole.NEW_CANDIDATE:
            raise SyntheticLabContractError("candidate Corpus selector has the wrong role")
        if (
            current.corpus.approved_fact_snapshot_id != candidate.corpus.approved_fact_snapshot_id
            or current.corpus.approved_fact_snapshot_hash
            != candidate.corpus.approved_fact_snapshot_hash
            or current.corpus.profile_version_id != candidate.corpus.profile_version_id
            or current.corpus.profile_hash != candidate.corpus.profile_hash
        ):
            raise SyntheticLabContractError(
                "Offline Experiment Corpora do not share frozen Fact/Profile inputs"
            )
        question_set_hash, questions, question_text = self._experiment_questions(
            project_id, question_set_id
        )
        prompt = self._prompt(
            project_id=project_id,
            kind=ProgramKind.OFFLINE_ANSWER,
            runtime_selection_id=runtime_selection_id,
        )
        experiment_id = stable_id(project_id, idempotency_key, "offline-experiment")
        baseline = create_no_corpus_baseline(
            id=stable_id(project_id, idempotency_key, "offline-baseline-corpus"),
            project_id=project_id,
            corpus_id=stable_id(project_id, idempotency_key, "offline-baseline-identity"),
            approved_fact_snapshot_id=current.corpus.approved_fact_snapshot_id,
            approved_fact_snapshot_hash=current.corpus.approved_fact_snapshot_hash,
            profile_version_id=current.corpus.profile_version_id,
            profile_hash=current.corpus.profile_hash,
            prompt_release_id=prompt.release_id,
            prompt_release_hash=prompt.release_hash,
            experiment_id=experiment_id,
        )
        protocol_hash = canonical_hash(
            {
                "release": "synthetic-offline-paired-three-arm-v1",
                "repetitions_per_question": 10,
                "minimum_valid_pair_ratio": minimum_valid_pair_ratio,
                "retrieval": "question-corpus-deterministic-v1",
            }
        )
        metric_method_release = "synthetic-offline-answer-metric-v1"
        metric_method_hash = canonical_hash({"release": metric_method_release, "range": [0, 1]})
        model_identity_hash = canonical_hash(
            {
                "provider": prompt.route.provider,
                "configured_model": prompt.configured_model,
                "model_release_id": prompt.route.model_release_id,
                "model_release_hash": prompt.route.model_release_hash,
            }
        )
        corpora = (baseline, current.corpus, candidate.corpus)
        plan = create_offline_experiment_plan(
            id=experiment_id,
            project_id=project_id,
            question_set_id=question_set_id,
            question_set_hash=question_set_hash,
            protocol_id=stable_id(project_id, "offline-protocol-v1", "protocol"),
            protocol_hash=protocol_hash,
            prompt_release_id=prompt.release_id,
            prompt_release_hash=prompt.release_hash,
            approved_fact_snapshot_id=current.corpus.approved_fact_snapshot_id,
            approved_fact_snapshot_hash=current.corpus.approved_fact_snapshot_hash,
            profile_version_id=current.corpus.profile_version_id,
            profile_hash=current.corpus.profile_hash,
            model_policy_hash=prompt.model_policy_hash,
            model_provider=prompt.route.provider,
            configured_model=prompt.configured_model,
            reported_model=prompt.configured_model,
            model_identity_hash=model_identity_hash,
            metric_method_release=metric_method_release,
            metric_method_hash=metric_method_hash,
            seed_namespace_hash=canonical_hash(
                {
                    "project_id": project_id,
                    "question_set_hash": question_set_hash,
                    "corpus_hashes": [item.content_hash for item in corpora],
                    "protocol_hash": protocol_hash,
                }
            ),
            questions=questions,
            corpora=corpora,
            minimum_valid_pair_ratio=minimum_valid_pair_ratio,
        )
        runtime = RuntimeInputSnapshot(
            project_id=project_id,
            fact_snapshot_id=current.corpus.approved_fact_snapshot_id,
            fact_snapshot_hash=current.corpus.approved_fact_snapshot_hash,
            profile_version_id=current.corpus.profile_version_id,
            profile_hash=current.corpus.profile_hash,
            prompt_release_id=prompt.release_id,
            prompt_release_hash=prompt.release_hash,
            facts_current_approved=True,
            profile_frozen=True,
            prompt_frozen=True,
        )
        outputs = {current.corpus.id: current, candidate.corpus.id: candidate}
        question_context = {
            (corpus.id, question.question_version_id): (
                "No synthetic Corpus content is supplied for this baseline arm."
                if corpus.role is CorpusRole.NO_CORPUS_BASELINE
                else _retrieved_corpus_context(outputs[corpus.id], question.question_cluster_key)
            )
            for corpus in corpora
            for question in questions
        }
        task = OfflineExperimentRunTask(
            project_id=project_id,
            job_id=job_id,
            model_job_version=1,
            requested_by=principal.actor_id,
            result_id=stable_id(project_id, idempotency_key, "offline-result"),
            plan=plan,
            question_text=question_text,
            corpus_context={
                baseline.id: "No synthetic Corpus content is supplied.",
                current.corpus.id: "Frozen current-approved Corpus; use per-Question context.",
                candidate.corpus.id: "Frozen candidate Corpus; use per-Question context.",
            },
            question_corpus_context=question_context,
            runtime_inputs=runtime,
            prompt=prompt,
        )
        return self._application.enqueue(
            principal=principal,
            task=task,
            outbox_id=stable_id(project_id, idempotency_key, "offline-experiment-outbox"),
            runtime_inputs=self._runtime_inputs,
            prompts=self._prompt_resolver,
            idempotency_key=idempotency_key,
        )

    def _corpus_output(self, project_id: UUID, job_id: UUID) -> CorpusFinalizeOutput:
        _task, output = self._reads.completed_execution(project_id, job_id)
        if not isinstance(output, CorpusFinalizeOutput):
            raise SyntheticLabContractError("selected Job did not produce a Corpus")
        return output

    def _experiment_questions(
        self, project_id: UUID, question_set_id: UUID
    ) -> tuple[str, tuple[FrozenExperimentQuestion, ...], dict[UUID, str]]:
        connection = self._open(project_id)
        try:
            question_set = connection.execute(
                """SELECT content_hash FROM knowledge_question_sets
                   WHERE project_id = %s AND id = %s AND status = 'frozen'
                     AND content_hash IS NOT NULL""",
                (project_id, question_set_id),
            ).fetchone()
            rows = connection.execute(
                """SELECT id, ordinal, query_text_snapshot, query_text_hash,
                          query_cluster_key
                   FROM knowledge_question_set_items
                   WHERE project_id = %s AND question_set_id = %s
                   ORDER BY ordinal""",
                (project_id, question_set_id),
            ).fetchall()
            if question_set is None or not rows:
                raise SyntheticLabNotFound("frozen Offline Experiment QuestionSet is unavailable")
        finally:
            connection.rollback()
            connection.close()
        if any(
            hashlib.sha256(row["query_text_snapshot"].encode("utf-8")).hexdigest()
            != row["query_text_hash"]
            for row in rows
        ):
            raise SyntheticLabContractError("Offline Experiment Question text hash changed")
        questions = tuple(
            FrozenExperimentQuestion(
                project_id=project_id,
                question_version_id=row["id"],
                ordinal=row["ordinal"],
                question_hash=row["query_text_hash"],
                question_cluster_key=row["query_cluster_key"],
            )
            for row in rows
        )
        return (
            question_set["content_hash"],
            questions,
            {row["id"]: row["query_text_snapshot"] for row in rows},
        )

    def _prompt(
        self,
        *,
        project_id: UUID,
        kind: ProgramKind,
        runtime_selection_id: UUID,
    ) -> FrozenPromptRef:
        purpose = bootstrap_template(kind).purpose
        try:
            runtime = self._prompt_application.resolve_runtime_binding(
                project_id=project_id,
                purpose=purpose,
            )
            selection = self._runtime_catalog.resolve_approved_runtime(
                project_id=project_id,
                runtime_selection_id=runtime_selection_id,
                required_purpose=purpose,
                search_mode=None,
            )
        except (RuntimeError, ModelRouteError, psycopg.Error) as error:
            raise SyntheticLabContractError(
                f"{kind.value} requires a current Prompt binding and approved model runtime"
            ) from error
        if selection.adapter_release.expected_capture_method != ModelCaptureMethod.PROVIDER_API:
            raise SyntheticLabContractError(
                "Synthetic Lab model execution requires a Provider API runtime"
            )
        return _frozen_prompt(runtime, selection)

    def _fact_snapshot(self, project_id: UUID, fact_snapshot_id: UUID) -> tuple[str, UUID]:
        connection = self._open(project_id)
        try:
            row = connection.execute(
                """SELECT attempt.pack_hash, brief.primary_brand_entity_id
                   FROM evidence_pack_attempts AS attempt
                   JOIN placement_brief_versions AS version
                     ON version.project_id = attempt.project_id
                    AND version.id = attempt.brief_version_id
                   JOIN placement_briefs AS brief
                     ON brief.project_id = version.project_id
                    AND brief.id = version.brief_id
                   WHERE attempt.project_id = %s AND attempt.id = %s
                     AND attempt.status = 'ready' AND attempt.pack_hash IS NOT NULL""",
                (project_id, fact_snapshot_id),
            ).fetchone()
            if row is None:
                raise SyntheticLabNotFound("ready Fact snapshot is unavailable")
            return row["pack_hash"], row["primary_brand_entity_id"]
        finally:
            connection.rollback()
            connection.close()

    def _review_evidence(
        self,
        *,
        project_id: UUID,
        fact_snapshot_id: UUID,
        primary_subject_id: UUID,
    ) -> tuple[FrozenEvidence, ...]:
        connection = self._open(project_id)
        try:
            rows = connection.execute(
                """SELECT evidence.id, evidence.item_type,
                          evidence.subject_entity_id, evidence.snapshot_text,
                          evidence.snapshot_hash, evidence.citation_label,
                          item.ordinal
                   FROM evidence_pack_items AS item
                   JOIN evidence_items AS evidence
                     ON evidence.project_id = item.project_id
                    AND evidence.id = item.evidence_item_id
                   WHERE item.project_id = %s AND item.pack_attempt_id = %s
                   ORDER BY item.ordinal
                   LIMIT 500""",
                (project_id, fact_snapshot_id),
            ).fetchall()
            ids = tuple(row["id"] for row in rows)
            if not approved_fact_evidence_is_current(
                connection,
                project_id=project_id,
                evidence_ids=ids,
            ):
                raise SyntheticLabContractError(
                    "Fact snapshot contains retired approved Fact evidence"
                )
        finally:
            connection.rollback()
            connection.close()
        evidence: list[FrozenEvidence] = []
        for row in rows:
            summary = str(row["snapshot_text"] or row["citation_label"] or "").strip()
            if not summary:
                if row["item_type"] == "approved_fact":
                    raise SyntheticLabContractError(
                        "approved Fact evidence has no model-readable snapshot"
                    )
                continue
            subject_id = row["subject_entity_id"] or primary_subject_id
            approved_fact = row["item_type"] == "approved_fact"
            evidence.append(
                FrozenEvidence(
                    ref=f"evidence:{row['id']}:{row['snapshot_hash']}",
                    subject_id=str(subject_id),
                    summary=summary[:4_000],
                    fact_id=row["id"] if approved_fact else None,
                    fact_hash=row["snapshot_hash"] if approved_fact else None,
                )
            )
        if not evidence or all(item.subject_id != str(primary_subject_id) for item in evidence):
            raise SyntheticLabContractError(
                "Fact snapshot has no model-readable primary-subject evidence"
            )
        return tuple(evidence)

    def _profile(self, project_id: UUID, resource_id: UUID) -> StyleProfileVersion:
        record = self._reads.aggregate(
            project_id,
            kind="style_profile",
            resource_id=resource_id,
        )
        if not isinstance(record.payload, StyleProfileVersion):
            raise SyntheticLabNotFound("Style Profile payload type changed")
        return record.payload

    def _suite(self, project_id: UUID, resource_id: UUID) -> ReviewSuite:
        record = self._reads.aggregate(
            project_id,
            kind="review_suite",
            resource_id=resource_id,
        )
        if not isinstance(record.payload, ReviewSuite):
            raise SyntheticLabNotFound("Review Suite payload type changed")
        return record.payload

    def _case(self, project_id: UUID, resource_id: UUID) -> ReviewCase:
        record = self._reads.aggregate(
            project_id,
            kind="review_case",
            resource_id=resource_id,
        )
        if not isinstance(record.payload, ReviewCase):
            raise SyntheticLabNotFound("Review Case payload type changed")
        return record.payload

    def _open(self, project_id: UUID) -> Any:
        from geo_core.project_scope import set_project_scope

        connection = self._connect()
        set_project_scope(connection, project_id)
        return connection
