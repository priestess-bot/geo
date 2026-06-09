# Collector Worker

M2a has a deterministic fixture runner in `geno_core.collection` and fixture adapters in
`geno_core.collectors`. They implement the same `CollectorBackend` contract expected by real
platform adapters, so tests can verify AnswerRun, RawAnswer, citations, evidence assets, cost, and
AuditEvent without external API credentials.

P0a adapters:

- Implemented for contract testing: `FixturePerplexitySonarCollector`, `FixtureOpenAIWebSearchCollector`
- Implemented real API adapter shells: `PerplexitySonarCollector`, `OpenAIWebSearchCollector`

Local fixture slice:

```bash
PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode fixture
```

Persisted fixture slice:

```bash
DATABASE_URL=postgresql://geno:geno@localhost:5432/geno \
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py --mode fixture --persist
```

`--persist` first writes the AU `ProjectBootstrap` metadata (`Tenant`, `Project`,
`BrandEntity`, `CompetitorEntity`, and 100 `PromptQuestion` rows), then writes successful
`RawEvidenceRecord` rows and failed `CollectionFailureRecord` rows through
`PostgresEvidenceRepository`. If `DATABASE_URL` is missing, the worker exits with code `2` and
prints a persistence error instead of silently dropping evidence.

API adapter slice:

```bash
PERPLEXITY_API_KEY=... OPENAI_API_KEY=... \
PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode api
```

If API keys are missing, the worker returns `CollectionFailureRecord` items and writes
`answer_run_failed` audit events instead of pretending collection succeeded. With `--persist`,
the project/prompt metadata, failed runs, failure logs, collection costs, and audit events are
stored in PostgreSQL as well.

Google spike fixture:

```bash
PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-fixture
```

This runs the 30 prompt × 2 surfaces × 2 geo × k=2 spike matrix with fixture Google adapters and
prints the gate result. Real Google paths still require browser/API/manual runtime implementations.

Docker worker profile:

```bash
docker compose -f infra/docker-compose.yml --profile worker run --rm collector-worker
```

P0b planned adapters:

- `PlaywrightGoogleAIOCollector`
- `PlaywrightAIModeCollector`
- `ThirdPartySerpCollector`
- `ManualBackfillCollector`
