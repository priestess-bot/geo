# ADR 0004: Object Storage And Evidence Assets

Date: 2026-07-05

## Status

Accepted

## Context

The system must persist screenshots, HTML snapshots, raw provider payloads, report exports, CSV
attachments, and uploaded customer documents. The current stack already uses MinIO with an
S3-compatible object-store abstraction.

## Decision

Use an S3-compatible object-store boundary.

- Development and staging default: MinIO.
- Production may use AWS S3, Cloudflare R2, managed MinIO, or another S3-compatible backend.
- GEO code must depend on an object-store adapter, not MinIO-specific APIs.
- Evidence metadata lives in the database as `EvidenceAsset`/report artifact records with URI,
  content type, byte size, hash, scope, created actor, and retention policy.
- Downloads must go through API authorization and short-lived signed URLs or a proxy that enforces
  project scope.

## Consequences

- The application owns evidence asset metadata, hash verification, and customer/internal visibility.
- Raw object-store credentials must never reach the browser.
- Report and evidence retention can be changed without rewriting provider collectors.
