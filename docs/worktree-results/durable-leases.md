# Durable Job Lease Recovery Handoff

Branch: `codex/durable-leases`

## Delivered

- Migration `0029` adds fencing tokens, recovery metadata, persisted finalize descriptors,
  table-specific status checks, active-lease checks, claim/recovery indexes, fair cursors,
  and aggregate counters to all eight Knowledge queues plus `collection_jobs`.
- Claims use short `FOR UPDATE SKIP LOCKED` transactions, random UUID fencing tokens,
  PostgreSQL time, expired-first recovery, persisted round-robin fairness, cancellation CAS,
  retry/DLQ transitions, and token-fenced heartbeat/commit/fail/finalize operations.
- Knowledge business-result persistence and terminal promotion share one transaction.
  Artifact-producing jobs persist a finalizing descriptor before terminal promotion so a
  reclaimed finalizer does not repeat the external operation.
- Collection runs the blocking collector in an isolated process group. A separate DB
  connection heartbeats the lease; cancellation, timeout, or lost ownership terminates the
  full child process group. PostgreSQL session advisory locks enforce provider concurrency
  and are released immediately when an actor/container dies.
- Runtime Prometheus output includes durable queue depth/age, expired work, terminal counts,
  event counters, recovery cursors/slots, and worker heartbeat age without exposing tokens.
- `scripts/verify_durable_job_lease_recovery.py` performs schema checks and real Knowledge
  actor kill, Collection actor kill, and Collection child kill tests. The generated artifact
  is intentionally ignored at `tmp/durable-job-lease-recovery/latest.json`.

## Integration-Owned Changes

Do not deploy the branch without these shared-file changes:

1. Add `/migrations/up/0029_durable_job_lease_recovery.sql` to the `db-migrate` command in
   `infra/docker-compose.yml` and the production Compose equivalent.
2. Give `task-recovery-dispatcher` a runtime `DATABASE_URL`. It reads queue state and records
   maintenance-scoped recovery metrics in addition to publishing wakeups.
3. Change the runtime worker queue arguments from the single value `collection,report` to two
   arguments, `collection` and `report`, matching Dramatiq's CLI contract.
4. Add the following production environment settings:

```yaml
task-worker-knowledge:
  environment:
    GENO_KNOWLEDGE_WORKER_LEASE_SECONDS: ${GENO_KNOWLEDGE_WORKER_LEASE_SECONDS:-600}
    GENO_KNOWLEDGE_WORKER_MAX_JOBS: ${GENO_KNOWLEDGE_WORKER_MAX_JOBS:-25}
    GENO_KNOWLEDGE_DRAMATIQ_DRAIN_CYCLES: ${GENO_KNOWLEDGE_DRAMATIQ_DRAIN_CYCLES:-20}

task-worker-runtime:
  environment:
    GENO_COLLECTION_JOB_LEASE_SECONDS: ${GENO_COLLECTION_JOB_LEASE_SECONDS:-3600}
    GENO_COLLECTION_JOB_TIMEOUT_SECONDS: ${GENO_COLLECTION_JOB_TIMEOUT_SECONDS:-3600}
    GENO_COLLECTION_CHILD_TERMINATE_GRACE_SECONDS: ${GENO_COLLECTION_CHILD_TERMINATE_GRACE_SECONDS:-10}
    GENO_COLLECTION_RETRY_BACKOFF_SECONDS: ${GENO_COLLECTION_RETRY_BACKOFF_SECONDS:-120}
    GENO_COLLECTION_PROVIDER_CONCURRENCY: ${GENO_COLLECTION_PROVIDER_CONCURRENCY:-1}

task-recovery-dispatcher:
  environment:
    DATABASE_URL: postgresql://geno_runtime_app:geno_runtime_app@postgres:5432/geno
  command:
    - python
    - workers/task_queue/run_recovery_dispatcher.py
    - --interval-seconds
    - ${GENO_TASK_RECOVERY_INTERVAL_SECONDS:-30}
```

The heartbeat interval is internally capped at one third of the lease. Keep the Knowledge
lease above the longest expected external operation plus scheduling jitter. Keep the
Collection Dramatiq time limit (currently 3900 seconds) above
`GENO_COLLECTION_JOB_TIMEOUT_SECONDS + GENO_COLLECTION_CHILD_TERMINATE_GRACE_SECONDS`.
Never set `GENO_DURABLE_JOB_AFTER_*_FAILPOINT` or
`GENO_COLLECTION_TEST_BYPASS_RATE_LIMIT` outside a test deployment.

Add these Make targets in the integration branch:

```make
test-durable-leases:
	GENO_DURABLE_JOB_TEST_DATABASE_URL="$${GENO_DURABLE_JOB_TEST_DATABASE_URL:?required}" \
		PYTHONPATH=packages/geno_core:apps/api:. python3 -m pytest -q \
		tests/test_durable_job_lease_contracts.py \
		tests/test_durable_job_lease_postgres.py

smoke-durable-lease-recovery:
	PYTHONPATH=packages/geno_core:apps/api:. python3 scripts/verify_durable_job_lease_recovery.py \
		--database-url "$${GENO_DURABLE_JOB_TEST_DATABASE_URL}" \
		--compose-project "$${COMPOSE_PROJECT_NAME:-geo-durable-leases}" \
		--artifact-path tmp/durable-job-lease-recovery/latest.json \
		--run-actor-kill-tests
```

The total production gate must reject a missing, dirty, stale, or configuration-only artifact.
Require all of the following from `tmp/durable-job-lease-recovery/latest.json`:

- `status == "passed"`
- `evidence_level == "production_evidence"`
- `worktree_dirty == false`
- `git_commit` equals the commit under test
- `required_live_checks.actor_kill_tests == true`
- `required_live_checks.satisfied == true`
- every check is passed, including `knowledge_actor_kill_reclaim`,
  `collection_actor_kill_reclaim`, and `collection_child_kill_is_retry`
- recomputed `input_hash` and `output_hash` match the artifact contract

## Rollout And Rollback

1. Stop dispatchers and drain every pre-0029 Knowledge and Collection consumer.
2. Apply `0029`; its legacy normalization only changes active rows without a fencing token.
3. Start the new workers, then the recovery dispatcher, and verify metrics plus one live smoke.
4. Roll back only after all new consumers are drained. The down migration intentionally aborts
   while any active token owner exists, then maps new statuses back to legacy-compatible states.

## Operations

Suggested alert inputs exposed by `/metrics`:

- queue depth and oldest queued age, grouped by queue/job type;
- expired active count and oldest expired age;
- growth in `reclaimed`, `dead_lettered`, `lease_lost`, `stale_completion`, heartbeat failure,
  and cancellation counters;
- stale recovery worker heartbeat or a cursor whose recovery slots stop advancing;
- `geno_durable_job_snapshot_ok == 0`.

Initial alert thresholds should be derived from the configured lease and dispatcher interval:
expired work older than `lease + 2 * dispatcher interval` is actionable; any sustained
heartbeat failure or stale-completion growth is paging-worthy. Dashboard panels should retain
the `queue` and `job_type` labels and must not add job IDs, payloads, or lease tokens.

## Verification

Executed successfully in the isolated `geo-durable-leases` Compose project:

- 51 contract and existing regression tests, plus 4 subtests;
- 16 real PostgreSQL contention, fencing, finalizing, metric, and query-plan tests;
- Ruff, Python `compileall`, and `git diff --check`;
- a fresh database migration chain through `0029`;
- `0029` down/up/up migration round trip;
- live Knowledge actor kill/reclaim, Collection actor kill/reclaim, and Collection child
  kill-to-retry fault injection.

## Residual At-Least-Once Boundary

PostgreSQL result writes use stable IDs/conflict-safe persistence, MinIO uses natural or
content-hash keys, and Qdrant uses stable point IDs. Provider calls remain at least once: if a
Collection child commits its idempotent business rows and the parent dies before persisting the
finalizing descriptor, recovery may call the provider again. The persisted data remains
deduplicated, but upstream providers can observe a duplicate request. Closing that final narrow
window would require moving the descriptor write into the child transaction or an outbox/idempotency
contract supported by each provider.
