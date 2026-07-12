# Schema v2 baseline

This directory is the source of truth for fresh `geno_v2` database installs.
It is intentionally isolated from `infra/db/migrations/up`, which remains the
Schema v1 migration chain until the v2 cutover is approved.

The database name is fixed to `geno_v2` in both the manifest and the isolated
Compose stack. `SCHEMA_V2_POSTGRES_DB`, `SCHEMA_V2_DATABASE_URL`, and raw DSN
arguments are deliberately unsupported: the runner rejects any other database
identity and reads only structured libpq `PGHOST`, `PGPORT`, `PGDATABASE`,
`PGUSER`, and `PGPASSWORD` settings. Compose passes those settings from the same
required user and password variables used to initialize PostgreSQL, without
rendering credentials into a URI or command line. Make targets generate a
strong disposable local password when callers do not provide one.

`manifest.json` orders every executable SQL file and pins its SHA-256 digest.
The baseline hash is SHA-256 over the following UTF-8 record for each baseline
file, in manifest order:

```text
<relative-path>\0<file-sha256>\n
```

The installer refuses checksum drift before opening a database connection. It
then acquires the session-level advisory lock `geno:schema-v2:install` with a
bounded deadline while it installs or verifies the ledger. Each SQL file and
its ledger row are committed in the same transaction.

`SCHEMA_V2_CONNECT_TIMEOUT_SECONDS` is an overall retry deadline and must be at
least two seconds, which is libpq's minimum effective `connect_timeout`. Every
connection attempt receives the rounded-up remaining deadline explicitly; no
new attempt starts once less than two seconds remain. The advisory-lock timeout
is separate and may be zero for a single non-blocking acquisition attempt.

During pre-cutover development, changing the baseline requires deleting the
disposable `geno_v2` volume and performing a fresh install. After the baseline
is released, never edit a listed baseline file; add an ordered file under
`migrations/` and list it in `migration_files` instead.

## Runtime authorization boundary

Baseline `0010_tenancy_project_rls.sql` creates and forces RLS on the tenancy,
project, membership, derived-grant, profile, and audit tables, but deliberately
defines no runtime policies and grants `geno_v2_runtime` no schema, table, or
function access. Caller-controlled `app.actor_id`, `app.tenant_id`,
`app.project_id`, `app.project_ids`, or role GUCs are not authentication.

Baseline `0011_auth_session_context.sql` unlocks only the approved read surface.
It resolves actor, tenant, and project scope by looking up an active
`runtime_sessions` row from the transaction-local SHA-256
`app.session_token_hash`. Caller-supplied actor, tenant, project, or role GUCs
remain ignored, and the resolver never returns the hash or sensitive auth rows.
Invitation, redemption-attempt, and session lineage is closed by deferred
database constraints: tenant, actor, project, token fingerprint, invited role,
portal surface, policy, state, and issuance timeline must agree at commit.
Project-member reads expose only the caller's row unless the resolved project
scope contains `member.manage`.

Baseline `0012_auth_state_guards.sql` makes auth history single-directional and
revokes affected sessions when membership, derived grant, project archive, or
tenant-disable state changes. Session issuance takes shared locks on its scope
sources, so a concurrent stale session is either rejected or immediately
revoked. Revocation atomically creates one reauth queue row and remains
available while privilege-expanding auth writes are disabled.

Invitation creation/redemption, preflight counter consumption, session command
entry points, reauthentication resolution, write-control enablement, and LOGIN
provisioning remain sealed for the next sensitive command slice. Gate 1 remains pending
until that command boundary and its race/idempotency tests pass.

The baseline creates `geno_v2_api_login` as a `NOLOGIN`, passwordless,
`NOINHERIT`, `NOBYPASSRLS` deployment placeholder. It is the only permitted
member of `geno_v2_runtime`, with inheritance disabled and `SET` enabled. A
deployment must not provision or wire this LOGIN during 0011. Gate tests use an
installer-owned `SET ROLE` only to verify RLS logic; that is not production
authentication. Neither runtime role may inherit or set the BYPASSRLS authz
owner. The baseline clears global and database-specific role settings for the
placeholder; connection-pool checkout must still clear settings on existing
backends before beginning a request transaction.

The next command boundary must provide secret provisioning and real
LOGIN/connection-pool tests. Provisioning must atomically set a newly rotated
password and enable `LOGIN`; enabling `LOGIN` alone is forbidden because the
baseline always clears any pre-existing password with `PASSWORD NULL`. Every API
transaction must use `SET LOCAL ROLE geno_v2_runtime` and `SET LOCAL
app.session_token_hash`.
