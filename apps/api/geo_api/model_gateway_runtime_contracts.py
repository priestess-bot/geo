"""Sanitized Admin contracts for approved Model Gateway runtime choices."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


CaptureMethodValue = Literal["provider_api", "proxy_grounded_api"]


class ModelGatewayRuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApprovedRuntimeOptionResponse(ModelGatewayRuntimeContract):
    selection_id: UUID
    manifest_id: UUID
    provider: str
    adapter_release_id: str
    model_release_id: str
    configured_model: str
    capture_method: CaptureMethodValue
    allowed_purposes: list[str]
    allowed_search_modes: list[str | None]


class ApprovedRuntimeOptionsResponse(ModelGatewayRuntimeContract):
    current_manifest_id: UUID | None
    items: list[ApprovedRuntimeOptionResponse]


__all__ = [
    "ApprovedRuntimeOptionResponse",
    "ApprovedRuntimeOptionsResponse",
]
