"""Application helpers for fail-closed Campaign ancestry checks."""

from __future__ import annotations

from uuid import UUID

from geo_core.placements.domain import (
    CampaignResourceContext,
    CampaignResourceKind,
    CampaignScope,
    PlacementNotFound,
)


def require_campaign_resource(
    repository: object,
    *,
    scope: CampaignScope,
    kind: CampaignResourceKind,
    resource_id: UUID,
    lock: bool = False,
) -> CampaignResourceContext:
    resolver = getattr(repository, "resolve_campaign_resource", None)
    if resolver is None:
        raise RuntimeError("placement repository does not implement Campaign scope resolution")
    context = resolver(scope=scope, kind=kind, resource_id=resource_id, lock=lock)
    if context is None:
        raise PlacementNotFound("The requested placement resource does not exist in this Campaign.")
    return context


def require_job_control_scope(
    repository: object,
    *,
    project_id: UUID,
    campaign_id: UUID | None,
    job_id: UUID,
) -> None:
    if campaign_id is not None:
        require_campaign_resource(
            repository,
            scope=CampaignScope(project_id, campaign_id),
            kind=CampaignResourceKind.JOB,
            resource_id=job_id,
        )
        return
    checker = getattr(repository, "is_legacy_project_job", None)
    if checker is None:
        raise RuntimeError("placement repository does not implement legacy job scope resolution")
    if not checker(project_id=project_id, job_id=job_id):
        raise PlacementNotFound(
            "The requested job requires an explicit Campaign or exact legacy simulation lineage."
        )
