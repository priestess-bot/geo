# ADR 0007: Graph Store For Citation Graph

Date: 2026-07-05

## Status

Accepted

## Context

Citation Graph and Source Gap need graph-like relationships between answer runs, citations, source
domains, competitor evidence, source gaps, actions, reports, and audit events. Early production
does not require a dedicated graph database if the relationships are queryable and auditable in
PostgreSQL.

## Decision

Use PostgreSQL adjacency tables first.

- Store source nodes, source edges, graph evidence links, source gaps, and benchmark references in
  PostgreSQL.
- Keep a `GraphStore` interface and data export shape compatible with a future Neo4j or Apache
  Jena migration.
- Do not introduce Neo4j before query complexity, traversal depth, or graph analytics justify the
  operational cost.

## Consequences

- W5/W7 graph work can ship without a new database service.
- Graph visualizations must consume API read models, not database-specific graph query results.
- Future graph-store migration should not change report traceability semantics.
