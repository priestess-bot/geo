# Pack 05 consumer-surface parser evidence

Status date: 2026-07-24. Result: `LOCAL_COMPLETE / BOARD_B_LIVE_CAPTURE_EXCLUDED`.

## Reviewable vertical

1. Google AI Overviews, Google AI Mode and Bing Copilot each have an immutable, independently identified parser release. A release is only `fixture_ready`, always reports `automated_capture_eligible=false`, and cannot borrow another release's fixture count.
2. The parser consumes the exact `consumer-surface-artifact-v1` contract and distinguishes captured answers, verified surface absence, consent/login/access blocks, geographic mismatch, egress change, timeout, wrong surface and selector drift. Non-string structured fields, duplicate locators and cross-surface markers fail closed.
3. Governed manual JSON is redacted before parsing or storage. The persistent summary contains only release identity, outcome, block reason, eligibility, counts and hashes; answer text, citation values, URLs and raw locations are absent from API/Admin projections.
4. `0081_surface_parser_results` stores the text-free summary through a Project-scoped atomic wrapper around manual-evidence submission. App roles have no direct insert privilege, rows are immutable and downgrade refuses when evidence exists.
5. A maker-approved manual import creates exactly one Attempt/Durable Job. The Worker verifies the exact parser release against the frozen SourceStratum, writes parser lineage to the Observation, marks block/drift outcomes ineligible, and lets valid capture/absence evidence enter the existing semantic materializer without changing Task identity or denominator strata.
6. Admin lists the three releases separately, only offers the release matching the selected manual SourceStratum, forces parsed imports to JSON transcript evidence, and labels the result `manual_ui`, `non-live` and `no Australian egress proof`.

## Automated evidence

| Evidence | Result |
|---|---|
| Parser/API/Admin/migration/Worker/materializer focused suite | `54 passed`; includes 22 parser tests and three independent 30-case gold suites |
| Per-release fidelity | each release: 30 fixtures, 11 captured, 5 valid absences, 2 cases for each required block reason, classification `1.0`, answer completeness `1.0`, citation accuracy `1.0`, zero ordinary-result false positives and zero block-as-absence errors |
| Isolated PostgreSQL 16 + real temporary MinIO/Valkey | `2 passed`; fresh migration to `0081`, App/Worker RLS, parser-summary immutability, downgrade refusal, encrypted manual artifact, Durable Job, Observation and semantic snapshot |
| Workflow C Chromium | `4 passed`; existing fixed-denominator/statistics/alert flows plus desktop and 390px manual parser selection/review, no console error, framework overlay or horizontal overflow |
| Stable OpenAPI | `6 passed`; two surfaces exported and verified; API-client contract/typecheck passed |
| Static validation | Ruff passed; scoped mypy passed; Admin typecheck and `git diff --check` passed |

The browser flow proves `manual Google AI Overviews Run -> matching release selection -> JSON transcript contract -> text-free review summary`. The service-backed flow proves encrypted/redacted bytes reach a fenced Observation and semantic snapshot. Neither flow drives a third-party browser or establishes live/Australian capture.

## Acceptance mapping

| Pack item | Evidence |
|---|---|
| `P05-01` | immutable release IDs/hashes, separate API inventory and release-count isolation test |
| `P05-02` | strict parser outcome tests, ordinary SERP/featured-snippet absence tests, governed JSON API and PostgreSQL import |
| `P05-03` | parser release stored on manual Import/Attempt/Observation lineage; SourceStratum matching and unchanged Task identity |
| `P05-04` | 90 total per-release fixtures, mutation tests, strict structured-field/locator tests and deterministic fidelity hashes |
| `P05-05` | server-side Action validation, text-free type guard, desktop/mobile Chromium interaction and non-live scope banner |

## Consolidated external needs

- Governed, lawfully supplied real manual transcript exports for each consumer surface when operators want non-live real-page validation.
- Independent reviewer approval for any real manual evidence; the submitter cannot approve their own import.
- Board B must separately provide platform authorization, Browser Capture Connector, sticky Australian egress lease, pre/target/post geographic proof, account/device/cookie profile and per-Surface live fidelity evidence before any automated or Australian claim is permitted.

These needs remain non-blocking for Packs 06--08. Fixture/manual evidence must never satisfy `EXT-UI-*`, `EXT-EGR-*`, `REAL-EXT-*` or final live-release gates.
