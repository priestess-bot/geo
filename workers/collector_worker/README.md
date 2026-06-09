# Collector Worker

M0 only defines the worker boundary. Real collectors are added as adapters that implement
`CollectorBackend`.

P0a planned adapters:

- `PerplexitySonarCollector`
- `OpenAIWebSearchCollector`

P0b planned adapters:

- `PlaywrightGoogleAIOCollector`
- `PlaywrightAIModeCollector`
- `ThirdPartySerpCollector`
- `ManualBackfillCollector`
