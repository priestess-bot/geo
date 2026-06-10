from __future__ import annotations

import hashlib
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.responses import Response

from geno_core.action_plan import (
    build_action_plan_audit_event,
    build_action_recommendations,
    build_retest_schedule,
    build_retest_comparison_audit_event,
    compare_retest_windows,
)
from geno_core.analysis_pipeline import analyze_and_score_records
from geno_core.bootstrap import DEFAULT_AU_COMPETITORS, build_au_project_bootstrap
from geno_core.collection import (
    build_manual_backfill_record,
    build_p0a_collection_plan,
    run_collection_slice,
    run_fixture_collection_slice,
)
from geno_core.collectors import (
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
)
from geno_core.google_spike import (
    build_google_spike_plan,
    evaluate_google_spike_gate,
    select_google_spike_prompts,
)
from geno_core.graph import build_citation_graph
from geno_core.industry import build_au_dtc_ecommerce_profile
from geno_core.knowledge import (
    build_content_drafts,
    build_content_engine_audit_event,
    build_integration_connectors,
    build_localized_knowledge_facts,
    build_manual_distribution_records,
    search_knowledge_facts,
)
from geno_core.market import build_au_market_profile
from geno_core.models import (
    EntityAliasInput,
    RuntimeHumanReviewInput,
    ManualBackfillInput,
    RuntimeProjectBrandKitInput,
    RuntimePromptImportInput,
    RuntimeSavedViewInput,
    RuntimeScoreWeightConfigInput,
)
from geno_core.prompt_pack import build_au_dtc_prompt_pack
from geno_core.report import MarkdownCsvReportExporter
from geno_core.runtime import RuntimePersistenceError, build_repository_from_env, close_repository_connection
from geno_core.scoring import AU_VISIBILITY_V1, normalize_score_weights
from geno_core.traceability import build_traceability_bundle

app = FastAPI(title="GENO SaaS AU API", version="0.1.0")


class RuntimeSavedViewRequest(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    view_type: str = Field(default="runtime_evidence", min_length=1, max_length=80)
    filters: dict[str, object] = Field(default_factory=dict)
    sort: str = Field(default="collected_at_desc", max_length=80)
    query_path: str = Field(min_length=1, max_length=1000)
    export_path: str = Field(min_length=1, max_length=1000)
    created_by: str = Field(default="runtime-console", min_length=1, max_length=120)


class ProjectBrandKitRequest(BaseModel):
    project_id: str = Field(min_length=1)
    client_name: str = Field(min_length=1, max_length=160)
    prepared_by: str = Field(default="GENO SaaS AU", min_length=1, max_length=160)
    logo_url: str | None = Field(default=None, max_length=1000)
    primary_color: str | None = Field(default=None, max_length=40)
    secondary_color: str | None = Field(default=None, max_length=40)
    footer_text: str | None = Field(default=None, max_length=500)
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)


class ScoreWeightConfigRequest(BaseModel):
    project_id: str = Field(min_length=1)
    formula_version: str = Field(default="au_visibility_v1", min_length=1, max_length=80)
    weights: dict[str, float]
    updated_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=500)


class HumanReviewRequest(BaseModel):
    project_id: str = Field(min_length=1)
    target_type: str = Field(min_length=1, max_length=120)
    target_id: str = Field(min_length=1, max_length=240)
    review_status: str = Field(default="approved", min_length=1, max_length=80)
    decision: str = Field(min_length=1, max_length=240)
    reviewer_id: str = Field(default="runtime-console", min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    payload: dict[str, object] = Field(default_factory=dict)


class RuntimePromptImportRequest(BaseModel):
    project_id: str = Field(min_length=1)
    csv_content: str = Field(min_length=1, max_length=120000)
    imported_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    max_rows: int = Field(default=100, ge=1, le=200)


class ManualBackfillRequest(BaseModel):
    prompt_question_id: str = Field(min_length=1)
    platform: str = Field(default="google", min_length=1, max_length=80)
    surface: str = Field(default="google_ai_mode", min_length=1, max_length=120)
    answer_text: str = Field(min_length=1, max_length=20000)
    citation_urls: list[str] = Field(default_factory=list, max_length=20)
    screenshot_url: str | None = Field(default=None, max_length=1000)
    html_snapshot_url: str | None = Field(default=None, max_length=1000)
    answer_present: bool = True
    surface_triggered: bool = True
    sample_index: int = Field(default=1, ge=1, le=50)
    sample_size: int = Field(default=1, ge=1, le=50)
    device: str = Field(default="desktop", min_length=1, max_length=80)
    account_state: str | None = Field(default=None, max_length=120)
    submitted_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class EntityAliasConfirmRequest(BaseModel):
    entity_id: str = Field(min_length=1)
    entity_kind: str = Field(min_length=1, max_length=40)
    alias: str = Field(min_length=1, max_length=240)
    alias_type: str = Field(default="alias", min_length=1, max_length=80)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    confirmed_by: str = Field(default="runtime-console", min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class RuntimeProjectCreateRequest(BaseModel):
    tenant_name: str = Field(default="Design Partner AU", min_length=1, max_length=160)
    project_name: str = Field(default="AU DTC Evidence Pilot", min_length=1, max_length=160)
    target_brand: str = Field(default="ExampleBrand", min_length=1, max_length=160)
    category: str = Field(default="DTC ecommerce products", min_length=1, max_length=200)
    competitors: list[str] = Field(default_factory=list, max_length=5)
    brand_official_domains: list[str] = Field(default_factory=list, max_length=5)
    brand_parent_company: str | None = Field(default=None, max_length=160)
    brand_product_lines: list[str] = Field(default_factory=list, max_length=10)
    owner_user_id: str = Field(default="runtime-console", min_length=1, max_length=120)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "geno-saas-au-api"}


@app.get("/v1/market-profiles/au")
def au_market_profile() -> dict[str, object]:
    return asdict(build_au_market_profile())


@app.get("/v1/industry-profiles/au/dtc-ecommerce")
def au_dtc_industry_profile() -> dict[str, object]:
    return asdict(build_au_dtc_ecommerce_profile())


@app.get("/v1/prompt-packs/au/dtc-ecommerce")
def au_dtc_prompt_pack() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    return {
        "prompt_version": bootstrap.project.prompt_version,
        "market_code": bootstrap.project.market_code,
        "industry_code": bootstrap.project.industry_code,
        "target_brand": bootstrap.project.target_brand,
        "category": bootstrap.project.category,
        "count": len(bootstrap.prompt_questions),
        "prompts": [asdict(prompt) for prompt in bootstrap.prompt_questions],
    }


@app.get("/v1/project-bootstraps/au/dtc-ecommerce")
def au_dtc_project_bootstrap() -> dict[str, object]:
    return asdict(build_au_project_bootstrap())


@app.post("/v1/projects/runtime/au/dtc-ecommerce")
def create_runtime_au_dtc_project(payload: RuntimeProjectCreateRequest | None = None) -> dict[str, object]:
    request = payload or RuntimeProjectCreateRequest()
    competitors = tuple(item.strip() for item in request.competitors if item.strip())
    if not competitors:
        competitors = DEFAULT_AU_COMPETITORS
    brand_official_domains = tuple(item.strip() for item in request.brand_official_domains if item.strip())
    brand_product_lines = tuple(item.strip() for item in request.brand_product_lines if item.strip())
    try:
        bootstrap = build_au_project_bootstrap(
            tenant_name=request.tenant_name.strip(),
            project_name=request.project_name.strip(),
            target_brand=request.target_brand.strip(),
            category=request.category.strip(),
            competitors=competitors,
            brand_official_domains=brand_official_domains,
            brand_parent_company=request.brand_parent_company.strip() if request.brand_parent_company else None,
            brand_product_lines=brand_product_lines,
            owner_user_id=request.owner_user_id.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        repository.save_project_bootstrap(bootstrap)
        return {
            "tenant_id": bootstrap.tenant.id,
            "project_id": bootstrap.project.id,
            "market_code": bootstrap.project.market_code,
            "industry_code": bootstrap.project.industry_code,
            "prompt_count": len(bootstrap.prompt_questions),
            "competitor_count": len(bootstrap.competitors),
            "audit_event_ids": [event.id for event in bootstrap.audit_events],
            "bootstrap": asdict(bootstrap),
        }
    finally:
        close_repository_connection(repository)


@app.get("/v1/projects/runtime")
def runtime_projects(
    project_id: str | None = None,
    market_code: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_projects(
            project_id=project_id,
            market_code=market_code,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/entity-aliases/runtime")
def runtime_entity_aliases(
    project_id: str | None = None,
    entity_kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_entity_aliases(
            project_id=project_id,
            entity_kind=entity_kind,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/entity-aliases/runtime/candidates")
def runtime_entity_alias_candidates(
    project_id: str,
    entity_kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_entity_alias_candidates(
            project_id=project_id,
            entity_kind=entity_kind,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/entity-aliases/runtime/confirm")
def confirm_runtime_entity_alias(payload: EntityAliasConfirmRequest) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        try:
            record = repository.confirm_entity_alias(
                EntityAliasInput(
                    entity_id=payload.entity_id.strip(),
                    entity_kind=payload.entity_kind.strip(),
                    alias=payload.alias.strip(),
                    alias_type=payload.alias_type.strip(),
                    confidence=payload.confidence,
                    confirmed_by=payload.confirmed_by.strip(),
                    notes=payload.notes.strip() if payload.notes else None,
                )
            )
        except ValueError as exc:
            status_code = 404 if str(exc) == "entity not found" else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return asdict(record)
    finally:
        close_repository_connection(repository)


@app.get("/v1/prompts/runtime")
def runtime_prompts(
    project_id: str | None = None,
    market_code: str | None = None,
    intent_type: str | None = None,
    city: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_prompts(
            project_id=project_id,
            market_code=market_code,
            intent_type=intent_type,
            city=city,
            status=status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/prompts/runtime/import.csv")
def import_runtime_prompts_csv(payload: RuntimePromptImportRequest) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        result = repository.import_runtime_prompts_csv(
            RuntimePromptImportInput(
                project_id=payload.project_id.strip(),
                csv_content=payload.csv_content,
                imported_by=payload.imported_by.strip(),
                max_rows=payload.max_rows,
            )
        )
        return asdict(result)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/collection-plans/au/p0a")
def au_p0a_collection_plan() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    return asdict(
        build_p0a_collection_plan(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
        )
    )


@app.get("/v1/evidence-runs/au/p0a-fixture-slice")
def au_p0a_fixture_slice() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
    )
    return {
        "record_count": len(records),
        "answer_run_ids": [record.answer_run.id for record in records],
        "records": [asdict(record) for record in records],
    }


@app.get("/v1/evidence-runs/runtime")
def runtime_evidence_runs(
    project_id: str | None = None,
    platform: str | None = None,
    city: str | None = None,
    intent_type: str | None = None,
    status: str | None = None,
    sort: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_evidence_runs(
            project_id=project_id,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/collection-runs/runtime")
def runtime_collection_runs(
    project_id: str | None = None,
    run_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_collection_runs(
            project_id=project_id,
            run_type=run_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/evidence-runs/runtime/export.csv")
def runtime_evidence_export_csv(
    project_id: str | None = None,
    platform: str | None = None,
    city: str | None = None,
    intent_type: str | None = None,
    status: str | None = None,
    sort: str | None = None,
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Response:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        export = repository.export_runtime_evidence_csv(
            project_id=project_id,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return Response(
            content=export.content,
            media_type=export.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{export.filename}"',
                "X-GENO-Evidence-Export-Hash": export.content_hash,
                "X-GENO-Evidence-Export-Row-Count": str(export.row_count),
                "X-GENO-Evidence-Export-Total-Count": str(export.total_count),
                "X-GENO-Evidence-Export-Sort": str(export.filters.get("sort", "collected_at_desc")),
            },
        )
    finally:
        close_repository_connection(repository)


@app.post("/v1/evidence-runs/runtime/manual-backfill")
def runtime_manual_backfill(payload: ManualBackfillRequest) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        prompt = repository.get_runtime_prompt(payload.prompt_question_id)
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt question not found")
        citation_urls = tuple(url.strip() for url in payload.citation_urls if url.strip())
        record = build_manual_backfill_record(
            ManualBackfillInput(
                project_id=str(prompt["project_id"]),
                prompt_question_id=str(prompt["id"]),
                prompt_text=str(prompt["text"]),
                market_code=str(prompt["market_code"]),
                city=str(prompt["city"]),
                language=str(prompt["language"]),
                platform=payload.platform.strip(),
                surface=payload.surface.strip(),
                answer_text=payload.answer_text.strip(),
                citation_urls=citation_urls,
                screenshot_url=payload.screenshot_url.strip() if payload.screenshot_url else None,
                html_snapshot_url=payload.html_snapshot_url.strip() if payload.html_snapshot_url else None,
                answer_present=payload.answer_present,
                surface_triggered=payload.surface_triggered,
                sample_index=payload.sample_index,
                sample_size=payload.sample_size,
                device=payload.device.strip(),
                account_state=payload.account_state.strip() if payload.account_state else None,
                submitted_by=payload.submitted_by.strip(),
                notes=payload.notes.strip() if payload.notes else None,
            )
        )
        repository.save_raw_evidence_records((record,))
        return {
            "answer_run_id": record.answer_run.id,
            "raw_payload_hash": record.raw_answer.raw_payload_hash,
            "citation_count": len(record.citations),
            "evidence_asset_count": len(record.evidence_assets),
            "audit_event_ids": [event.id for event in record.audit_events],
            "record": asdict(record),
        }
    finally:
        close_repository_connection(repository)


@app.get("/v1/runtime-saved-views")
def runtime_saved_views(
    project_id: str | None = None,
    view_type: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_saved_views(
            project_id=project_id,
            view_type=view_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/runtime-saved-views")
def save_runtime_saved_view(payload: RuntimeSavedViewRequest) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        saved_view = repository.save_runtime_saved_view(
            RuntimeSavedViewInput(
                project_id=payload.project_id,
                name=payload.name.strip(),
                view_type=payload.view_type,
                filters=payload.filters,
                sort=payload.sort,
                query_path=payload.query_path,
                export_path=payload.export_path,
                created_by=payload.created_by,
            )
        )
        return asdict(saved_view)
    finally:
        close_repository_connection(repository)


@app.get("/v1/project-brand-kits/runtime")
def runtime_project_brand_kit(project_id: str = Query(min_length=1)) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        brand_kit = repository.get_project_brand_kit(project_id=project_id)
        if brand_kit is None:
            raise HTTPException(status_code=404, detail="Project brand kit not found")
        return asdict(brand_kit)
    finally:
        close_repository_connection(repository)


@app.post("/v1/project-brand-kits/runtime")
def save_runtime_project_brand_kit(payload: ProjectBrandKitRequest) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        brand_kit = repository.save_project_brand_kit(
            RuntimeProjectBrandKitInput(
                project_id=payload.project_id.strip(),
                client_name=payload.client_name.strip(),
                prepared_by=payload.prepared_by.strip(),
                logo_url=payload.logo_url.strip() if payload.logo_url else None,
                primary_color=payload.primary_color.strip() if payload.primary_color else None,
                secondary_color=payload.secondary_color.strip() if payload.secondary_color else None,
                footer_text=payload.footer_text.strip() if payload.footer_text else None,
                updated_by=payload.updated_by.strip(),
            )
        )
        return asdict(brand_kit)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/score-weight-configs/runtime")
def runtime_score_weight_config(
    project_id: str = Query(min_length=1),
    formula_version: str = Query(default="au_visibility_v1", min_length=1),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        config = repository.get_score_weight_config(project_id=project_id, formula_version=formula_version)
        if config is None:
            return {
                "score_weight_config": {
                    "id": None,
                    "project_id": project_id,
                    "formula_version": formula_version,
                    "weights": AU_VISIBILITY_V1,
                    "updated_by": "system-default",
                    "notes": "Default AU visibility score weights",
                },
                "audit_events": [],
            }
        return asdict(config)
    finally:
        close_repository_connection(repository)


@app.post("/v1/score-weight-configs/runtime")
def save_runtime_score_weight_config(payload: ScoreWeightConfigRequest) -> dict[str, object]:
    try:
        weights = normalize_score_weights(payload.weights)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        config = repository.save_score_weight_config(
            RuntimeScoreWeightConfigInput(
                project_id=payload.project_id.strip(),
                formula_version=payload.formula_version.strip(),
                weights=weights,
                updated_by=payload.updated_by.strip(),
                notes=payload.notes.strip() if payload.notes else None,
            )
        )
        return asdict(config)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/human-reviews/runtime")
def runtime_human_reviews(
    project_id: str | None = None,
    target_type: str | None = None,
    review_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_human_reviews(
            project_id=project_id,
            target_type=target_type,
            review_status=review_status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.post("/v1/human-reviews/runtime")
def record_runtime_human_review(payload: HumanReviewRequest) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        record = repository.save_human_review(
            RuntimeHumanReviewInput(
                project_id=payload.project_id.strip(),
                target_type=payload.target_type.strip(),
                target_id=payload.target_id.strip(),
                review_status=payload.review_status.strip(),
                decision=payload.decision.strip(),
                reviewer_id=payload.reviewer_id.strip(),
                notes=payload.notes.strip() if payload.notes else None,
                payload=payload.payload,
            )
        )
        return asdict(record)
    except ValueError as exc:
        status_code = 404 if str(exc) == "project not found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/visibility-scores/runtime")
def runtime_visibility_scores(
    project_id: str | None = None,
    scope_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_score_snapshots(
            project_id=project_id,
            scope_type=scope_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/citation-graphs/runtime")
def runtime_citation_graphs(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_citation_graphs(
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/reports/runtime")
def runtime_reports(
    project_id: str | None = None,
    report_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_report_exports(
            project_id=project_id,
            report_type=report_type,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/reports/runtime/{report_export_id}/artifact")
def runtime_report_artifact(
    report_export_id: str,
    artifact_type: str = Query(default="markdown", alias="type", pattern="^(markdown|csv|pdf)$"),
    template: str = Query(default="standard", pattern="^(standard|white_label)$"),
    client_name: str | None = None,
    prepared_by: str | None = None,
    platform: str | None = None,
    city: str | None = None,
    intent_type: str | None = None,
    status: str | None = None,
    sort: str | None = None,
) -> Response:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        artifact = repository.get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type=artifact_type,
            platform=platform,
            city=city,
            intent_type=intent_type,
            status=status,
            sort=sort,
            template=template,
            client_name=client_name,
            prepared_by=prepared_by,
        )
        if artifact is None:
            raise HTTPException(status_code=404, detail="Runtime report artifact not found")
        return Response(
            content=artifact.content,
            media_type=artifact.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{artifact.filename}"',
                "X-GENO-Report-Artifact-Hash": artifact.content_hash,
                "X-GENO-Report-Artifact-Filter-Hash": artifact.filter_hash,
                "X-GENO-Report-Artifact-Template": artifact.template,
                "X-GENO-Report-Artifact-Template-Hash": artifact.template_hash,
                "X-GENO-Report-Artifact-Sort": artifact.sort,
                "X-GENO-Report-Artifact-Row-Count": str(artifact.row_count),
                "X-GENO-Report-Artifact-Total-Count": str(artifact.total_count),
            },
        )
    finally:
        close_repository_connection(repository)


@app.get("/v1/action-plans/runtime")
def runtime_action_plans(
    project_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_action_plans(
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/content-engines/runtime")
def runtime_content_engines(
    project_id: str | None = None,
    review_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.list_runtime_content_engines(
            project_id=project_id,
            review_status=review_status,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    finally:
        close_repository_connection(repository)


@app.get("/v1/knowledge-facts/runtime/search")
def runtime_knowledge_fact_search(
    project_id: str = Query(min_length=1),
    query: str = Query(min_length=1),
    market_code: str = Query(default="AU", min_length=1, max_length=20),
    city: str | None = None,
    embedding_model: str = Query(default="fixture-knowledge-embedding-v1", min_length=1, max_length=120),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        page = repository.search_runtime_knowledge_facts(
            project_id=project_id,
            query=query,
            market_code=market_code,
            city=city,
            embedding_model=embedding_model,
            limit=limit,
            offset=offset,
        )
        return asdict(page)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        close_repository_connection(repository)


@app.get("/v1/traceability/runtime")
def runtime_traceability(
    project_id: str | None = None,
    report_export_id: str | None = None,
) -> dict[str, object]:
    try:
        repository = build_repository_from_env()
    except RuntimePersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        detail = repository.get_runtime_traceability_detail(
            project_id=project_id,
            report_export_id=report_export_id,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="Runtime traceability bundle not found")
        return asdict(detail)
    finally:
        close_repository_connection(repository)


@app.get("/v1/google-spikes/au/plan")
def au_google_spike_plan() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    return asdict(build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions))


@app.get("/v1/google-spikes/au/fixture-gate")
def au_google_spike_fixture_gate() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
    prompts = select_google_spike_prompts(bootstrap.prompt_questions)
    records = run_collection_slice(
        project_id=bootstrap.project.id,
        prompts=prompts,
        market_profile=bootstrap.market_profile,
        collectors=(FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector()),
        cities=plan.geo_cities,
        sample_size=plan.sample_size,
        prompt_limit=plan.prompt_count,
    )
    gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
    return {
        "plan": asdict(plan),
        "gate": asdict(gate),
        "record_count": len(records),
    }


@app.get("/v1/visibility-scores/au/p0a-fixture")
def au_p0a_fixture_visibility_score() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
        scope_type="project",
        scope_value="p0a_fixture",
    )
    return {
        "analysis_count": len(result.analyses),
        "snapshot": asdict(result.snapshot),
        "contributions": [asdict(contribution) for contribution in result.contributions],
        "audit_event": asdict(result.audit_event),
    }


@app.get("/v1/citation-graphs/au/p0a-fixture")
def au_p0a_fixture_citation_graph() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    return {
        "node_count": len(graph.nodes),
        "evidence_link_count": len(graph.evidence_links),
        "source_gap_count": len(graph.source_gaps),
        "competitor_count": len(graph.competitor_benchmarks),
        "nodes": [asdict(node) for node in graph.nodes],
        "source_gaps": [asdict(gap) for gap in graph.source_gaps],
        "competitor_benchmarks": [asdict(item) for item in graph.competitor_benchmarks],
    }


@app.get("/v1/reports/au/p0a-fixture")
def au_p0a_fixture_report() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    google_plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
    google_gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=google_plan, records=())
    report = MarkdownCsvReportExporter().export(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        report_version="p0a-fixture-v1",
        report_type="design_partner_fixture",
        prompt_version=bootstrap.project.prompt_version,
        snapshot=analysis_result.snapshot,
        contributions=analysis_result.contributions,
        records=records,
        graph=graph,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
        google_spike_gate=google_gate,
    )
    return {
        "report_export": asdict(report.report_export),
        "markdown": report.markdown,
        "csv_content": report.csv_content,
        "pdf_content_hash": hashlib.sha256(report.pdf_content).hexdigest(),
        "pdf_size_bytes": len(report.pdf_content),
        "audit_event": asdict(report.audit_event),
        "report_evidence_answer_run_ids": list(report.report_evidence_answer_run_ids),
    }


@app.get("/v1/action-plans/au/p0a-fixture")
def au_p0a_fixture_action_plan() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    actions = build_action_recommendations(
        project_id=bootstrap.project.id,
        graph=graph,
        snapshot=analysis_result.snapshot,
    )
    schedule = build_retest_schedule(
        project_id=bootstrap.project.id,
        prompt_version=bootstrap.project.prompt_version,
        sample_size=1,
        answer_run_ids=tuple(record.answer_run.id for record in records),
    )
    audit_event = build_action_plan_audit_event(
        project_id=bootstrap.project.id,
        actions=actions,
        schedule=schedule,
    )
    retest_snapshot = analysis_result.snapshot.__class__(
        **{
            **asdict(analysis_result.snapshot),
            "id": f"retest-{analysis_result.snapshot.id}",
            "final_score": round(analysis_result.snapshot.final_score + 2.5, 4),
        }
    )
    comparison = compare_retest_windows(
        project_id=bootstrap.project.id,
        baseline=analysis_result.snapshot,
        retest=retest_snapshot,
    )
    comparison_audit_event = build_retest_comparison_audit_event(
        project_id=bootstrap.project.id,
        comparison=comparison,
    )
    return {
        "action_count": len(actions),
        "actions": [asdict(action) for action in actions],
        "retest_schedule": asdict(schedule),
        "retest_comparison": asdict(comparison),
        "audit_event": asdict(audit_event),
        "comparison_audit_event": asdict(comparison_audit_event),
    }


@app.get("/v1/content-engines/au/p0a-fixture")
def au_p0a_fixture_content_engine() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    actions = build_action_recommendations(
        project_id=bootstrap.project.id,
        graph=graph,
        snapshot=analysis_result.snapshot,
    )
    answer_run_ids = tuple(record.answer_run.id for record in records)
    facts = build_localized_knowledge_facts(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        brand=bootstrap.brand,
        category=bootstrap.project.category,
        answer_run_ids=answer_run_ids,
    )
    knowledge_results = search_knowledge_facts(
        facts=facts,
        query=f"{bootstrap.project.target_brand} {bootstrap.project.category} Australia shipping reviews",
        market_code=bootstrap.project.market_code,
        city="Sydney",
        limit=5,
    )
    drafts = build_content_drafts(
        project_id=bootstrap.project.id,
        target_brand=bootstrap.project.target_brand,
        category=bootstrap.project.category,
        actions=actions,
        prompts=bootstrap.prompt_questions,
        knowledge_results=knowledge_results,
    )
    connectors = build_integration_connectors(project_id=bootstrap.project.id)
    distribution_records = build_manual_distribution_records(project_id=bootstrap.project.id, drafts=drafts)
    audit_event = build_content_engine_audit_event(
        project_id=bootstrap.project.id,
        facts=facts,
        drafts=drafts,
        connectors=connectors,
        distribution_records=distribution_records,
    )
    return {
        "knowledge_fact_count": len(facts),
        "search_results": [asdict(result) for result in knowledge_results],
        "content_draft_count": len(drafts),
        "content_drafts": [asdict(draft) for draft in drafts],
        "integration_connectors": [asdict(connector) for connector in connectors],
        "manual_distribution_records": [asdict(record) for record in distribution_records],
        "audit_event": asdict(audit_event),
    }


@app.get("/v1/traceability/au/p0a-fixture")
def au_p0a_fixture_traceability() -> dict[str, object]:
    bootstrap = build_au_project_bootstrap()
    records = run_fixture_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
        cities=("Australia", "Sydney"),
        sample_size=1,
        prompt_limit=10,
    )
    analysis_result = analyze_and_score_records(
        project_id=bootstrap.project.id,
        records=records,
        brand=bootstrap.brand,
        competitors=bootstrap.competitors,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    graph = build_citation_graph(
        project_id=bootstrap.project.id,
        records=records,
        analyses=analysis_result.analyses,
        competitors=bootstrap.competitors,
        industry_profile=bootstrap.industry_profile,
    )
    report = MarkdownCsvReportExporter().export(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        report_version="p0a-fixture-v1",
        report_type="design_partner_fixture",
        prompt_version=bootstrap.project.prompt_version,
        snapshot=analysis_result.snapshot,
        contributions=analysis_result.contributions,
        records=records,
        graph=graph,
        platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25, "google": 0.45},
    )
    actions = build_action_recommendations(
        project_id=bootstrap.project.id,
        graph=graph,
        snapshot=analysis_result.snapshot,
    )
    facts = build_localized_knowledge_facts(
        project_id=bootstrap.project.id,
        market_code=bootstrap.project.market_code,
        brand=bootstrap.brand,
        category=bootstrap.project.category,
        answer_run_ids=tuple(record.answer_run.id for record in records),
    )
    knowledge_results = search_knowledge_facts(
        facts=facts,
        query=f"{bootstrap.project.target_brand} {bootstrap.project.category} Australia shipping reviews",
        market_code=bootstrap.project.market_code,
        city="Sydney",
        limit=5,
    )
    drafts = build_content_drafts(
        project_id=bootstrap.project.id,
        target_brand=bootstrap.project.target_brand,
        category=bootstrap.project.category,
        actions=actions,
        prompts=bootstrap.prompt_questions,
        knowledge_results=knowledge_results,
    )
    bundle = build_traceability_bundle(
        project_id=bootstrap.project.id,
        report_export=report.report_export,
        snapshot=analysis_result.snapshot,
        contributions=analysis_result.contributions,
        records=records,
        graph=graph,
        actions=actions,
        content_drafts=drafts,
        audit_events=tuple(record.audit_events[0] for record in records)
        + (analysis_result.audit_event, report.audit_event),
    )
    return {
        "traceability_bundle": asdict(bundle),
        "report_export": asdict(report.report_export),
        "score_contribution_count": len(analysis_result.contributions),
        "answer_run_count": len(records),
    }


@app.get("/v1/contracts")
def contracts() -> dict[str, list[str]]:
    return {
        "interfaces": [
            "CollectorBackend",
            "LLMGateway",
            "ParserEngine",
            "VectorStore",
            "GraphStore",
            "GeoProvider",
            "ScoringFormula",
            "ReportExporter",
        ],
        "auditability": [
            "AuditEvent",
            "EvidenceLink",
            "LLMCallLog",
            "ScoreContribution",
            "ReportExport",
            "RuntimeHumanReviewRecord",
            "TraceabilityBundle",
        ],
        "m1_bootstrap": [
            "Tenant",
            "Project",
            "ProjectMember",
            "BrandEntity",
            "CompetitorEntity",
            "EntityAlias",
            "EntityAliasInput",
            "RuntimeEntityAlias",
            "RuntimeEntityAliasCandidate",
            "RuntimeEntityAliasCandidatePage",
            "RuntimeEntityAliasPage",
            "IndustryProfile",
            "PromptQuestion",
            "ProjectBootstrap",
        ],
        "m2a_evidence": [
            "CollectionPlan",
            "AnswerRun",
            "RawAnswer",
            "AnswerCitation",
            "EvidenceAsset",
            "CollectorLog",
            "CollectionCost",
            "CollectionRunSummary",
            "RawEvidenceRecord",
            "CollectionFailureRecord",
            "ManualBackfillInput",
            "PerplexitySonarCollector",
            "OpenAIWebSearchCollector",
        ],
        "m2b_google_spike": [
            "GoogleSpikePlan",
            "GoogleSpikeGateResult",
            "PlaywrightGoogleAIOCollector",
            "PlaywrightAIModeCollector",
            "ThirdPartySerpCollector",
            "ManualBackfillCollector",
        ],
        "m3_analysis_scoring": [
            "RuleBasedAnswerParser",
            "LLMJudgeAnswerParser",
            "ComparativeAnswerParser",
            "parser_ab_compare_v1",
            "llm_judge_prompt_v1",
            "FixtureLLMGateway",
            "LLMCallLog",
            "AnswerAnalysis",
            "VisibilityScoreSnapshot",
            "ScoreContribution",
            "RuntimeScoreWeightConfig",
            "RuntimeScoreWeightConfigInput",
            "ScoreWeightConfigRequest",
            "RuntimeHumanReviewRecord",
            "RuntimeHumanReviewPage",
            "RuntimeHumanReviewInput",
            "HumanReviewRequest",
            "au_visibility_v1",
        ],
        "m4_graph_benchmark": [
            "SourceGraphNode",
            "SourceGraphEvidence",
            "SourceGap",
            "CompetitorBenchmark",
            "CitationGraphResult",
        ],
        "m5_report_export": [
            "ReportExport",
            "MarkdownCsvReportExporter",
            "EvidenceReport",
        ],
        "m6_action_retest": [
            "ActionRecommendation",
            "RetestSchedule",
            "RetestComparison",
        ],
        "m7_content_integrations": [
            "LocalizedKnowledgeFact",
            "KnowledgeSearchResult",
            "KnowledgeFactEmbedding",
            "RuntimeKnowledgeSearchResult",
            "RuntimeKnowledgeSearchPage",
            "ContentDraft",
            "IntegrationConnector",
            "ManualDistributionRecord",
        ],
        "traceability": [
            "EvidenceLink",
            "TraceabilityBundle",
            "build_traceability_bundle",
        ],
        "persistence": [
            "build_repository_from_env",
            "build_object_store_from_env",
            "connect_postgres_from_env",
            "close_repository_connection",
            "RuntimePersistenceError",
            "PostgresEvidenceRepository",
            "save_project_bootstrap",
            "RuntimeProject",
            "RuntimeProjectPage",
            "RuntimeProjectCreateRequest",
            "RuntimeProjectBrandKit",
            "RuntimeProjectBrandKitInput",
            "ProjectBrandKitRequest",
            "RuntimeScoreWeightConfig",
            "RuntimeScoreWeightConfigInput",
            "ScoreWeightConfigRequest",
            "RuntimeHumanReviewRecord",
            "RuntimeHumanReviewPage",
            "RuntimeHumanReviewInput",
            "HumanReviewRequest",
            "RuntimePromptPage",
            "RuntimePromptImportInput",
            "RuntimePromptImportResult",
            "RuntimePromptImportRequest",
            "EntityAliasInput",
            "RuntimeEntityAlias",
            "RuntimeEntityAliasCandidate",
            "RuntimeEntityAliasCandidatePage",
            "RuntimeEntityAliasPage",
            "RuntimeEvidenceRun",
            "RuntimeEvidencePage",
            "RuntimeEvidenceExport",
            "RuntimeCollectionRun",
            "RuntimeCollectionRunPage",
            "ManualBackfillInput",
            "RuntimeSavedView",
            "RuntimeSavedViewPage",
            "RuntimeSavedViewInput",
            "RuntimeScoreSnapshot",
            "RuntimeScoreSnapshotPage",
            "RuntimeCitationGraph",
            "RuntimeCitationGraphPage",
            "RuntimeReportArtifact",
            "RuntimeReportExport",
            "RuntimeReportExportPage",
            "RuntimeActionPlan",
            "RuntimeActionPlanPage",
            "RuntimeContentDraft",
            "RuntimeContentEngine",
            "RuntimeContentEnginePage",
            "RuntimeKnowledgeSearchResult",
            "RuntimeKnowledgeSearchPage",
            "RuntimeTraceabilityDetail",
            "ProjectBootstrap",
            "PromptQuestion",
            "RawEvidenceRecord",
            "CollectionFailureRecord",
            "VisibilityScoreSnapshot",
            "ReportExport",
            "TraceabilityBundle",
            "/v1/projects/runtime",
            "/v1/projects/runtime/au/dtc-ecommerce",
            "/v1/entity-aliases/runtime",
            "/v1/entity-aliases/runtime/candidates",
            "/v1/entity-aliases/runtime/confirm",
            "/v1/prompts/runtime",
            "/v1/prompts/runtime/import.csv",
            "/v1/evidence-runs/runtime",
            "/v1/collection-runs/runtime",
            "/v1/evidence-runs/runtime/export.csv",
            "/v1/evidence-runs/runtime/manual-backfill",
            "/v1/runtime-saved-views",
            "/v1/project-brand-kits/runtime",
            "/v1/score-weight-configs/runtime",
            "/v1/human-reviews/runtime",
            "worker --persist",
            "worker --persist-analysis",
            "/v1/visibility-scores/runtime",
            "/v1/citation-graphs/runtime",
            "/v1/reports/runtime",
            "/v1/reports/runtime/{report_export_id}/artifact",
            "/v1/action-plans/runtime",
            "/v1/content-engines/runtime",
            "/v1/knowledge-facts/runtime/search",
            "/v1/traceability/runtime",
        ],
    }
