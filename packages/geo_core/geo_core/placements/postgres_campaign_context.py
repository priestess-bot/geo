"""Closed PostgreSQL ancestry resolver for Campaign-owned Placement resources."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from geo_core.placements.domain import (
    CampaignResourceContext,
    CampaignResourceKind,
    CampaignScope,
)


_RESOURCE_CONTEXT_SQL: Mapping[CampaignResourceKind, str] = {
    CampaignResourceKind.OPPORTUNITY: """
        SELECT id AS resource_id, project_id, campaign_id, id AS opportunity_id,
               destination_id
        FROM placement_opportunities WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.BRIEF_VERSION: """
        SELECT id AS resource_id, project_id, campaign_id, opportunity_id, destination_id
        FROM placement_brief_versions WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.EVIDENCE_ATTEMPT: """
        SELECT id AS resource_id, project_id, campaign_id, opportunity_id, destination_id
        FROM evidence_pack_attempts WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.PROMPT_BUNDLE: """
        SELECT id AS resource_id, project_id, campaign_id, opportunity_id, destination_id
        FROM prompt_bundles WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.PACKAGE: """
        SELECT id AS resource_id, project_id, campaign_id, opportunity_id, destination_id
        FROM placement_packages WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.PACKAGE_VERSION: """
        SELECT id AS resource_id, project_id, campaign_id, opportunity_id, destination_id
        FROM placement_package_versions WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.EXPORT: """
        SELECT id AS resource_id, project_id, campaign_id, opportunity_id, destination_id
        FROM placement_export_receipts WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.PUBLICATION: """
        SELECT id AS resource_id, project_id, campaign_id, opportunity_id, destination_id
        FROM publication_requests WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.SUBMISSION: """
        SELECT id AS resource_id, project_id, campaign_id, opportunity_id, destination_id
        FROM publication_submissions WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.MEASUREMENT_TASK: """
        SELECT id AS resource_id, project_id, campaign_id, opportunity_id, destination_id
        FROM measurement_collection_tasks WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.SIMULATION: """
        SELECT id AS resource_id, project_id, campaign_id, opportunity_id, destination_id
        FROM prompt_simulations WHERE id = %(resource_id)s
    """,
    CampaignResourceKind.JOB: """
        SELECT job.id AS resource_id, job.project_id, job.campaign_id,
               context.opportunity_id, context.destination_id
        FROM durable_jobs AS job
        JOIN LATERAL (
            SELECT attempt.opportunity_id, attempt.destination_id
            FROM evidence_pack_job_specs AS spec
            JOIN evidence_pack_attempts AS attempt
              ON attempt.id = spec.evidence_pack_attempt_id
             AND attempt.project_id = spec.project_id
            WHERE spec.job_id = job.id AND spec.project_id = job.project_id
            UNION ALL
            SELECT bundle.opportunity_id, bundle.destination_id
            FROM generation_job_specs AS spec
            JOIN prompt_bundles AS bundle
              ON bundle.id = spec.prompt_bundle_id AND bundle.project_id = spec.project_id
            WHERE spec.job_id = job.id AND spec.project_id = job.project_id
            UNION ALL
            SELECT submission.opportunity_id, submission.destination_id
            FROM verification_job_specs AS spec
            JOIN publication_submissions AS submission
              ON submission.id = spec.submission_id AND submission.project_id = spec.project_id
            WHERE spec.job_id = job.id AND spec.project_id = job.project_id
            UNION ALL
            SELECT submission.opportunity_id, submission.destination_id
            FROM measurement_job_specs AS spec
            JOIN publication_submissions AS submission
              ON submission.id = spec.submission_id AND submission.project_id = spec.project_id
            WHERE spec.job_id = job.id AND spec.project_id = job.project_id
            UNION ALL
            SELECT simulation.opportunity_id, simulation.destination_id
            FROM prompt_simulation_job_specs AS spec
            JOIN prompt_simulations AS simulation
              ON simulation.id = spec.simulation_id AND simulation.project_id = spec.project_id
            WHERE spec.job_id = job.id AND spec.project_id = job.project_id
            UNION ALL
            SELECT artifact.opportunity_id, artifact.destination_id
            FROM artifact_finalize_outbox AS artifact
            JOIN LATERAL (
              WITH RECURSIVE descendants(id) AS (
                SELECT job.id
                UNION ALL
                SELECT child.id FROM durable_jobs AS child
                JOIN descendants AS parent ON child.parent_job_id = parent.id
                WHERE child.project_id = job.project_id
                  AND child.campaign_id = job.campaign_id
              )
              SELECT id FROM descendants
            ) AS descendant ON descendant.id = artifact.job_id
            WHERE artifact.project_id = job.project_id
              AND artifact.campaign_id = job.campaign_id
              AND artifact.campaign_id IS NOT NULL
            LIMIT 1
        ) AS context ON true
        WHERE job.id = %(resource_id)s
    """,
}


class PostgresCampaignContextMixin:
    _db: Any

    def resolve_campaign_resource(
        self,
        *,
        scope: CampaignScope,
        kind: CampaignResourceKind,
        resource_id: UUID,
        lock: bool = False,
    ) -> CampaignResourceContext | None:
        resource_query = _RESOURCE_CONTEXT_SQL[kind]
        lock_clause = "FOR UPDATE OF opportunity" if lock else ""
        cursor = self._db.execute(
            f"""
            SELECT resource.resource_id, opportunity.id AS opportunity_id,
                   opportunity.destination_id
            FROM ({resource_query}) AS resource
            JOIN placement_opportunities AS opportunity
              ON opportunity.id = resource.opportunity_id
             AND opportunity.project_id = resource.project_id
             AND opportunity.campaign_id = resource.campaign_id
             AND opportunity.destination_id = resource.destination_id
            WHERE resource.project_id = %(project_id)s
              AND resource.campaign_id = %(campaign_id)s
            {lock_clause}
            """,
            {
                "resource_id": resource_id,
                "project_id": scope.project_id,
                "campaign_id": scope.campaign_id,
            },
        )
        row = cursor.fetchone()
        if row is None:
            return None
        if not isinstance(row, Mapping):
            row = dict(zip((item.name for item in cursor.description), row, strict=True))
        return CampaignResourceContext(
            scope=scope,
            kind=kind,
            resource_id=row["resource_id"],
            opportunity_id=row["opportunity_id"],
            destination_id=row["destination_id"],
        )
