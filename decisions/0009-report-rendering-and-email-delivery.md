# ADR 0009: Report Rendering And Email Delivery

Date: 2026-07-05

## Status

Accepted

## Context

The system must produce customer-facing reports and send invitations, report notifications, and
operational alerts. PDF layout engines and email delivery infrastructure are mature commodity
capabilities and should not be reimplemented.

## Decision

Use existing rendering and email infrastructure.

- Report HTML is owned by the GEO application.
- PDF rendering starts with HTML-to-PDF through Playwright print. WeasyPrint remains an alternative
  if browser rendering is too heavy.
- CSV and Markdown exports use standard libraries and deterministic templates.
- Email delivery uses an adapter over SMTP, AWS SES, SendGrid, Resend, or another delivery provider.
- GEO owns report template versioning, report snapshot metadata, method disclosure, evidence
  appendix, email event semantics, and notification authorization.

## Consequences

- Reports are immutable `ReportExport` snapshots and are not overwritten when templates change.
- Email provider changes should not affect invitation, report, or alert workflows.
- Customer-facing report downloads must enforce project authorization and short-lived access.
