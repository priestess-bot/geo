# GEO non-B autonomous execution index

Status date: 2026-08-10

This index records the autonomous-agent execution packs that originally covered the non-B scope in `GEO-next-phase-six-month-roadmap-2026-07-21.md`. Timeboxes are elapsed agent time. Board B now has a locally runnable MVP and canonical runtime integration, governed by `GEO-external-data-cross-engine-sampling-implementation-plan-2026-07-22.md`; live Provider, GSC/GA4, Australian egress/browser capture and attribution evidence are not accepted by these non-B packs.

## Completion contract

- A checkbox is complete only when its implementation, automated verification and evidence reference exist.
- Fixtures prove deterministic behavior only; they never count as live external evidence.
- Consumer-surface parser and Browser Capture execution paths exist locally; live acceptance still requires approved Surface admission, Australian sticky egress and per-Attempt evidence.
- Recommendation attribution consumes the local attribution contract when evidence exists and records an explicit `unavailable` reference otherwise; no real Session-to-Revenue journey has been accepted.
- User-supplied credentials, accounts and approvals are collected as non-blocking requirements and requested together after all locally controllable work is complete.

## Current convergence evidence

- Commit `1877b29d779dcbc102d44ba03d6e23b16e91b6b7` is the current canonical source and runtime release identity. GitHub Actions run `31351738043` completed all four jobs successfully; the local v3 release receipt reports a clean source, exact GEO/Dify Compose identity, all required running/healthy/completed services, database head `0130_serpapi_secret_purpose` and content-addressed images.
- Private Release `geo-migration-geo-runtime-20260810T031448Z` contains the source-bound encrypted canonical GEO + Dify baseline. Its 28,863,108-byte payload was downloaded again from GitHub, reassembled and successfully decrypted/verified on this host; the payload SHA-256 is `22cea592a2ac0f62d19f724357ce9c2447a8b11034937ceb81ef1f6f12a543a1`.
- This source-side export/transport proof does not satisfy the target-host gate. A new empty primary host, historical keyring restore, live Secret canary and explicit post-restore business checks are still required.

| Pack | Budget | Scope | Status | Reviewable outcome |
|---|---:|---|---|---|
| 01 | 12h | Semantic metric durable vertical | LOCAL_COMPLETE / BLOCKED_EXTERNAL | Approved protocol and frozen manifest produce a fenced metric snapshot through Durable Job; live input and independent verification remain external |
| 02 | 10h | Statistics, drift, alerts and approved report | LOCAL_COMPLETE / BLOCKED_EXTERNAL | Deterministic comparisons and drift drive deduplicated alert/report projections; production notification and independent verification remain external |
| 03 | 10h | Five Provider sampling releases | LOCAL_COMPLETE / BLOCKED_EXTERNAL | Provider adapters execute through governed Sampling with replayable, semantically verified canaries; five live manifests still require real credentials |
| 04 | 12h | Synthetic review laboratory | LOCAL_COMPLETE / BLOCKED_EXTERNAL | Review cases progress through generation, evaluation, revision, Corpus and paired offline experiment; live nine-channel evidence remains external |
| 05 | 8h | Consumer-surface artifact parsers | LOCAL_COMPLETE / BLOCKED_EXTERNAL_LIVE_CAPTURE | Versioned parsers and the local Browser Capture path validate fixture/manual artifacts without claiming live Australian capture |
| 06 | 10h | Prompt and recommendation closure | LOCAL_COMPLETE / BLOCKED_EXTERNAL | Maker-checker Prompt Releases and evidence-bound Recommendation drafts work end to end; real model, B attribution and live approval remain external |
| 07 | 10h | Migration and operational hardening | LOCAL_COMPLETE / BLOCKED_EXTERNAL_FINAL_GATES | Upgrade, dual-write cutover, authenticated restore, historical keyrings, runtime faults and frozen performance contracts are verified |
| 08 | 8h | Full review, usability and evidence closure | LOCAL_COMPLETE / BLOCKED_EXTERNAL_REVIEW | Exact 331-ID register has zero local gaps; security/usability repairs and final source-bound gates pass; live evidence and independent signatures remain external |
| 09 | 6h | Dify Style Profile and Recommendation migration | LOCAL_COMPLETE / BLOCKED_EXTERNAL_BUSINESS_EVIDENCE | Both flows freeze the published Dify identity, persist fenced results and expose read-only Admin lineage; real approved-sample Profile build and evidence-backed Recommendation Job remain external |

Each pack has a dedicated checklist in this directory. The main roadmap remains the source of product acceptance IDs; these files are execution evidence maps, not substitute acceptance criteria. Current Board B local/live status is authoritative only in the main roadmap and the external-data implementation plan, not in the historical non-B pack boundaries.
