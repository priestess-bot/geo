from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from geno_core.audit import build_audit_event
from geno_core.action_plan import (
    build_action_plan_audit_event,
    build_action_recommendations,
    build_retest_comparison_audit_event,
    build_retest_schedule,
    compare_retest_windows,
)
from geno_core.analysis_pipeline import analyze_and_score_records, build_score_input_policy, select_score_input_records
from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import (
    CollectionExecutionPolicy,
    build_collection_run_audit_event,
    build_collection_run_summary,
    run_collection_slice,
    evaluate_p0a_collection_readiness,
)
from geno_core.collectors import (
    DeepSeekChatCollector,
    FixtureChatGPTSearchBrowserCollector,
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
    FixtureThirdPartySerpCollector,
    ManualBackfillCollector,
    OpenAIWebSearchCollector,
    PerplexitySonarCollector,
    PlaywrightChatGPTSearchCollector,
    PlaywrightGoogleAIOCollector,
    ThirdPartySerpCollector,
)
from geno_core.contracts import CollectorBackend
from geno_core.graph import build_citation_graph
from geno_core.fidelity import build_runtime_fidelity_check_from_records
from geno_core.fidelity_schedule import build_browser_fidelity_sampling_plan
from geno_core.google_spike import (
    build_google_spike_plan,
    evaluate_google_spike_gate,
    evaluate_google_spike_readiness_gate,
    select_google_spike_prompts,
)
from geno_core.llm_gateway import LiteLLMGateway
from geno_core.models import (
    BrandEntity,
    CollectionFailureRecord,
    CompetitorEntity,
    IndustryProfile,
    MarketProfile,
    PlatformConfig,
    Project,
    ProjectBootstrap,
    ProjectMember,
    PromptQuestion,
    RawEvidenceRecord,
    Tenant,
)
from geno_core.object_store import (
    archive_api_snapshot_assets,
    archive_browser_capture_assets,
    archive_report_artifacts,
)
from geno_core.parser import ComparativeAnswerParser, LLMJudgeAnswerParser
from geno_core.knowledge import (
    build_content_drafts,
    build_content_engine_audit_event,
    build_integration_connectors,
    build_localized_knowledge_facts,
    build_manual_distribution_records,
    search_knowledge_facts,
)
from geno_core.report import MarkdownCsvReportExporter
from geno_core.runtime import (
    RuntimePersistenceError,
    build_object_store_from_env,
    build_repository_from_env,
    close_repository_connection,
)
from geno_core.traceability import build_traceability_bundle


def _tuple_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _datetime_value(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(UTC)
    return datetime.now(UTC)


def _prompt_from_record(record: dict[str, object]) -> PromptQuestion:
    return PromptQuestion(
        id=str(record["id"]),
        project_id=str(record["project_id"]),
        market_code=str(record.get("market_code") or "GLOBAL"),
        industry_code=str(record.get("industry_code") or "general"),
        text=str(record.get("text") or record.get("prompt_text") or ""),
        intent_type=str(record.get("intent_type") or "brand_awareness"),
        city=str(record.get("city") or "Global"),
        language=str(record.get("language") or "en"),
        target_brand=str(record.get("target_brand") or ""),
        competitors=_tuple_strings(record.get("competitors")),
        priority=int(record.get("priority") or 0),
        intent_weight=float(record.get("intent_weight") or 1.0),
        prompt_version=str(record.get("prompt_version") or "project_prompts_v1"),
        status=str(record.get("status") or "active"),
    )


def _load_runtime_project_bootstrap(project_id: str) -> ProjectBootstrap:
    repository = build_repository_from_env()
    try:
        project_page = repository.list_runtime_projects(project_id=project_id, include_archived=True, limit=1, offset=0)
        if project_page.total_count < 1 or not project_page.records:
            raise RuntimePersistenceError(f"project not found: {project_id}")
        record = project_page.records[0]
        project_row = record.project
        tenant_row = record.tenant
        brand_row = record.brand
        if not brand_row:
            raise RuntimePersistenceError(f"project brand entity not found: {project_id}")
        active_competitors = tuple(
            competitor
            for competitor in record.competitors
            if str(competitor.get("status") or "active") in {"active", "paused"}
        )
        if len(active_competitors) < 3 or len(active_competitors) > 5:
            raise RuntimePersistenceError("runtime project must have 3-5 active or paused competitors before collection")
        prompt_page = repository.list_runtime_prompts(project_id=project_id, status="active", limit=200, offset=0)
        prompts = tuple(_prompt_from_record(prompt) for prompt in prompt_page.records)
        if not prompts:
            raise RuntimePersistenceError(f"project has no active prompts: {project_id}")
        get_launch_config = getattr(repository, "get_project_launch_config", None)
        launch_record = get_launch_config(project_id=project_id) if callable(get_launch_config) else None
        launch_config = launch_record.launch_config if launch_record is not None else {}
    finally:
        close_repository_connection(repository)
    market_code = str(project_row.get("market_code") or launch_config.get("country_code") or "GLOBAL")
    locale = str(launch_config.get("locale") or prompts[0].language or "en")
    timezone = str(launch_config.get("timezone") or "UTC")
    metadata = launch_config.get("metadata") if isinstance(launch_config.get("metadata"), dict) else {}
    cities = list(dict.fromkeys(prompt.city for prompt in prompts if prompt.city)) or [market_code]
    market_profile = MarketProfile(
        market=str(metadata.get("market_name") or market_code),
        market_code=market_code,
        locale=locale,
        timezone=timezone,
        currency=str(metadata.get("currency") or "USD"),
        primary_language=str(metadata.get("primary_language") or locale),
        cities=cities,
        source_types=[],
        platforms=[
            PlatformConfig("deepseek", "chat_completions", "production_v1", 1.0, True),
            PlatformConfig("chatgpt", "chatgpt_search", "production_v1", 0.0, False),
            PlatformConfig("perplexity", "sonar", "production_v1", 0.0, False),
            PlatformConfig("google", "google_ai_mode", "production_v1", 0.0, False),
        ],
    )
    industry_code = str(project_row.get("industry_code") or "general")
    industry_profile = IndustryProfile(
        market_code=market_code,
        industry_code=industry_code,
        display_name=str(metadata.get("industry_name") or industry_code),
        default_prompt_templates=(),
        source_type_weights={},
        competitor_fields=("canonical_name", "official_domains", "product_lines"),
        required_local_facts=(),
        report_template="geo_visibility_v1",
    )
    project = Project(
        id=str(project_row["id"]),
        tenant_id=str(project_row["tenant_id"]),
        name=str(project_row.get("name") or ""),
        market_code=str(project_row.get("market_code") or market_profile.market_code),
        industry_code=str(project_row.get("industry_code") or industry_profile.industry_code),
        target_brand=str(project_row.get("target_brand") or brand_row.get("canonical_name") or ""),
        category=str(project_row.get("category") or ""),
        prompt_version=str(project_row.get("prompt_version") or "project_prompts_v1"),
        status=str(project_row.get("status") or "paused"),
        created_at=_datetime_value(project_row.get("created_at")),
    )
    tenant = Tenant(
        id=str(tenant_row["id"]),
        name=str(tenant_row.get("name") or ""),
        slug=str(tenant_row.get("slug") or ""),
        created_at=_datetime_value(tenant_row.get("created_at")),
    )
    brand = BrandEntity(
        id=str(brand_row["id"]),
        project_id=str(brand_row["project_id"]),
        canonical_name=str(brand_row.get("canonical_name") or project.target_brand),
        official_domains=_tuple_strings(brand_row.get("official_domains")),
        parent_company=str(brand_row["parent_company"]) if brand_row.get("parent_company") else None,
        product_lines=_tuple_strings(brand_row.get("product_lines")),
        status=str(brand_row.get("status") or "active"),
    )
    competitors = tuple(
        CompetitorEntity(
            id=str(competitor["id"]),
            project_id=str(competitor["project_id"]),
            canonical_name=str(competitor.get("canonical_name") or ""),
            official_domains=_tuple_strings(competitor.get("official_domains")),
            parent_company=str(competitor["parent_company"]) if competitor.get("parent_company") else None,
            product_lines=_tuple_strings(competitor.get("product_lines")),
            status=str(competitor.get("status") or "active"),
        )
        for competitor in active_competitors
    )
    return ProjectBootstrap(
        tenant=tenant,
        project=project,
        members=(
            ProjectMember(
                id=f"runtime-worker-member-{project.id}",
                project_id=project.id,
                user_id="runtime-worker",
                role="owner",
                created_at=datetime.now(UTC),
            ),
        ),
        brand=brand,
        competitors=competitors,
        market_profile=market_profile,
        industry_profile=industry_profile,
        prompt_questions=prompts,
        audit_events=(),
    )


def _configured_project_collectors(project_id: str) -> tuple[CollectorBackend, ...]:
    repository = build_repository_from_env()
    try:
        launch_record = repository.get_project_launch_config(project_id=project_id)
        if launch_record is None:
            raise RuntimePersistenceError(f"project launch config not found: {project_id}")
        launch = launch_record.launch_config
        configured = launch.get("external_connectors") if isinstance(launch.get("external_connectors"), dict) else {}
        collectors: list[CollectorBackend] = []
        seen_ids: set[str] = set()
        for provider in ("openai", "perplexity"):
            config = configured.get(provider) if isinstance(configured.get(provider), dict) else {}
            status = str(config.get("status") or "not_configured").strip().lower()
            mode = str(config.get("mode") or "official_api").strip().lower()
            if status not in {"active", "ready"} or mode == "disabled":
                continue
            secret_ref = str(config.get("secret_ref") or "").strip()
            if not secret_ref:
                raise RuntimePersistenceError(f"{provider} connector has no secret_ref")
            api_key = repository.resolve_connector_secret(secret_ref=secret_ref)
            model = str(config.get("model") or "").strip()
            if mode == "deepseek_fallback":
                collector: CollectorBackend = DeepSeekChatCollector(
                    api_key=api_key,
                    model=model or "deepseek-v4-flash",
                )
            elif provider == "openai":
                collector = OpenAIWebSearchCollector(api_key=api_key, model=model or "gpt-4.1-mini")
            else:
                collector = PerplexitySonarCollector(api_key=api_key, model=model or "sonar")
            if collector.id() not in seen_ids:
                seen_ids.add(collector.id())
                collectors.append(collector)
        if not collectors:
            raise RuntimePersistenceError("project has no active API connector with a saved secret_ref")
        return tuple(collectors)
    finally:
        close_repository_connection(repository)


def _collectors(mode: str, *, project_id: str | None = None) -> tuple[CollectorBackend, ...]:
    if mode == "fixture":
        return (FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector())
    if mode == "api":
        if project_id:
            return _configured_project_collectors(project_id)
        return (PerplexitySonarCollector(), OpenAIWebSearchCollector())
    if mode == "deepseek":
        return (DeepSeekChatCollector(),)
    if mode == "google-fixture":
        return (FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector())
    if mode == "google-spike":
        return (PlaywrightGoogleAIOCollector(), ManualBackfillCollector())
    if mode == "google-serp-fixture":
        return (FixtureThirdPartySerpCollector(),)
    if mode == "google-serp-spike":
        return (ThirdPartySerpCollector(),)
    raise ValueError(f"Unsupported collector mode: {mode}")


def _fidelity_fixture_collectors(mode: str) -> tuple[CollectorBackend, ...]:
    if mode == "fixture":
        return (FixtureChatGPTSearchBrowserCollector(),)
    return ()


def _fidelity_playwright_collectors(mode: str) -> tuple[CollectorBackend, ...]:
    if mode == "api":
        return (PlaywrightChatGPTSearchCollector(),)
    return ()


def _collector_health_report(collectors: tuple[CollectorBackend, ...]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "collector_backend_id": collector.id(),
            "health": collector.health(),
            "capabilities": collector.capabilities(),
        }
        for collector in collectors
    )


def _collector_health_failure_reasons(collector_health: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    ready_statuses = {"ready", "fixture_ready"}
    return tuple(
        f"{item['collector_backend_id']}:{item['health']}"
        for item in collector_health
        if item["health"] not in ready_statuses
    )


def _gate_field(gate: object | None, field: str) -> object | None:
    if gate is None:
        return None
    if isinstance(gate, dict):
        return gate.get(field)
    return getattr(gate, field, None)


def _string_tuple(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple | list):
        return tuple(str(item) for item in value)
    return (str(value),)


def _google_serp_comparison_plan(*, google_plan: object | None) -> dict[str, object] | None:
    if google_plan is None:
        return None
    prompt_count = int(getattr(google_plan, "prompt_count", 0))
    geo_cities = tuple(str(city) for city in getattr(google_plan, "geo_cities", ()))
    sample_size = int(getattr(google_plan, "sample_size", 0))
    planned_runs = prompt_count * len(geo_cities) * sample_size
    return {
        "comparison_version": "google_serp_comparison_plan_v1",
        "surface": "google_aio",
        "access_method": "third_party_api",
        "collector_backend_id": "google.third_party_serp",
        "prompt_count": prompt_count,
        "geo_cities": geo_cities,
        "sample_size": sample_size,
        "planned_runs": planned_runs,
        "main_google_spike_planned_runs": int(getattr(google_plan, "planned_runs", 0)),
        "score_input_policy": "comparison evidence only until merged with full GoogleSpikeGateResult and GoogleSpikeReadinessGate",
    }


def _google_serp_comparison_summary(
    *,
    records: tuple[RawEvidenceRecord | CollectionFailureRecord, ...],
    comparison_plan: dict[str, object] | None,
) -> dict[str, object] | None:
    if comparison_plan is None:
        return None
    successes = tuple(record for record in records if isinstance(record, RawEvidenceRecord))
    failures = tuple(record for record in records if isinstance(record, CollectionFailureRecord))
    triggered_runs = sum(1 for record in successes if record.answer_run.surface_triggered)
    answer_present_runs = sum(1 for record in successes if record.answer_run.answer_present)
    asset_runs = sum(
        1
        for record in successes
        if any(asset.asset_type in {"screenshot", "html_snapshot"} for asset in record.evidence_assets)
    )
    planned_runs = int(comparison_plan["planned_runs"])
    return {
        "comparison_version": "google_serp_comparison_summary_v1",
        "planned_runs": planned_runs,
        "attempted_runs": len(records),
        "completed_runs": len(successes),
        "failure_count": len(failures),
        "success_rate": round(len(successes) / len(records), 4) if records else 0.0,
        "surface_trigger_rate": round(triggered_runs / len(successes), 4) if successes else 0.0,
        "answer_present_rate": round(answer_present_runs / len(successes), 4) if successes else 0.0,
        "screenshot_or_html_runs": asset_runs,
        "ready_for_comparison": bool(records) and len(records) == planned_runs and not failures and asset_runs == len(successes),
        "failure_summary": dict(Counter(str(record.error_message or record.error_type) for record in failures)),
        "score_input_policy": comparison_plan["score_input_policy"],
    }


def _provider_preflight_next_action(
    *,
    collector_health_status: str,
    p0a_readiness_status: str | None,
    failure_count: int,
    exit_code: int,
    ready_for_design_partner: bool,
) -> str:
    if ready_for_design_partner:
        return "promote_to_small_real_au_batch"
    if collector_health_status != "pass":
        return "configure_missing_provider_credentials_or_collectors"
    if exit_code == 5 or failure_count:
        return "inspect_collection_failures_before_design_partner"
    if exit_code == 4 or p0a_readiness_status == "fail":
        return "inspect_p0a_readiness_failure_reasons_before_design_partner"
    return "inspect_preflight_output"


def _build_preflight_summary(
    *,
    mode: str,
    phase: str,
    exit_code: int,
    planned_runs: int,
    record_count: int,
    success_count: int,
    failure_count: int,
    cities: tuple[str, ...],
    sample_size: int,
    prompt_limit: int,
    collector_health_gate: dict[str, object],
    p0a_readiness_gate: object | None,
    persistence: dict[str, object],
    output_path: str | None,
) -> dict[str, object]:
    collector_health_status = str(collector_health_gate.get("gate_status", "unknown"))
    p0a_readiness_status_value = _gate_field(p0a_readiness_gate, "gate_status")
    p0a_readiness_status = str(p0a_readiness_status_value) if p0a_readiness_status_value is not None else None
    ready_for_design_partner = (
        mode in {"fixture", "api"}
        and exit_code == 0
        and collector_health_status == "pass"
        and p0a_readiness_status == "pass"
        and failure_count == 0
    )
    recommended_next_action = _provider_preflight_next_action(
        collector_health_status=collector_health_status,
        p0a_readiness_status=p0a_readiness_status,
        failure_count=failure_count,
        exit_code=exit_code,
        ready_for_design_partner=ready_for_design_partner,
    )
    return {
        "summary_version": "provider_preflight_v1",
        "mode": mode,
        "phase": phase,
        "exit_code": exit_code,
        "ready_for_design_partner": ready_for_design_partner,
        "planned_runs": planned_runs,
        "record_count": record_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "cities": cities,
        "sample_size": sample_size,
        "prompt_limit": prompt_limit,
        "collector_health_status": collector_health_status,
        "collector_health_failure_reasons": _string_tuple(collector_health_gate.get("failure_reasons")),
        "p0a_readiness_status": p0a_readiness_status,
        "p0a_readiness_failure_reasons": _string_tuple(_gate_field(p0a_readiness_gate, "failure_reasons")),
        "persistence_enabled": bool(persistence.get("enabled")),
        "audit_output_path": str(Path(output_path)) if output_path else "",
        "recommended_next_action": recommended_next_action,
    }


def _build_preflight_audit_checklist(
    *,
    mode: str,
    phase: str,
    exit_code: int,
    planned_runs: int,
    record_count: int,
    success_count: int,
    failure_count: int,
    collector_health_gate: dict[str, object],
    p0a_readiness_gate: object | None,
    preflight_summary: dict[str, object],
    output_path: str | None,
    worker_args: tuple[str, ...],
) -> dict[str, object]:
    collector_health_status = str(collector_health_gate.get("gate_status", "unknown"))
    collector_health_reasons = _string_tuple(collector_health_gate.get("failure_reasons"))
    p0a_required = mode in {"fixture", "api"}
    p0a_status_value = _gate_field(p0a_readiness_gate, "gate_status")
    if p0a_status_value is None:
        p0a_status = "not_run" if p0a_required else "not_applicable"
    else:
        p0a_status = str(p0a_status_value)
    p0a_reasons = _string_tuple(_gate_field(p0a_readiness_gate, "failure_reasons"))
    blocking_reasons = tuple(
        item
        for item in (
            *collector_health_reasons,
            *p0a_reasons,
            "p0a_readiness_not_run" if p0a_required and p0a_status == "not_run" else "",
            f"collection_failures={failure_count}" if failure_count else "",
        )
        if item
    )
    ready_for_design_partner = bool(preflight_summary.get("ready_for_design_partner"))
    return {
        "checklist_version": "provider_preflight_audit_checklist_v1",
        "overall_status": "pass" if ready_for_design_partner else "fail",
        "ready_for_design_partner": ready_for_design_partner,
        "phase": phase,
        "exit_code": exit_code,
        "blocking_reasons": blocking_reasons,
        "worker_args": worker_args,
        "evidence_refs": {
            "collector_health": "collector_health",
            "collector_health_gate": "collector_health_gate",
            "p0a_readiness_gate": "p0a_readiness_gate",
            "preflight_summary": "preflight_summary",
            "answer_run_ids": "answer_run_ids" if record_count else "",
            "failure_events": "failure_events" if failure_count else "",
            "preflight_output_path": str(Path(output_path)) if output_path else "",
        },
        "checks": (
            {
                "id": "collector_health",
                "required": True,
                "status": collector_health_status,
                "detail": "All selected collectors are ready"
                if collector_health_status == "pass"
                else "One or more selected collectors are not ready",
                "failure_reasons": collector_health_reasons,
                "evidence_refs": ("collector_health", "collector_health_gate"),
            },
            {
                "id": "p0a_readiness",
                "required": p0a_required,
                "status": p0a_status,
                "detail": "P0a readiness gate passed"
                if p0a_status == "pass"
                else ("P0a readiness gate is not required for this mode" if not p0a_required else "P0a readiness gate did not pass"),
                "failure_reasons": p0a_reasons,
                "evidence_refs": ("p0a_readiness_gate",),
            },
            {
                "id": "collection_failures",
                "required": True,
                "status": "fail" if failure_count else "pass",
                "detail": f"{failure_count} collection failure records" if failure_count else "No collection failure records",
                "failure_reasons": (f"collection_failures={failure_count}",) if failure_count else (),
                "evidence_refs": ("failure_events",) if failure_count else ("answer_run_ids",),
            },
            {
                "id": "preflight_output_path",
                "required": False,
                "status": "pass" if output_path else "warn",
                "detail": "Worker JSON is written to the configured audit output path"
                if output_path
                else "No --preflight-output-path configured; stdout remains the only machine-readable output",
                "failure_reasons": (),
                "evidence_refs": ("preflight_output_path",) if output_path else (),
            },
            {
                "id": "replay_context",
                "required": True,
                "status": "pass" if worker_args else "warn",
                "detail": "Worker CLI args are captured for replay",
                "failure_reasons": (),
                "evidence_refs": ("preflight_audit_checklist.worker_args",),
            },
        ),
        "run_totals": {
            "planned_runs": planned_runs,
            "record_count": record_count,
            "success_count": success_count,
            "failure_count": failure_count,
        },
        "recommended_next_action": preflight_summary.get("recommended_next_action", "inspect_preflight_output"),
    }


def _stable_preflight_payload_bytes(output: dict[str, object]) -> bytes:
    return json.dumps(
        output,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _with_preflight_payload_hash(output: dict[str, object]) -> dict[str, object]:
    output_with_hash = dict(output)
    payload_for_hash = dict(output_with_hash)
    payload_for_hash.pop("preflight_payload_hash", None)
    output_with_hash["preflight_payload_hash"] = hashlib.sha256(
        _stable_preflight_payload_bytes(payload_for_hash)
    ).hexdigest()
    return output_with_hash


def _emit_json_output(output: dict[str, object], output_path: str | None = None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        output = {**output, "preflight_output_path": str(path)}
    output = _with_preflight_payload_hash(output)
    text_output = json.dumps(output, ensure_ascii=False, indent=2, default=str)
    if output_path:
        path.write_text(text_output + "\n", encoding="utf-8")
    print(text_output)


def _analysis_parser(*, judge_gateway: str, judge_model: str) -> ComparativeAnswerParser:
    if judge_gateway == "fixture":
        return ComparativeAnswerParser()
    if judge_gateway == "litellm":
        return ComparativeAnswerParser(
            judge_parser=LLMJudgeAnswerParser(
                model=judge_model,
                gateway=LiteLLMGateway(),
            )
        )
    raise ValueError(f"Unsupported judge gateway: {judge_gateway}")


def _filter_prompts_by_ids(
    prompts: tuple[PromptQuestion, ...],
    prompt_ids_csv: str | None,
) -> tuple[PromptQuestion, ...]:
    if not prompt_ids_csv:
        return prompts
    requested_ids = tuple(item.strip() for item in prompt_ids_csv.split(",") if item.strip())
    if not requested_ids:
        return prompts
    prompt_by_id = {str(getattr(prompt, "id")): prompt for prompt in prompts}
    missing = tuple(prompt_id for prompt_id in requested_ids if prompt_id not in prompt_by_id)
    if missing:
        raise ValueError(f"Unknown prompt ids: {', '.join(missing)}")
    return tuple(prompt_by_id[prompt_id] for prompt_id in requested_ids)


def _default_market_run_date(bootstrap: ProjectBootstrap) -> date:
    try:
        return datetime.now(ZoneInfo(bootstrap.market_profile.timezone)).date()
    except ZoneInfoNotFoundError:
        return datetime.now().date()


def _persist_records(
    *,
    bootstrap: ProjectBootstrap,
    mode: str,
    run_type: str,
    planned_runs: int,
    records: tuple[RawEvidenceRecord | CollectionFailureRecord, ...],
    successes: tuple[RawEvidenceRecord, ...],
    failures: tuple[CollectionFailureRecord, ...],
    persist_analysis: bool,
    score_formula_version: str,
    judge_gateway: str,
    judge_model: str,
    ensure_project_bootstrap: bool = True,
) -> dict[str, object]:
    repository = build_repository_from_env()
    if ensure_project_bootstrap:
        repository.save_project_bootstrap(bootstrap)
    snapshot_archive_summary: dict[str, object] = {
        "enabled": False,
        "reason": "OBJECT_STORE_ENDPOINT not configured",
    }
    browser_archive_summary: dict[str, object] = {
        "enabled": False,
        "reason": "OBJECT_STORE_ENDPOINT not configured",
    }
    snapshot_archive_audit = None
    browser_archive_audit = None
    if successes and os.environ.get("OBJECT_STORE_ENDPOINT", "").strip():
        object_store = build_object_store_from_env()
        successes, stored_snapshot_assets = archive_api_snapshot_assets(
            records=successes,
            store=object_store,
        )
        if stored_snapshot_assets:
            snapshot_archive_audit = build_audit_event(
                event_type="api_snapshot_assets_archived",
                project_id=bootstrap.project.id,
                actor_type="worker",
                actor_id="collector_worker",
                target_type="project",
                target_id=bootstrap.project.id,
                before=None,
                after={
                    "stored_snapshot_assets": [asdict(item) for item in stored_snapshot_assets],
                },
                input_refs={"answer_run_ids": [record.answer_run.id for record in successes]},
                output_refs={"artifact_uris": [item.uri for item in stored_snapshot_assets]},
                method_version="s3_compatible_api_snapshot_archive_v1",
                reason="Archive official API response snapshots to configured object storage",
            )
            snapshot_archive_summary = {
                "enabled": True,
                "stored_snapshot_assets": [asdict(item) for item in stored_snapshot_assets],
                "audit_event_id": snapshot_archive_audit.id,
            }
        else:
            snapshot_archive_summary = {
                "enabled": True,
                "stored_snapshot_assets": [],
                "reason": "no_api_snapshot_assets",
            }
        successes, stored_browser_assets = archive_browser_capture_assets(
            records=successes,
            store=object_store,
        )
        if stored_browser_assets:
            browser_archive_audit = build_audit_event(
                event_type="browser_capture_assets_archived",
                project_id=bootstrap.project.id,
                actor_type="worker",
                actor_id="collector_worker",
                target_type="project",
                target_id=bootstrap.project.id,
                before=None,
                after={
                    "stored_browser_assets": [asdict(item) for item in stored_browser_assets],
                },
                input_refs={"answer_run_ids": [record.answer_run.id for record in successes]},
                output_refs={"artifact_uris": [item.uri for item in stored_browser_assets]},
                method_version="s3_compatible_browser_capture_archive_v1",
                reason="Archive browser screenshots and HTML captures to configured object storage",
            )
            browser_archive_summary = {
                "enabled": True,
                "stored_browser_assets": [asdict(item) for item in stored_browser_assets],
                "audit_event_id": browser_archive_audit.id,
            }
        else:
            browser_archive_summary = {
                "enabled": True,
                "stored_browser_assets": [],
                "reason": "no_browser_capture_assets",
            }
    else:
        pass
    if successes:
        repository.save_raw_evidence_records(successes)
    archive_audit_events = tuple(
        audit_event
        for audit_event in (snapshot_archive_audit, browser_archive_audit)
        if audit_event is not None
    )
    if archive_audit_events:
        repository.save_audit_events(archive_audit_events)
    if failures:
        repository.save_collection_failure_records(failures)
    collection_summary = build_collection_run_summary(
        project_id=bootstrap.project.id,
        run_type=run_type,
        mode=mode,
        planned_runs=planned_runs,
        records=records,
    )
    collection_summary_audit = build_collection_run_audit_event(collection_summary)
    repository.save_collection_run_summary(collection_summary, collection_summary_audit)
    analysis_summary: dict[str, object] = {"enabled": False}
    if persist_analysis and successes:
        entity_aliases = repository.get_confirmed_entity_alias_terms(bootstrap.project.id)
        platform_weights_snapshot = {
            item.platform: item.weight for item in bootstrap.market_profile.platforms if item.enabled
        }
        score_weights = repository.get_score_weights_snapshot(
            project_id=bootstrap.project.id,
            formula_version=score_formula_version,
        )
        google_plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        google_gate = evaluate_google_spike_gate(
            project_id=bootstrap.project.id,
            plan=google_plan,
            records=records if run_type == "google_spike" else (),
        )
        google_readiness_gate = evaluate_google_spike_readiness_gate(
            project_id=bootstrap.project.id,
            plan=google_plan,
            records=records if run_type == "google_spike" else (),
        )
        score_input_successes = select_score_input_records(
            records=successes,
            google_spike_gate=google_gate,
            google_spike_readiness_gate=google_readiness_gate,
        )
        score_input_policy = build_score_input_policy(
            records=successes,
            score_input_records=score_input_successes,
            google_spike_gate=google_gate,
            google_spike_readiness_gate=google_readiness_gate,
        )
        if not score_input_successes:
            return {
                "enabled": True,
                "project_bootstrap": ensure_project_bootstrap,
                "tenant_id": bootstrap.tenant.id,
                "project_id": bootstrap.project.id,
                "prompt_questions": len(bootstrap.prompt_questions),
                "competitors": len(bootstrap.competitors),
                "raw_evidence_records": len(successes),
                "collection_failure_records": len(failures),
                "api_snapshot_artifacts": snapshot_archive_summary,
                "browser_capture_artifacts": browser_archive_summary,
                "evidence_artifacts": {
                    "api_snapshot_artifacts": snapshot_archive_summary,
                    "browser_capture_artifacts": browser_archive_summary,
                },
                "collection_run_summary": asdict(collection_summary),
                "collection_run_audit_event_id": collection_summary_audit.id,
                "analysis": {
                    "enabled": True,
                    "analysis_count": 0,
                    "score_input_record_count": 0,
                    "score_input_policy": score_input_policy,
                    "score_contributions": 0,
                    "reason": "no_score_input_records",
                },
            }
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=successes,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot=platform_weights_snapshot,
            score_weights=score_weights,
            formula_version=score_formula_version,
            entity_aliases=entity_aliases,
            scope_type="collection_slice",
            scope_value="worker_runtime",
            google_spike_gate=google_gate,
            google_spike_readiness_gate=google_readiness_gate,
            parser=_analysis_parser(judge_gateway=judge_gateway, judge_model=judge_model),
        )
        repository.save_answer_analyses(analysis_result.analyses)
        repository.save_score_snapshot(
            analysis_result.snapshot,
            analysis_result.contributions,
            analysis_result.audit_event,
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=analysis_result.score_input_records,
            analyses=analysis_result.score_input_analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        repository.save_citation_graph(bootstrap.project.id, graph)
        report_version = (
            f"worker-runtime-{collection_summary.created_at.strftime('%Y%m%dT%H%M%S%fZ')}"
            f"-{collection_summary.id[:8]}"
        )
        report = MarkdownCsvReportExporter().export(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            report_version=report_version,
            report_type="worker_runtime",
            prompt_version=bootstrap.project.prompt_version,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=analysis_result.score_input_records,
            graph=graph,
            platform_weights_snapshot=platform_weights_snapshot,
            google_spike_gate=google_gate,
            score_input_policy=analysis_result.score_input_policy,
            fidelity_records=successes,
            audit_events=(collection_summary_audit, analysis_result.audit_event),
        )
        repository.save_report_export(report.report_export, report.audit_event)
        fidelity_check, fidelity_audit = build_runtime_fidelity_check_from_records(
            project_id=bootstrap.project.id,
            report_export_id=report.report_export.id,
            records=successes,
            checked_by="collector_worker",
        )
        repository.save_fidelity_check(fidelity_check, fidelity_audit)
        report_artifact_summary: dict[str, object] = {
            "enabled": False,
            "reason": "OBJECT_STORE_ENDPOINT not configured",
        }
        if os.environ.get("OBJECT_STORE_ENDPOINT", "").strip():
            stored_artifacts = archive_report_artifacts(report, build_object_store_from_env())
            archive_audit = build_audit_event(
                event_type="report_artifacts_archived",
                project_id=bootstrap.project.id,
                actor_type="worker",
                actor_id="collector_worker",
                target_type="report_export",
                target_id=report.report_export.id,
                before=None,
                after={
                    "report_export_id": report.report_export.id,
                    "stored_artifacts": [asdict(item) for item in stored_artifacts],
                },
                input_refs={"report_export_ids": [report.report_export.id]},
                output_refs={"artifact_uris": [item.uri for item in stored_artifacts]},
                method_version="s3_compatible_report_artifact_archive_v1",
                reason="Archive M5 report artifacts to configured object storage",
            )
            repository.save_audit_events((archive_audit,))
            report_artifact_summary = {
                "enabled": True,
                "stored_artifacts": [asdict(item) for item in stored_artifacts],
                "audit_event_id": archive_audit.id,
            }
        actions = build_action_recommendations(
            project_id=bootstrap.project.id,
            graph=graph,
            snapshot=analysis_result.snapshot,
        )
        schedule = build_retest_schedule(
            project_id=bootstrap.project.id,
            prompt_version=bootstrap.project.prompt_version,
            sample_size=analysis_result.score_input_records[0].answer_run.sample_size,
            answer_run_ids=tuple(record.answer_run.id for record in analysis_result.score_input_records),
        )
        action_audit = build_action_plan_audit_event(
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
        comparison_audit = build_retest_comparison_audit_event(
            project_id=bootstrap.project.id,
            comparison=comparison,
        )
        repository.save_action_plan(
            actions=actions,
            schedule=schedule,
            comparison=comparison,
            audit_events=(action_audit, comparison_audit),
        )
        facts = build_localized_knowledge_facts(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            brand=bootstrap.brand,
            category=bootstrap.project.category,
            answer_run_ids=tuple(record.answer_run.id for record in analysis_result.score_input_records),
        )
        knowledge_results = search_knowledge_facts(
            facts=facts,
            query=(
                f"{bootstrap.project.target_brand} {bootstrap.project.category} "
                f"{bootstrap.project.market_code} shipping reviews"
            ),
            market_code=bootstrap.project.market_code,
            city=bootstrap.market_profile.cities[0] if bootstrap.market_profile.cities else bootstrap.project.market_code,
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
        content_audit = build_content_engine_audit_event(
            project_id=bootstrap.project.id,
            facts=facts,
            drafts=drafts,
            connectors=connectors,
            distribution_records=distribution_records,
        )
        repository.save_content_engine(
            facts=facts,
            drafts=drafts,
            connectors=connectors,
            distribution_records=distribution_records,
            audit_event=content_audit,
        )
        traceability_bundle = build_traceability_bundle(
            project_id=bootstrap.project.id,
            report_export=report.report_export,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=analysis_result.score_input_records,
            graph=graph,
            actions=actions,
            content_drafts=drafts,
            audit_events=tuple(record.audit_events[0] for record in analysis_result.score_input_records)
            + (
                analysis_result.audit_event,
                report.audit_event,
                action_audit,
                comparison_audit,
                content_audit,
            ),
        )
        repository.save_traceability_bundle(traceability_bundle)
        analysis_summary = {
            "enabled": True,
            "analysis_count": len(analysis_result.analyses),
            "score_input_record_count": len(analysis_result.score_input_records),
            "score_input_policy": analysis_result.score_input_policy,
            "entity_alias_entity_count": len(entity_aliases),
            "entity_alias_term_count": sum(len(aliases) for aliases in entity_aliases.values()),
            "judge_gateway": judge_gateway,
            "judge_model": judge_model,
            "score_snapshot_id": analysis_result.snapshot.id,
            "score_formula_version": analysis_result.snapshot.formula_version,
            "score_contributions": len(analysis_result.contributions),
            "final_score": analysis_result.snapshot.final_score,
            "source_graph_nodes": len(graph.nodes),
            "source_graph_evidence": len(graph.evidence_links),
            "source_gaps": len(graph.source_gaps),
            "competitor_benchmarks": len(graph.competitor_benchmarks),
            "report_export_id": report.report_export.id,
            "report_version": report.report_export.report_version,
            "report_evidence_answer_runs": len(report.report_evidence_answer_run_ids),
            "fidelity_check_id": fidelity_check["id"],
            "fidelity_check_status": fidelity_check["status"],
            "fidelity_difference_rate": fidelity_check["difference_rate"],
            "report_artifacts": report_artifact_summary,
            "action_recommendations": len(actions),
            "retest_schedule_id": schedule.id,
            "retest_comparison_id": comparison.id,
            "retest_trend": comparison.trend,
            "knowledge_facts": len(facts),
            "content_drafts": len(drafts),
            "integration_connectors": len(connectors),
            "manual_distribution_records": len(distribution_records),
            "traceability_bundle_id": traceability_bundle.id,
            "evidence_links": len(traceability_bundle.evidence_links),
        }
    elif persist_analysis:
        analysis_summary = {
            "enabled": True,
            "analysis_count": 0,
            "score_contributions": 0,
            "reason": "no_successful_records",
        }
    return {
        "enabled": True,
        "project_bootstrap": ensure_project_bootstrap,
        "tenant_id": bootstrap.tenant.id,
        "project_id": bootstrap.project.id,
        "prompt_questions": len(bootstrap.prompt_questions),
        "competitors": len(bootstrap.competitors),
        "raw_evidence_records": len(successes),
        "collection_failure_records": len(failures),
        "api_snapshot_artifacts": snapshot_archive_summary,
        "browser_capture_artifacts": browser_archive_summary,
        "evidence_artifacts": {
            "api_snapshot_artifacts": snapshot_archive_summary,
            "browser_capture_artifacts": browser_archive_summary,
        },
        "collection_run_summary": asdict(collection_summary),
        "collection_run_audit_event_id": collection_summary_audit.id,
        "analysis": analysis_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a GEO collection slice")
    parser.add_argument(
        "--mode",
        choices=["fixture", "api", "deepseek", "google-fixture", "google-spike", "google-serp-fixture", "google-serp-spike"],
        default="api",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Load an existing runtime project from DATABASE_URL instead of using the built-in AU bootstrap.",
    )
    parser.add_argument("--prompt-limit", type=int, default=2)
    parser.add_argument(
        "--prompt-ids",
        default=None,
        help="Comma-separated PromptQuestion ids to run; used by scheduled fidelity sampling plans.",
    )
    parser.add_argument("--sample-size", type=int, default=1)
    parser.add_argument(
        "--cities",
        default=None,
        help="Comma-separated cities. Defaults to the first two cities in the selected project's market profile.",
    )
    parser.add_argument(
        "--plan-browser-fidelity-sampling",
        action="store_true",
        help="Only build a deterministic API-vs-browser sampling plan; do not collect.",
    )
    parser.add_argument(
        "--fidelity-run-date",
        default=None,
        help="YYYY-MM-DD date used to seed browser fidelity sampling; defaults to today.",
    )
    parser.add_argument("--fidelity-cadence", default="weekly")
    parser.add_argument("--fidelity-prompt-count", type=int, default=10)
    parser.add_argument("--fidelity-city-count", type=int, default=2)
    parser.add_argument("--fidelity-selection-seed", default=None)
    parser.add_argument(
        "--include-browser-fidelity-fixture",
        action="store_true",
        help="In fixture mode, add paired browser answer runs for API-vs-browser fidelity sampling only.",
    )
    parser.add_argument(
        "--include-browser-fidelity-playwright",
        action="store_true",
        help="In api mode, add the Playwright browser collector for real API-vs-browser fidelity sampling.",
    )
    parser.add_argument(
        "--require-ready-collectors",
        action="store_true",
        help="Exit before collection if any selected collector health is not ready.",
    )
    parser.add_argument(
        "--health-check-only",
        action="store_true",
        help="Only emit collector health and audit checklist output; do not collect prompts.",
    )
    parser.add_argument(
        "--require-p0a-readiness",
        action="store_true",
        help="Exit non-zero when the P0a readiness gate fails after collection.",
    )
    parser.add_argument(
        "--require-google-spike-gates",
        action="store_true",
        help="Exit non-zero when the Google spike success/readiness gates fail.",
    )
    parser.add_argument(
        "--require-no-collection-failures",
        action="store_true",
        help="Exit non-zero after collection if any selected collector produced a failure record.",
    )
    parser.add_argument(
        "--collection-max-retries",
        type=int,
        default=int(os.environ.get("GENO_COLLECTION_MAX_RETRIES", "0")),
        help="Retry each prompt/city/sample collector call this many times after the first failure.",
    )
    parser.add_argument(
        "--collection-retry-backoff-seconds",
        type=float,
        default=float(os.environ.get("GENO_COLLECTION_RETRY_BACKOFF_SECONDS", "0")),
        help="Base exponential backoff between collection retries.",
    )
    parser.add_argument(
        "--collection-rate-limit-delay-seconds",
        type=float,
        default=float(os.environ.get("GENO_COLLECTION_RATE_LIMIT_DELAY_SECONDS", "0")),
        help="Sleep between planned collection attempts to respect provider/browser rate limits.",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist successful and failed collection records through DATABASE_URL",
    )
    parser.add_argument(
        "--persist-analysis",
        action="store_true",
        help="After --persist, parse successful records and persist score snapshot/contributions",
    )
    parser.add_argument(
        "--score-formula-version",
        default="visibility_v1.0",
        help="Registered score formula version to use with --persist-analysis",
    )
    parser.add_argument(
        "--judge-gateway",
        choices=["fixture", "litellm"],
        default="fixture",
        help="LLMGateway implementation for parser judge calls during --persist-analysis.",
    )
    parser.add_argument(
        "--judge-model",
        default="local-fixture-judge",
        help="Judge model name passed to the selected LLMGateway.",
    )
    parser.add_argument(
        "--preflight-output-path",
        default=None,
        help="Write the final worker JSON output to this path for preflight audit replay.",
    )
    args = parser.parse_args()
    google_modes = {"google-fixture", "google-spike", "google-serp-fixture", "google-serp-spike"}
    google_full_spike_modes = {"google-fixture", "google-spike"}
    google_serp_modes = {"google-serp-fixture", "google-serp-spike"}
    if args.persist_analysis and not args.persist:
        parser.error("--persist-analysis requires --persist")
    if args.persist_analysis and args.mode in google_serp_modes:
        parser.error("--persist-analysis is not valid for google-serp comparison modes")
    if args.require_p0a_readiness and args.mode in google_modes:
        parser.error("--require-p0a-readiness is only valid for fixture/api P0a modes")
    if args.require_google_spike_gates and args.mode not in google_full_spike_modes:
        parser.error("--require-google-spike-gates is only valid for google-fixture/google-spike modes")
    if args.prompt_ids and args.mode in google_modes:
        parser.error("--prompt-ids is only valid for fixture/api modes")
    try:
        execution_policy = CollectionExecutionPolicy(
            max_retries=args.collection_max_retries,
            retry_backoff_seconds=args.collection_retry_backoff_seconds,
            rate_limit_delay_seconds=args.collection_rate_limit_delay_seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))

    try:
        bootstrap = _load_runtime_project_bootstrap(args.project_id.strip()) if args.project_id else build_au_project_bootstrap()
    except RuntimePersistenceError as exc:
        print(f"runtime_project_load_error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if args.plan_browser_fidelity_sampling:
        try:
            run_date = (
                date.fromisoformat(args.fidelity_run_date)
                if args.fidelity_run_date
                else _default_market_run_date(bootstrap)
            )
            sampling_plan, sampling_audit = build_browser_fidelity_sampling_plan(
                project_id=bootstrap.project.id,
                prompts=bootstrap.prompt_questions,
                available_cities=tuple(bootstrap.market_profile.cities),
                run_date=run_date,
                cadence=args.fidelity_cadence,
                prompt_count=args.fidelity_prompt_count,
                city_count=args.fidelity_city_count,
                sample_size=args.sample_size,
                selection_seed=args.fidelity_selection_seed,
            )
        except ValueError as exc:
            parser.error(str(exc))
        persistence: dict[str, object] = {"enabled": False}
        if args.persist:
            try:
                repository = build_repository_from_env()
                if not args.project_id:
                    repository.save_project_bootstrap(bootstrap)
                repository.save_audit_events((sampling_audit,))
                persistence = {
                    "enabled": True,
                    "project_bootstrap": not bool(args.project_id),
                    "audit_event_id": sampling_audit.id,
                }
            except RuntimePersistenceError as exc:
                print(f"persistence_error: {exc}", file=sys.stderr)
                raise SystemExit(2) from exc
        output = {
            "mode": "browser_fidelity_sampling_plan",
            "record_count": 0,
            "planned_runs": sampling_plan.planned_runs,
            "browser_fidelity_sampling_plan": asdict(sampling_plan),
            "audit_event": asdict(sampling_audit),
            "recommended_worker_args": list(sampling_plan.recommended_worker_args),
            "persistence": persistence,
        }
        _emit_json_output(output, args.preflight_output_path)
        return

    prompts = bootstrap.prompt_questions
    cities = (
        tuple(city.strip() for city in args.cities.split(",") if city.strip())
        if args.cities
        else tuple(bootstrap.market_profile.cities[:2])
    )
    if not cities:
        cities = (bootstrap.project.market_code or "GLOBAL",)
    if args.mode in google_modes:
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        prompts = select_google_spike_prompts(bootstrap.prompt_questions)
        cities = plan.geo_cities
        args.sample_size = plan.sample_size
        args.prompt_limit = plan.prompt_count
    else:
        plan = None
        try:
            prompts = _filter_prompts_by_ids(prompts, args.prompt_ids)
        except ValueError as exc:
            parser.error(str(exc))
        if args.prompt_ids:
            args.prompt_limit = max(args.prompt_limit, len(prompts))
    google_serp_comparison_plan = (
        _google_serp_comparison_plan(google_plan=plan) if args.mode in google_serp_modes else None
    )
    base_collectors = _collectors(args.mode, project_id=args.project_id.strip() if args.project_id else None)
    fidelity_collectors = _fidelity_fixture_collectors(args.mode) if args.include_browser_fidelity_fixture else ()
    if args.include_browser_fidelity_playwright:
        fidelity_collectors = fidelity_collectors + _fidelity_playwright_collectors(args.mode)
    collectors = base_collectors + fidelity_collectors
    collector_health = _collector_health_report(collectors)
    collector_health_failure_reasons = _collector_health_failure_reasons(collector_health)
    collector_health_gate = {
        "gate_status": "fail" if collector_health_failure_reasons else "pass",
        "failure_reasons": collector_health_failure_reasons,
    }
    planned_runs = (
        int(google_serp_comparison_plan["planned_runs"])
        if google_serp_comparison_plan is not None
        else plan.planned_runs
        if plan is not None
        else len(prompts[: args.prompt_limit]) * len(collectors) * len(cities) * args.sample_size
    )
    if args.require_ready_collectors and collector_health_failure_reasons:
        persistence: dict[str, object] = {"enabled": False}
        output = {
            "mode": args.mode,
            "record_count": 0,
            "planned_runs": planned_runs,
            "success_count": 0,
            "failure_count": 0,
            "collection_execution_policy": asdict(execution_policy),
            "collector_health": collector_health,
            "collector_health_gate": collector_health_gate,
            "p0a_readiness_gate": None,
            "persistence": persistence,
        }
        if plan is not None:
            output["google_spike_plan"] = asdict(plan)
        if google_serp_comparison_plan is not None:
            output["google_serp_comparison_plan"] = google_serp_comparison_plan
        preflight_summary = _build_preflight_summary(
            mode=args.mode,
            phase="collector_health",
            exit_code=3,
            planned_runs=planned_runs,
            record_count=0,
            success_count=0,
            failure_count=0,
            cities=cities,
            sample_size=args.sample_size,
            prompt_limit=args.prompt_limit,
            collector_health_gate=collector_health_gate,
            p0a_readiness_gate=None,
            persistence=persistence,
            output_path=args.preflight_output_path,
        )
        output["preflight_summary"] = preflight_summary
        output["preflight_audit_checklist"] = _build_preflight_audit_checklist(
            mode=args.mode,
            phase="collector_health",
            exit_code=3,
            planned_runs=planned_runs,
            record_count=0,
            success_count=0,
            failure_count=0,
            collector_health_gate=collector_health_gate,
            p0a_readiness_gate=None,
            preflight_summary=preflight_summary,
            output_path=args.preflight_output_path,
            worker_args=tuple(sys.argv[1:]),
        )
        _emit_json_output(output, args.preflight_output_path)
        print(f"collector_preflight_failed: {', '.join(collector_health_failure_reasons)}", file=sys.stderr)
        raise SystemExit(3)
    if args.health_check_only:
        persistence = {"enabled": False}
        exit_code = 0
        output = {
            "mode": args.mode,
            "record_count": 0,
            "planned_runs": planned_runs,
            "success_count": 0,
            "failure_count": 0,
            "collection_execution_policy": asdict(execution_policy),
            "answer_run_ids": [],
            "failure_events": [],
            "collector_health": collector_health,
            "collector_health_gate": collector_health_gate,
            "p0a_readiness_gate": None,
            "persistence": persistence,
        }
        if plan is not None:
            output["google_spike_plan"] = asdict(plan)
        if google_serp_comparison_plan is not None:
            output["google_serp_comparison_plan"] = google_serp_comparison_plan
        preflight_summary = _build_preflight_summary(
            mode=args.mode,
            phase="collector_health",
            exit_code=exit_code,
            planned_runs=planned_runs,
            record_count=0,
            success_count=0,
            failure_count=0,
            cities=cities,
            sample_size=args.sample_size,
            prompt_limit=args.prompt_limit,
            collector_health_gate=collector_health_gate,
            p0a_readiness_gate=None,
            persistence=persistence,
            output_path=args.preflight_output_path,
        )
        output["preflight_summary"] = preflight_summary
        output["preflight_audit_checklist"] = _build_preflight_audit_checklist(
            mode=args.mode,
            phase="collector_health",
            exit_code=exit_code,
            planned_runs=planned_runs,
            record_count=0,
            success_count=0,
            failure_count=0,
            collector_health_gate=collector_health_gate,
            p0a_readiness_gate=None,
            preflight_summary=preflight_summary,
            output_path=args.preflight_output_path,
            worker_args=tuple(sys.argv[1:]),
        )
        _emit_json_output(output, args.preflight_output_path)
        return
    records = run_collection_slice(
        project_id=bootstrap.project.id,
        prompts=prompts,
        market_profile=bootstrap.market_profile,
        collectors=collectors,
        cities=cities,
        sample_size=args.sample_size,
        prompt_limit=args.prompt_limit,
        execution_policy=execution_policy,
    )
    successes = tuple(record for record in records if isinstance(record, RawEvidenceRecord))
    failures = tuple(record for record in records if isinstance(record, CollectionFailureRecord))
    p0a_readiness_gate = evaluate_p0a_collection_readiness(records=records) if args.mode not in google_modes else None
    google_spike_gate = (
        evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
        if plan is not None and args.mode in google_full_spike_modes
        else None
    )
    google_spike_readiness_gate = (
        evaluate_google_spike_readiness_gate(project_id=bootstrap.project.id, plan=plan, records=records)
        if plan is not None and args.mode in google_full_spike_modes
        else None
    )
    google_serp_comparison_summary = _google_serp_comparison_summary(
        records=records,
        comparison_plan=google_serp_comparison_plan,
    )
    persistence: dict[str, object] = {"enabled": False}
    if args.persist:
        try:
            persistence = _persist_records(
                bootstrap=bootstrap,
                mode=args.mode,
                run_type=(
                    "google_serp_comparison"
                    if args.mode in google_serp_modes
                    else "google_spike"
                    if args.mode in google_full_spike_modes
                    else "deepseek_slice"
                    if args.mode == "deepseek"
                    else "p0a_slice"
                ),
                planned_runs=planned_runs,
                records=records,
                successes=successes,
                failures=failures,
                persist_analysis=args.persist_analysis,
                score_formula_version=args.score_formula_version,
                judge_gateway=args.judge_gateway,
                judge_model=args.judge_model,
                ensure_project_bootstrap=not bool(args.project_id),
            )
        except RuntimePersistenceError as exc:
            print(f"persistence_error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    exit_code = 0
    phase = "collection_completed"
    if args.require_no_collection_failures and failures:
        exit_code = 5
        phase = "collection_failures"
    elif args.require_p0a_readiness and p0a_readiness_gate is not None and p0a_readiness_gate.gate_status != "pass":
        exit_code = 4
        phase = "p0a_readiness"
    elif (
        args.require_google_spike_gates
        and (
            google_spike_gate is None
            or google_spike_readiness_gate is None
            or google_spike_gate.gate_status != "pass"
            or google_spike_readiness_gate.gate_status != "pass"
        )
    ):
        exit_code = 6
        phase = "google_spike_gates"
    output = {
        "mode": args.mode,
        "record_count": len(records),
        "planned_runs": planned_runs,
        "success_count": len(successes),
        "failure_count": len(failures),
        "collection_execution_policy": asdict(execution_policy),
        "answer_run_ids": [record.answer_run.id for record in records],
        "failure_events": [asdict(record) for record in failures],
        "collector_health": collector_health,
        "collector_health_gate": collector_health_gate,
        "p0a_readiness_gate": asdict(p0a_readiness_gate) if p0a_readiness_gate is not None else None,
        "persistence": persistence,
    }
    preflight_summary = _build_preflight_summary(
        mode=args.mode,
        phase=phase,
        exit_code=exit_code,
        planned_runs=planned_runs,
        record_count=len(records),
        success_count=len(successes),
        failure_count=len(failures),
        cities=cities,
        sample_size=args.sample_size,
        prompt_limit=args.prompt_limit,
        collector_health_gate=collector_health_gate,
        p0a_readiness_gate=p0a_readiness_gate,
        persistence=persistence,
        output_path=args.preflight_output_path,
    )
    output["preflight_summary"] = preflight_summary
    output["preflight_audit_checklist"] = _build_preflight_audit_checklist(
        mode=args.mode,
        phase=phase,
        exit_code=exit_code,
        planned_runs=planned_runs,
        record_count=len(records),
        success_count=len(successes),
        failure_count=len(failures),
        collector_health_gate=collector_health_gate,
        p0a_readiness_gate=p0a_readiness_gate,
        preflight_summary=preflight_summary,
        output_path=args.preflight_output_path,
        worker_args=tuple(sys.argv[1:]),
    )
    if plan is not None:
        output["google_spike_plan"] = asdict(plan)
    if google_serp_comparison_plan is not None:
        output["google_serp_comparison_plan"] = google_serp_comparison_plan
        output["google_serp_comparison_summary"] = google_serp_comparison_summary
    if plan is not None and args.mode in google_full_spike_modes:
        output["google_spike_gate"] = asdict(google_spike_gate) if google_spike_gate is not None else None
        output["google_spike_readiness_gate"] = (
            asdict(google_spike_readiness_gate) if google_spike_readiness_gate is not None else None
        )
    _emit_json_output(output, args.preflight_output_path)
    if args.require_no_collection_failures and failures:
        print(
            f"collection_failures_found: {len(failures)}",
            file=sys.stderr,
        )
        raise SystemExit(5)
    if args.require_p0a_readiness and p0a_readiness_gate is not None and p0a_readiness_gate.gate_status != "pass":
        print(
            f"p0a_readiness_failed: {', '.join(p0a_readiness_gate.failure_reasons)}",
            file=sys.stderr,
        )
        raise SystemExit(4)
    if (
        args.require_google_spike_gates
        and (
            google_spike_gate is None
            or google_spike_readiness_gate is None
            or google_spike_gate.gate_status != "pass"
            or google_spike_readiness_gate.gate_status != "pass"
        )
    ):
        gate_status = getattr(google_spike_gate, "gate_status", "missing")
        readiness_status = getattr(google_spike_readiness_gate, "gate_status", "missing")
        print(
            f"google_spike_gates_failed: gate={gate_status}, readiness={readiness_status}",
            file=sys.stderr,
        )
        raise SystemExit(6)


if __name__ == "__main__":
    main()
