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

The worker always prints `p0a_readiness_gate` for stable P0a modes. The default local slice uses
`--sample-size 1`, so it is useful for fast smoke tests but intentionally fails the P0a k=3 gate.
Run a gate-ready fixture slice with:

```bash
PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py \
  --mode fixture --prompt-limit 1 --sample-size 3
```

`P0ACollectionReadinessGate` checks required platforms (`chatgpt`, `perplexity`), required metadata,
`answer_present` / `surface_triggered`, citation presence, screenshot or HTML evidence assets, and
sample size k=3. Real API mode must pass the same gate before P0a design partner data is considered
ready.

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
for the selected score formula and freezes both the formula version and active component weights into
`VisibilityScoreSnapshot.formula_version` and `VisibilityScoreSnapshot.component_weights_snapshot`.
The worker then stores `VisibilityScoreSnapshot`, `ScoreContribution`,
`ScoreSnapshotRun`, and the score audit event. It also builds and stores the M4 citation graph, source graph evidence,
source gaps, competitor benchmarks, and the M5 `ReportExport` snapshot. After the report is saved,
it freezes the current API-vs-browser fidelity payload into `api_browser_fidelity_checks` and writes
an `api_browser_fidelity_checked` audit event. The fixture path currently contains official API
samples only, so the check truthfully records `not_run` until a browser collector provides comparable
samples. The worker then stores the M6 `ActionRecommendation`, `RetestSchedule`, `RetestComparison`,
action plan audit event, and retest comparison audit event. It then persists the M7
`LocalizedKnowledgeFact`, upserts
`KnowledgeFactEmbedding` rows into pgvector through `knowledge_fact_embeddings`, persists
`ContentDraft`, `IntegrationConnector`, `ManualDistributionRecord`, and writes both the
`knowledge_fact_embeddings_indexed` and content engine audit events. Failed records remain auditable
through `CollectionFailureRecord`.

Human review is intentionally not created by the worker. Review decisions are appended later through
`POST /v1/human-reviews/runtime` or the Runtime Console Human Review Trail, which writes
`human_review_records` and a `human_review_recorded` audit event against the reviewed score snapshot,
content draft, answer analysis/run, score weight config, or project.

The default formula is `au_visibility_v1`. To exercise a candidate formula without changing old
snapshots, pass a registered version:

```bash
DATABASE_URL=postgresql://geno:geno@localhost:5432/geno \
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py \
  --mode fixture --prompt-limit 1 --persist --persist-analysis \
  --score-formula-version au_visibility_v1_1_local_boost
```

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
prints `google_spike_gate` plus `google_spike_readiness_gate`. The first gate checks whether AIO
coverage can enter the main scoring denominator; the readiness gate checks whether at least two
collection paths are present across browser, third-party API, and manual backfill. The default
`google-fixture` uses browser fixtures only, so it can pass the AIO success gate while still failing
the two-path readiness gate. Real Google paths still require browser/API/manual runtime
implementations.
When `--persist-analysis` creates a report from the stable fixture path, the report Method Disclosure
is frozen into `report_exports.method_disclosure`, records Google as limited coverage until a Google
spike gate is available, and records the current API-vs-browser fidelity status plus access-method
distribution. The same fidelity status is also available as a standalone runtime object through
`GET /v1/fidelity-checks/runtime` and can be regenerated for a report with
`POST /v1/fidelity-checks/runtime`.

Docker worker profile:

```bash
docker compose -f infra/docker-compose.yml --profile worker run --rm collector-worker
```

P0b planned adapters:

- `PlaywrightGoogleAIOCollector`
- `PlaywrightAIModeCollector`
- `ThirdPartySerpCollector`
- `ManualBackfillCollector`
