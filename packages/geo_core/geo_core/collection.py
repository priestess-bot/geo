from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter, sleep
from typing import TYPE_CHECKING, Callable, Iterable
from uuid import uuid5, NAMESPACE_URL
from urllib.parse import urlparse

from geo_core.audit import build_audit_event, hash_payload
from geo_core.contracts import CollectorBackend
from geo_core.geo import StaticAUGeoProvider
from geo_core.models import (
    AnswerCitation,
    AnswerRun,
    CollectionFailureRecord,
    CollectionCost,
    CollectionPlan,
    CollectionRunSummary,
    CollectorLog,
    EvidenceAsset,
    ManualBackfillInput,
    MarketProfile,
    P0ACollectionReadinessGate,
    PromptQuestion,
    RawAnswer,
    RawEvidenceRecord,
)

if TYPE_CHECKING:
    from geo_core.models import AuditEvent


P0A_GEO_CITIES = ("Australia", "Sydney", "Melbourne", "Brisbane")
P0A_SAMPLE_SIZE = 3
DEFAULT_DEVICE = "desktop"


@dataclass(frozen=True)
class CollectionExecutionPolicy:
    max_retries: int = 0
    retry_backoff_seconds: float = 0.0
    rate_limit_delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        if self.rate_limit_delay_seconds < 0:
            raise ValueError("rate_limit_delay_seconds must be non-negative")


DEFAULT_COLLECTION_EXECUTION_POLICY = CollectionExecutionPolicy()


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geo", kind, *(str(part) for part in parts)))))


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


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc:
        return parsed.netloc
    return url.split("//", 1)[-1].split("/", 1)[0]


def _collector_cost(collector: CollectorBackend) -> float:
    return float(getattr(collector, "vendor_cost", 0.0))


def _run_value(record: RawEvidenceRecord | CollectionFailureRecord, field: str) -> str:
    return str(getattr(record.answer_run, field) or "unknown")


def build_collection_run_summary(
    *,
    project_id: str,
    run_type: str,
    mode: str,
    planned_runs: int,
    records: tuple[RawEvidenceRecord | CollectionFailureRecord, ...],
) -> CollectionRunSummary:
    if planned_runs < 0:
        raise ValueError("planned_runs must be non-negative")
    if not records:
        now = datetime.now(UTC)
        return CollectionRunSummary(
            id=_stable_id("collection-run", project_id, run_type, mode, planned_runs, "empty"),
            project_id=project_id,
            run_type=run_type,
            mode=mode,
            planned_runs=planned_runs,
            attempted_runs=0,
            success_count=0,
            failure_count=0,
            success_rate=0.0,
            trigger_rate=0.0,
            answer_present_rate=0.0,
            total_cost=0.0,
            average_cost_per_run=0.0,
            total_duration_ms=0,
            average_duration_ms=0,
            collector_backend_ids=(),
            platform_distribution={},
            city_distribution={},
            access_method_distribution={},
            failure_summary={},
            answer_run_ids=(),
            started_at=now,
            completed_at=now,
            created_at=now,
        )
    attempted_runs = len(records)
    successes = tuple(record for record in records if isinstance(record, RawEvidenceRecord))
    failures = tuple(record for record in records if isinstance(record, CollectionFailureRecord))
    answer_run_ids = tuple(record.answer_run.id for record in records)
    started_at = min(record.answer_run.collected_at for record in records)
    completed_at = max(record.answer_run.collected_at for record in records)
    total_cost = round(sum(float(record.collection_cost.total_cost) for record in records), 6)
    total_duration_ms = sum(int(record.collection_cost.duration_ms) for record in records)
    trigger_rate = sum(1 for record in records if record.answer_run.surface_triggered) / attempted_runs
    answer_present_rate = sum(1 for record in records if record.answer_run.answer_present) / attempted_runs
    failure_summary = Counter(
        record.error_message or record.error_type
        for record in failures
    )
    return CollectionRunSummary(
        id=_stable_id("collection-run", project_id, run_type, mode, planned_runs, *answer_run_ids),
        project_id=project_id,
        run_type=run_type,
        mode=mode,
        planned_runs=planned_runs,
        attempted_runs=attempted_runs,
        success_count=len(successes),
        failure_count=len(failures),
        success_rate=round(len(successes) / attempted_runs, 4),
        trigger_rate=round(trigger_rate, 4),
        answer_present_rate=round(answer_present_rate, 4),
        total_cost=total_cost,
        average_cost_per_run=round(total_cost / attempted_runs, 6),
        total_duration_ms=total_duration_ms,
        average_duration_ms=round(total_duration_ms / attempted_runs),
        collector_backend_ids=tuple(sorted({_run_value(record, "collector_backend_id") for record in records})),
        platform_distribution=dict(sorted(Counter(_run_value(record, "platform") for record in records).items())),
        city_distribution=dict(sorted(Counter(_run_value(record, "city") for record in records).items())),
        access_method_distribution=dict(sorted(Counter(_run_value(record, "access_method") for record in records).items())),
        failure_summary=dict(sorted(failure_summary.items())),
        answer_run_ids=answer_run_ids,
        started_at=started_at,
        completed_at=completed_at,
        created_at=datetime.now(UTC),
    )


def build_collection_run_audit_event(summary: CollectionRunSummary) -> "AuditEvent":
    return build_audit_event(
        event_type="collection_run_summarized",
        project_id=summary.project_id,
        actor_type="worker",
        actor_id="collector_worker",
        target_type="collection_run",
        target_id=summary.id,
        before=None,
        after={
            "collection_run_id": summary.id,
            "run_type": summary.run_type,
            "mode": summary.mode,
            "planned_runs": summary.planned_runs,
            "attempted_runs": summary.attempted_runs,
            "success_count": summary.success_count,
            "failure_count": summary.failure_count,
            "success_rate": summary.success_rate,
            "trigger_rate": summary.trigger_rate,
            "answer_present_rate": summary.answer_present_rate,
            "total_cost": summary.total_cost,
            "average_cost_per_run": summary.average_cost_per_run,
            "total_duration_ms": summary.total_duration_ms,
            "average_duration_ms": summary.average_duration_ms,
            "failure_summary": summary.failure_summary,
        },
        input_refs={"answer_run_ids": list(summary.answer_run_ids)},
        output_refs={"collection_run_ids": [summary.id]},
        method_version="collection_run_summary_v1",
        reason="Summarize collection run quality, cost, and failure rates for audit and reporting",
    )


P0A_REQUIRED_PLATFORMS = ("chatgpt", "perplexity")
P0A_REQUIRED_METADATA_FIELDS = (
    "platform",
    "surface",
    "access_method",
    "city",
    "language",
    "device",
    "collected_at",
    "collector_version",
    "collector_backend_id",
)


def evaluate_p0a_collection_readiness(
    *,
    records: tuple[RawEvidenceRecord | CollectionFailureRecord, ...],
    required_platforms: tuple[str, ...] = P0A_REQUIRED_PLATFORMS,
    required_sample_size: int = P0A_SAMPLE_SIZE,
) -> P0ACollectionReadinessGate:
    successes = tuple(record for record in records if isinstance(record, RawEvidenceRecord))
    failures = tuple(record for record in records if isinstance(record, CollectionFailureRecord))
    observed_platforms = tuple(
        sorted({_run_value(record, "platform") for record in records if _run_value(record, "platform") != "unknown"})
    )
    observed_sample_sizes = tuple(sorted({int(record.answer_run.sample_size) for record in records}))
    missing_metadata_fields: dict[str, tuple[str, ...]] = {}
    records_without_answer_flags: list[str] = []
    records_below_sample_size: list[str] = []
    for record in records:
        answer_run = record.answer_run
        missing = tuple(
            field
            for field in P0A_REQUIRED_METADATA_FIELDS
            if getattr(answer_run, field) is None or str(getattr(answer_run, field)).strip() == ""
        )
        if missing:
            missing_metadata_fields[answer_run.id] = missing
        if answer_run.answer_present is None or answer_run.surface_triggered is None:
            records_without_answer_flags.append(answer_run.id)
        if int(answer_run.sample_size) < required_sample_size:
            records_below_sample_size.append(answer_run.id)
    records_without_citations = tuple(record.answer_run.id for record in successes if not record.citations)
    records_without_evidence_assets = tuple(
        record.answer_run.id
        for record in successes
        if not {asset.asset_type for asset in record.evidence_assets} & {"screenshot", "html_snapshot"}
    )
    failure_reasons: list[str] = []
    missing_platforms = tuple(platform for platform in required_platforms if platform not in observed_platforms)
    if missing_platforms:
        failure_reasons.append(f"missing_platforms={','.join(missing_platforms)}")
    if failures:
        failure_reasons.append(f"collection_failures={len(failures)}")
    if missing_metadata_fields:
        failure_reasons.append(f"missing_metadata_records={len(missing_metadata_fields)}")
    if records_without_answer_flags:
        failure_reasons.append(f"missing_answer_flags={len(records_without_answer_flags)}")
    if records_below_sample_size:
        failure_reasons.append(f"below_required_sample_size={len(records_below_sample_size)}")
    if records_without_citations:
        failure_reasons.append(f"records_without_citations={len(records_without_citations)}")
    if records_without_evidence_assets:
        failure_reasons.append(f"records_without_evidence_assets={len(records_without_evidence_assets)}")
    return P0ACollectionReadinessGate(
        gate_status="pass" if not failure_reasons and bool(records) else "fail",
        required_platforms=required_platforms,
        observed_platforms=observed_platforms,
        required_sample_size=required_sample_size,
        observed_sample_sizes=observed_sample_sizes,
        attempted_runs=len(records),
        success_count=len(successes),
        failure_count=len(failures),
        missing_metadata_fields=missing_metadata_fields,
        records_without_citations=records_without_citations,
        records_without_evidence_assets=records_without_evidence_assets,
        records_without_answer_flags=tuple(records_without_answer_flags),
        records_below_sample_size=tuple(records_below_sample_size),
        failure_reasons=tuple(failure_reasons),
    )


def build_manual_backfill_record(backfill: ManualBackfillInput) -> RawEvidenceRecord:
    collected_at = backfill.collected_at or datetime.now(UTC)
    answer_run_id = _stable_id(
        "answer-run-manual-backfill",
        backfill.project_id,
        backfill.prompt_question_id,
        backfill.platform,
        backfill.surface,
        backfill.city,
        backfill.sample_index,
        backfill.sample_size,
        backfill.answer_text,
    )
    collector_backend_id = f"{backfill.platform}.manual_backfill"
    raw_payload = {
        "prompt": backfill.prompt_text,
        "project_id": backfill.project_id,
        "prompt_question_id": backfill.prompt_question_id,
        "market_code": backfill.market_code,
        "city": backfill.city,
        "language": backfill.language,
        "device": backfill.device,
        "platform": backfill.platform,
        "surface": backfill.surface,
        "answer_present": backfill.answer_present,
        "surface_triggered": backfill.surface_triggered,
        "citation_urls": list(backfill.citation_urls),
        "screenshot_url": backfill.screenshot_url,
        "html_snapshot_url": backfill.html_snapshot_url,
        "submitted_by": backfill.submitted_by,
        "notes": backfill.notes,
        "source": "manual_backfill",
    }
    answer_run = AnswerRun(
        id=answer_run_id,
        project_id=backfill.project_id,
        prompt_question_id=backfill.prompt_question_id,
        platform=backfill.platform,
        surface=backfill.surface,
        access_method="manual",
        market_code=backfill.market_code,
        city=backfill.city,
        language=backfill.language,
        device=backfill.device,
        answer_present=backfill.answer_present,
        surface_triggered=backfill.surface_triggered,
        sample_index=backfill.sample_index,
        sample_size=backfill.sample_size,
        model_or_surface="manual_backfill",
        account_state=backfill.account_state,
        collector_backend_id=collector_backend_id,
        collector_version="manual_backfill_v1",
        collected_at=collected_at,
        status="completed",
    )
    raw_answer = RawAnswer(
        id=_stable_id("raw-answer", answer_run_id),
        answer_run_id=answer_run_id,
        answer_text=backfill.answer_text,
        raw_payload=raw_payload,
        raw_payload_hash=hash_payload(raw_payload),
    )
    citations = tuple(
        AnswerCitation(
            id=_stable_id("answer-citation", answer_run_id, url, index),
            answer_run_id=answer_run_id,
            url=url,
            domain=_extract_domain(url),
            position=index,
            source_type="manual_source",
        )
        for index, url in enumerate(backfill.citation_urls, start=1)
        if url
    )
    evidence_assets = tuple(
        asset
        for asset in (
            EvidenceAsset(
                id=_stable_id("evidence-asset", answer_run_id, "screenshot"),
                answer_run_id=answer_run_id,
                asset_type="screenshot",
                url=backfill.screenshot_url or "",
                content_hash=_asset_hash(backfill.screenshot_url),
            )
            if backfill.screenshot_url
            else None,
            EvidenceAsset(
                id=_stable_id("evidence-asset", answer_run_id, "html_snapshot"),
                answer_run_id=answer_run_id,
                asset_type="html_snapshot",
                url=backfill.html_snapshot_url or "",
                content_hash=_asset_hash(backfill.html_snapshot_url),
            )
            if backfill.html_snapshot_url
            else None,
        )
        if asset is not None
    )
    collector_logs = (
        CollectorLog(
            id=_stable_id("collector-log", answer_run_id, "manual-backfill"),
            answer_run_id=answer_run_id,
            collector_backend_id=collector_backend_id,
            event_type="manual_backfill_recorded",
            payload={
                "submitted_by": backfill.submitted_by,
                "notes": backfill.notes,
                "citation_count": len(citations),
                "asset_count": len(evidence_assets),
            },
            created_at=collected_at,
        ),
    )
    collection_cost = CollectionCost(
        id=_stable_id("collection-cost", answer_run_id),
        answer_run_id=answer_run_id,
        project_id=backfill.project_id,
        collector_backend_id=collector_backend_id,
        llm_provider=None,
        llm_tokens=0,
        llm_cost=0.0,
        proxy_or_vendor_cost=0.0,
        compute_cost=0.0,
        total_cost=0.0,
        duration_ms=0,
        created_at=collected_at,
    )
    audit_events = (
        build_audit_event(
            event_type="manual_backfill_recorded",
            project_id=backfill.project_id,
            actor_type="user",
            actor_id=backfill.submitted_by,
            target_type="answer_run",
            target_id=answer_run_id,
            before=None,
            after={
                "answer_run_id": answer_run_id,
                "prompt_question_id": backfill.prompt_question_id,
                "platform": backfill.platform,
                "surface": backfill.surface,
                "city": backfill.city,
                "sample_index": backfill.sample_index,
                "sample_size": backfill.sample_size,
                "answer_present": backfill.answer_present,
                "surface_triggered": backfill.surface_triggered,
                "raw_payload_hash": raw_answer.raw_payload_hash,
                "citation_count": len(citations),
                "asset_count": len(evidence_assets),
                "notes": backfill.notes,
            },
            input_refs={"prompt_question_ids": [backfill.prompt_question_id]},
            output_refs={
                "answer_run_ids": [answer_run_id],
                "raw_answer_ids": [raw_answer.id],
                "answer_citation_ids": [citation.id for citation in citations],
                "evidence_asset_ids": [asset.id for asset in evidence_assets],
            },
            method_version="manual_backfill_v1",
            reason="manual answer backfill converted into auditable raw evidence",
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
    started_counter = perf_counter()
    result = collector.collect(
        prompt=prompt.text,
        market=market_profile,
        city=city,
        language=prompt.language,
        device=device,
    )
    duration_ms = max(0, round((perf_counter() - started_counter) * 1000))
    collected_at = datetime.now(UTC)
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
                content_hash=(result.evidence_asset_hashes or {}).get("screenshot") or _asset_hash(result.screenshot_url),
            )
            if result.screenshot_url
            else None,
            EvidenceAsset(
                id=_stable_id("evidence-asset", answer_run_id, "html_snapshot"),
                answer_run_id=answer_run_id,
                asset_type="html_snapshot",
                url=result.html_snapshot_url or "",
                content_hash=(result.evidence_asset_hashes or {}).get("html_snapshot") or _asset_hash(result.html_snapshot_url),
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
                "asset_types": [asset.asset_type for asset in evidence_assets],
                "geo_params": geo_params,
                "duration_ms": duration_ms,
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
        duration_ms=duration_ms,
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
                "duration_ms": duration_ms,
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


def collect_prompt_with_failure_record(
    *,
    project_id: str,
    prompt: PromptQuestion,
    market_profile: MarketProfile,
    collector: CollectorBackend,
    city: str,
    sample_index: int,
    sample_size: int,
    device: str = DEFAULT_DEVICE,
    execution_policy: CollectionExecutionPolicy = DEFAULT_COLLECTION_EXECUTION_POLICY,
    sleep_fn: Callable[[float], None] = sleep,
) -> RawEvidenceRecord | CollectionFailureRecord:
    started_counter = perf_counter()
    retry_errors: list[dict[str, str | int]] = []
    attempt_count = 0
    try:
        last_error: Exception | None = None
        for attempt_index in range(execution_policy.max_retries + 1):
            attempt_count = attempt_index + 1
            try:
                record = collect_prompt_once(
                    project_id=project_id,
                    prompt=prompt,
                    market_profile=market_profile,
                    collector=collector,
                    city=city,
                    sample_index=sample_index,
                    sample_size=sample_size,
                    device=device,
                )
                if attempt_count > 1 or retry_errors:
                    total_duration_ms = max(0, round((perf_counter() - started_counter) * 1000))
                    completed_log = record.collector_logs[0]
                    retry_payload = {
                        **completed_log.payload,
                        "duration_ms": total_duration_ms,
                        "attempt_count": attempt_count,
                        "retry_errors": retry_errors,
                    }
                    retry_log = replace(completed_log, payload=retry_payload)
                    retry_cost = replace(record.collection_cost, duration_ms=total_duration_ms)
                    retry_audit = build_audit_event(
                        event_type="collection_retry_succeeded",
                        project_id=project_id,
                        actor_type="worker",
                        actor_id=collector.id(),
                        target_type="answer_run",
                        target_id=record.answer_run.id,
                        before=None,
                        after={
                            "answer_run_id": record.answer_run.id,
                            "prompt_question_id": prompt.id,
                            "collector_backend_id": collector.id(),
                            "city": city,
                            "sample_index": sample_index,
                            "sample_size": sample_size,
                            "attempt_count": attempt_count,
                            "retry_errors": retry_errors,
                            "duration_ms": total_duration_ms,
                        },
                        input_refs={"prompt_question_ids": [prompt.id]},
                        output_refs={"answer_run_ids": [record.answer_run.id]},
                        method_version="collection_retry_policy_v1",
                        reason="Collection succeeded after retry attempts",
                    )
                    return RawEvidenceRecord(
                        answer_run=record.answer_run,
                        raw_answer=record.raw_answer,
                        citations=record.citations,
                        evidence_assets=record.evidence_assets,
                        collector_logs=(retry_log,),
                        collection_cost=retry_cost,
                        audit_events=record.audit_events + (retry_audit,),
                    )
                return record
            except Exception as exc:  # noqa: BLE001 - heterogeneous collector failures are retried uniformly.
                last_error = exc
                if attempt_index >= execution_policy.max_retries:
                    raise
                retry_errors.append(
                    {
                        "attempt": attempt_count,
                        "error_type": exc.__class__.__name__,
                        "error_message": str(exc),
                    }
                )
                if execution_policy.retry_backoff_seconds > 0:
                    sleep_fn(execution_policy.retry_backoff_seconds * (2**attempt_index))
        if last_error is not None:
            raise last_error
        raise RuntimeError("unreachable collection retry state")
    except Exception as exc:  # noqa: BLE001 - failures must be converted into audit records.
        duration_ms = max(0, round((perf_counter() - started_counter) * 1000))
        capabilities = collector.capabilities()
        collected_at = datetime.now(UTC)
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
            answer_present=False,
            surface_triggered=False,
            sample_index=sample_index,
            sample_size=sample_size,
            model_or_surface=None,
            account_state=None,
            collector_backend_id=collector.id(),
            collector_version="unavailable",
            collected_at=collected_at,
            status="failed",
        )
        error_type = exc.__class__.__name__
        error_message = str(exc)
        collector_logs = (
            CollectorLog(
                id=_stable_id("collector-log", answer_run_id, "failed"),
                answer_run_id=answer_run_id,
                collector_backend_id=collector.id(),
                event_type="collection_failed",
                payload={
                    "error_type": error_type,
                    "error_message": error_message,
                    "duration_ms": duration_ms,
                    "attempt_count": attempt_count or 1,
                    "retry_errors": retry_errors,
                    "max_retries": execution_policy.max_retries,
                },
                created_at=collected_at,
            ),
        )
        collection_cost = CollectionCost(
            id=_stable_id("collection-cost", answer_run_id),
            answer_run_id=answer_run_id,
            project_id=project_id,
            collector_backend_id=collector.id(),
            llm_provider=str(capabilities["platform"]),
            llm_tokens=0,
            llm_cost=0.0,
            proxy_or_vendor_cost=0.0,
            compute_cost=0.0001,
            total_cost=0.0001,
            duration_ms=duration_ms,
            created_at=collected_at,
        )
        audit_events = (
            build_audit_event(
                event_type="answer_run_failed",
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
                    "error_type": error_type,
                    "error_message": error_message,
                    "duration_ms": duration_ms,
                    "attempt_count": attempt_count or 1,
                    "retry_errors": retry_errors,
                    "max_retries": execution_policy.max_retries,
                },
                input_refs={"prompt_question_ids": [prompt.id]},
                output_refs={"answer_run_ids": [answer_run_id]},
                method_version="collector_failure_v1+retry_policy_v1"
                if execution_policy.max_retries
                else "collector_failure_v1",
                reason="M2a collection failure converted into auditable evidence record",
            ),
        )
        return CollectionFailureRecord(
            answer_run=answer_run,
            collector_logs=collector_logs,
            collection_cost=collection_cost,
            audit_events=audit_events,
            error_type=error_type,
            error_message=error_message,
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
    execution_policy: CollectionExecutionPolicy = DEFAULT_COLLECTION_EXECUTION_POLICY,
    sleep_fn: Callable[[float], None] = sleep,
) -> tuple[RawEvidenceRecord, ...]:
    records = run_collection_slice(
        project_id=project_id,
        prompts=prompts,
        market_profile=market_profile,
        collectors=collectors,
        cities=cities,
        sample_size=sample_size,
        prompt_limit=prompt_limit,
        execution_policy=execution_policy,
        sleep_fn=sleep_fn,
    )
    return tuple(record for record in records if isinstance(record, RawEvidenceRecord))


def run_collection_slice(
    *,
    project_id: str,
    prompts: tuple[PromptQuestion, ...],
    market_profile: MarketProfile,
    collectors: Iterable[CollectorBackend],
    cities: tuple[str, ...] = ("Australia", "Sydney"),
    sample_size: int = 1,
    prompt_limit: int = 2,
    execution_policy: CollectionExecutionPolicy = DEFAULT_COLLECTION_EXECUTION_POLICY,
    sleep_fn: Callable[[float], None] = sleep,
) -> tuple[RawEvidenceRecord | CollectionFailureRecord, ...]:
    selected_prompts = prompts[:prompt_limit]
    records: list[RawEvidenceRecord | CollectionFailureRecord] = []
    for prompt in selected_prompts:
        for collector in collectors:
            for city in cities:
                for sample_index in range(1, sample_size + 1):
                    if records and execution_policy.rate_limit_delay_seconds > 0:
                        sleep_fn(execution_policy.rate_limit_delay_seconds)
                    result = collect_prompt_with_failure_record(
                        project_id=project_id,
                        prompt=prompt,
                        market_profile=market_profile,
                        collector=collector,
                        city=city,
                        sample_index=sample_index,
                        sample_size=sample_size,
                        execution_policy=execution_policy,
                        sleep_fn=sleep_fn,
                    )
                    records.append(result)
    return tuple(records)
