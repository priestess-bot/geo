# ADR 0001: M0 Lightweight Open-source Stack

Date: 2026-06-09

## Status

Accepted

## Context

The AU launch path prioritizes a stable evidence chain before content generation or broad
platform coverage. M0 needs runnable infrastructure, interface contracts, and auditable data
models without locking the project into heavyweight components too early.

## Decision

Use the following M0 stack:

- FastAPI for the API service.
- Next.js for the console shell.
- PostgreSQL with pgvector for primary data and early vector needs.
- MinIO for evidence assets and report exports.
- LiteLLM as the LLM gateway integration point.
- Playwright as the browser automation integration point.
- simple worker/cron before Temporal.

ClickHouse, Temporal, Langfuse, promptfoo, SearXNG, Metabase, Qdrant, and Neo4j remain explicit
interfaces or migration paths, not P0a blockers.

## Consequences

- The first vertical slice can run with fewer services.
- Data contracts must be stable enough to support future backend replacement.
- Every collector, parser, scoring run, manual backfill, entity confirmation, and report export
  must write `AuditEvent` or evidence links once the runtime persistence layer is wired.
