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
