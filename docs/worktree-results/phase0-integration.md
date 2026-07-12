# Phase 0 Integration Handoff

## Branches Integrated

- Integration branch: `codex/phase0-integration`
- Base branch: `codex/parallel-base-20260712` (`44729afe6e232ae68725cd77752018ed22ec8959`)
- Storage hardening: `codex/storage-hardening` (`7ffab2813dd62bf77d16e0594090e7451df1c70d`)
- Durable leases: `codex/durable-leases` (`719e6c6a64108fd42205dca79e9be9c5c0f18099`)
- Auth core: `codex/auth-core` (`9663bcca05633a0e5db477a3beb3cd213aeff933`)
- Auth web: `codex/auth-web` (`005044f45388d42067677aabd986d58304d40263`)

## Integration Wiring Added

- `infra/docker-compose.yml` now applies `0029_durable_job_lease_recovery.sql` before `0030_auth_session_scope_v2.sql`.
- Runtime worker Compose env includes the durable lease and recovery-dispatcher settings from the lease branch.
- Production Compose keeps object-store credentials on MinIO/bootstrap/runtime consumers and mounts auth delivery/recovery secrets through Docker secrets.
- Admin and Customer Dockerfiles run `npm run build`; production Compose overrides their commands to `npm run start`.
- `scripts/bootstrap_admin_session.py` now creates `runtime_session_scope_v2` sessions with explicit `tenant_id`, `auth_surface_policy_v1`, `tenant_roles`, and per-project `RuntimeProjectSessionScope` values. It rejects cross-tenant project sets.
- Make targets added:
  - `test-auth-core`
  - `smoke-auth-session-v2`
  - `test-auth-web`
  - `smoke-auth-surface-session`
  - `test-durable-leases`
  - `smoke-durable-lease-recovery`

## Verification In This Integration Worktree

- `PYTHONPATH=packages/geno_core:apps/api:. python3 -m compileall -q scripts/bootstrap_admin_session.py apps/api/geno_api packages/geno_core/geno_core tests/test_auth_postgres_integration.py tests/test_auth_session_v2_contracts.py tests/test_auth_web_contracts.py`: passed.
- `PYTHONPATH=packages/geno_core:apps/api:. python3 -m ruff check ...`: passed.
- `git diff --check`: passed.
- `make test-auth-core`: `38 passed`.
- `make test-auth-web`: `15 passed`, plus Admin and Customer `tsc --noEmit` passed.
- `make smoke-auth-surface-session`: `64` HTTP/BFF contract checks passed.
- `npm --prefix apps/admin-web run build`: passed.
- `npm --prefix apps/customer-web run build`: passed.
- `docker compose -f infra/docker-compose.yml config --quiet`: passed.
- `python3 scripts/verify_production_object_store.py --config-only`: passed.
- Fresh integration migration chain `infra/db/migrations/up/*.sql` on a temporary PostgreSQL database, including `0029` and `0030`: passed.
- `AUTH_TEST_DATABASE_URL=postgresql://geno:geno@localhost:55433/geno AUTH_TEST_APP_DATABASE_URL=postgresql://geno_runtime_app:geno_runtime_app@localhost:55433/geno PYTHONPATH=packages/geno_core:apps/api:. python3 -m pytest -q tests/test_auth_postgres_integration.py`: `21 passed`.
- `GENO_AUTH_DELIVERY_MASTER_KEY=... GENO_AUTH_DELIVERY_KEY_ID=integration-test-key AUTH_E2E_DATABASE_URL=postgresql://geno:geno@localhost:55433/geno AUTH_E2E_APP_DATABASE_URL=postgresql://geno_runtime_app:geno_runtime_app@localhost:55433/geno PYTHONPATH=packages/geno_core:apps/api:. python3 scripts/run_auth_session_v2_e2e.py`: passed.
- `PYTHONPATH=packages/geno_core:apps/api:. python3 scripts/bootstrap_admin_session.py --help`: passed.
- Direct `bootstrap_admin_session()` call against a seeded tenant/project created a scope-v2 session with matching tenant/project IDs and one-time session token: passed.

## Known Remaining Blockers

- Production object-store Final Gate still needs external evidence, not code:
  - real encrypted MinIO volume provisioning receipt;
  - new-node encrypted snapshot restore receipt.
- Browser plugin was unavailable in this session. Auth-web branch previously used regular Playwright/Chromium; integration re-ran the contract-only smoke after installing local `node_modules`.
- Full aggregate `production-v1-final-gate` was not run here because it includes broader unrelated production checks and the storage Final Gate external evidence remains pending.
