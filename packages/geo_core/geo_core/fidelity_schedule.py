from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import NAMESPACE_URL, uuid5

from geo_core.audit import build_audit_event, hash_payload
from geo_core.models import AuditEvent, BrowserFidelitySamplingPlan, PromptQuestion


DEFAULT_BROWSER_FIDELITY_CADENCE = "weekly"
DEFAULT_BROWSER_FIDELITY_PROMPT_COUNT = 10
DEFAULT_BROWSER_FIDELITY_CITIES = ("Sydney", "Melbourne")
DEFAULT_OFFICIAL_API_BACKENDS = ("perplexity.sonar.api", "openai.web_search.api")
DEFAULT_BROWSER_BACKENDS = ("chatgpt_search.browser.playwright",)


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geo", kind, *(str(part) for part in parts)))))


def _stable_rank(seed: str, value: str) -> str:
    return hash_payload({"seed": seed, "value": value})


def _select_prompts(
    *,
    prompts: tuple[PromptQuestion, ...],
    prompt_count: int,
    seed: str,
) -> tuple[PromptQuestion, ...]:
    active_prompts = tuple(prompt for prompt in prompts if prompt.status == "active")
    ranked = sorted(
        active_prompts,
        key=lambda prompt: (
            _stable_rank(seed, prompt.id),
            -prompt.priority,
            prompt.id,
        ),
    )
    return tuple(ranked[: max(0, min(prompt_count, len(ranked)))])


def _select_cities(*, cities: tuple[str, ...], city_count: int, seed: str) -> tuple[str, ...]:
    ranked = sorted(
        tuple(city for city in cities if city.strip()),
        key=lambda city: (_stable_rank(seed, city), city),
    )
    return tuple(ranked[: max(0, min(city_count, len(ranked)))])


def build_browser_fidelity_sampling_plan(
    *,
    project_id: str,
    prompts: tuple[PromptQuestion, ...],
    available_cities: tuple[str, ...],
    run_date: date | None = None,
    cadence: str = DEFAULT_BROWSER_FIDELITY_CADENCE,
    prompt_count: int = DEFAULT_BROWSER_FIDELITY_PROMPT_COUNT,
    city_count: int = 2,
    sample_size: int = 1,
    official_api_backend_ids: tuple[str, ...] = DEFAULT_OFFICIAL_API_BACKENDS,
    browser_backend_ids: tuple[str, ...] = DEFAULT_BROWSER_BACKENDS,
    selection_seed: str | None = None,
) -> tuple[BrowserFidelitySamplingPlan, AuditEvent]:
    if prompt_count < 1:
        raise ValueError("prompt_count must be positive")
    if city_count < 1:
        raise ValueError("city_count must be positive")
    if sample_size < 1:
        raise ValueError("sample_size must be positive")
    if not official_api_backend_ids:
        raise ValueError("official_api_backend_ids must not be empty")
    if not browser_backend_ids:
        raise ValueError("browser_backend_ids must not be empty")
    plan_date = run_date or datetime.now(UTC).date()
    seed = selection_seed or f"{project_id}:{cadence}:{plan_date.isoformat()}"
    city_pool = available_cities or DEFAULT_BROWSER_FIDELITY_CITIES
    selected_prompts = _select_prompts(prompts=prompts, prompt_count=prompt_count, seed=seed)
    selected_cities = _select_cities(cities=city_pool, city_count=city_count, seed=seed)
    if not selected_prompts:
        raise ValueError("No active prompts available for browser fidelity sampling")
    if not selected_cities:
        raise ValueError("No cities available for browser fidelity sampling")
    planned_runs = len(selected_prompts) * len(selected_cities) * (
        len(official_api_backend_ids) + len(browser_backend_ids)
    ) * sample_size
    prompt_ids_csv = ",".join(prompt.id for prompt in selected_prompts)
    cities_csv = ",".join(selected_cities)
    recommended_args = (
        "--mode",
        "api",
        "--prompt-ids",
        prompt_ids_csv,
        "--prompt-limit",
        str(len(selected_prompts)),
        "--cities",
        cities_csv,
        "--sample-size",
        str(sample_size),
        "--include-browser-fidelity-playwright",
        "--require-ready-collectors",
        "--require-no-collection-failures",
        "--persist",
        "--persist-analysis",
    )
    plan = BrowserFidelitySamplingPlan(
        id=_stable_id(
            "browser-fidelity-sampling-plan",
            project_id,
            cadence,
            plan_date.isoformat(),
            seed,
            prompt_ids_csv,
            cities_csv,
            sample_size,
        ),
        project_id=project_id,
        cadence=cadence,
        run_date=plan_date.isoformat(),
        selection_seed=seed,
        source_prompt_count=len(tuple(prompt for prompt in prompts if prompt.status == "active")),
        source_city_count=len(city_pool),
        prompt_count=len(selected_prompts),
        city_count=len(selected_cities),
        sample_size=sample_size,
        prompt_question_ids=tuple(prompt.id for prompt in selected_prompts),
        prompt_texts=tuple(prompt.text for prompt in selected_prompts),
        cities=selected_cities,
        official_api_backend_ids=official_api_backend_ids,
        browser_backend_ids=browser_backend_ids,
        planned_runs=planned_runs,
        recommended_worker_args=recommended_args,
        created_at=datetime.now(UTC),
    )
    audit_event = build_audit_event(
        event_type="browser_fidelity_sampling_planned",
        project_id=project_id,
        actor_type="worker",
        actor_id="collector_worker",
        target_type="browser_fidelity_sampling_plan",
        target_id=plan.id,
        before=None,
        after=plan,
        input_refs={"prompt_question_ids": list(plan.prompt_question_ids)},
        output_refs={"browser_fidelity_sampling_plan_ids": [plan.id]},
        method_version="browser_fidelity_sampling_plan_v1",
        reason="deterministically select prompt/city samples for scheduled API-vs-browser fidelity collection",
    )
    return plan, audit_event
