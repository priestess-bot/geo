from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid5, NAMESPACE_URL

from geno_core.audit import build_audit_event
from geno_core.industry import build_au_dtc_ecommerce_profile
from geno_core.market import build_au_market_profile
from geno_core.models import (
    BrandEntity,
    CompetitorEntity,
    Project,
    ProjectBootstrap,
    ProjectMember,
    Tenant,
)
from geno_core.prompt_pack import PROMPT_VERSION_AU_DTC_V1, build_au_dtc_prompt_pack


DEFAULT_AU_COMPETITORS = ("Emma Sleep", "Sleeping Duck", "Ecosa", "IKEA Australia")


def _stable_id(kind: str, *parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geno", kind, *parts))))


def build_au_project_bootstrap(
    *,
    tenant_name: str = "Design Partner AU",
    project_name: str = "AU DTC Evidence Pilot",
    target_brand: str = "ExampleBrand",
    category: str = "DTC ecommerce products",
    competitors: tuple[str, ...] = DEFAULT_AU_COMPETITORS,
    owner_user_id: str = "user-owner",
) -> ProjectBootstrap:
    if len(competitors) < 3 or len(competitors) > 5:
        raise ValueError("M1 project bootstrap requires 3-5 competitors")

    now = datetime.now(UTC)
    tenant_slug = tenant_name.lower().replace(" ", "-")
    tenant = Tenant(
        id=_stable_id("tenant", tenant_slug),
        name=tenant_name,
        slug=tenant_slug,
        created_at=now,
    )
    market_profile = build_au_market_profile()
    industry_profile = build_au_dtc_ecommerce_profile()
    project = Project(
        id=_stable_id("project", tenant.id, project_name, market_profile.market_code),
        tenant_id=tenant.id,
        name=project_name,
        market_code=market_profile.market_code,
        industry_code=industry_profile.industry_code,
        target_brand=target_brand,
        category=category,
        prompt_version=PROMPT_VERSION_AU_DTC_V1,
        status="configured",
        created_at=now,
    )
    members = (
        ProjectMember(
            id=_stable_id("project-member", project.id, owner_user_id),
            project_id=project.id,
            user_id=owner_user_id,
            role="owner",
            created_at=now,
        ),
    )
    brand = BrandEntity(
        id=_stable_id("brand", project.id, target_brand),
        project_id=project.id,
        canonical_name=target_brand,
        official_domains=(),
        parent_company=None,
        product_lines=(),
        status="active",
    )
    competitor_entities = tuple(
        CompetitorEntity(
            id=_stable_id("competitor", project.id, competitor),
            project_id=project.id,
            canonical_name=competitor,
            official_domains=(),
            parent_company=None,
            product_lines=(),
            status="active",
        )
        for competitor in competitors
    )
    prompt_questions = build_au_dtc_prompt_pack(
        project_id=project.id,
        market_profile=market_profile,
        industry_code=industry_profile.industry_code,
        target_brand=target_brand,
        category=category,
        competitors=competitors,
        prompt_version=project.prompt_version,
    )
    audit_events = (
        build_audit_event(
            event_type="project_bootstrap_created",
            project_id=project.id,
            actor_type="system",
            actor_id="geno-core.bootstrap",
            target_type="project",
            target_id=project.id,
            before=None,
            after={
                "tenant_id": tenant.id,
                "market_code": project.market_code,
                "industry_code": project.industry_code,
                "prompt_version": project.prompt_version,
                "prompt_count": len(prompt_questions),
                "competitor_count": len(competitor_entities),
            },
            output_refs={
                "prompt_question_ids": [prompt.id for prompt in prompt_questions],
                "competitor_entity_ids": [competitor.id for competitor in competitor_entities],
            },
            method_version="m1_project_bootstrap_v1",
            reason="Create auditable AU design-partner project bootstrap package",
        ),
    )
    return ProjectBootstrap(
        tenant=tenant,
        project=project,
        members=members,
        brand=brand,
        competitors=competitor_entities,
        market_profile=market_profile,
        industry_profile=industry_profile,
        prompt_questions=prompt_questions,
        audit_events=audit_events,
    )
