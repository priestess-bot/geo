# Collector Worker

M2a has a deterministic fixture runner in `geno_core.collection` and fixture adapters in
`geno_core.collectors`. They implement the same `CollectorBackend` contract expected by real
platform adapters, so tests can verify AnswerRun, RawAnswer, citations, evidence assets, cost, and
AuditEvent without external API credentials.

P0a adapters:

- Implemented for contract testing: `FixturePerplexitySonarCollector`, `FixtureOpenAIWebSearchCollector`
- Implemented real API adapter shells: `PerplexitySonarCollector`, `OpenAIWebSearchCollector`
- Implemented real browser fidelity adapter entrypoint: `PlaywrightChatGPTSearchCollector`

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
ready. Official API adapters generate `geno-api-snapshot://...` HTML snapshot evidence assets from
the raw provider response, with the snapshot hash stored on `EvidenceAsset.content_hash`; these
prove API-response provenance but do not replace browser fidelity samples. During `--persist`, if
`OBJECT_STORE_ENDPOINT` is configured, the worker archives those API snapshots to
`evidence/<project_id>/<answer_run_id>/<asset_id>.html`, replaces the asset URL/hash with the
stored `s3://...` object, and writes an `api_snapshot_assets_archived` audit event before saving
raw evidence rows.

Collection retry/rate-limit policy:

```bash
PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py \
  --mode api --prompt-limit 1 --cities Sydney \
  --collection-max-retries 2 \
  --collection-retry-backoff-seconds 1 \
  --collection-rate-limit-delay-seconds 0.5
```

The default policy is no retry and no sleep, matching local fixture smoke behavior. When enabled,
each planned prompt/city/sample still produces at most one final `RawEvidenceRecord` or
`CollectionFailureRecord`, so planned/attempted denominators are not inflated by retry attempts.
Successful retry paths add `attempt_count`, `retry_errors`, and a `collection_retry_succeeded` audit
event; exhausted failures keep the final `answer_run_failed` record and include `attempt_count`,
`retry_errors`, and `max_retries` in the collector log and audit payload. The worker JSON always
prints `collection_execution_policy`. This is a worker-local policy, not a distributed retry queue or
Temporal workflow.

Persisted fixture slice:

```bash
DATABASE_URL=postgresql://geno_runtime_app:geno_runtime_app@localhost:5432/geno \
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py --mode fixture --persist
```

`--persist` first writes the AU `ProjectBootstrap` metadata (`Tenant`, `Project`,
`BrandEntity`, `CompetitorEntity`, and 100 `PromptQuestion` rows), then writes successful
`RawEvidenceRecord` rows, failed `CollectionFailureRecord` rows, and a batch-level
`CollectionRunSummary` through `PostgresEvidenceRepository`. Each `CollectionCost` records
`duration_ms` for the collector call. If object storage is configured, API snapshot evidence assets
are archived before the evidence rows are saved, so downstream report/traceability reads see the
durable `s3://...` URI rather than the temporary `geno-api-snapshot://...` reference. The summary
records planned runs, attempted runs, success/failure counts, success rate, trigger rate,
answer-present rate, total cost, average cost per run, total duration, average duration,
platform/city/access-method distributions, failure summary, and linked `answer_run_ids`, then
writes a `collection_run_summarized` audit event. If `DATABASE_URL` is missing, the worker exits with code `2` and
prints a persistence error instead of silently dropping evidence.

The local Compose stack creates a non-bypass runtime database role, `geno_runtime_app`, through
migration `0010_runtime_project_rls`. Use that role for worker/API runtime commands; keep the
bootstrap `geno` role for database initialization and migration/admin operations only.

Persisted fixture slice with analysis/scoring:

```bash
DATABASE_URL=postgresql://geno_runtime_app:geno_runtime_app@localhost:5432/geno \
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py --mode fixture --prompt-limit 1 --persist --persist-analysis
```

`--persist-analysis` requires `--persist`; it parses successful records with the comparative
parser, using `rule_based_v2_aliases` as the primary result and `llm_judge_fixture_v1` as the judge
comparison. By default the judge uses `FixtureLLMGateway`; `--judge-gateway litellm --judge-model <model>`
switches the same parser path to `LiteLLMGateway` through `LITELLM_BASE_URL` and `LITELLM_API_KEY`.
The `AnswerAnalysis` payload stores `parser_ab_compare_v1` agreement, mismatch fields, the secondary
judge result, and the selected gateway `llm_call_log`; the same call log is upserted into
`llm_call_logs` with provider/model/prompt version, request/response hashes, token counts, estimated
cost, latency, status, retry attempts, retry errors, and failed-call error messages. `LiteLLMGateway`
uses bounded exponential backoff for chat requests and prefers upstream response cost fields before
falling back to local token-price estimates. It also reads any project-level `score_weight_configs`
for the selected score formula and freezes both the formula version and active component weights into
`VisibilityScoreSnapshot.formula_version` and `VisibilityScoreSnapshot.component_weights_snapshot`.
The worker then stores `VisibilityScoreSnapshot`, `ScoreContribution`,
`ScoreSnapshotRun`, and the score audit event. It also builds and stores the M4 citation graph, source graph evidence,
source gaps, competitor benchmarks, and the M5 `ReportExport` snapshot. After the report is saved,
it freezes the current API-vs-browser fidelity payload into `api_browser_fidelity_checks` and writes
an `api_browser_fidelity_checked` audit event. The default fixture path contains official API
samples only, so the check truthfully records `not_run`; adding `--include-browser-fidelity-fixture`
also collects `chatgpt_search.browser.fixture` on the same prompt/city, records `sampled`, and keeps
those browser runs out of `VisibilityScoreSnapshot.answer_run_ids` through `score_input_policy`.
The worker then stores the M6 `ActionRecommendation`, `RetestSchedule`, `RetestComparison`,
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
For `target_type=content_draft`, the runtime review path also projects the review status onto
`content_drafts.review_status` and writes a `content_draft_review_status_updated` audit event. It
does not rewrite the draft markdown, facts, source gaps, or evidence answer-run bindings.

The read-only review queue is exposed through `GET /v1/human-reviews/runtime/queue`. It derives
queue items from persisted `visibility_score_snapshots` and content drafts that are pending or need
changes, joins the latest `human_review_records` decision, and returns priority, reason, status, and
evidence refs without mutating the reviewed objects.

The default formula is `au_visibility_v1`. To exercise a candidate formula without changing old
snapshots, pass a registered version:

```bash
DATABASE_URL=postgresql://geno_runtime_app:geno_runtime_app@localhost:5432/geno \
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py \
  --mode fixture --prompt-limit 1 --persist --persist-analysis \
  --score-formula-version au_visibility_v1_1_local_boost
```

LiteLLM judge adapter slice:

```bash
LITELLM_BASE_URL=http://localhost:4000 LITELLM_API_KEY=... \
DATABASE_URL=postgresql://geno_runtime_app:geno_runtime_app@localhost:5432/geno \
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py \
  --mode fixture --prompt-limit 1 --persist --persist-analysis \
  --judge-gateway litellm --judge-model geno-gpt-4.1-mini
```

The adapter-level retry/cost behavior is covered by local contract tests. The Compose stack also
includes an optional `llm-gateway` profile with `litellm` and `collector-worker-litellm`; it mounts
`infra/litellm_config.yaml`, reads provider secrets from environment variables, and routes the judge
worker through `http://litellm:4000`.

```bash
OPENAI_API_KEY=... LITELLM_MASTER_KEY=... \
docker compose -f infra/docker-compose.yml --profile llm-gateway run --rm collector-worker-litellm
```

Production use still needs real provider routing choices, live provider-key smoke tests, and
reconciliation against provider billing exports.

Fixture API-vs-browser fidelity sample:

```bash
DATABASE_URL=postgresql://geno_runtime_app:geno_runtime_app@localhost:5432/geno \
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py \
  --mode fixture --prompt-limit 1 --cities Sydney \
  --include-browser-fidelity-fixture --persist --persist-analysis
```

Scheduled browser fidelity sampling plan:

```bash
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py \
  --plan-browser-fidelity-sampling \
  --fidelity-run-date 2026-06-11 \
  --fidelity-prompt-count 10 \
  --fidelity-city-count 2 \
  --sample-size 1
```

This is a cron-friendly scheduling primitive. It does not collect answers; it deterministically
selects active prompt ids and AU cities from the run date/cadence/seed, prints a
`BrowserFidelitySamplingPlan`, emits a `browser_fidelity_sampling_planned` audit event, and returns
`recommended_worker_args` that can be passed back to this worker for the actual API-vs-browser run.
Use `--persist` with the planning command to write the project bootstrap and sampling audit event to
PostgreSQL. The execution path accepts `--prompt-ids`, so the exact planned prompt set can be
replayed instead of relying on `--prompt-limit` ordering.

Lightweight browser fidelity scheduler:

```bash
PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_browser_fidelity_scheduler.py
GENO_BROWSER_FIDELITY_EXECUTE=1 PYTHONPATH=packages/geno_core:apps/api python3 scripts/run_browser_fidelity_scheduler.py
docker compose -f infra/docker-compose.yml --profile scheduler run --rm browser-fidelity-scheduler
```

The scheduler is a JSON wrapper for cron or Kubernetes CronJob. It runs the planning command,
returns the plan payload and the exact worker command, and only executes the worker when
`--execute` or `GENO_BROWSER_FIDELITY_EXECUTE=1` is set. Compose `scheduler` defaults to
`GENO_BROWSER_FIDELITY_PERSIST_PLAN=1` and `GENO_BROWSER_FIDELITY_EXECUTE=0`, so a scheduled job can
record the `browser_fidelity_sampling_planned` audit event without accidentally calling external
providers or launching a browser before credentials/selectors are ready.

Real API-vs-browser browser fidelity preflight:

```bash
PERPLEXITY_API_KEY=... OPENAI_API_KEY=... \
GENO_BROWSER_COLLECTOR_ENABLED=1 \
GENO_BROWSER_PROMPT_SELECTOR='textarea' \
GENO_BROWSER_ANSWER_SELECTOR='[data-message-author-role="assistant"]' \
GENO_BROWSER_STORAGE_STATE=/path/to/chatgpt-storage-state.json \
GENO_BROWSER_ARTIFACT_DIR=/tmp/geno-browser-artifacts \
make api-browser-fidelity-preflight
```

`--include-browser-fidelity-playwright` is only available in `--mode api`. It adds
`chatgpt_search.browser.playwright` next to the official API collectors so the same prompt/city can
be sampled through the consumer browser surface. The collector is deliberately strict: health is
`not_configured` until `GENO_BROWSER_COLLECTOR_ENABLED=1`; `selector_missing` until prompt and
answer selectors are configured; `session_state_missing` if the optional storage-state file is
configured but absent; and `playwright_missing` if the Python Playwright package is not installed.
`--require-ready-collectors` turns those states into worker exit code `3` before any external
collection starts. `make api-browser-fidelity-preflight` also passes
`--require-no-collection-failures`, so it exits with worker code `5` if browser launch, login,
selector matching, page interaction, or an official API call fails after health has passed.
Successful browser collection writes both screenshot and HTML snapshot evidence hashes into the
standard `RawEvidenceRecord` path. When `GENO_BROWSER_ARTIFACT_DIR` is configured and
`OBJECT_STORE_ENDPOINT` is available, `--persist` archives local `file://` browser HTML/PNG assets
to `evidence/<project_id>/<answer_run_id>/<asset_id>.<ext>`, replaces the EvidenceAsset URL/hash
with the stored `s3://...` object, and writes a `browser_capture_assets_archived` audit event before
raw evidence rows are saved. Browser `geno-browser-*://` metadata references are not archived
because they do not carry retrievable artifact bytes.

API adapter slice:

```bash
PERPLEXITY_API_KEY=... OPENAI_API_KEY=... \
PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode api
```

If API keys are missing, the worker returns `CollectionFailureRecord` items and writes
`answer_run_failed` audit events instead of pretending collection succeeded. With `--persist`,
the project/prompt metadata, failed runs, failure logs, collection costs, batch-level collection
summary, and audit events are stored in PostgreSQL as well.

Use the stricter preflight path when validating real AU P0a provider readiness:

```bash
PERPLEXITY_API_KEY=... OPENAI_API_KEY=... make api-preflight
make verify-api-preflight
make preflight-manifest
make au-p0a-runbook
make verify-au-p0a-runbook
make au-p0a-runbook-dry-run
make au-p0a-readiness
make au-p0a-package
make verify-au-p0a-package
make au-p0a-status
make verify-au-p0a-status
```

`make api-preflight` runs `--mode api --prompt-limit 1 --cities Sydney --sample-size 3
--require-ready-collectors --require-p0a-readiness --preflight-output-path
${GENO_API_PREFLIGHT_OUTPUT_PATH:-docs/runtime_preflight/api-preflight-latest.json}`.
`--require-ready-collectors` exits before collection with worker exit code `3` if a selected
collector health is not `ready`; the JSON output still includes `collector_health` and
`collector_health_gate` for audit, and the same payload is written to `--preflight-output-path`.
`--require-p0a-readiness` exits with worker exit code `4` after collection if the P0a gate fails,
for example because k=3, required platforms, citations, or HTML snapshot evidence are missing.
Every preflight payload also includes `preflight_summary`, a stable audit summary with phase,
exit code, `ready_for_design_partner`, gate failure reasons, `audit_output_path`, and
`recommended_next_action`. It also includes `preflight_audit_checklist`, which records blocking
reasons, evidence field references, run totals, output path status, and replayable worker args.
`preflight_payload_hash` is a sha256 over the canonical JSON payload after removing only the
`preflight_payload_hash` field itself; when `--preflight-output-path` is set, the hash includes
that top-level path so stdout and the written file can be recomputed against the same payload.
`make verify-api-preflight` runs `scripts/verify_preflight_payload.py` against the same path and
verifies the hash plus summary/checklist structure offline. Failed provider preflights, such as
missing keys, still pass this audit verifier when the payload is complete; use
`python3 scripts/verify_preflight_payload.py --require-design-partner-ready` when the check is
intended to gate expansion to a design-partner batch.
`make preflight-manifest` writes
`${GENO_API_PREFLIGHT_MANIFEST_PATH:-docs/runtime_preflight/api-preflight-manifest-latest.json}`.
The manifest records the preflight file sha256, payload hash, verifier result, run summary,
blocking reasons, replayable worker args, and its own `manifest_payload_hash` for package-level
audit indexing.
`make au-p0a-runbook` writes
`${GENO_AU_P0A_RUNBOOK_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-latest.json}` with the
ordered command plan for preflight, 5-prompt Sydney small batch, and full 100 prompts × 4 geo × k=3
batch. `make verify-au-p0a-runbook` verifies its payload hash, step order, planned runs, and required
gate commands. `make au-p0a-runbook-dry-run` writes
`${GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-runbook-execution-latest.json}`
with all planned steps, output paths, external provider call risk, environment gaps, and zero executed
commands by default. `make au-p0a-readiness` writes
`${GENO_AU_P0A_READINESS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-readiness-latest.json}` and
checks the selected phase (`GENO_AU_P0A_READINESS_PHASE=preflight|small_batch|full_batch`) against
required environment variables, the verified runbook, and upstream design-partner-ready payload and
manifest gates. By default it only verifies that `DATABASE_URL` is present; set
`GENO_AU_P0A_REQUIRE_DB_CHECK=1` or pass `--require-db-check` to run a read-only `SELECT 1`
PostgreSQL connection check before starting real batches. The checked-in Chinese runbook is
`docs/AU-P0a-真实批次运行手册.md`. `make au-p0a-package` writes
`${GENO_AU_P0A_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-evidence-package-latest.json}`
with file hashes, verifier status, design-partner readiness, and missing-artifact gaps across the
runbook, readiness file, preflight, small batch, and full batch artifacts. `make verify-au-p0a-package`
recomputes the package hash and verifies that summary counts, missing/failed/ready artifacts, and
blocking reasons match the embedded artifact entries. `make au-p0a-status` writes
`${GENO_AU_P0A_STATUS_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-status-latest.json}` with a single
machine-readable progress view across the runbook, all three readiness phases, package verifier,
completion percentage, design-ready percentage, remaining blockers, and next action.
`make verify-au-p0a-status` recomputes the status report hash and checks that completion, blockers,
ready state, and next action can be derived from the embedded gate summaries.
The default preflight JSON path is gitignored because live provider status and run context belong
to local audit evidence, not committed project docs. This is the minimum real API smoke; it does
not replace the full 100 prompts × 4 geo × k=3 design-partner batch.

Google spike fixture:

```bash
PYTHONPATH=packages/geno_core:apps/api python3 workers/collector_worker/run_collection_slice.py --mode google-fixture
```

This runs the 30 prompt × 2 surfaces × 2 geo × k=2 spike matrix with fixture Google adapters and
prints `google_spike_gate` plus `google_spike_readiness_gate`. The first gate checks Google AIO
coverage; the readiness gate checks whether at least two collection paths are present across
browser, third-party API, and manual backfill. `--persist-analysis` applies `score_input_policy`
before creating a `VisibilityScoreSnapshot`: Google answer runs enter the main scoring denominator
only when both gates pass. The default `google-fixture` uses browser fixtures only, so it can pass
the AIO success gate while still failing the two-path readiness gate; in that case raw evidence and
the collection summary persist, but main scoring/report generation is skipped with
`reason=no_score_input_records`. Real Google paths still require browser/API/manual runtime
implementations.
When `--persist-analysis` creates a report from the stable fixture path, the report Method Disclosure
is frozen into `report_exports.method_disclosure`, records Google as limited coverage until a Google
spike gate is available, and records the current API-vs-browser fidelity status plus access-method
distribution. With `--include-browser-fidelity-fixture`, Method Disclosure uses the paired official
API + browser sample for fidelity, while the report evidence appendix and score denominator remain
restricted to `score_input_records`. The same fidelity status is also available as a standalone runtime object through
`GET /v1/fidelity-checks/runtime` and can be regenerated for a report with
`POST /v1/fidelity-checks/runtime`. Stored checks can be summarized through
`GET /v1/fidelity-checks/runtime/trend`, which reports sampled/total, latest/earliest/average/max
difference rate, trend window, and improving/worsening/flat/no_data direction for the selected
project or report.

Docker worker profile:

```bash
docker compose -f infra/docker-compose.yml --profile worker run --rm collector-worker
OPENAI_API_KEY=... LITELLM_MASTER_KEY=... docker compose -f infra/docker-compose.yml --profile llm-gateway run --rm collector-worker-litellm
```

P0b planned adapters:

- `PlaywrightGoogleAIOCollector`
- `PlaywrightAIModeCollector`
- `ThirdPartySerpCollector`
- `ManualBackfillCollector`
