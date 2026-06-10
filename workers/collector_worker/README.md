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
`RawEvidenceRecord` rows, failed `CollectionFailureRecord` rows, and a batch-level
`CollectionRunSummary` through `PostgresEvidenceRepository`. Each `CollectionCost` records
`duration_ms` for the collector call. The summary records planned runs, attempted runs,
success/failure counts, success rate, trigger rate, answer-present rate, total cost, average cost
per run, total duration, average duration, platform/city/access-method distributions, failure
summary, and linked `answer_run_ids`, then writes a `collection_run_summarized` audit event. If `DATABASE_URL` is missing, the worker exits with code `2` and
prints a persistence error instead of silently dropping evidence.

Persisted fixture slice with analysis/scoring:

```bash
DATABASE_URL=postgresql://geno:geno@localhost:5432/geno \
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py --mode fixture --prompt-limit 1 --persist --persist-analysis
```

`--persist-analysis` requires `--persist`; it parses successful records with the comparative
parser, using `rule_based_v2_aliases` as the primary result and `llm_judge_fixture_v1` as the local
judge comparison. The `AnswerAnalysis` payload stores `parser_ab_compare_v1` agreement, mismatch
fields, the secondary judge result, and a `FixtureLLMGateway` `llm_call_log`; the same call log is
upserted into `llm_call_logs` with provider/model/prompt version, request/response hashes, token
counts, estimated cost, latency, and status. It also reads any project-level `score_weight_configs`
and freezes the active component weights into `VisibilityScoreSnapshot.component_weights_snapshot`.
The worker then stores `VisibilityScoreSnapshot`, `ScoreContribution`,
`ScoreSnapshotRun`, and the score audit event. It also builds and stores the M4 citation graph, source graph evidence,
source gaps, competitor benchmarks, the M5 `ReportExport` snapshot, and the M6
`ActionRecommendation`, `RetestSchedule`, `RetestComparison`, action plan audit event, and retest
comparison audit event. It then persists the M7 `LocalizedKnowledgeFact`, upserts
`KnowledgeFactEmbedding` rows into pgvector through `knowledge_fact_embeddings`, persists
`ContentDraft`, `IntegrationConnector`, `ManualDistributionRecord`, and writes both the
`knowledge_fact_embeddings_indexed` and content engine audit events. Failed records remain auditable
through `CollectionFailureRecord`.

Human review is intentionally not created by the worker. Review decisions are appended later through
`POST /v1/human-reviews/runtime` or the Runtime Console Human Review Trail, which writes
`human_review_records` and a `human_review_recorded` audit event against the reviewed score snapshot,
content draft, answer analysis/run, score weight config, or project.

API adapter slice:

```bash
PERPLEXITY_API_KEY=... OPENAI_API_KEY=... \
PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode api
```

If API keys are missing, the worker returns `CollectionFailureRecord` items and writes
`answer_run_failed` audit events instead of pretending collection succeeded. With `--persist`,
the project/prompt metadata, failed runs, failure logs, collection costs, batch-level collection
summary, and audit events are stored in PostgreSQL as well.

Google spike fixture:

```bash
PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-fixture
```

This runs the 30 prompt × 2 surfaces × 2 geo × k=2 spike matrix with fixture Google adapters and
prints the gate result. Real Google paths still require browser/API/manual runtime implementations.
When `--persist-analysis` creates a report from the stable fixture path, the report Method Disclosure
is frozen into `report_exports.method_disclosure`, records Google as limited coverage until a Google
spike gate is available, and records the current API-vs-browser fidelity status plus access-method
distribution.

Docker worker profile:

```bash
docker compose -f infra/docker-compose.yml --profile worker run --rm collector-worker
```

P0b planned adapters:

- `PlaywrightGoogleAIOCollector`
- `PlaywrightAIModeCollector`
- `ThirdPartySerpCollector`
- `ManualBackfillCollector`
