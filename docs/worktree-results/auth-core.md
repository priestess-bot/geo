# Auth Core Worktree Handoff

## Delivered

- Added the additive, rerunnable `0030_auth_session_scope_v2` migration and a fail-closed down migration.
- Added tenant-scoped Session v2, frozen surface policy, atomic invitation redemption, stable idempotent Cookie replay, AES-GCM delivery recovery, delivery confirmation, and secret erasure.
- Added direct-member and tenant-role Grant scope materialization, FORCE RLS policies, fixed-owner authz helpers, scope-change revocation, reauthentication queueing, and DB/API auth write kill switches.
- Added the frozen auth API contract (`preflight`, `redeem`, `me`, `logout`) and the authoritative surface-aware `GET /v1/projects/runtime` projection.
- Changed invitation email delivery to keep the raw one-time code out of URLs and audit payloads; links contain only `invitation_id`, while the code is displayed separately in the v2 email template.
- Retired the legacy invitation acceptance mutation with `410` and rejected the legacy auth redeem shape with `422`.
- Added bounded maintenance cleanup and a real Session v2 E2E script.

## Integration Configuration

Use a Compose secret/file mount for the active 32-byte URL-safe-base64 key. Do not place the raw key in the merged Compose environment.

```text
GENO_AUTH_DELIVERY_MASTER_KEY_FILE=/run/secrets/geno_auth_delivery_master_key
GENO_AUTH_DELIVERY_KEY_ID=<stable-key-id>
GENO_AUTH_DELIVERY_PREVIOUS_KEYS_FILE=/run/secrets/geno_auth_delivery_previous_keys
GENO_AUTH_DELIVERY_RECOVERY_TTL_SECONDS=600
GENO_AUTH_DELIVERY_MAX_REPLAY=5
GENO_RUNTIME_SESSION_TTL_SECONDS=604800
GENO_RUNTIME_SESSION_COOKIE_SECURE=true
AUTH_WRITES_ENABLED=1
GENO_AUTH_PREFLIGHT_RATE_LIMIT=20
GENO_AUTH_PREFLIGHT_RATE_WINDOW_SECONDS=600
```

`GENO_AUTH_DELIVERY_PREVIOUS_KEYS_FILE` is optional JSON mapping old key IDs to encoded keys. Keep every key that can decrypt delivery ciphertext still inside the recovery TTL, then remove it only after cleanup has erased that ciphertext.

Preflight defaults to a shared invitation-ID bucket. This is deliberate because the API normally observes the BFF container address, not the browser address. Source-wide throttling is optional:

```text
GENO_AUTH_PREFLIGHT_TRUSTED_SOURCE_HEADER=X-GENO-Trusted-Client-Fingerprint
GENO_AUTH_PREFLIGHT_SOURCE_RATE_LIMIT=100
```

Enable it only when ingress strips any client-supplied copy of that header and the BFF injects an authenticated, stable fingerprint. Otherwise leave both variables unset.

## Migration And Rollback

Apply `infra/db/migrations/up/0030_auth_session_scope_v2.sql` with the migration owner. It creates/updates the `geno_rls_authz_owner` and `geno_runtime_rollback_app` roles, so the migration runner needs role-management authority.

The down migration is intentionally additive and fail closed. It revokes active v2 sessions, disables `auth_runtime_write_controls`, and keeps `geno_runtime_rollback_app` read-only. Reapplying the up migration is the forward-fix path and re-enables the DB write control. Edge rollback must also set `AUTH_WRITES_ENABLED=0` before an old binary is started.

Verified against the dedicated `geo-auth-core-postgres-1` project:

- Complete `0001..0030` chain on an empty database: passed.
- `0030` rerun on the fully migrated database: passed.
- Dirty duplicate/conflict upgrade and rerun: passed, with quarantine/reconciliation records retained.
- Down fail-closed checks and forward reapply: passed.
- App-role FORCE RLS, cross-tenant rejection, helper owner/ACL/search-path drift, lineage FKs, v1 rejection, and scope revocation races: passed.

## Operations Wiring

Run ciphertext and expired preflight-bucket cleanup from a maintenance role that can bypass the runtime RLS policies:

```bash
AUTH_MAINTENANCE_DATABASE_URL=<maintenance-url> \
PYTHONPATH=packages/geno_core:apps/api:. \
python3 scripts/cleanup_auth_redemption_attempts.py --all --batch-size 500
```

Schedule this more frequently than the recovery TTL. Add the E2E probe to the production gate:

```bash
AUTH_E2E_DATABASE_URL=<owner-test-url> \
AUTH_E2E_APP_DATABASE_URL=<runtime-app-test-url> \
PYTHONPATH=packages/geno_core:apps/api:. \
python3 scripts/run_auth_session_v2_e2e.py
```

The repository has no committed OpenAPI snapshot/generator. After merge, regenerate through the integration session's chosen artifact path from `geno_api.main:app.openapi()` or capture the running API's `/openapi.json`; verify there is exactly one `GET /v1/projects/runtime` operation and the new auth schemas/routes are present.

## Merge Follow-Ups

- `scripts/bootstrap_admin_session.py` still constructs a scope-v1 session. Migration `0030` rejects active v1 sessions, so update that script in the integration branch to resolve a real tenant and build explicit Session v2 project scopes before deployment.
- Wire the key files, cleanup job, migration role, rollback role, and auth E2E into Compose/Make/Gates; those files were outside this worktree's ownership.
- The surface projection correctly handles scopes above the repository page cap by fetching authorized projects individually before pagination. It is intentionally conservative but can issue many queries; add a batch-by-ID repository method after merge if this becomes a measured hotspot.

## Verification

- New auth suites: `35 passed`.
- Real PostgreSQL auth integration: `15 passed`.
- Related API contracts: `27 passed`.
- Ruff, compileall, and `git diff --check`: passed.
- Session v2 E2E: passed, including mismatch zero-side-effects, stable replay, validation, confirmation, and ciphertext erasure.

The related Core auth/email contract selection has `18 passed`. The full baselines are `341 passed, 14 skipped, 1 failed` for API and `269 passed, 10 failed` for Core. Those remaining failures are existing exact floating-point sum assertions (`0.9999999999999999` versus `1.0`) or searches inside the truncated `str(psycopg.types.json.Jsonb(...))`; both categories reproduce on `main` and are unrelated to this branch.
