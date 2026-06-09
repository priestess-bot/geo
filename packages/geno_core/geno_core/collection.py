from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable
from uuid import uuid5, NAMESPACE_URL

from geno_core.audit import build_audit_event, hash_payload
from geno_core.contracts import CollectorBackend
from geno_core.geo import StaticAUGeoProvider
from geno_core.models import (
    AnswerCitation,
    AnswerRun,
    CollectionCost,
    CollectionPlan,
    CollectorLog,
    EvidenceAsset,
    MarketProfile,
    PromptQuestion,
    RawAnswer,
    RawEvidenceRecord,
)


P0A_GEO_CITIES = ("Australia", "Sydney", "Melbourne", "Brisbane")
P0A_SAMPLE_SIZE = 3
DEFAULT_DEVICE = "desktop"


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geno", kind, *(str(part) for part in parts)))))


def _enabled_p0a_platforms(market_profile: MarketProfile) -> tuple[str, ...]:
    return tuple(
        f"{platform.platform}:{platform.surface}"
        for platform in market_profile.platforms
        if platform.enabled and platform.build_stage == "P0a"
    )


def build_p0a_collection_plan(
    *,
    project_id: str,
    prompts: tuple[PromptQuestion, ...],
    market_profile: MarketProfile,
    geo_cities: tuple[str, ...] = P0A_GEO_CITIES,
    sample_size: int = P0A_SAMPLE_SIZE,
) -> CollectionPlan:
    available_cities = set(market_profile.cities)
    missing = [city for city in geo_cities if city not in available_cities]
    if missing:
        raise ValueError(f"MarketProfile missing P0a geo cities: {missing}")
    platform_surfaces = _enabled_p0a_platforms(market_profile)
    if not platform_surfaces:
        raise ValueError("No enabled P0a platforms in MarketProfile")
    return CollectionPlan(
        project_id=project_id,
        prompt_count=len(prompts),
        platform_count=len(platform_surfaces),
        geo_count=len(geo_cities),
        sample_size=sample_size,
        planned_runs=len(prompts) * len(platform_surfaces) * len(geo_cities) * sample_size,
        platform_surfaces=platform_surfaces,
        geo_cities=geo_cities,
    )


def _asset_hash(url: str | None) -> str | None:
    return hash_payload({"url": url}) if url else None


def _collector_cost(collector: CollectorBackend) -> float:
    return float(getattr(collector, "vendor_cost", 0.0))


def collect_prompt_once(
    *,
    project_id: str,
    prompt: PromptQuestion,
    market_profile: MarketProfile,
    collector: CollectorBackend,
    city: str,
    sample_index: int,
    sample_size: int,
    device: str = DEFAULT_DEVICE,
) -> RawEvidenceRecord:
    capabilities = collector.capabilities()
    geo_params = StaticAUGeoProvider().resolve(
        market_code=market_profile.market_code,
        city=city,
        language=prompt.language,
        device=device,
    )
    collected_at = datetime.now(UTC)
    result = collector.collect(
        prompt=prompt.text,
        market=market_profile,
        city=city,
        language=prompt.language,
        device=device,
    )
    answer_run_id = _stable_id(
        "answer-run",
        project_id,
        prompt.id,
        collector.id(),
        city,
        sample_index,
        sample_size,
    )
    answer_run = AnswerRun(
        id=answer_run_id,
        project_id=project_id,
        prompt_question_id=prompt.id,
        platform=str(capabilities["platform"]),
        surface=str(capabilities["surface"]),
        access_method=capabilities["access_method"],  # type: ignore[arg-type]
        market_code=market_profile.market_code,
        city=city,
        language=prompt.language,
        device=device,
        answer_present=result.answer_present,
        surface_triggered=result.surface_triggered,
        sample_index=sample_index,
        sample_size=sample_size,
        model_or_surface=result.model_or_surface,
        account_state=result.account_state,
        collector_backend_id=collector.id(),
        collector_version=result.collector_version,
        collected_at=collected_at,
        status="completed",
    )
    raw_answer = RawAnswer(
        id=_stable_id("raw-answer", answer_run_id),
        answer_run_id=answer_run_id,
        answer_text=result.answer_text,
        raw_payload=result.raw_payload,
        raw_payload_hash=hash_payload(result.raw_payload),
    )
    citations = tuple(
        AnswerCitation(
            id=_stable_id("answer-citation", answer_run_id, citation["url"], citation["position"]),
            answer_run_id=answer_run_id,
            url=str(citation["url"]),
            domain=str(citation["domain"]),
            position=int(citation["position"]),
            source_type=str(citation["source_type"]) if citation.get("source_type") else None,
        )
        for citation in result.citations
    )
    evidence_assets = tuple(
        asset
        for asset in (
            EvidenceAsset(
                id=_stable_id("evidence-asset", answer_run_id, "screenshot"),
                answer_run_id=answer_run_id,
                asset_type="screenshot",
                url=result.screenshot_url or "",
                content_hash=_asset_hash(result.screenshot_url),
            )
            if result.screenshot_url
            else None,
            EvidenceAsset(
                id=_stable_id("evidence-asset", answer_run_id, "html_snapshot"),
                answer_run_id=answer_run_id,
                asset_type="html_snapshot",
                url=result.html_snapshot_url or "",
                content_hash=_asset_hash(result.html_snapshot_url),
            )
            if result.html_snapshot_url
            else None,
        )
        if asset is not None
    )
    collector_logs = (
        CollectorLog(
            id=_stable_id("collector-log", answer_run_id, "completed"),
            answer_run_id=answer_run_id,
            collector_backend_id=collector.id(),
            event_type="collection_completed",
            payload={
                "answer_present": result.answer_present,
                "surface_triggered": result.surface_triggered,
                "citation_count": len(citations),
                "asset_count": len(evidence_assets),
                "geo_params": geo_params,
            },
            created_at=collected_at,
        ),
    )
    vendor_cost = _collector_cost(collector)
    collection_cost = CollectionCost(
        id=_stable_id("collection-cost", answer_run_id),
        answer_run_id=answer_run_id,
        project_id=project_id,
        collector_backend_id=collector.id(),
        llm_provider=str(capabilities["platform"]),
        llm_tokens=max(len(result.answer_text.split()) * 2, 1),
        llm_cost=vendor_cost,
        proxy_or_vendor_cost=vendor_cost,
        compute_cost=0.0005,
        total_cost=round(vendor_cost + 0.0005, 6),
        created_at=collected_at,
    )
    audit_events = (
        build_audit_event(
            event_type="answer_run_collected",
            project_id=project_id,
            actor_type="worker",
            actor_id=collector.id(),
            target_type="answer_run",
            target_id=answer_run_id,
            before=None,
            after={
                "answer_run_id": answer_run_id,
                "prompt_question_id": prompt.id,
                "platform": answer_run.platform,
                "surface": answer_run.surface,
                "city": city,
                "sample_index": sample_index,
                "sample_size": sample_size,
                "answer_present": result.answer_present,
                "surface_triggered": result.surface_triggered,
                "raw_payload_hash": raw_answer.raw_payload_hash,
                "geo_params": geo_params,
            },
            input_refs={"prompt_question_ids": [prompt.id]},
            output_refs={
                "answer_run_ids": [answer_run_id],
                "raw_answer_ids": [raw_answer.id],
                "answer_citation_ids": [citation.id for citation in citations],
                "evidence_asset_ids": [asset.id for asset in evidence_assets],
            },
            method_version=result.collector_version,
            reason="M2a stable evidence chain fixture collection",
        ),
    )
    return RawEvidenceRecord(
        answer_run=answer_run,
        raw_answer=raw_answer,
        citations=citations,
        evidence_assets=evidence_assets,
        collector_logs=collector_logs,
        collection_cost=collection_cost,
        audit_events=audit_events,
    )


def run_fixture_collection_slice(
    *,
    project_id: str,
    prompts: tuple[PromptQuestion, ...],
    market_profile: MarketProfile,
    collectors: Iterable[CollectorBackend],
    cities: tuple[str, ...] = ("Australia", "Sydney"),
    sample_size: int = 1,
    prompt_limit: int = 2,
) -> tuple[RawEvidenceRecord, ...]:
    selected_prompts = prompts[:prompt_limit]
    records: list[RawEvidenceRecord] = []
    for prompt in selected_prompts:
        for collector in collectors:
            for city in cities:
                for sample_index in range(1, sample_size + 1):
                    records.append(
                        collect_prompt_once(
                            project_id=project_id,
                            prompt=prompt,
                            market_profile=market_profile,
                            collector=collector,
                            city=city,
                            sample_index=sample_index,
                            sample_size=sample_size,
                        )
                    )
    return tuple(records)
