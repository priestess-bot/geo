# ADR 0008: Document Parsing And Knowledge Extraction

Date: 2026-07-05

## Status

Accepted

## Context

The knowledge base must import PDFs, DOCX, TXT, Markdown, CSV, HTML pages, FAQs, product pages, and
case studies. Writing robust parsers for these formats is not GEO-specific and would add avoidable
maintenance risk.

## Decision

Do not build document parsers from scratch.

- Use mature parsers such as unstructured, Apache Tika, PyMuPDF, python-docx, or docling after a
  small compatibility spike.
- GEO owns ingestion batches, object-store archival, chunking policy, metadata, fact extraction,
  fact review status, evidence binding, and permission checks.
- Parsed content and extracted facts must preserve source document references and hashes.

## Consequences

- W8 implementation starts with a parser adapter interface and a parser spike.
- Parser failure and partial extraction must be represented in import batch status.
- Approved facts are the only facts allowed to feed customer-facing content generation.
