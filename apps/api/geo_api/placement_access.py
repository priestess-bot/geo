"""Shared authenticated project-role dependencies for internal placement routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request

from geo_api.foundation_services import AuthenticationInput, FoundationServices
from geo_core.access.models import AccessForbidden, AccessPrincipal


def _principal_for_roles(*allowed_roles: str):
    def dependency(
        project_id: UUID,
        request: Request,
        authorization: str | None = Header(default=None, alias="Authorization"),
        development_actor_id: str | None = Header(default=None, alias="X-GEO-Actor-ID"),
        development_tenant_id: str | None = Header(default=None, alias="X-GEO-Tenant-ID"),
    ) -> AccessPrincipal:
        services: FoundationServices = request.app.state.services
        principal = services.authenticate(
            AuthenticationInput(
                authorization=authorization,
                development_actor_id=development_actor_id,
                development_tenant_id=development_tenant_id,
            )
        )
        membership = next(
            (item for item in principal.memberships if item.project_id == project_id), None
        )
        if membership is None or membership.role not in allowed_roles:
            raise AccessForbidden("The identity cannot perform this project command.")
        return principal

    return dependency


PlacementViewer = Annotated[
    AccessPrincipal, Depends(_principal_for_roles("owner", "admin", "analyst", "viewer"))
]
PlacementEditor = Annotated[
    AccessPrincipal, Depends(_principal_for_roles("owner", "admin", "analyst"))
]
PlacementApprover = Annotated[
    AccessPrincipal, Depends(_principal_for_roles("owner", "admin", "analyst"))
]
PlacementOwnerAdmin = Annotated[AccessPrincipal, Depends(_principal_for_roles("owner", "admin"))]
PlacementPublisher = Annotated[AccessPrincipal, Depends(_principal_for_roles("owner", "admin"))]
