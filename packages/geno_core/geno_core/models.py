from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


ActorType = Literal["user", "system", "worker", "api"]
AccessMethod = Literal["browser", "official_api", "third_party_api", "manual"]
ProjectRole = Literal["owner", "admin", "analyst", "viewer"]


@dataclass(frozen=True)
class PlatformConfig:
    platform: str
    surface: str
    build_stage: str
    weight: float
    enabled: bool


@dataclass(frozen=True)
class MarketProfile:
    market: str
    market_code: str
    locale: str
    timezone: str
    currency: str
    primary_language: str
    cities: list[str]
    source_types: list[str]
    platforms: list[PlatformConfig]


@dataclass(frozen=True)
class IndustryProfile:
    market_code: str
    industry_code: str
    display_name: str
    default_prompt_templates: tuple[str, ...]
    source_type_weights: dict[str, float]
    competitor_fields: tuple[str, ...]
    required_local_facts: tuple[str, ...]
    report_template: str


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    slug: str
    created_at: datetime


@dataclass(frozen=True)
class Project:
    id: str
    tenant_id: str
    name: str
    market_code: str
    industry_code: str
    target_brand: str
    category: str
    prompt_version: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class ProjectMember:
    id: str
    project_id: str
    user_id: str
    role: ProjectRole
    created_at: datetime


@dataclass(frozen=True)
class BrandEntity:
    id: str
    project_id: str
    canonical_name: str
    official_domains: tuple[str, ...]
    parent_company: str | None
    product_lines: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class CompetitorEntity:
    id: str
    project_id: str
    canonical_name: str
    official_domains: tuple[str, ...]
    parent_company: str | None
    product_lines: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class PromptQuestion:
    id: str
    project_id: str
    market_code: str
    industry_code: str
    text: str
    intent_type: str
    city: str
    language: str
    target_brand: str
    competitors: tuple[str, ...]
    priority: int
    intent_weight: float
    prompt_version: str
    status: str


@dataclass(frozen=True)
class ProjectBootstrap:
    tenant: Tenant
    project: Project
    members: tuple[ProjectMember, ...]
    brand: BrandEntity
    competitors: tuple[CompetitorEntity, ...]
    market_profile: MarketProfile
    industry_profile: IndustryProfile
    prompt_questions: tuple[PromptQuestion, ...]
    audit_events: tuple["AuditEvent", ...]


@dataclass(frozen=True)
class RawCollectResult:
    answer_present: bool
    surface_triggered: bool
    answer_text: str
    citations: list[dict[str, Any]]
    screenshot_url: str | None
    html_snapshot_url: str | None
    raw_payload: dict[str, Any]
    model_or_surface: str
    account_state: str | None
    collector_version: str


@dataclass(frozen=True)
class RawAnswer:
    id: str
    answer_run_id: str
    answer_text: str
    raw_payload_hash: str


@dataclass(frozen=True)
class AnswerAnalysis:
    id: str
    answer_run_id: str
    parser_engine_id: str
    analysis_version: str
    brand_mentioned: bool
    brand_recommended: bool
    brand_position: int | None
    competitors_mentioned: list[str]
    citation_count: int
    local_relevance_score: float
    sentiment_score: float
    freshness_score: float
    competitor_share_score: float
    confidence: float
    uncertainty_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisibilityScoreSnapshot:
    id: str
    project_id: str
    scope_type: str
    scope_value: str
    formula_version: str
    platform_weights_snapshot: dict[str, float]
    final_score: float
    trigger_rate: float
    mention_rate: float
    recommendation_rate: float
    answer_run_ids: list[str]
    created_at: datetime


@dataclass(frozen=True)
class ScoreContribution:
    id: str
    score_snapshot_id: str
    component_name: str
    component_score: float
    weight: float
    weighted_contribution: float
    denominator: str
    evidence_answer_run_ids: list[str]
    positive_evidence_summary: str
    negative_evidence_summary: str
    confidence_note: str
    created_at: datetime


@dataclass(frozen=True)
class AuditEvent:
    id: str
    event_type: str
    project_id: str
    actor_type: ActorType
    actor_id: str
    target_type: str
    target_id: str
    before_hash: str | None
    after_hash: str | None
    input_refs: dict[str, list[str]]
    output_refs: dict[str, list[str]]
    method_version: str | None
    reason: str | None
    created_at: datetime


@dataclass(frozen=True)
class ReportExport:
    id: str
    project_id: str
    market_code: str
    report_version: str
    report_type: str
    score_snapshot_ids: tuple[str, ...]
    answer_run_ids: tuple[str, ...]
    prompt_version: str
    scoring_formula_version: str
    platform_weights_snapshot: dict[str, float]
    sample_size: int
    window_start: datetime
    window_end: datetime
    methodology_hash: str
    pdf_url: str | None
    csv_url: str | None
    exported_by: str
    exported_at: datetime
