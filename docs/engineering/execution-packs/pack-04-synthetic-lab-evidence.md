# Pack 04 synthetic review laboratory evidence

Status date: 2026-07-24. Result: `LOCAL_COMPLETE / BLOCKED_EXTERNAL`.

## Reviewable vertical

1. Admin submits only governed selectors for Profile build, Review Case execution, candidate Corpus, Corpus approval and Offline Experiment.
2. Server admission resolves immutable Fact, Profile, QuestionSet, Prompt Release, model runtime and completed Review/Corpus lineage before atomically creating a Durable Job, exact task and outbox event.
3. Review execution produces four candidates, runs claim/conflict/style/arbiter checks, performs at most two revision rounds and one regenerate batch, and preserves the selected candidate text/hash.
4. Corpus finalization accepts only passed/warning results, rejects duplicate candidate outputs, uses the current lease/fence and persists warning strata.
5. Offline execution derives no-corpus/current/candidate arms, runs exactly ten paired repetitions per question, persists every slot plus a deterministic result summary, enforces the frozen valid-pair threshold and exposes warning strata in Admin.
6. Synthetic resources remain `synthetic=true`, `test_only=true`, `publication_eligible=false`; Customer OpenAPI has no Synthetic Lab route and the domain projection rejects publication.

## Automated evidence

| Evidence | Result |
|---|---|
| Synthetic unit/API/Admin/migration/worker focused suite | `255 passed` |
| Isolated PostgreSQL Synthetic suite at Alembic head `0080_synthetic_corpus_execution` | `2 passed`; fresh upgrade, `0029 -> head`, App/Worker RLS, lease/fence finalization and Corpus-evidence downgrade refusal |
| Admin Chromium flow | `4 passed`; desktop/mobile boundary, unavailable/conflict behavior and selector-only Corpus/three-arm commands |
| Stable OpenAPI verifier | `6 passed`; 2 surfaces verified |
| Python static validation | Ruff passed; mypy passed for `78 source files`; `git diff --check` passed |
| Admin and API-client TypeScript | both typechecks passed |

The PostgreSQL Corpus case verifies a real App enqueue, Worker claim/load, fenced result insert, Durable Job completion and Admin warning projection. The migration ID `0079_synth_profile_runtime` is intentionally at most 32 characters so fresh PostgreSQL databases can store it in Alembic's default version column.

## Acceptance mapping

| Pack item | Evidence |
|---|---|
| `P04-01` | nine-channel workload/release-gate contracts and existing release-gate tests; live inputs remain external |
| `P04-02` | selector-only Review API/Admin, governed six-prompt task and four-candidate executor tests |
| `P04-03` | claim/conflict/subject/style/arbiter tests including `derived_or_unknown` warning behavior |
| `P04-04` | deterministic two-revision/one-regenerate/cancel/lease/Fact-stale tests |
| `P04-05` | Corpus/Offline domain tests, typed Worker output summary, PostgreSQL Corpus vertical and result hash recomputation |
| `P04-06` | Chromium selector-only commands, warning presentation, retention integration already recorded in the main roadmap and Customer denial tests |

## Consolidated external needs

- Approved access or compliant manual-import material for all nine channels, including any normal-login account used for live collection.
- At least 200 deduplicated, anonymized, human-approved Australian-English samples per channel.
- One independent operator/reviewer for Profile and Corpus maker-checker actions and the 360 fixed Case rubric.
- Real budgeted model credentials for at least three providers used across generation, judge and arbiter roles.
- Final per-channel release evidence: `passed >= 95%`, subject mix `0`, anti-copy violations `0`, mean style score `>= 4.2/5`, plus human sign-off.

These needs are non-blocking for later local execution packs and must be requested together during final evidence closure. No fixture, mock or single-channel result may satisfy them.
