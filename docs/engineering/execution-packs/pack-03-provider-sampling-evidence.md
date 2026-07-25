# Pack 03 local evidence: five Provider sampling releases

Evidence date: 2026-07-24. Local status: `LOCAL_COMPLETE / BLOCKED_EXTERNAL`.

This evidence covers Board C Provider/Grounded API sampling only. It does not implement or accept Board B connectors, official reports, Australian proxy/browser capture, or attribution.

## Frozen identity matrix

| Gateway provider | Observation source | Capture method | Frozen search contract | Local acceptance rule |
|---|---|---|---|---|
| OpenAI | `openai/openai_api` | `provider_api` | `web` | Structured output, web-search event, citation, reported model and country-level location receipt |
| Gemini | `google/google_gemini_api` | `provider_api` | `google_search` | Structured output plus grounding chunk/support/query lineage; Gateway provider remains `gemini` |
| Perplexity | `perplexity/perplexity_api` | `provider_api` | `web` | Structured output, search result, citation, usage/cost and country-level request lineage |
| Microsoft | `microsoft/microsoft_foundry_bing_grounding` | `proxy_grounded_api` | `bing_grounding` | Frozen Foundry Agent, website citation and Bing display/query reference; never labelled Copilot UI |
| Kimi | `kimi/kimi_api` | `provider_api` | `disabled` | Structured output and reported model; search/citation counts must remain zero until native Search is separately proven |

`provider_sources.py` is the single business-source-to-Gateway route map. Known Provider surfaces fail closed when platform, surface, capture method or Gateway provider differ. Migration `0078_provider_source_identity` makes Kimi a first-class Monitoring source without inventing a consumer-UI identity.

## Reviewable local outputs

- `ProviderSamplingRelease` freezes Model Gateway Adapter/Model identities and hashes, request/result/error/citation/location contracts, fixture/test/dependency hashes, reported-model policy, search capability, data policy, retention/display decisions, documentation, owner and full source commit. Published states require a real canary and maker evidence; terminal states require a reason.
- Release parsing rejects unknown fields, hash drift, credential-bearing documentation URLs, contradictory raw storage/display/retention policy, invalid source commits and unsupported Kimi Search claims.
- `ProviderCanaryRunEvidence` freezes the exact Question/version/repetitions `1..10` denominator. Acceptance requires at least 80% valid observations and at least eight valid repeats for every question.
- The redacted manifest contains planned Task identity, call/Job/Attempt IDs, hashes, provider request/model, citation/search counts, policy decisions and location lineage. It cannot contain prompts, answers, headers, credentials, artifact URIs or raw content.
- Verification requires an independently supplied frozen release and semantically rebuilds the Run and manifest. Recalculating SHA-256 after forging completion counts, model identity, denominator or citations does not pass.
- `workflow_c_provider_canary.py execute` validates Suite/Release identity before writes, replays Run start and bulk enqueue with the same idempotency keys, polls an explicit terminal state, reads the completed PostgreSQL projection twice, then writes a `0600` manifest. Authentication and database URLs are read only from named environment variables or secret files.

## Verification executed

| Evidence | Result |
|---|---|
| Five adapter, secure transport, credential resolver, artifact, Sampling execution, canary, CLI and migration contract tests | `108 passed` |
| Focused semantic verifier/release/PostgreSQL reader/CLI tests | `21 passed` |
| Ruff on Provider release/canary/CLI and tests | passed |
| Scoped mypy on Provider release/canary/verifier/CLI | passed |
| Stable Internal/Customer OpenAPI export and verification | `6 passed`; two snapshots verified |
| Admin Web TypeScript check for `kimi/kimi_api` | passed |
| Isolated `pgvector:pg16` migration | empty database `upgrade head -> downgrade 0077 -> upgrade head`; Kimi surface true after upgrade and false after downgrade |

No fixture, mock response or local migration result is counted as a live Provider release.

## Consolidated external needs

The following are non-blocking for subsequent local packs, but block each corresponding Provider from `live_candidate` or `approved`:

- Five project-scoped Secret References, approved Model Gateway Adapter/Model Releases, exact configured/reported model policy, and current provider data-retention/display decision.
- An approved Sampling admission policy and one immutable ten-repeat Suite per Provider with `purpose=provider_live_canary`.
- For Microsoft, the approved Foundry project endpoint plus exact Agent name/version and Australian market/language settings; for Kimi, an explicit decision to keep Search disabled or new official capability evidence and a new release.
- Live quota/budget for every planned task, an authorized operator identity, and a database reader URL supplied through a secret file or protected environment.
- One completed manifest per Provider produced by `execute`, followed by verification against its release and independent maker/checker review. Failed, partial or unavailable providers remain `BLOCKED_EXTERNAL`; other providers cannot lend them evidence.
