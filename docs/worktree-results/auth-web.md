# auth-web Worktree Handoff

## Branch And Commits

- Branch: `codex/auth-web`
- Base: `44729afe6e232ae68725cd77752018ed22ec8959`
- Main implementation: `16b3be1` (`fix(auth-web): make invitation redemption recoverable`)
- Complete-delivery follow-up: `75d273f` (`fix(auth-web): require complete session delivery proof`)
- This handoff is committed separately as the branch head.

## Delivered Behavior

- Admin and Customer consume byte-identical typed Auth v2 contracts. Preflight is a discriminated union and accepts the backend's nullable `recommended_surface`/`invitation_role` only for the compatible states where null is valid.
- Both surfaces use `redeem-prepare -> redeem -> session-confirm`. Prepare reuses a matching, unexpired recovery Cookie before calling preflight, so a page refresh after a lost 303 keeps the original `Idempotency-Key`.
- Recovery data is AES-256-GCM authenticated and binds key, surface, token fingerprint, request hash, issued time and expiry. The 10-minute Cookie is HttpOnly, SameSite=Lax, Path=/ and Secure in production.
- Recovery configuration supports exactly one of `GENO_AUTH_RECOVERY_COOKIE_SECRET` or `GENO_AUTH_RECOVERY_COOKIE_SECRET_FILE`; dual sources, secrets shorter than 32 bytes, invalid booleans and insecure production Cookies fail closed.
- Login requires a valid recovery Cookie before any upstream mutation, sends no client `accepted_by/reason`, forwards every upstream `Set-Cookie`, and only returns fixed 303 landings (`/projects` or `/`).
- Wrong-surface results are rejected before redeem, preserve stable code/detail/correlation/recommended surface, and link to the other portal with only the safe `invitation_id` query.
- Session confirmation validates the complete nested scope-v2 DTO and exact `project_ids` projection. It requires both Session and CSRF Cookies, forwards only those allowlisted values to `/v1/auth/me`, and clears recovery only after a valid response.
- `ADMIN_ROLES`, flat-role inference and the Admin bootstrap-session form were removed.
- Admin and Customer request server-side `surface=admin|customer` project projections. Customer pages retain structured partial-load errors and handle zero projects or a revoked selection.
- Customer project scopes are fetched in 200-row pages up to a fail-closed 5,000-project limit; total drift, duplicates, invalid IDs and truncated pages are rejected. The E2E selects project 201. Admin uses explicit 50-row offset pagination and redirects stale offsets.
- Raw invitation tokens are held only in component memory. New invitation URLs no longer contain the token.

## Environment And Integration Wiring

Production should mount one shared Docker/Compose secret into both web services and set:

```text
GENO_AUTH_RECOVERY_COOKIE_SECRET_FILE=/run/secrets/geno_auth_recovery_cookie
GENO_RUNTIME_SESSION_COOKIE_SECURE=true
CUSTOMER_WEB_BASE_URL=https://<customer-public-origin>/
ADMIN_WEB_BASE_URL=https://<admin-public-origin>/login
```

Do not also set `GENO_AUTH_RECOVERY_COOKIE_SECRET`. The secret file must contain at least 32 bytes and must not use a `NEXT_PUBLIC_` variable. `CUSTOMER_WEB_BASE_URL` and `ADMIN_WEB_BASE_URL` must be browser-reachable public origins, not Docker-internal service names.

The integration branch still owns Compose/secret mounting. It must propagate the recovery secret and public counterpart URL to both services. Existing `API_INTERNAL_BASE_URL`, runtime Session Cookie names and `GENO_RUNTIME_AUTH_MODE=session` remain required.

Reconcile the committed DTO with the merged Auth OpenAPI snapshot/generated types. The worktree was manually checked against the in-progress auth-core response envelope (`session`) and also accepts the legacy wrapper key (`auth`) while requiring scope v2.

## Verification

Passed:

```text
python3 -m unittest \
  tests.test_auth_web_contracts \
  tests.test_admin_customer_web_contracts \
  tests.test_web_console_contracts
# 47 tests

npm --prefix apps/admin-web run typecheck
npm --prefix apps/customer-web run typecheck
npm --prefix apps/admin-web run build
npm --prefix apps/customer-web run build

python3 scripts/run_auth_surface_session_e2e.py --contract-only
# 36 HTTP/BFF checks

python3 scripts/run_auth_surface_session_e2e.py --browser
# 36 contract checks plus Chromium desktop/mobile interaction

git diff --check
python3 -m py_compile scripts/run_auth_surface_session_e2e.py tests/test_auth_web_contracts.py
```

The mock E2E proves wrong-surface zero consumption, no-recovery zero mutation, invalid/stale preflight mapping, lost-303 refresh recovery with unchanged key/Cookies, Session/CSRF forwarding, partial-Cookie confirmation rejection, recovery-cookie non-forwarding, invalid nested scope rejection, fixed landing, Admin/Customer projection and selection of the 201st customer project.

Browser plugin was not available, so regular Python Playwright/Chromium was used as allowed by the task. It covered Admin wrong-surface and successful desktop login plus Customer 390x844 mobile login. There were no unexpected console errors; the one expected browser resource event was the deliberately exercised 409 mismatch.

Uncommitted screenshots were written outside the repository:

```text
/tmp/geo-auth-web-playwright-1zqiyp7z/admin-surface-mismatch.png
/tmp/geo-auth-web-playwright-1zqiyp7z/admin-desktop.png
/tmp/geo-auth-web-playwright-1zqiyp7z/customer-mobile.png
```

## Remaining Integration Checks

- Run the same E2E against the merged auth-core API and PostgreSQL migration instead of the strict mock.
- Verify byte-equivalent replay after a real API commit/response loss and confirm backend ciphertext erasure requires valid CSRF proof.
- Run merged OpenAPI diff/generated DTO checks and the aggregate Production Gate.
- Run Chromium plus the supported Firefox/WebKit matrix if cross-browser release coverage is required.
- Add Compose wiring for the two public portal URL variables and recovery secret file; this branch intentionally did not edit shared Compose, Makefile or Gate files.

## Rollback And Risk

- This frontend intentionally fails closed against an old backend that lacks Auth v2 preflight/redeem/scope projection.
- The 5,000 customer-project hard limit is deliberate. Larger scopes show a structured error instead of silently truncating authorization.
- Rolling back only the web branch would restore the unsafe post-redeem role check. Roll back auth-core and auth-web only under the design's global Auth-write-disable procedure.
