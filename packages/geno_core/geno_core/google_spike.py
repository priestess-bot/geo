from __future__ import annotations

from collections import Counter, defaultdict

from geno_core.models import (
    CollectionFailureRecord,
    GoogleSpikeGateResult,
    GoogleSpikePlan,
    PromptQuestion,
    RawEvidenceRecord,
)


GOOGLE_SPIKE_SURFACES = ("google_aio", "google_ai_mode")
GOOGLE_SPIKE_GEO_CITIES = ("Australia", "Sydney")
GOOGLE_SPIKE_SAMPLE_SIZE = 2
GOOGLE_SPIKE_PROMPT_COUNT = 30
GOOGLE_SPIKE_FAILURE_REASONS = (
    "not_triggered",
    "layout_changed",
    "blocked",
    "timeout",
    "geo_mismatch",
    "account_state",
    "not_configured",
)
GOOGLE_SPIKE_CANDIDATE_BACKENDS = (
    "google_aio.playwright.fixture",
    "google_ai_mode.playwright.fixture",
    "google.third_party_serp.fixture",
    "google.manual_backfill.fixture",
)


def select_google_spike_prompts(prompts: tuple[PromptQuestion, ...]) -> tuple[PromptQuestion, ...]:
    high_intent = {
        "category_recommendation",
        "city_category_recommendation",
        "competitor_comparison",
        "purchase_decision",
        "local_trust",
        "alternative",
    }
    selected = [prompt for prompt in prompts if prompt.intent_type in high_intent]
    return tuple(selected[:GOOGLE_SPIKE_PROMPT_COUNT])


def build_google_spike_plan(*, project_id: str, prompts: tuple[PromptQuestion, ...]) -> GoogleSpikePlan:
    selected = select_google_spike_prompts(prompts)
    return GoogleSpikePlan(
        project_id=project_id,
        prompt_count=len(selected),
        surfaces=GOOGLE_SPIKE_SURFACES,
        geo_cities=GOOGLE_SPIKE_GEO_CITIES,
        sample_size=GOOGLE_SPIKE_SAMPLE_SIZE,
        planned_runs=len(selected)
        * len(GOOGLE_SPIKE_SURFACES)
        * len(GOOGLE_SPIKE_GEO_CITIES)
        * GOOGLE_SPIKE_SAMPLE_SIZE,
        candidate_backends=GOOGLE_SPIKE_CANDIDATE_BACKENDS,
        failure_reasons=GOOGLE_SPIKE_FAILURE_REASONS,
    )


def evaluate_google_spike_gate(
    *,
    project_id: str,
    plan: GoogleSpikePlan,
    records: tuple[RawEvidenceRecord | CollectionFailureRecord, ...],
    pass_threshold: float = 0.80,
) -> GoogleSpikeGateResult:
    completed_records = [record for record in records if isinstance(record, RawEvidenceRecord)]
    google_aio_records = [
        record
        for record in completed_records
        if record.answer_run.platform == "google" and record.answer_run.surface == "google_aio"
    ]
    by_backend: dict[str, int] = defaultdict(int)
    for record in google_aio_records:
        by_backend[record.answer_run.collector_backend_id] += 1
    best_backend_id = max(by_backend, key=by_backend.get) if by_backend else None
    expected_google_aio_runs = plan.prompt_count * len(plan.geo_cities) * plan.sample_size
    google_aio_success_rate = (
        len(google_aio_records) / expected_google_aio_runs if expected_google_aio_runs else 0.0
    )
    trigger_rate = (
        sum(1 for record in completed_records if record.answer_run.surface_triggered) / len(records)
        if records
        else 0.0
    )
    failure_counter: Counter[str] = Counter()
    for record in records:
        if isinstance(record, CollectionFailureRecord):
            failure_counter[record.error_message or record.error_type] += 1
    gate_status = "pass" if google_aio_success_rate >= pass_threshold else "fail"
    return GoogleSpikeGateResult(
        project_id=project_id,
        gate_status=gate_status,
        planned_runs=plan.planned_runs,
        completed_runs=len(completed_records),
        google_aio_completed_runs=len(google_aio_records),
        success_rate=round(len(completed_records) / len(records), 4) if records else 0.0,
        trigger_rate=round(trigger_rate, 4),
        best_backend_id=best_backend_id,
        limited_coverage=gate_status == "fail",
        failure_summary=dict(failure_counter),
        recommendation=(
            "Allow google_aio into main scoring denominator"
            if gate_status == "pass"
            else "Keep Google in limited coverage appendix until a google_aio backend reaches 80% completion"
        ),
    )
