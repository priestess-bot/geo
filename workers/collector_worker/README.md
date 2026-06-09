# Collector Worker

M2a has a deterministic fixture runner in `geno_core.collection` and fixture adapters in
`geno_core.collectors`. They implement the same `CollectorBackend` contract expected by real
platform adapters, so tests can verify AnswerRun, RawAnswer, citations, evidence assets, cost, and
AuditEvent without external API credentials.

P0a adapters:

- Implemented for contract testing: `FixturePerplexitySonarCollector`, `FixtureOpenAIWebSearchCollector`
- Planned real adapters: `PerplexitySonarCollector`, `OpenAIWebSearchCollector`

P0b planned adapters:

- `PlaywrightGoogleAIOCollector`
- `PlaywrightAIModeCollector`
- `ThirdPartySerpCollector`
- `ManualBackfillCollector`
