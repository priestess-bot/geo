# ADR 0002: Auth Provider And RBAC

Date: 2026-07-05

## Status

Accepted

## Context

The production GEO system needs real tenants, real users, project-scoped authorization, customer
portal access, audit trails, and future SSO. Reimplementing password handling, MFA, OIDC, and
session security would increase risk without creating GEO-specific product value.

## Decision

Use an OIDC-compatible authentication boundary.

- Preferred production provider: Keycloak when self-hosting is required, or a managed OIDC
  provider when operations favor hosted identity.
- Short-term internal session support is allowed only as a bridge if it keeps the API and data
  model OIDC-compatible.
- Do not build custom password, MFA, SSO, or identity-broker functionality.
- GEO owns tenant membership, project membership, role mapping, permission checks, and audit
  semantics.
- Customer portal invitation tokens are one-time redemption credentials. After redemption, the
  portal must use an httpOnly secure session cookie, not a long-lived URL query token.

## Consequences

- W2 implementation must define users, tenant members, project members, external identity
  mappings, sessions, and invitation redemption in a way that can sit behind OIDC.
- Every protected API must derive actor, tenant, and project scope from the authenticated session
  or a trusted system actor.
- Provider secrets, customer tokens, and session identifiers must never be returned in API
  responses or written to ordinary logs.
- RBAC remains a GEO domain concern and is tested with allow/deny contract tests.
