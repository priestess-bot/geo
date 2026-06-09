from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import run_collection_slice
from geno_core.collectors import (
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
    OpenAIWebSearchCollector,
    PerplexitySonarCollector,
)
from geno_core.contracts import CollectorBackend
from geno_core.models import CollectionFailureRecord, RawEvidenceRecord


def _collectors(mode: str) -> tuple[CollectorBackend, ...]:
    if mode == "fixture":
        return (FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector())
    if mode == "api":
        return (PerplexitySonarCollector(), OpenAIWebSearchCollector())
    raise ValueError(f"Unsupported collector mode: {mode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small AU P0a collection slice")
    parser.add_argument("--mode", choices=["fixture", "api"], default="fixture")
    parser.add_argument("--prompt-limit", type=int, default=2)
    parser.add_argument("--sample-size", type=int, default=1)
    parser.add_argument("--cities", default="Australia,Sydney")
    args = parser.parse_args()

    bootstrap = build_au_project_bootstrap()
    records = run_collection_slice(
        project_id=bootstrap.project.id,
        prompts=bootstrap.prompt_questions,
        market_profile=bootstrap.market_profile,
        collectors=_collectors(args.mode),
        cities=tuple(city.strip() for city in args.cities.split(",") if city.strip()),
        sample_size=args.sample_size,
        prompt_limit=args.prompt_limit,
    )
    successes = [record for record in records if isinstance(record, RawEvidenceRecord)]
    failures = [record for record in records if isinstance(record, CollectionFailureRecord)]
    output = {
        "mode": args.mode,
        "record_count": len(records),
        "success_count": len(successes),
        "failure_count": len(failures),
        "answer_run_ids": [record.answer_run.id for record in records],
        "failure_events": [asdict(record) for record in failures],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
