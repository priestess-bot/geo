"""Internal-only engineering governance and GitHub integration routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, status
from starlette.responses import StreamingResponse

from geo_api.contracts import (
    EngineeringAxis,
    EngineeringAxes,
    EngineeringEvidence,
    EngineeringHealthProbeRequest,
    EngineeringStatus,
    EngineeringSyncRequest,
    EngineeringWorkItem,
    EngineeringWorkItemList,
    GitHubWebhookAccepted,
    JobAccepted,
)
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.engineering.ports import DeliveryConflictError, UnknownRepositoryError
from geo_core.engineering.service import (
    EngineeringService,
    WebhookAuthenticationError,
    WebhookConfigurationError,
)


MAX_GITHUB_BODY_BYTES = 5 * 1024 * 1024


def engineering_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/engineering", tags=["engineering"], responses=PROBLEM_RESPONSES
    )

    @router.get("/status", response_model=EngineeringStatus, operation_id="getEngineeringStatus")
    def engineering_status(request: Request) -> EngineeringStatus:
        service = _service(request)
        persistence = bool(getattr(service, "persistence_available", True))
        github = persistence and bool(getattr(service, "github_available", False))
        runtime = persistence and bool(getattr(service, "runtime_available", False))
        return EngineeringStatus(
            status="available" if persistence else "unavailable",
            capabilities=["code", "ci", "runtime-health"],
            sources={
                "github": "available" if github else "unavailable",
                "ci": "available" if github else "unavailable",
                "runtime-health": "available" if runtime else "unavailable",
            },
        )

    @router.get(
        "/work-items",
        response_model=EngineeringWorkItemList,
        operation_id="listEngineeringWorkItems",
    )
    def list_work_items(request: Request) -> EngineeringWorkItemList:
        service = _service(request)
        items = [
            EngineeringWorkItem(
                id=item.id,
                title=item.title,
                summary=item.summary,
                axes=EngineeringAxes(
                    **{
                        name: EngineeringAxis(
                            status=axis.status.value,
                            evidence=[
                                EngineeringEvidence(label=evidence.label, url=evidence.url)
                                for evidence in axis.evidence
                            ],
                            observed_at=axis.observed_at,
                        )
                        for name, axis in item.axes.items()
                    }
                ),
                blockers=list(item.blockers),
                observed_at=item.observed_at,
                freshness=service.freshness_for(item).value,
            )
            for item in service.list_work_items()
        ]
        observed_at = max((item.observed_at for item in items), default=None)
        return EngineeringWorkItemList(items=items, observed_at=observed_at)

    @router.post(
        "/reconciliations",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="requestEngineeringReconciliation",
    )
    def request_reconciliation(
        payload: EngineeringSyncRequest,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    ) -> JobAccepted:
        try:
            receipt = _service(request).request_reconciliation(
                repository_id=payload.repository_id,
                reason=payload.reason,
                idempotency_key=idempotency_key,
            )
        except UnknownRepositoryError as exc:
            raise _repository_problem(exc) from exc
        return JobAccepted(
            job_id=receipt.job_id,
            status=receipt.status,
            status_url=f"/v1/jobs/{receipt.job_id}",
        )

    @router.post(
        "/health-probes",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="requestEngineeringHealthProbe",
    )
    def request_health_probe(
        payload: EngineeringHealthProbeRequest,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    ) -> JobAccepted:
        try:
            receipt = _service(request).request_health_probe(
                repository_id=payload.repository_id,
                service_key=payload.service_key,
                reason=payload.reason,
                idempotency_key=idempotency_key,
            )
        except UnknownRepositoryError as exc:
            raise _repository_problem(exc) from exc
        return JobAccepted(
            job_id=receipt.job_id,
            status=receipt.status,
            status_url=f"/v1/jobs/{receipt.job_id}",
        )

    @router.get("/events", operation_id="streamEngineeringEvents")
    def events(
        request: Request,
        after: Annotated[int, Query(ge=0)] = 0,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        cursor = _event_cursor(after=after, last_event_id=last_event_id)
        return StreamingResponse(
            _event_stream(request=request, service=_service(request), after=cursor),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def github_integration_router() -> APIRouter:
    router = APIRouter(prefix="/v1/integrations/github", tags=["GitHub App"])

    @router.post(
        "/events",
        response_model=GitHubWebhookAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        responses=PROBLEM_RESPONSES,
        operation_id="acceptGitHubEvent",
    )
    async def accept_event(
        request: Request,
        signature: Annotated[str, Header(alias="X-Hub-Signature-256")],
        delivery_id: Annotated[str, Header(alias="X-GitHub-Delivery", min_length=1)],
        event_name: Annotated[str, Header(alias="X-GitHub-Event", min_length=1)],
    ) -> GitHubWebhookAccepted:
        body = await request.body()
        if len(body) > MAX_GITHUB_BODY_BYTES:
            raise ApiProblem(
                status=413,
                title="Payload Too Large",
                detail="The GitHub webhook payload exceeds the 5 MiB limit.",
                type_uri="urn:geo:problem:github-payload-too-large",
            )
        try:
            receipt = _service(request).accept_github_delivery(
                delivery_id=delivery_id,
                event_name=event_name,
                signature=signature,
                body=body,
            )
        except WebhookAuthenticationError as exc:
            raise ApiProblem(
                status=401,
                title="Unauthorized",
                detail=str(exc),
                type_uri="urn:geo:problem:github-signature-invalid",
            ) from exc
        except WebhookConfigurationError as exc:
            raise ApiProblem(
                status=503,
                title="Service Unavailable",
                detail=str(exc),
                type_uri="urn:geo:problem:github-unavailable",
            ) from exc
        except UnknownRepositoryError as exc:
            raise ApiProblem(
                status=422,
                title="Unprocessable Content",
                detail=str(exc),
                type_uri="urn:geo:problem:github-repository-unbound",
            ) from exc
        except DeliveryConflictError as exc:
            raise ApiProblem(
                status=409,
                title="Conflict",
                detail=str(exc),
                type_uri="urn:geo:problem:github-delivery-conflict",
            ) from exc
        except ValueError as exc:
            raise ApiProblem(
                status=400,
                title="Bad Request",
                detail=str(exc),
                type_uri="urn:geo:problem:github-payload-invalid",
            ) from exc
        return GitHubWebhookAccepted(
            delivery_id=receipt.delivery_id,
            duplicate=receipt.duplicate,
            job_id=receipt.job_id,
            status=receipt.job_status,
            status_url=f"/v1/jobs/{receipt.job_id}",
        )

    return router


async def _event_stream(
    *, request: Request, service: EngineeringService, after: int
) -> AsyncIterator[str]:
    cursor = after
    while not await request.is_disconnected():
        emitted = False
        for event in service.events(after=cursor):
            cursor = event.sequence
            emitted = True
            yield encode_sse_event(
                event_id=event.sequence,
                event_type=event.event_type,
                data=dict(event.data) | {"observed_at": event.observed_at.isoformat()},
            )
        if not emitted:
            yield ": keep-alive\n\n"
        await asyncio.sleep(15)


def encode_sse_event(*, event_id: int, event_type: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
    return f"id: {event_id}\nevent: {event_type}\ndata: {payload}\n\n"


def _event_cursor(*, after: int, last_event_id: str | None) -> int:
    if not last_event_id:
        return after
    try:
        return max(after, int(last_event_id))
    except ValueError as exc:
        raise ApiProblem(
            status=400,
            title="Bad Request",
            detail="Last-Event-ID must be a non-negative integer.",
            type_uri="urn:geo:problem:engineering-event-cursor-invalid",
        ) from exc


def _service(request: Request) -> Any:
    return request.app.state.engineering_service


def _repository_problem(exc: UnknownRepositoryError) -> ApiProblem:
    return ApiProblem(
        status=422,
        title="Unprocessable Content",
        detail=str(exc),
        type_uri="urn:geo:problem:engineering-repository-unbound",
    )
