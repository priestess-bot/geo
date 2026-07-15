"""Shared transport helpers for internal placement routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, Request

from geo_api.foundation_services import FoundationServiceUnavailable
from geo_core.placements.application import PlacementApplication


IdempotencyHeader = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=512)
]


def placement_services(request: Request) -> PlacementApplication:
    services = getattr(request.app.state, "placement_services", None)
    if services is None:
        raise FoundationServiceUnavailable(
            "The placement application service is not connected."
        )
    return services
