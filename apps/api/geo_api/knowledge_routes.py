"""Internal project-scoped routes for enterprise knowledge preprocessing."""

from __future__ import annotations

from base64 import b64decode
import binascii
import re
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator

from geo_api.catalog_routes import _principal
from geo_api.foundation_services import FoundationServiceUnavailable
from geo_api.knowledge_contracts import (
    FactEvidencePromotionResponse,
    FactEvidenceProposalResponse,
    PromoteFactEvidenceRequest,
)
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_core.catalog.domain import Confidentiality, PublicCitation, SubjectRole, UsageRights
from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.domain import (
    KnowledgeConflict,
    KnowledgeForbidden,
    KnowledgeNotFound,
    KnowledgeValidationError,
    SourceInput,
)


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


class CreateKnowledgeSourceRequest(BaseModel):
    source_kind: str = Field(pattern="^(url|file|text)$")
    title: str = Field(min_length=1, max_length=300)
    source_url: str | None = Field(default=None, max_length=2000)
    filename: str | None = Field(default=None, max_length=300)
    media_type: str = Field(default="text/html", min_length=1, max_length=200)
    content_base64: str | None = Field(default=None, max_length=7_100_000)
    content_text: str | None = Field(default=None, max_length=5_000_000)

    @model_validator(mode="after")
    def source_contract(self) -> "CreateKnowledgeSourceRequest":
        if self.source_kind == "url" and not self.source_url:
            raise ValueError("URL source requires source_url")
        if self.source_kind != "url" and not (self.content_base64 or self.content_text):
            raise ValueError("file and text sources require content")
        if self.content_base64 and self.content_text:
            raise ValueError("provide content_base64 or content_text, not both")
        return self


class ReviewKnowledgeFactRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    notes: str = Field(default="", max_length=2000)


class ReviewKnowledgeFindingRequest(BaseModel):
    decision: str = Field(pattern="^(accepted|resolved)$")


def knowledge_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/knowledge",
        tags=["enterprise knowledge"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post("/sources", status_code=status.HTTP_202_ACCEPTED)
    def create_source(
        project_id: UUID,
        payload: CreateKnowledgeSourceRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        content = _content(payload)
        return _call(
            lambda: _application(request).create_source(
                _principal(request, authorization),
                project_id=project_id,
                source=SourceInput(
                    source_kind=payload.source_kind,
                    title=payload.title,
                    source_url=payload.source_url,
                    filename=payload.filename,
                    media_type=payload.media_type,
                    raw_content=content,
                ),
                idempotency_key=idempotency_key,
            )
        )

    @router.get("/sources")
    def list_sources(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).list_sources(
                _principal(request, authorization), project_id=project_id
            )
        )

    @router.post("/sources/{source_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
    def reprocess_source(
        project_id: UUID,
        source_id: UUID,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).reprocess_source(
                _principal(request, authorization),
                project_id=project_id,
                source_id=source_id,
                idempotency_key=idempotency_key,
            )
        )

    @router.get("/sources/{source_id}/download")
    def download_source(
        project_id: UUID,
        source_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Response:
        content, media_type, filename = _call(
            lambda: _application(request).source_content(
                _principal(request, authorization),
                project_id=project_id,
                source_id=source_id,
            )
        )
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-") or "knowledge-source"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )

    @router.get("/pipeline-runs")
    def list_runs(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).list_runs(
                _principal(request, authorization), project_id=project_id
            )
        )

    @router.get("/pipeline-runs/{run_id}/stages")
    def list_stages(
        project_id: UUID,
        run_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).list_stages(
                _principal(request, authorization), project_id=project_id, run_id=run_id
            )
        )

    @router.get("/chunks")
    def list_chunks(
        project_id: UUID,
        request: Request,
        query: Annotated[str, Query(max_length=300)] = "",
        chunk_status: Annotated[str, Query(pattern="^(|active|disabled)$")] = "",
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).list_chunks(
                _principal(request, authorization),
                project_id=project_id,
                query=query,
                status=chunk_status,
            )
        )

    @router.post("/chunks/{chunk_id}/disable")
    def disable_chunk(
        project_id: UUID,
        chunk_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).disable_chunk(
                _principal(request, authorization), project_id=project_id, chunk_id=chunk_id
            )
        )

    @router.get("/fact-candidates")
    def list_facts(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).list_facts(
                _principal(request, authorization), project_id=project_id
            )
        )

    @router.get(
        "/fact-candidates/{fact_id}/evidence-proposal",
        response_model=FactEvidenceProposalResponse,
        operation_id="getKnowledgeFactEvidenceProposal",
    )
    def evidence_proposal(
        project_id: UUID,
        fact_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).evidence_proposal(
                _principal(request, authorization),
                project_id=project_id,
                fact_id=fact_id,
            )
        )

    @router.post(
        "/fact-candidates/{fact_id}/evidence",
        response_model=FactEvidencePromotionResponse,
        operation_id="promoteKnowledgeFactEvidence",
    )
    def promote_evidence(
        project_id: UUID,
        fact_id: UUID,
        payload: PromoteFactEvidenceRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        citation = payload.public_citation
        return _call(
            lambda: _application(request).promote_fact_to_evidence(
                _principal(request, authorization),
                project_id=project_id,
                fact_id=fact_id,
                idempotency_key=idempotency_key,
                title=payload.title,
                subject_entity_id=payload.subject_entity_id,
                subject_role=SubjectRole(payload.subject_role),
                usage_rights=UsageRights(payload.usage_rights),
                confidentiality=Confidentiality(payload.confidentiality),
                public_citation=PublicCitation(
                    disclosure_allowed=citation.disclosure_allowed,
                    source_url=citation.source_url,
                    source_title=citation.source_title,
                    label=citation.label,
                    quotation_allowed=citation.quotation_allowed,
                    attribution_required=citation.attribution_required,
                ),
            )
        )

    @router.patch("/fact-candidates/{fact_id}")
    def review_fact(
        project_id: UUID,
        fact_id: UUID,
        payload: ReviewKnowledgeFactRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).review_fact(
                _principal(request, authorization),
                project_id=project_id,
                fact_id=fact_id,
                decision=payload.decision,
                notes=payload.notes,
            )
        )

    @router.get("/quality-findings")
    def list_findings(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).list_findings(
                _principal(request, authorization), project_id=project_id
            )
        )

    @router.patch("/quality-findings/{finding_id}")
    def review_finding(
        project_id: UUID,
        finding_id: UUID,
        payload: ReviewKnowledgeFindingRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).review_finding(
                _principal(request, authorization),
                project_id=project_id,
                finding_id=finding_id,
                decision=payload.decision,
            )
        )

    @router.get("/dashboard")
    def dashboard(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> Any:
        return _call(
            lambda: _application(request).dashboard(
                _principal(request, authorization), project_id=project_id
            )
        )

    return router


def _content(payload: CreateKnowledgeSourceRequest) -> bytes | None:
    if payload.content_text is not None:
        return payload.content_text.encode("utf-8")
    if payload.content_base64 is None:
        return None
    try:
        return b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiProblem(
            status=422,
            title="Unprocessable Content",
            detail="content_base64 is invalid",
            type_uri="urn:geo:problem:knowledge-content-invalid",
        ) from exc


def _application(request: Request) -> KnowledgeApplication:
    application = request.app.state.knowledge_application
    if not isinstance(application, KnowledgeApplication):
        raise FoundationServiceUnavailable("The Knowledge application is not configured.")
    return application


def _call(operation: Any) -> Any:
    try:
        return operation()
    except KnowledgeValidationError as error:
        raise ApiProblem(
            status=422,
            title="Unprocessable Content",
            detail=str(error),
            type_uri="urn:geo:problem:knowledge-validation",
        ) from error
    except KnowledgeForbidden as error:
        raise ApiProblem(
            status=403,
            title="Forbidden",
            detail=str(error),
            type_uri="urn:geo:problem:knowledge-forbidden",
        ) from error
    except KnowledgeNotFound as error:
        raise ApiProblem(
            status=404,
            title="Not Found",
            detail=str(error),
            type_uri="urn:geo:problem:knowledge-not-found",
        ) from error
    except KnowledgeConflict as error:
        raise ApiProblem(
            status=409,
            title="Conflict",
            detail=str(error),
            type_uri="urn:geo:problem:knowledge-conflict",
        ) from error
