from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import run_collection_slice
from geno_core.collectors import (
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
    OpenAIWebSearchCollector,
    PerplexitySonarCollector,
)
from geno_core.contracts import CollectorBackend
from geno_core.google_spike import (
    build_google_spike_plan,
    evaluate_google_spike_gate,
    select_google_spike_prompts,
)
from geno_core.models import CollectionFailureRecord, ProjectBootstrap, RawEvidenceRecord
from geno_core.runtime import RuntimePersistenceError, build_repository_from_env


def _collectors(mode: str) -> tuple[CollectorBackend, ...]:
    if mode == "fixture":
        return (FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector())
    if mode == "api":
        return (PerplexitySonarCollector(), OpenAIWebSearchCollector())
    if mode == "google-fixture":
        return (FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector())
    raise ValueError(f"Unsupported collector mode: {mode}")


def _persist_records(
    *,
    bootstrap: ProjectBootstrap,
    successes: tuple[RawEvidenceRecord, ...],
    failures: tuple[CollectionFailureRecord, ...],
) -> dict[str, object]:
    repository = build_repository_from_env()
    repository.save_project_bootstrap(bootstrap)
    if successes:
        repository.save_raw_evidence_records(successes)
    if failures:
        repository.save_collection_failure_records(failures)
    return {
        "enabled": True,
        "project_bootstrap": True,
        "tenant_id": bootstrap.tenant.id,
        "project_id": bootstrap.project.id,
        "prompt_questions": len(bootstrap.prompt_questions),
        "competitors": len(bootstrap.competitors),
        "raw_evidence_records": len(successes),
        "collection_failure_records": len(failures),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small AU P0a collection slice")
    parser.add_argument("--mode", choices=["fixture", "api", "google-fixture"], default="fixture")
    parser.add_argument("--prompt-limit", type=int, default=2)
    parser.add_argument("--sample-size", type=int, default=1)
    parser.add_argument("--cities", default="Australia,Sydney")
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist successful and failed collection records through DATABASE_URL",
    )
    args = parser.parse_args()

    bootstrap = build_au_project_bootstrap()
    prompts = bootstrap.prompt_questions
    cities = tuple(city.strip() for city in args.cities.split(",") if city.strip())
    if args.mode == "google-fixture":
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        prompts = select_google_spike_prompts(bootstrap.prompt_questions)
        cities = plan.geo_cities
        args.sample_size = plan.sample_size
        args.prompt_limit = plan.prompt_count
    else:
        plan = None
    records = run_collection_slice(
        project_id=bootstrap.project.id,
        prompts=prompts,
        market_profile=bootstrap.market_profile,
        collectors=_collectors(args.mode),
        cities=cities,
        sample_size=args.sample_size,
        prompt_limit=args.prompt_limit,
    )
    successes = tuple(record for record in records if isinstance(record, RawEvidenceRecord))
    failures = tuple(record for record in records if isinstance(record, CollectionFailureRecord))
    persistence: dict[str, object] = {"enabled": False}
    if args.persist:
        try:
            persistence = _persist_records(bootstrap=bootstrap, successes=successes, failures=failures)
        except RuntimePersistenceError as exc:
            print(f"persistence_error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    output = {
        "mode": args.mode,
        "record_count": len(records),
        "success_count": len(successes),
        "failure_count": len(failures),
        "answer_run_ids": [record.answer_run.id for record in records],
        "failure_events": [asdict(record) for record in failures],
        "persistence": persistence,
    }
    if plan is not None:
        output["google_spike_gate"] = asdict(
            evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
        )
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
