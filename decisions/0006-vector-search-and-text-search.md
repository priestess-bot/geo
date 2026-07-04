# ADR 0006: Vector Search And Text Search

Date: 2026-07-05

## Status

Accepted

## Context

The system needs semantic search over customer documents and knowledge facts, plus keyword/full-text
search over prompts, evidence, reports, and operational data. The current database image already
includes pgvector.

## Decision

Use PostgreSQL first.

- Vector search starts with pgvector.
- Keyword search starts with PostgreSQL full-text search and indexed structured fields.
- Qdrant or Milvus becomes the vector-store migration path when pgvector cannot satisfy scale,
  latency, filtering, or operational isolation needs.
- OpenSearch becomes the search migration path when PostgreSQL full-text search cannot satisfy
  evidence/report/log search needs.
- GEO owns document chunking, metadata, fact status, project scope, and permission filtering.

## Consequences

- W8 knowledge-base work should not introduce a separate vector database by default.
- VectorStore and SearchStore interfaces should be defined so Qdrant/Milvus/OpenSearch can be added
  later without changing product workflows.
- All search results must respect tenant and project authorization.
