# ADR 0001: Lightweight Open-source Stack Foundation

Date: 2026-06-09

## Status

Accepted

## Context

The current execution target is GEO Production v1, not an MVP, pilot, AU-only launch, or phased
external release. Production v1 still needs a lightweight, runnable infrastructure foundation,
stable interface contracts, and auditable data models without locking the project into heavyweight
components too early.

## Decision

Use the following foundation stack:

- FastAPI for the API service.
- Next.js for the console shell.
- PostgreSQL with pgvector for primary data and early vector needs.
- MinIO for evidence assets and report exports.
- LiteLLM as the LLM gateway integration point.
- Playwright as the browser automation integration point.
- standardized Python workers before Temporal is introduced for durable workflows.

ClickHouse, Temporal, Langfuse, promptfoo, SearXNG, Metabase, Qdrant, and Neo4j remain explicit
interfaces or migration paths. They are introduced when the corresponding Production v1 workstream
requires their capabilities, not as default prerequisites for every local run.

## Consequences

- Production v1 development can run locally with fewer services while preserving migration paths.
- Data contracts must be stable enough to support future backend replacement.
- Every collector, parser, scoring run, manual backfill, entity confirmation, and report export
  must write `AuditEvent` or evidence links once the runtime persistence layer is wired.
