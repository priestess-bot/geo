# Pack 08: full review, usability and evidence closure

Budget: 8h agent time. Status: `LOCAL_COMPLETE / BLOCKED_EXTERNAL_REVIEW`.

- [x] `P08-01` Reconcile every non-B roadmap ID to implementation, test and evidence (90m).
- [x] `P08-02` Run unit, integration, OpenAPI, both web builds and Chromium suites (2h).
- [x] `P08-03` Review role boundaries, raw-data leakage, accessibility and repeated operator workflows (90m).
- [x] `P08-04` Inspect prompt/process outputs and autonomously revise weak defaults or confusing states (90m).
- [x] `P08-05` Run production-network and backup/restore checks that are locally controllable (1h).
- [x] `P08-06` Produce final evidence manifest and one consolidated request for external credentials/accounts/approvals (30m).

Stop condition result: every locally controllable non-B item is implemented and reviewed. The exact
register has zero `LOCAL_GAP`; remaining items are either `BLOCKED_EXTERNAL`,
`READY_FOR_REVIEW` pending an independent verifier, or `EXCLUDED_B_FOR_CURRENT_ITERATION`. No fixture,
controlled acceptance run or manual artifact is represented as live external evidence.

## Final evidence ledger

| Gate | Final result |
|---|---|
| Exact roadmap reconciliation | `scripts/non_b_roadmap_acceptance.py` covers all 312 stable IDs: 252 included non-B, 47 excluded B and 13 DoR/DoD templates. The final self-hashed register is `pack-08-acceptance-register.json`; it is exported only after this ledger and all source edits are frozen so its dirty-tree fingerprint remains verifiable. |
| Required non-live suite | `2317 passed, 0 failed, 0 skipped`; 121 live/integration/browser tests deselected by the declared gate. |
| Python/Web/architecture quality | Ruff passed; MyPy passed 741 source files; six Web workspaces typechecked; repository secret scan passed 1,995 files; architecture `42/42`. Backup scan disclosed only the two pre-existing 2026-07-16 plaintext backup directories, which remain an explicit residual risk. |
| Stable API and Web contracts | Two OpenAPI surfaces re-exported; stable OpenAPI `7/7`; Web API/BFF contracts passed; Admin and Customer production builds passed. |
| Required Chromium | Admin `28/28`, Customer `12/12`, Workflow C `6/6`; total `46 passed`, `0 skipped`, `0 flaky`. Manual 320px and desktop screenshot review found no overlap or horizontal overflow after the Workflow C label-size repair. |
| Real dependency integration | Fresh PostgreSQL 16 database migrated `base -> 0087`; restricted App/Worker roles, real MinIO and real Valkey: `117 passed, 0 failed, 0 skipped`. Controlled inline acceptance passed in `inline_isolated` mode; result SHA-256 `d82c546b4faa7913822dfaa7aa3fa2123d42faf08d8d1c16198b54fe3e1ed80f`. |
| Infrastructure/runtime | Infrastructure contracts `71/71`; production network isolation `2/2`; disposable F018 Docker runtime `7/7`, all temporary resources removed. |
| Migration | Dual-write/catch-up/cutover/rollback receipt remains accepted; canonical hash `8b293086e540a93fd52d3f76e7467ea9b4741f820c9b1d466ef4af836f583857`. |
| Fault recovery | Dedicated empty database; 8 scenarios/21 hashed targets; `148 passed, 0 failed, 0 skipped`; verified receipt hash `0587318d710e3386c911d2e797a9fca28fd22a25e50116025c50f1461ecffc1d`. |
| Empty-environment restore | Restored through `0087_wfc_report_receipts`: 234 tables, 109 non-B relations, 12 objects in five buckets, 87 migration checksums, ACL/RLS and historical Secret/Provider/Synthetic/Recommendation/Workflow C keyrings. Receipt file SHA-256 `e25deddf96b97adcd19e0cdc8e947ea4d82114867a58b457307bba86553286c5`. |

Diagnostic runs that exposed a stale Prompt compiler fixture, missing object-store bucket, missing
database isolation marker and a reused fault database are intentionally excluded from acceptance
counts. Each was corrected at the fixture/environment boundary, reproduced in isolation and followed
by the clean final run above.

## Review repairs

- Customer Workflow C reports now use a positive payload allowlist, exact decimal parsing and an
  approved/current/real-only projection. Unrelated portal modules do not request or surface report
  failures.
- Admin Workflow C now exposes maker-checker Protocol and Report commands plus durable analysis Jobs;
  retired synchronous compute endpoints return authenticated RFC 9457 `410` responses instead of
  pretending to run in memory.
- Prompt structured input has a versioned secure compiler, bounded depth/node/number limits, duplicate
  and non-finite JSON rejection, delimiter escaping and centralized Unicode/confusable injection
  checks. Frozen v1 Releases retain their historical render/hash behavior.
- Synthetic governance forms start neutral, require complete allowances and prevent a submitter from
  approving their own import. Warning results remain separately visible while contributing to the
  governed aggregate exactly as frozen by the roadmap.
- Recommendation evidence resolves only from producer-owned immutable Workflow C lineage. Directly
  seeded/orphan statistical projections remain RLS-readable for diagnostics but cannot become
  Recommendation evidence.

## Machine evidence and decision

- Final local evidence manifest: `pack-08-final-evidence-manifest.json`. Its status is
  `BLOCKED_EXTERNAL`, not `ACCEPTED`, because `DOR-01`, `DOD-06` and `DOD-07` still need named people,
  applicable live evidence and an independent signature.
- Exact stable-ID register: `pack-08-acceptance-register.json`; its source identity explicitly binds
  the current dirty working tree rather than claiming that uncommitted changes are present in `HEAD`.
- Consolidated external request: `pack-08-external-needs-register.md`.
- Change record awaiting independent decision: `pack-08-change-record.md`.

Board B remains excluded: Connector Core, GSC/GA4, official reports, Australian egress/browser
capture, event intake and attribution ledger are not completed or accepted by Pack 08.
