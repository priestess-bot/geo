# Pack 07 migration and operations evidence

Status date: 2026-07-25. Result: `LOCAL_COMPLETE / BLOCKED_EXTERNAL_FINAL_GATES`.

## Reviewable contracts

1. The online migration rehearsal covers Prompt, Protocol, Observation and Metric with an explicit
   two-writer inventory. A PostgreSQL trigger captures every legacy write into the new projection in
   the same transaction; a rejected new-side write proves that old-side and change-log writes roll
   back together.
2. Initial backfill is followed by a monotonic change-sequence catch-up. The cutover takes an
   advisory lock that a second connection proves blocks a live legacy writer, then requires two
   consecutive zero-difference reconciliations across eight Project/Campaign/resource scopes. The
   rollback window remains dual-written, and contract rejects the retired writer.
3. Backup artifacts are encrypted before durable storage, directories/files are `0700/0600`, the
   ephemeral bundle key is destroyed, and restore copies are removed. Missing or incorrect Secret,
   Provider, Recommendation, Workflow C, Synthetic and request-HMAC key material fails closed.
4. Empty-environment restore verifies PostgreSQL relations, FKs, ACL/RLS, five MinIO buckets, object
   hashes, historical key versions and representative encrypted artifacts. Recommendation and
   Workflow C now contain real seeded encrypted artifacts, not empty-domain key canaries.
5. The fault runner binds its contract and every selected test source by SHA-256. It terminates a
   real lease-holding child process, stops/restarts a dedicated Valkey, injects a second-object MinIO
   write failure, and stops/restarts isolated PostgreSQL, MinIO and Valkey dependencies.
6. `performance-profile-v1-non-b` freezes 10 Projects/4 active, four 1,000-Task Sampling Runs,
   400 immediately eligible Tasks, nine channels, 30 minutes at 20 read/5 write RPS, fixed Worker
   topology/resources, queue limits and zero correctness-error budgets. Reduced runs remain
   diagnostic and cannot pass the result verifier.

## Automated evidence

| Evidence | Result |
|---|---|
| Migration contract/unit suite | `9 passed`; receipt validation rejects missing lock, non-atomic dual-write, unstable reconciliation, stale hash and self-declared acceptance |
| Real PostgreSQL migration rehearsal | `1 passed`; watermarks `16 -> 17 -> 19`, two cutover rounds and rollback-window round all have `difference_count=0`, `lag=0` |
| Migration receipt | `artifacts/migration-cutover/20260725T000608Z/receipt.json`; mode `0600`; file SHA-256 `4d27684617749ff60611a8133b1e4c2013de680338266e42c2f63ae155dd0e67`; canonical receipt hash `8b293086e540a93fd52d3f76e7467ea9b4741f820c9b1d466ef4af836f583857` |
| Backup/restore and performance/fault contract regression | `53 passed, 0 failed, 0 skipped` |
| Authenticated empty-environment restore | Alembic `0087_wfc_report_receipts`; `234/234` tables; `12/12` objects across five buckets; FK, critical hashes, ACL/RLS and 109-relation non-B consistency exact |
| Secret/artifact restore | Secret versions `1,2`; 2 representative Secrets; Provider `2`, Recommendation `1`, Workflow C `1`, Synthetic restricted/tier artifacts decryptable with historical keyrings |
| Authenticated restore receipt | `artifacts/backup-restore-smoke-authenticated/20260725T035704Z-619020/receipt.json`; mode `0600`; file SHA-256 `e25deddf96b97adcd19e0cdc8e947ea4d82114867a58b457307bba86553286c5`; manifest SHA-256 `30350c7dedd8913f2addb217f287ccc423a3b6d4c681229035c75d9c2e8be1e4` |
| Full isolated fault matrix | `148 passed, 0 failed, 0 skipped`; 8 scenarios and 21 deduplicated targets |
| Fault receipt | `artifacts/non-b-fault/20260725T040225Z/receipt.json`; mode `0600`; file SHA-256 `bce182fb6a06bbada551e445a9139af3e87673222b06490f00878d170582dc4f`; canonical receipt hash `0587318d710e3386c911d2e797a9fca28fd22a25e50116025c50f1461ecffc1d` |
| Frozen performance identity | profile hash `6cdfa3309c1f893cbdf99d509b23e15917fa31c250b5fc0fa872edc39d5cc5fa`; workload hash `6c32898e620eaf4fb78ecbde35cf6c3df826dd669a297f505d887fc8e46997e2` |

All fault-test containers were absent after the run. The failed atomic migration probe consumes an
identity sequence value by PostgreSQL design, so the final watermark is `19` while both projections
contain 18 rows; reconciliation compares business keys, row values and hashes rather than assuming
gapless sequences.

## Acceptance mapping

| Pack item | Evidence |
|---|---|
| `P07-01` | stable receipt schema, fail-closed verifier, PostgreSQL dual-write/catch-up/cutover/rollback rehearsal and cleanup assertion |
| `P07-02` | encrypted bundle, private modes, destroyed ephemeral key, plaintext scanner and ten missing/wrong-key negative tests |
| `P07-03` | empty PostgreSQL/MinIO restore, historical Secret and four artifact keyrings, representative decrypt reads and ACL/RLS canary |
| `P07-04` | 148-test hashed runtime receipt covering termination/fence, broker retry, outbox replay, partial object write cleanup and dependency outages |
| `P07-05` | immutable profile/workload generators, hashes, strict result schema and anti-downscale acceptance tests |
| `P07-06` | migration, authenticated restore, performance contract and full runtime fault receipt verifiers all pass |

## Consolidated external needs

- An isolated production-equivalent staging allocation matching every frozen CPU/memory and process
  limit, plus authorization to run the full 30-minute workload and retain raw resource reports.
- A supplied copy or approved fixture derived from real legacy Prompt/Protocol/Observation/Metric
  data for the final data migration; the generic rehearsal does not claim a real-data cutover.
- Production backup/storage identities, independent historical-key custodians, escrow material and
  an independent verifier for a production restore drill.
- Release, Security, Migration and QA signatures. Local receipts never substitute these signatures.
