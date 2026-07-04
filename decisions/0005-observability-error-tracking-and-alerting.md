# ADR 0005: Observability, Error Tracking, And Alerting

Date: 2026-07-05

## Status

Accepted

## Context

Production GEO needs visibility into API health, worker failures, collection success rate, provider
cost, queue backlog, report generation, object-store failures, audit writes, and security-relevant
access denials. The current compose stack already includes Prometheus and Grafana.

## Decision

Use established observability tooling.

- Metrics: Prometheus.
- Dashboards and metric alerts: Grafana.
- Tracing: OpenTelemetry.
- Error tracking: Sentry or an equivalent error-tracking backend before customer production.
- LLM evaluation/trace observability may use Langfuse or promptfoo once parser/evaluator quality
  becomes a bottleneck.
- Do not build a custom metrics database, dashboard, or error tracking system.

## Consequences

- W1/W9 fixes must resolve the Grafana/Admin default port conflict.
- API and worker code must expose consistent metric names for request latency, task state,
  provider calls, cost, collection outcomes, report jobs, audit writes, and access denials.
- PII, provider secrets, customer tokens, raw prompts where inappropriate, and raw answers where
  restricted must be scrubbed before logs or traces leave the application.
