# ADR 0003: Task Queue And Workflow

Date: 2026-07-05

## Status

Accepted

## Context

Collection, parsing, scoring, report generation, notification, and retest jobs cannot depend on
long-running synchronous HTTP requests. The repository already has Python worker scripts, but
production workflows need consistent task state, retries, cancellation, observability, and
idempotency.

## Decision

Use a two-step worker strategy.

- Near term: standardize the existing Python workers behind a common task interface and shared
  run state tables.
- Production durable workflows: use Temporal for long-running or multi-step flows such as
  collect -> parse -> score -> report -> retest.
- Short queue/broker needs may use Celery, RQ, or Dramatiq with Valkey if a simple queue is needed
  before Temporal is fully introduced.
- Prefer Valkey over Redis for a strictly open-source cache/broker default.
- Do not build a custom general-purpose queue, scheduler, retry engine, or workflow runtime.

## Consequences

- W1/W3 tasks must define idempotency keys, retry policy, cancellation, dead-letter handling, and
  task status read models.
- Workers must write audit events with the triggering actor or system actor.
- Temporal adoption is not required before the first real connector, but task interfaces must not
  block a later Temporal migration.
