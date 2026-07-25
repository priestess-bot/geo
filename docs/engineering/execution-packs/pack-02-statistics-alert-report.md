# Pack 02: statistics, drift, alerts and approved report

Budget: 10h agent time. Status: `LOCAL_COMPLETE / BLOCKED_EXTERNAL` (2026-07-24).

- [x] `P02-01` Freeze comparison/drift protocols and add async admission; verify replay and project isolation (2h).
- [x] `P02-02` Materialize paired inputs from immutable metric snapshots without denominator mixing (2h).
- [x] `P02-03` Persist deterministic bootstrap/Newcombe/Holm outcomes including `inconclusive` and negative gain (2h).
- [x] `P02-04` Drive deduplicated alert lifecycle and inbox/SMTP/signed Webhook delivery from frozen outputs (2h).
- [x] `P02-05` Approve an immutable Workflow C report and expose only its approved Customer projection (90m).
- [x] `P02-06` Run quality, failure/replay tests and update evidence/checklists (30m).

Validation: unit, isolated PostgreSQL/Valkey, delivery fixture and API contract suites. No B official-report import is accepted here.

Evidence:

- `0076_wfc_stat_protocols` and `0077_wfc_alert_report_api` provide governed maker-checker releases, selector-only server admission, project RLS, immutable receipts and report approval guards.
- `test_workflow_c_semantic_vertical_postgres.py` passed against an isolated PostgreSQL database plus temporary real MinIO and Valkey, covering manual Observation -> semantic snapshots -> comparison -> drift -> threshold alert -> three notification jobs.
- Alert/report compatibility integration tests passed against isolated PostgreSQL, including disposition replay, report source recheck and Customer-approved-only projection.
- The combined alert, analysis, API and migration suite passed `133` tests; the three isolated service-backed vertical/compatibility tests passed separately. Ruff and scoped mypy passed.
- The stable API keeps the former synchronous semantic/comparison/drift paths only as deprecated compatibility endpoints returning RFC 9457 `410 Gone` with a successor `Link`; durable `/jobs` admission is the sole production computation path and is enforced by the OpenAPI verifier.
- Live Provider evidence, connector failure alerts, B official-report imports and independent verification remain external/B Gate requirements and are not claimed by this Pack.
