# Connector Worker runtime

PyAirbyte runs in this isolated environment because its pinned Airbyte CDK
dependency conflicts with the optional Knowledge RAG dependency in the main
application environment.

```bash
uv sync --project apps/connector_worker --frozen
```

The process imports Connector Core from `packages/geo_core`; credentials are
resolved after a durable lease is acquired and must never be passed on the
command line or written to this directory.
