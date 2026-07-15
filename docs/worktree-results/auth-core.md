# Auth Core Worktree Handoff

## Delivered

- Added the additive, rerunnable `0030_auth_session_scope_v2` migration and a fail-closed down migration.
- Added tenant-scoped Session v2, frozen surface policy, atomic invitation redemption, stable idempotent Cookie replay, AES-GCM delivery recovery, delivery confirmation, and secret erasure.
- Added direct-member and tenant-role Grant scope materialization, FORCE RLS policies, fixed-owner authz helpers, scope-change revocation, reauthentication queueing, and DB/API auth write kill switches.
- Added the frozen auth API contract (`preflight`, `redeem`, `me`, `logout`) and the authoritative surface-aware `GET /v1/projects/runtime` projection.
- Changed invitation email delivery to keep the raw one-time code out of URLs and audit payloads; links contain only `invitation_id`, while the code is displayed separately in the v2 email template.
- Retired the legacy invitation acceptance mutation with `410` and rejected the legacy auth redeem shape with `422`.
- Added bounded maintenance cleanup and a real Session v2 E2E script.
- Tightened the reviewer follow-up findings:
  - `invitation_id` is now validated as a UUID at the API boundary before repository/rate-limit calls.
  - Runtime invitation redemption can no longer mutate pending invitation snapshots or create arbitrary membership rows.
  - Runtime app cannot forge `runtime_project_access_grants` or escalate immutable Session v2 authorization snapshots.
  - Viewer runtime contexts cannot update project memberships.
  - Production startup validation fails closed unless the Session cookie is secure and the auth delivery keyring is configured.
  - Auth invitation email writes honor the `AUTH_WRITES_ENABLED` kill switch.

## Integration Configuration

Use a Compose secret/file mount for the active 32-byte URL-safe-base64 key. Do not place the raw key in the merged Compose environment.

```text
GEO_AUTH_DELIVERY_MASTER_KEY_FILE=/run/secrets/geo_auth_delivery_master_key
GEO_AUTH_DELIVERY_KEY_ID=<stable-key-id>
GEO_AUTH_DELIVERY_PREVIOUS_KEYS_FILE=/run/secrets/geo_auth_delivery_previous_keys
GEO_AUTH_DELIVERY_RECOVERY_TTL_SECONDS=600
GEO_AUTH_DELIVERY_MAX_REPLAY=5
GEO_RUNTIME_SESSION_TTL_SECONDS=604800
GEO_RUNTIME_SESSION_COOKIE_SECURE=true
AUTH_WRITES_ENABLED=1
GEO_AUTH_PREFLIGHT_RATE_LIMIT=20
GEO_AUTH_PREFLIGHT_RATE_WINDOW_SECONDS=600
```

`GEO_AUTH_DELIVERY_PREVIOUS_KEYS_FILE` is optional JSON mapping old key IDs to encoded keys. Keep every key that can decrypt delivery ciphertext still inside the recovery TTL, then remove it only after cleanup has erased that ciphertext.

Preflight defaults to a shared invitation-ID bucket. This is deliberate because the API normally observes the BFF container address, not the browser address. Source-wide throttling is optional:

```text
GEO_AUTH_PREFLIGHT_TRUSTED_SOURCE_HEADER=X-GEO-Trusted-Client-Fingerprint
GEO_AUTH_PREFLIGHT_SOURCE_RATE_LIMIT=100
```

Enable it only when ingress strips any client-supplied copy of that header and the BFF injects an authenticated, stable fingerprint. Otherwise leave both variables unset.

## Migration And Rollback

Apply `infra/db/migrations/up/0030_auth_session_scope_v2.sql` with the migration owner. It creates/updates the `geo_rls_authz_owner` and `geo_runtime_rollback_app` roles, so the migration runner needs role-management authority.

The down migration is intentionally additive and fail closed. It revokes active v2 sessions, disables `auth_runtime_write_controls`, and keeps `geo_runtime_rollback_app` read-only. Reapplying the up migration is the forward-fix path and re-enables the DB write control. Edge rollback must also set `AUTH_WRITES_ENABLED=0` before an old binary is started.

Verified against the dedicated `geo-auth-core-postgres-1` project:

- Complete `0001..0030` chain on an empty database: passed.
- `0030` rerun on the fully migrated database: passed.
- `0030` down/up roundtrip followed by the PostgreSQL auth suite: passed.
- Dirty duplicate/conflict upgrade and rerun: passed, with quarantine/reconciliation records retained.
- Down fail-closed checks and forward reapply: passed.
- App-role FORCE RLS, cross-tenant rejection, helper owner/ACL/search-path drift, lineage FKs, v1 rejection, scope revocation races, invitation snapshot immutability, grant-forgery rejection, membership escalation rejection, and Session v2 scope-forgery rejection: passed.

## Operations Wiring

Run ciphertext and expired preflight-bucket cleanup from a maintenance role that can bypass the runtime RLS policies:

```bash
AUTH_MAINTENANCE_DATABASE_URL=<maintenance-url> \
PYTHONPATH=packages/geo_core:apps/api:. \
python3 scripts/cleanup_auth_redemption_attempts.py --all --batch-size 500
```

Schedule this more frequently than the recovery TTL. Add the E2E probe to the production gate:

```bash
AUTH_E2E_DATABASE_URL=<owner-test-url> \
AUTH_E2E_APP_DATABASE_URL=<runtime-app-test-url> \
PYTHONPATH=packages/geo_core:apps/api:. \
python3 scripts/run_auth_session_v2_e2e.py
```

The repository has no committed OpenAPI snapshot/generator. After merge, regenerate through the integration session's chosen artifact path from `geo_api.main:app.openapi()` or capture the running API's `/openapi.json`; verify there is exactly one `GET /v1/projects/runtime` operation and the new auth schemas/routes are present.

## Merge Follow-Ups

- `scripts/bootstrap_admin_session.py` still constructs a scope-v1 session. Migration `0030` rejects active v1 sessions, so update that script in the integration branch to resolve a real tenant and build explicit Session v2 project scopes before deployment.
- Wire the key files, cleanup job, migration role, rollback role, and auth E2E into Compose/Make/Gates; those files were outside this worktree's ownership.
- Ensure Compose migration wiring applies `0029_durable_job_lease_recovery.sql` before `0030_auth_session_scope_v2.sql` when this branch is merged with the durable-lease branch.
- The surface projection correctly handles scopes above the repository page cap by fetching authorized projects individually before pagination. It is intentionally conservative but can issue many queries; add a batch-by-ID repository method after merge if this becomes a measured hotspot.

## Verification

- `AUTH_TEST_DATABASE_URL=postgresql://geo:geo@localhost:55433/geo AUTH_TEST_APP_DATABASE_URL=postgresql://geo_runtime_app:geo_runtime_app@localhost:55433/geo PYTHONPATH=packages/geo_core:apps/api:. python3 -m pytest -q tests/test_auth_postgres_integration.py`: `21 passed`.
- `PYTHONPATH=packages/geo_core:apps/api:. python3 -m pytest -q tests/test_auth_session_v2_contracts.py tests/test_production_runtime_contracts.py tests/test_api_contracts.py::ApiContractsTest::test_auth_invitation_preflight_rejects_malformed_invitation_id_before_repository`: `21 passed`.
- `PYTHONPATH=packages/geo_core:apps/api:. python3 -m pytest -q tests/test_auth_session_v2_contracts.py tests/test_auth_redemption_repository.py tests/test_auth_context_contracts.py tests/test_production_runtime_contracts.py`: `37 passed`.
- Focused API auth unittest selection: `6 passed`.
- Focused Core auth/email unittest selection: `5 passed`.
- Fresh `0001..0030` migration chain on a temporary PostgreSQL database: passed.
- `0030` rerun on the fully migrated database: passed.
- `0030` down/up roundtrip followed by the PostgreSQL auth suite: passed.
- `python3 -m compileall -q apps/api/geo_api packages/geo_core/geo_core tests/test_auth_postgres_integration.py tests/test_auth_session_v2_contracts.py tests/test_production_runtime_contracts.py`: passed.
- `python3 -m ruff check ...`: passed.
- `git diff --check`: passed.
