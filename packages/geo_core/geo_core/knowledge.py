from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from geo_core.audit import build_audit_event
from geo_core.models import (
    ActionRecommendation,
    AuditEvent,
    BrandEntity,
    ContentDraft,
    IntegrationConnector,
    KnowledgeSearchResult,
    LocalizedKnowledgeFact,
    ManualDistributionRecord,
    PromptQuestion,
)

KNOWLEDGE_EMBEDDING_MODEL = "fixture-knowledge-embedding-v1"
# An approved fact becomes an active production fact. Review decisions still use
# the verb "approved"; the persisted fact lifecycle uses active/superseded/etc.
KNOWLEDGE_FACT_APPROVED_STATUS = "active"
CONTENT_REVIEW_PENDING_STATUS = "pending_human_review"
MANUAL_DISTRIBUTION_BACKFILL_REQUIRED_STATUS = "awaiting_url_backfill"
MANUAL_DISTRIBUTION_BACKFILLED_STATUS = "url_backfilled"


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geo", kind, *(str(part) for part in parts)))))


def knowledge_fact_text(fact: LocalizedKnowledgeFact) -> str:
    return " | ".join(
        (
            fact.market_code,
            fact.fact_type,
            fact.subject,
            fact.predicate,
            fact.object_value,
            fact.city or "global",
        )
    )


def knowledge_fact_content_hash(fact: LocalizedKnowledgeFact) -> str:
    return hashlib.sha256(knowledge_fact_text(fact).encode("utf-8")).hexdigest()


def embed_knowledge_text(text: str, *, dimensions: int = 8) -> tuple[float, ...]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return tuple(round(digest[index] / 255, 6) for index in range(dimensions))


def build_localized_knowledge_facts(
    *,
    project_id: str,
    market_code: str,
    brand: BrandEntity,
    category: str,
    answer_run_ids: tuple[str, ...],
    now: datetime | None = None,
) -> tuple[LocalizedKnowledgeFact, ...]:
    created_at = now or datetime.now(UTC)
    evidence_source_id = answer_run_ids[0] if answer_run_ids else None
    fact_specs = (
        ("australian_shipping_policy", brand.canonical_name, "supports_market", market_code, None, 0.72),
        ("aud_pricing", brand.canonical_name, "requires_local_price_page", "AUD pricing should be explicit", None, 0.68),
        ("returns_policy", brand.canonical_name, "requires_local_policy", "Australian returns policy should be explicit", None, 0.66),
        ("customer_support_hours", brand.canonical_name, "requires_local_support_hours", "Australia support hours are required", None, 0.62),
        ("local_review_sources", brand.canonical_name, "needs_review_sources", "Australian review sources should cite local proof", None, 0.7),
        ("city_coverage", category, "primary_city", "Sydney", "Sydney", 0.64),
        ("global_category_context", category, "category", category, None, 0.55),
    )
    return tuple(
        LocalizedKnowledgeFact(
            id=_stable_id("knowledge-fact", project_id, fact_type, subject, predicate, city or "global"),
            project_id=project_id,
            market_code=market_code if fact_type != "global_category_context" else "GLOBAL",
            fact_type=fact_type,
            subject=subject,
            predicate=predicate,
            object_value=object_value,
            city=city,
            evidence_source_id=evidence_source_id,
            confidence=confidence,
            status=KNOWLEDGE_FACT_APPROVED_STATUS,
            valid_from=created_at,
            valid_until=None,
        )
        for fact_type, subject, predicate, object_value, city, confidence in fact_specs
    )


def search_knowledge_facts(
    *,
    facts: tuple[LocalizedKnowledgeFact, ...],
    query: str,
    market_code: str,
    city: str | None = None,
    limit: int = 5,
) -> tuple[KnowledgeSearchResult, ...]:
    query_terms = {term.strip().lower() for term in query.replace("/", " ").replace("-", " ").split() if term.strip()}
    scored: list[KnowledgeSearchResult] = []
    for fact in facts:
        if fact.status != KNOWLEDGE_FACT_APPROVED_STATUS:
            continue
        is_market_match = fact.market_code == market_code
        is_global_fallback = fact.market_code == "GLOBAL"
        if not is_market_match and not is_global_fallback:
            continue
        if city and fact.city and fact.city != city:
            continue
        haystack = " ".join((fact.fact_type, fact.subject, fact.predicate, fact.object_value, fact.city or "")).lower()
        overlap = sum(1 for term in query_terms if term in haystack)
        market_boost = 2.0 if is_market_match else 0.5
        city_boost = 1.0 if city and fact.city == city else 0.0
        score = round(overlap + market_boost + city_boost + fact.confidence, 4)
        scored.append(KnowledgeSearchResult(fact=fact, score=score, fallback_used=is_global_fallback))
    ordered = sorted(scored, key=lambda item: item.score, reverse=True)
    selected = ordered[:limit]
    if selected and not any(item.fallback_used for item in selected):
        fallback = next((item for item in ordered[limit:] if item.fallback_used), None)
        if fallback and limit > 0:
            selected = selected[:-1] + [fallback]
    return tuple(selected)


def build_content_drafts(
    *,
    project_id: str,
    target_brand: str,
    category: str,
    actions: tuple[ActionRecommendation, ...],
    prompts: tuple[PromptQuestion, ...],
    knowledge_results: tuple[KnowledgeSearchResult, ...],
    now: datetime | None = None,
    created_by: str = "geo-core.knowledge",
) -> tuple[ContentDraft, ...]:
    created_at = now or datetime.now(UTC)
    prompt_ids = tuple(prompt.id for prompt in prompts[:5])
    prompt_city = next((prompt.city for prompt in prompts if prompt.city != "Australia"), "Australia")
    drafts: list[ContentDraft] = []
    for index, action in enumerate(actions[:3], start=1):
        source_type = action.related_source_types[0] if action.related_source_types else "official_site"
        template_id = _select_template_id(action)
        used_fact_ids = tuple(result.fact.id for result in knowledge_results[:5])
        fallback_notes = tuple(result.fact.id for result in knowledge_results if result.fallback_used)
        title = _draft_title(template_id, target_brand, category, source_type)
        source_gap_types = (action.source_gap_type,) if action.source_gap_type else ()
        draft_markdown = _render_draft_markdown(
            title=title,
            target_brand=target_brand,
            category=category,
            action=action,
            knowledge_results=knowledge_results[:5],
            fallback_fact_ids=fallback_notes,
        )
        drafts.append(
            ContentDraft(
                id=_stable_id("content-draft", project_id, action.id, template_id, index),
                project_id=project_id,
                title=title,
                content_type="evidence_backed_outline",
                content_template_id=template_id,
                target_question_ids=prompt_ids,
                target_city=prompt_city,
                target_platform="chatgpt/perplexity",
                target_source_type=source_type,
                used_knowledge_fact_ids=used_fact_ids,
                source_gap_types=source_gap_types,
                source_action_id=action.id,
                evidence_answer_run_ids=action.evidence_answer_run_ids,
                draft_markdown=draft_markdown,
                review_status=CONTENT_REVIEW_PENDING_STATUS,
                created_by=created_by,
                created_at=created_at,
            )
        )
    return tuple(drafts)


def build_integration_connectors(
    *,
    project_id: str,
    now: datetime | None = None,
) -> tuple[IntegrationConnector, ...]:
    created_at = now or datetime.now(UTC)
    specs = (
        ("google_search_console", ("read_search_queries", "inspect_url"), "oauth"),
        ("ga4", ("read_traffic", "read_conversions"), "oauth"),
        ("shopify", ("create_draft_page", "read_products"), "oauth"),
        ("wordpress", ("create_draft_post", "read_pages"), "oauth"),
        ("webflow", ("create_cms_draft",), "api_token"),
        ("hubspot", ("create_task", "create_landing_page_draft"), "oauth"),
        ("cloudflare", ("purge_cache", "read_zone"), "api_token"),
    )
    return tuple(
        IntegrationConnector(
            id=_stable_id("integration", project_id, provider),
            project_id=project_id,
            provider=provider,
            connection_status="planned",
            capabilities=capabilities,
            auth_mode=auth_mode,
            created_at=created_at,
        )
        for provider, capabilities, auth_mode in specs
    )


def build_manual_distribution_records(
    *,
    project_id: str,
    drafts: tuple[ContentDraft, ...],
) -> tuple[ManualDistributionRecord, ...]:
    return tuple(
        ManualDistributionRecord(
            id=_stable_id("manual-distribution", project_id, draft.id),
            project_id=project_id,
            content_draft_id=draft.id,
            platform="manual",
            target_url="",
            status=MANUAL_DISTRIBUTION_BACKFILL_REQUIRED_STATUS,
            submitted_at=None,
            checked_at=None,
            notes="Manual distribution only records URL/status after human review; no automatic publishing in Production v1.",
        )
        for draft in drafts
    )


def backfill_manual_distribution_record(
    record: ManualDistributionRecord,
    *,
    target_url: str,
    checked_at: datetime | None = None,
    notes: str | None = None,
) -> ManualDistributionRecord:
    url = target_url.strip()
    if not url:
        raise ValueError("target_url is required")
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("target_url must be http(s)")
    return ManualDistributionRecord(
        id=record.id,
        project_id=record.project_id,
        content_draft_id=record.content_draft_id,
        platform=record.platform,
        target_url=url,
        status=MANUAL_DISTRIBUTION_BACKFILLED_STATUS,
        submitted_at=record.submitted_at or checked_at or datetime.now(UTC),
        checked_at=checked_at or datetime.now(UTC),
        notes=notes.strip() if notes else record.notes,
    )


def build_content_engine_audit_event(
    *,
    project_id: str,
    facts: tuple[LocalizedKnowledgeFact, ...],
    drafts: tuple[ContentDraft, ...],
    connectors: tuple[IntegrationConnector, ...],
    distribution_records: tuple[ManualDistributionRecord, ...],
) -> AuditEvent:
    return build_audit_event(
        event_type="content_engine_fixture_created",
        project_id=project_id,
        actor_type="system",
        actor_id="geo-core.knowledge",
        target_type="content_engine_fixture",
        target_id=project_id,
        before=None,
        after={
            "knowledge_fact_count": len(facts),
            "content_draft_count": len(drafts),
            "integration_connector_count": len(connectors),
            "manual_distribution_record_count": len(distribution_records),
        },
        input_refs={
            "knowledge_fact_ids": [fact.id for fact in facts],
            "evidence_answer_run_ids": sorted(
                {answer_run_id for draft in drafts for answer_run_id in draft.evidence_answer_run_ids}
            ),
        },
        output_refs={
            "content_draft_ids": [draft.id for draft in drafts],
            "integration_connector_ids": [connector.id for connector in connectors],
            "manual_distribution_record_ids": [record.id for record in distribution_records],
        },
        method_version="content_engine_fixture_v1",
        reason="M7 evidence-backed content draft and integration planning fixture",
    )


def _select_template_id(action: ActionRecommendation) -> str:
    if action.source_gap_type == "low_mention_rate":
        return "faq_for_australian_customers"
    if action.source_gap_type == "low_recommendation_rate":
        return "comparison_table"
    if action.related_source_types and action.related_source_types[0] == "review_site":
        return "brand_review_australia"
    if action.related_source_types and action.related_source_types[0] == "comparison_site":
        return "brand_vs_competitor"
    return "how_to_choose_category_australia"


def _draft_title(template_id: str, target_brand: str, category: str, source_type: str) -> str:
    if template_id == "faq_for_australian_customers":
        return f"{target_brand} FAQ for Australian customers"
    if template_id == "comparison_table":
        return f"{target_brand} comparison proof for Australian {category}"
    if template_id == "brand_review_australia":
        return f"{target_brand} review Australia"
    if template_id == "brand_vs_competitor":
        return f"{target_brand} vs competitor evidence outline"
    return f"How to choose {category} in Australia for {source_type}"


def _render_draft_markdown(
    *,
    title: str,
    target_brand: str,
    category: str,
    action: ActionRecommendation,
    knowledge_results: tuple[KnowledgeSearchResult, ...],
    fallback_fact_ids: tuple[str, ...],
) -> str:
    fact_lines = "\n".join(
        f"- {result.fact.fact_type}: {result.fact.subject} {result.fact.predicate} {result.fact.object_value}"
        + (" (global fallback)" if result.fallback_used else "")
        for result in knowledge_results
    )
    fallback_note = (
        f"\n\nFallback facts require AU localization before publishing: {', '.join(fallback_fact_ids)}"
        if fallback_fact_ids
        else ""
    )
    return (
        f"# {title}\n\n"
        f"Purpose: address `{action.source_gap_type}` for {target_brand} in Australian {category} queries.\n\n"
        f"Evidence anchor answer_run_ids: {', '.join(action.evidence_answer_run_ids)}\n\n"
        "Knowledge facts used:\n"
        f"{fact_lines}\n\n"
        "Review checklist:\n"
        "- Confirm every claim against the linked evidence.\n"
        "- Replace global fallback facts with AU-local proof before publishing.\n"
        "- Keep as draft until a human reviewer approves it."
        f"{fallback_note}"
    )
