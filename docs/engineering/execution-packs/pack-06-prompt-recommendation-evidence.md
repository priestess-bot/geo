# Pack 06 Prompt and Recommendation evidence

Status date: 2026-07-24. Result: `LOCAL_COMPLETE / BLOCKED_EXTERNAL`.

## Reviewable vertical

1. The ten locally supported Prompt Program kinds have strict bootstrap schemas, fixed test sets, frozen model policies and immutable Release hashes. `reference_translation` remains intentionally outside the first delivery catalog.
2. Admin supports create, fixed-input diff, governed test enqueue, independent approve, freeze, runtime bind and one-way retire. Retired Releases remain historical lineage but are rejected for new runtime resolution or binding.
3. Recommendation generation freezes a real non-B evidence graph containing approved/redacted Observations, a server-computed Metric Comparison, approved Fact and Rule, frozen Question/Surface identities and the exact Recommendation Prompt Release. Board B Attribution is represented as an explicit unavailable reference, never fabricated.
4. Evidence insufficiency is a normal terminal result. An underpowered comparison reaches `insufficient_evidence`, records exact reasons and creates no model task or model call; it is not misclassified as stale and is not forced into a directional recommendation.
5. Six recommendation types map only to the governed outcomes: `hard_blocker` and `optional` create Content Brief drafts, `gap` creates a QuestionSet draft, `experiment` creates an Experiment Plan draft, `insufficient_evidence` creates a Sampling Plan draft, and `no_change` creates no draft.
6. Approval requires independent review and creates exactly one unstarted draft. `stale` and `expired` are append-only persisted versions; only unstarted drafts are blocked, pending outbox work is cancelled, and every downstream prepare action rechecks the exact approved source version.
7. The production Recommendation Worker uses the PostgreSQL Prompt resolver, durable lease/fence and immutable result projection. Producer-owned bounded summaries make approved Observation, Metric Comparison and Rule evidence usable without exposing answer text or raw artifacts.

## Automated evidence

| Evidence | Result |
|---|---|
| Prompt/Recommendation unit, API, Admin and migration contracts | `341 passed` |
| Scoped static validation | Ruff passed; mypy passed for `107 source files`; Admin typecheck passed |
| Prompt PostgreSQL lifecycle | `1 passed`; create/test/approve/freeze/bind/retire, replay and restricted roles |
| Recommendation PostgreSQL lifecycle | `1 passed`; production Worker insufficiency result, maker-checker approval, Fact retirement to persisted stale, draft block and pending outbox cancellation |
| Workflow C to Recommendation PostgreSQL vertical | `1 passed`; three independently approved encrypted/redacted Observations, semantic snapshot, comparison, rule, Fact, Question, Surface, frozen Prompt and explicit unavailable Attribution |
| Migration replay | current single head `0086_recommendation_summaries`; explicit `0086 -> 0085 -> 0086` succeeded, while the vertical also exercises `head -> 0074 -> head` |
| Stable OpenAPI | `6 passed`; Internal and Customer snapshots exported and verified |
| Chromium Admin | `5 passed`; Prompt governance/retirement and Recommendation approval, unavailable state, role denial and generation catalog; desktop plus 390px responsive checks where applicable |

## Acceptance mapping

| Pack item | Evidence |
|---|---|
| `P06-01` | ten-kind bootstrap catalog, schema/output validation, immutable policy/test identities and runtime selector tests |
| `P06-02` | API/domain/PostgreSQL lifecycle plus rendered create/diff/test/approve/freeze/bind/retire flow |
| `P06-03` | service-backed Workflow C semantic vertical and production Recommendation Worker result graph |
| `P06-04` | independent reviewer guards, append-only stale/expired versions, atomic draft/outbox propagation and prepare-action recheck |
| `P06-05` | six-type matrix, four typed downstream adapters, `no_change` zero-draft rule and direct transition bypass rejection |
| `P06-06` | partial-503 and analyst denial states, retired Release UX, unified project runtime fixture, OpenAPI/type/browser checks |

## Consolidated external needs

- At least one approved real Recommendation model runtime and budget for a governed live call; fixture/model stubs do not count.
- Board B must provide the real Attribution projection. Until then every Recommendation freezes the documented unavailable reason and cannot satisfy full `D-CONTRACT-01` or attribution acceptance.
- Independent operator approval of live Prompt test evidence and any live Recommendation before downstream use.
- Live staging, Customer approved-only projection and independent verifier evidence remain final Gate work, not Pack 06 local evidence.
