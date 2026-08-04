"""Server-resolved admission for direct Synthetic Lab generation."""

from __future__ import annotations

from uuid import UUID

from geo_core.placements.execution_eligibility import approved_fact_evidence_is_current
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.direct_generation import (
    DirectGenerationScenario,
    DirectKnowledgeItem,
    DirectKnowledgeSnapshot,
)
from geo_core.synthetic_lab.domain import SyntheticLabContractError
from geo_core.synthetic_lab.execution_contracts import (
    DirectGenerationTask,
    FrozenEvidence,
)
from geo_core.synthetic_lab.ports import (
    CommandReceipt,
    LabPrincipal,
    RuntimeInputSnapshot,
    SyntheticLabIdempotencyConflict,
    SyntheticLabNotFound,
    SyntheticJob,
    VersionedAggregate,
)
from geo_core.synthetic_lab.postgres_api_support import stable_id
from geo_core.synthetic_lab.review_programs import REVIEW_PROGRAM_KINDS


class _PostgresSyntheticDirectGenerationAdmission:
    def enqueue_direct_generation(
        self,
        *,
        principal: LabPrincipal,
        channel: str,
        subject_entity_id: UUID,
        generation_goal: str,
        runtime_selection_id: UUID,
        channel_style_version_id: UUID,
        channel_style_hash: str,
        knowledge_snapshot_hash: str,
        style_pass_threshold: float,
        include_competitor_context: bool,
        idempotency_key: str,
    ) -> CommandReceipt | SyntheticJob:
        project_id = principal.project_id
        job_id = stable_id(project_id, idempotency_key, "direct-generation-job")
        existing = self._reads.execution_task_or_none(project_id, job_id)
        if existing is not None:
            if not isinstance(existing, DirectGenerationTask) or (
                existing.case.channel != channel
                or existing.subject_id != subject_entity_id
                or existing.case.generation_goal != generation_goal.strip()
                or existing.channel_style.id != channel_style_version_id
                or existing.channel_style.style_hash != channel_style_hash
                or existing.knowledge_snapshot.snapshot_hash != knowledge_snapshot_hash
                or existing.style_pass_threshold != style_pass_threshold
                or any(
                    prompt.runtime_option_id != runtime_selection_id
                    for prompt in existing.prompts.values()
                )
            ):
                raise SyntheticLabIdempotencyConflict(
                    "Direct Generation Idempotency-Key was reused"
                )
            return self._reads.job(project_id, job_id)

        style = self._reads.current_channel_style(project_id, channel)
        if style is None:
            raise SyntheticLabContractError(
                f"{channel} has no manual Channel Style; create it and retry"
            )
        if style.id != channel_style_version_id or style.style_hash != channel_style_hash:
            raise SyntheticLabContractError(
                "Channel Style changed after preview; refresh the generation options"
            )
        snapshot_id = stable_id(project_id, idempotency_key, "direct-knowledge-snapshot")
        subject_name, snapshot = self._direct_knowledge_snapshot(
            project_id=project_id,
            snapshot_id=snapshot_id,
            subject_entity_id=subject_entity_id,
            include_competitor_context=include_competitor_context,
        )
        if snapshot.snapshot_hash != knowledge_snapshot_hash:
            raise SyntheticLabContractError(
                "Knowledge context changed after preview; refresh before retrying"
            )
        prompts = {
            kind: self._prompt(
                project_id=project_id,
                kind=kind,
                runtime_selection_id=runtime_selection_id,
            )
            for kind in REVIEW_PROGRAM_KINDS
        }
        primary = prompts[ProgramKind.GENERATION]
        runtime = RuntimeInputSnapshot(
            project_id=project_id,
            fact_snapshot_id=snapshot.id,
            fact_snapshot_hash=snapshot.snapshot_hash,
            profile_version_id=style.style_id,
            profile_hash=style.style_hash,
            prompt_release_id=primary.release_id,
            prompt_release_hash=primary.release_hash,
            facts_current_approved=True,
            profile_frozen=True,
            prompt_frozen=True,
            fact_source_kind="direct_knowledge",
            profile_source_kind="manual_channel_style",
        )
        scenario = DirectGenerationScenario(
            id=stable_id(project_id, idempotency_key, "direct-generation-scenario"),
            project_id=project_id,
            input_snapshot_id=snapshot.id,
            channel=channel,
            persona=f"An Australian consumer considering {subject_name}",
            use_case=generation_goal.strip(),
            subject=subject_name,
            generation_goal=generation_goal.strip(),
            competitor_scenario=include_competitor_context,
        )
        task = DirectGenerationTask(
            project_id=project_id,
            job_id=job_id,
            model_job_version=1,
            requested_by=principal.actor_id,
            review_run_id=stable_id(project_id, idempotency_key, "direct-generation-run"),
            case=scenario,
            subject_id=subject_entity_id,
            evidence=tuple(
                FrozenEvidence(
                    ref=item.ref,
                    subject_id=str(item.subject_entity_id),
                    summary=item.summary,
                    fact_id=item.evidence_id if item.kind == "approved_fact" else None,
                    fact_hash=item.snapshot_hash if item.kind == "approved_fact" else None,
                )
                for item in snapshot.items
            ),
            knowledge_snapshot=snapshot,
            channel_style=style,
            style_profile_summary=style.directive,
            style_pass_threshold=style_pass_threshold,
            runtime_inputs=runtime,
            prompts=prompts,
        )
        return self._application.enqueue(
            principal=principal,
            task=task,
            outbox_id=stable_id(project_id, idempotency_key, "direct-generation-outbox"),
            runtime_inputs=self._runtime_inputs,
            prompts=self._prompt_resolver,
            idempotency_key=idempotency_key,
            supporting_aggregates=(
                VersionedAggregate(
                    project_id=project_id,
                    kind="direct_knowledge_snapshot",
                    resource_id=snapshot.id,
                    version=1,
                    submitted_by=principal.actor_id,
                    payload=snapshot,
                ),
            ),
        )

    def _direct_knowledge_snapshot(
        self,
        *,
        project_id: UUID,
        snapshot_id: UUID,
        subject_entity_id: UUID,
        include_competitor_context: bool,
    ) -> tuple[str, DirectKnowledgeSnapshot]:
        connection = self._open(project_id)
        try:
            subject = connection.execute(
                """SELECT id, canonical_name FROM product_entities
                   WHERE project_id = %s AND id = %s AND entity_type = 'product'
                     AND status = 'active'""",
                (project_id, subject_entity_id),
            ).fetchone()
            if subject is None:
                raise SyntheticLabNotFound("active Direct Generation product is unavailable")
            subjects = connection.execute(
                """SELECT id, entity_type FROM product_entities
                   WHERE project_id = %s AND status = 'active'
                     AND (entity_type = 'brand' OR id = %s
                          OR (%s AND entity_type = 'competitor'))
                   ORDER BY entity_type, id""",
                (project_id, subject_entity_id, include_competitor_context),
            ).fetchall()
            competitor_ids = {row["id"] for row in subjects if row["entity_type"] == "competitor"}
            subject_ids = tuple(row["id"] for row in subjects)
            rows = connection.execute(
                """SELECT evidence.id, evidence.item_type,
                          evidence.subject_entity_id, entity.canonical_name,
                          evidence.snapshot_text, evidence.snapshot_hash,
                          evidence.public_source_title, evidence.public_source_url
                   FROM evidence_items AS evidence
                   JOIN product_entities AS entity
                     ON entity.project_id = evidence.project_id
                    AND entity.id = evidence.subject_entity_id
                   WHERE evidence.project_id = %s
                     AND evidence.subject_entity_id = ANY(%s)
                     AND evidence.item_type = 'approved_fact'
                     AND evidence.snapshot_text IS NOT NULL
                   ORDER BY CASE WHEN entity.entity_type = 'brand' THEN 0 ELSE 1 END,
                            entity.canonical_name, evidence.item_type, evidence.id""",
                (project_id, list(subject_ids)),
            ).fetchall()
            approved_ids = tuple(row["id"] for row in rows if row["item_type"] == "approved_fact")
            if not any(row["subject_entity_id"] == subject_entity_id for row in rows):
                raise SyntheticLabContractError(
                    "Direct Generation requires a current approved Fact for the selected product"
                )
            if include_competitor_context and not any(
                row["subject_entity_id"] in competitor_ids for row in rows
            ):
                raise SyntheticLabContractError(
                    "competitor context was requested but no approved competitor Fact exists"
                )
            if not approved_fact_evidence_is_current(
                connection, project_id=project_id, evidence_ids=approved_ids
            ):
                raise SyntheticLabContractError(
                    "Direct Generation contains retired approved Fact evidence"
                )
            items = tuple(
                DirectKnowledgeItem(
                    evidence_id=row["id"],
                    subject_entity_id=row["subject_entity_id"],
                    subject_name=row["canonical_name"],
                    kind=row["item_type"],
                    summary=row["snapshot_text"][:4_000],
                    snapshot_hash=row["snapshot_hash"],
                    source_title=row["public_source_title"],
                    source_url=row["public_source_url"],
                )
                for row in rows
            )
            return str(subject["canonical_name"]), DirectKnowledgeSnapshot(
                id=snapshot_id,
                project_id=project_id,
                primary_subject_id=subject_entity_id,
                items=items,
            )
        finally:
            connection.rollback()
            connection.close()


__all__ = ["_PostgresSyntheticDirectGenerationAdmission"]
