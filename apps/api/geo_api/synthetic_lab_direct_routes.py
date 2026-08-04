"""Direct generation option and manual channel-style routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from geo_api.catalog_routes import _principal
from geo_api.synthetic_lab_contracts import Channel
from geo_api.synthetic_lab_direct_contracts import (
    ChannelStylePageResponse,
    ChannelStyleResponse,
    CreateChannelStyleRequest,
    DirectGenerationOptionsResponse,
)
from geo_api.synthetic_lab_direct_presenters import (
    channel_style_page,
    channel_style_response,
    direct_generation_options_response,
)
from geo_api.synthetic_lab_route_support import (
    AuthorizationHeader,
    IdempotencyHeader,
    LimitQuery,
    OffsetQuery,
    run,
    run_write,
)


def synthetic_lab_direct_resource_router() -> APIRouter:
    router = APIRouter()

    @router.get(
        "/direct-generation/options",
        response_model=DirectGenerationOptionsResponse,
        operation_id="getSyntheticDirectGenerationOptions",
    )
    def direct_generation_options(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> DirectGenerationOptionsResponse:
        return direct_generation_options_response(
            run(
                request,
                "direct_generation_options",
                _principal(request, authorization),
                project_id=project_id,
            ),
            project_id=project_id,
        )

    @router.get(
        "/channel-styles",
        response_model=ChannelStylePageResponse,
        operation_id="listSyntheticChannelStyles",
    )
    def list_channel_styles(
        project_id: UUID,
        request: Request,
        limit: LimitQuery = 50,
        offset: OffsetQuery = 0,
        channel: Channel | None = None,
        include_history: bool = Query(default=False),
        authorization: AuthorizationHeader = None,
    ) -> ChannelStylePageResponse:
        return channel_style_page(
            run(
                request,
                "list_channel_styles",
                _principal(request, authorization),
                project_id=project_id,
                limit=limit,
                offset=offset,
                channel=channel,
                include_history=include_history,
            )
        )

    @router.post(
        "/channel-styles/{channel}/versions",
        response_model=ChannelStyleResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createSyntheticChannelStyleVersion",
    )
    def create_channel_style(
        project_id: UUID,
        channel: Channel,
        payload: CreateChannelStyleRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> ChannelStyleResponse:
        return channel_style_response(
            run_write(
                request,
                "create_channel_style",
                _principal(request, authorization),
                idempotency_key,
                project_id=project_id,
                channel=channel,
                payload=payload,
            )
        )

    return router


__all__ = ["synthetic_lab_direct_resource_router"]
