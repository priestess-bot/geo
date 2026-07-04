# ADR 0010: Frontend Component Stack

Date: 2026-07-05

## Status

Accepted

## Context

The Admin, Customer, and Dashboard apps need complex forms, tables, tabs, dialogs, accordions,
charts, and graph views. Hand-writing low-level UI primitives would slow delivery and introduce
accessibility and interaction bugs.

## Decision

Use mature frontend primitives.

- Continue Next.js, React, and TypeScript.
- Use shadcn/ui and Radix primitives for dialogs, tabs, menus, accordions, popovers, and form UI
  primitives where appropriate.
- Use Zod and React Hook Form for non-trivial form validation.
- Use TanStack Table for complex table sorting, filtering, pagination, column visibility, and row
  actions.
- Use ECharts or Recharts for ordinary charts. Choose one during the first chart-heavy task.
- Use React Flow or Cytoscape.js for Citation Graph visualization. Choose one during the first
  graph-heavy task.

## Consequences

- GEO still owns page composition, information architecture, visual style, permission-gated actions,
  and business-specific components.
- Component dependencies should be introduced intentionally rather than all at once.
- Playwright tests must cover critical customer/admin interactions, especially permissions,
  report access, prompt import/edit, connector configuration, and evidence drill-down.
