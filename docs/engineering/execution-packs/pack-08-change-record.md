# Pack 08 non-B implementation change record

Record ID: `CR-NONB-2026-07-25-01`. Status: `READY_FOR_REVIEW / BLOCKED_EXTERNAL`.
Independent approval: pending.

## Intent and boundary

This record covers autonomous implementation of roadmap A, non-B portions of C, D and shared
foundations through Packs 01--08. Board B remains excluded exactly as defined in the main roadmap:
Connector Core, GSC/GA4, official reports, Australian egress/Browser Capture Connector, event intake
and attribution ledger are not accepted by this record.

The implementation does not lower or reinterpret any frozen threshold. In particular it preserves:

- ten Provider repetitions and the 80% valid-completion floor;
- separate capture/source denominators and Attempt-only egress evidence;
- Wilson/Newcombe, paired bootstrap, Holm and explicit `inconclusive`/`insufficient_evidence`;
- nine independent style channels, 200 approved samples per channel, 40 Cases per channel and the
  `95% / zero subject mix / zero anti-copy / 4.2` release thresholds;
- manual approval/publication boundaries and Customer approved/current/real-only projection rules;
- encrypted Secret/artifact storage, historical keyrings, retention/hold and empty-environment restore;
- no automatic browser access without authorization and no CAPTCHA, ban, rate-limit or access-control
  bypass.

## Changes

| Change | Impacted stable IDs | Capability/contract effect |
|---|---|---|
| Durable semantic, comparison, drift, alert and approved report verticals | `C-CONTRACT-01/04/05/06`, `M4-*`, `STAT-*`, `REPO-GATE-02` | Implements frozen server-side inputs, fenced persistence and explicit statistical terminal states; no denominator change |
| Five governed Provider adapters and canary verifier | `SHARED-GATEWAY-*`, Provider portion of `C-CONTRACT-03`, `REAL-MODEL-AC-01` | Adds local contracts and redacted canary tooling; live evidence remains empty until real credentials are supplied |
| Synthetic Profile/Review/Revision/Corpus/Offline workflow | `SYN-CONTRACT-*`, `LAB-*` | Implements local workflow and release arithmetic; does not claim nine-channel live samples or human sign-off |
| AIO/AI Mode/Copilot manual-artifact parsers | non-B manual portion of `C-CONTRACT-03`, `STAT-SAMPLE-*` | Parses governed fixture/manual artifacts only; automated capture/Australian egress remains Board B |
| Prompt and Recommendation lifecycle | `SHARED-PROMPT-01`, `D-CONTRACT-*`, `REC-*` | Adds maker-checker/freeze/retire and stale/expired draft blocking; Attribution remains explicit `unavailable` |
| Migration, restore, fault and performance contracts | `SHARED-COMPAT-01`, `M6-MIG/FAIL/RESTORE/PERF-*`, `REPO-GATE-02/03/07`, `PERF-*` | Adds local deterministic receipts and frozen load contract; real legacy/staging/production evidence remains external |
| Structural module split | `REPO-GATE-01` | Restores the 600-line product/800-line test architecture budget without behavior, schema or OpenAPI changes |
| Exact 312-ID acceptance register and consolidated external needs | `FND-EVIDENCE-01`, `FND-CHANGE-01`, `M0-EVD-01`, `M6-EVD-01` | Makes exclusions, mixed atomic IDs, source hashes and blockers explicit; does not create owner/verifier signatures |
| Adversarial Prompt, report and governance repair | `SHARED-PROMPT-01`, `C-CONTRACT-04/06`, `D-CONTRACT-01/04`, `M5-CUST-01` | Adds secure compiler versioning, bounded structured input, injection/confusable checks, positive Customer projection, exact decimals and neutral maker-checker defaults without changing frozen thresholds |
| Admin/Customer completion paths | `C-CONTRACT-04/05/06`, `M4-*`, `M5-CUST-01` | Adds durable Protocol/analysis/report controls and approved Customer report rendering; legacy synchronous compute is an explicit `410`, never an in-memory success |

## Compatibility and rollback

- Alembic remains one linear head. Database changes use additive/compatible contracts and the Pack 07
  dual-write/catch-up/cutover receipt; a real-data cutover still requires its own approved run.
- Stable Internal/Customer OpenAPI snapshots and Web client contracts are regenerated and verified.
- The module split preserves public facades/imports, persisted type identity and operation IDs. It can
  be rolled back as one source change without a schema/data rollback.
- Runtime release rollback rebinds an older frozen Prompt/Adapter/Profile/Protocol; immutable history is
  retained. New writes after a database cutover require the documented rollback window or forward-fix,
  never an uncoordinated schema downgrade.
- If the final verifier rejects this record, all original roadmap checkboxes remain authoritative and
  unaccepted; local Pack checkmarks do not grant release authority.

## Evidence and decision

Evidence is indexed by `GEO-non-B-execution-index-2026-07-24.md`, Pack 01--07 evidence files,
`pack-08-final-review-evidence.md`, the final evidence manifest and the exact Pack 08 machine register.
The clean final gates are `2317/2317` required non-live, `117/117` PostgreSQL/MinIO/Valkey integration,
`46/46` Chromium, `71/71` infrastructure contracts, `7/7` disposable runtime and `148/148` fault
recovery, all with zero skip. OpenAPI contracts, both Web production builds, quality and authenticated
restore through `0087` also pass. The register binds the dirty working-tree fingerprint; it does not
claim these uncommitted changes are already in `HEAD`.

Required decision roles: Product owner, engineering owner, Migration owner, QA, Security, DevOps,
release owner and an independent verifier. The autonomous implementation agent is the engineering
producer and cannot fill any of those approval/signature fields on their behalf.
