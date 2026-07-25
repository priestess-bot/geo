# GEO non-B autonomous execution index

Status date: 2026-07-24

This index converts the non-B scope in `GEO-next-phase-six-month-roadmap-2026-07-21.md` into autonomous-agent execution packs. Timeboxes are elapsed agent time. Board B remains excluded: Connector Core, GSC/GA4, official reports, Australian egress/browser capture connectors, attribution event intake and attribution ledger are neither implemented nor accepted by these packs.

## Completion contract

- A checkbox is complete only when its implementation, automated verification and evidence reference exist.
- Fixtures prove deterministic behavior only; they never count as live external evidence.
- Consumer-surface parsing is limited to supplied/manual artifacts until Board B authorization, sticky egress and browser capture exist.
- Recommendation attribution uses an explicit `unavailable` reference while Board B is excluded.
- User-supplied credentials, accounts and approvals are collected as non-blocking requirements and requested together after all locally controllable work is complete.

| Pack | Budget | Scope | Status | Reviewable outcome |
|---|---:|---|---|---|
| 01 | 12h | Semantic metric durable vertical | LOCAL_COMPLETE / BLOCKED_EXTERNAL | Approved protocol and frozen manifest produce a fenced metric snapshot through Durable Job; live input and independent verification remain external |
| 02 | 10h | Statistics, drift, alerts and approved report | LOCAL_COMPLETE / BLOCKED_EXTERNAL | Deterministic comparisons and drift drive deduplicated alert/report projections; production notification and independent verification remain external |
| 03 | 10h | Five Provider sampling releases | LOCAL_COMPLETE / BLOCKED_EXTERNAL | Provider adapters execute through governed Sampling with replayable, semantically verified canaries; five live manifests still require real credentials |
| 04 | 12h | Synthetic review laboratory | LOCAL_COMPLETE / BLOCKED_EXTERNAL | Review cases progress through generation, evaluation, revision, Corpus and paired offline experiment; live nine-channel evidence remains external |
| 05 | 8h | Consumer-surface artifact parsers | LOCAL_COMPLETE / BOARD_B_LIVE_CAPTURE_EXCLUDED | Versioned parsers validate fixture/manual artifacts without claiming live capture |
| 06 | 10h | Prompt and recommendation closure | LOCAL_COMPLETE / BLOCKED_EXTERNAL | Maker-checker Prompt Releases and evidence-bound Recommendation drafts work end to end; real model, B attribution and live approval remain external |
| 07 | 10h | Migration and operational hardening | LOCAL_COMPLETE / BLOCKED_EXTERNAL_FINAL_GATES | Upgrade, dual-write cutover, authenticated restore, historical keyrings, runtime faults and frozen performance contracts are verified |
| 08 | 8h | Full review, usability and evidence closure | LOCAL_COMPLETE / BLOCKED_EXTERNAL_REVIEW | Exact 312-ID register has zero local gaps; security/usability repairs and final source-bound gates pass; live evidence and independent signatures remain external |

Each pack has a dedicated checklist in this directory. The main roadmap remains the source of product acceptance IDs; these files are execution evidence maps, not substitute acceptance criteria.
