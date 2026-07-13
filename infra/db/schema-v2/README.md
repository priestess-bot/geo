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

Baseline `0013_auth_commands.sql` exposes the nine reviewed auth command entry
points. It keeps runtime table DML sealed, consumes preflight buckets before
token disclosure, creates immutable redemption attempts, snapshots every
current project membership into a successful session, and allows delivery
confirmation, secret erasure, logout, and reauthentication resolution while
privilege-expanding writes are disabled. The final statement enables auth
writes only after the function owner, fixed search path, ACL, passwordless
`NOLOGIN` placeholder, and sealed write-control catalog checks pass.

The fresh-install gate runs a dedicated real-PostgreSQL command suite in
addition to the general schema and Session UoW suites. It verifies the 20/21
preflight boundary, invalid-token non-mutation, natural expiry, invitation
idempotency and `member.manage`, full multi-project session snapshots, exact
replay, same-invitation concurrency, recovery expiry and replay-limit erasure
with the write switch disabled, lifecycle idempotency, and the final runtime
ACL surface.

Baseline `0014_auth_login_provision.sql` installs the immutable deployment
attempt, terminal receipt, redacted audit, and startup-readiness contracts. It
does not contain a credential and its final operation always seals
`geno_v2_api_login` as `NOLOGIN` with `PASSWORD NULL`. The latest monotonic
attempt per `login_kind` is the readiness truth; `api` is active in this slice
and the reserved `worker` kind lets the later worker LOGIN reuse the same
contract without sharing credentials or state. A pending, failed, or disable attempt makes the
narrow runtime readiness function return false even if an older successful
receipt exists. Runtime roles cannot read or write the provisioning tables.

The Anonymous Auth UoW PostgreSQL gate additionally uses a real
`AuthDeliveryKeyring` and AES-GCM envelope to exercise preflight, redemption,
idempotent concurrency, delivery recovery, transaction cleanup, and immediate
reuse of one physical connection by the authenticated Session UoW. A network
disconnect during `COMMIT` cannot be made deterministic in this local gate;
the commit-outcome-unknown and forced-discard path remains covered by the
fault-injected unit gate in `tests/test_schema_v2_anonymous_auth_uow.py`.

The baseline creates `geno_v2_api_login` as a `NOLOGIN`, passwordless,
`NOINHERIT`, `NOBYPASSRLS` deployment placeholder. It is the only permitted
member of `geno_v2_runtime`, with inheritance disabled and `SET` enabled. A
deployment must not provision or wire this LOGIN during 0011. Gate tests use an
installer-owned `SET ROLE` only to verify RLS logic; that is not production
authentication. Neither runtime role may inherit or set the BYPASSRLS authz
owner. The baseline clears global and database-specific role settings for the
placeholder; connection-pool checkout must still clear settings on existing
backends before beginning a request transaction.

## API LOGIN provisioning

Run `scripts/schema_v2_provision_login.py` only as a one-shot deployment job
after baseline install and verification. Installer connectivity is accepted
only from structured `PGHOST`, `PGPORT`, fixed `PGDATABASE=geno_v2`, `PGUSER`,
and `PGPASSWORD` settings. Raw DSNs, service files, database URLs, plaintext API
password environment variables, and password command-line arguments are
rejected.

The API credential must be supplied through `--credential-file`. The file must
be external to the repository, owned by the process effective user, a regular
non-symlink file with exact `0400` or `0600` mode, and contain one strong UTF-8
line of at least 32 characters. The API credential must differ from the
installer credential. The tool derives a SCRAM verifier client-side and never
stores the secret value, verifier, DSN, or environment in a receipt, audit
event, output, or command line. The non-secret mount path is passed as
`--credential-file`.

Example deployment sequence, where the file path is a secret mount and the
version is the non-secret secret-manager version:

```bash
python scripts/schema_v2_provision_login.py \
  --initiated-by deployment-controller \
  provision \
  --credential-file /run/secrets/geno_v2_api_login \
  --credential-version api-login-2026-07-13-01

unset PGUSER PGPASSWORD
python scripts/schema_v2_provision_login.py \
  check \
  --credential-file /run/secrets/geno_v2_api_login \
  --credential-version api-login-2026-07-13-01
```

Provisioning acquires the Schema install lock followed by the dedicated
`geno:schema-v2:auth-login-provision` lock. It first fail-closes any interrupted
`preparing` attempt by setting `NOLOGIN PASSWORD NULL` and writing a failed
receipt. The new attempt and role update then commit atomically, followed by a
real new-credential login and anonymous runtime smoke. A deterministic smoke
failure is compensated with `NOLOGIN PASSWORD NULL` and a failed receipt.

Rotation requires all API and worker pools to be drained or stopped before the
command runs; PostgreSQL password changes and `NOLOGIN` do not terminate
already-authenticated backends. The explicit acknowledgement is mandatory:

```bash
python scripts/schema_v2_provision_login.py \
  --initiated-by deployment-controller \
  rotate \
  --drain-confirmed \
  --credential-file /run/secrets/geno_v2_api_login_next \
  --credential-version api-login-2026-07-13-02
```

To revoke future connections and erase the stored verifier, run:

```bash
python scripts/schema_v2_provision_login.py \
  --initiated-by incident-controller \
  disable
```

Every Schema v2 API and database worker deployment must run the `check` command
with its configured credential version before process startup. This creates a
fresh connection using the same secret, switches to `geno_v2_runtime`, verifies
anonymous session resolution and sealed sensitive DML, and requires the latest
attempt and matching receipt to be successful. A missing, pending, failed,
disabled, or version-mismatched state fails closed. The startup environment
must contain only the structured endpoint fields and must not receive the
installer `PGUSER` or `PGPASSWORD`. Every request transaction
must still use `SET LOCAL ROLE geno_v2_runtime` and `SET LOCAL
app.session_token_hash`; pooled connections must rollback/reset before reuse.

## Worker LOGIN provisioning

Baseline `0021_worker_login_provision.sql` extends the same immutable ledger for
the `worker` login kind after 0020 has installed the capability role and narrow
durable-job functions. The baseline always ends with
`geno_v2_worker_login NOLOGIN PASSWORD NULL`. Its sole membership is
`geno_v2_worker -> geno_v2_worker_login` with `ADMIN FALSE`, `INHERIT FALSE`,
and `SET TRUE`; the LOGIN has no direct public-schema, table, sequence, or
function privileges.

Worker credentials use a separate secret file, credential-version sequence,
latest-attempt projection, and pending recovery. API and worker operations keep
the shared global provisioning advisory lock because they mutate one ledger and
catalog boundary, while all state queries remain filtered by login kind. Role
identifiers come only from the provisioner's fixed profile registry. The same
external-file ownership, `0400`/`0600` mode, strength, installer-reuse,
structured `PG*`, SCRAM redaction, fail-closed compensation, and drain rules as
the API profile apply.

```bash
python scripts/schema_v2_provision_login.py \
  --login-kind worker \
  --initiated-by deployment-controller \
  provision \
  --credential-file /run/secrets/geno_v2_worker_login \
  --credential-version worker-login-2026-07-13-01

python scripts/schema_v2_provision_login.py \
  --login-kind worker \
  --initiated-by deployment-controller \
  rotate \
  --drain-confirmed \
  --credential-file /run/secrets/geno_v2_worker_login_next \
  --credential-version worker-login-2026-07-13-02

python scripts/schema_v2_provision_login.py \
  --login-kind worker \
  --initiated-by incident-controller \
  disable
```

Before a worker process starts, clear installer identity variables and run:

```bash
unset PGUSER PGPASSWORD
python scripts/schema_v2_provision_login.py \
  --login-kind worker \
  check \
  --credential-file /run/secrets/geno_v2_worker_login \
  --credential-version worker-login-2026-07-13-02
```

The check creates a real worker-authenticated connection, proves the LOGIN has
zero direct privileges, rejects access to the runtime role, switches with
`SET LOCAL ROLE geno_v2_worker`, and evaluates the worker-only startup readiness
function. The isolated PostgreSQL behavior gate, rather than an operational
startup check, exercises a real durable dispatch claim/heartbeat/complete
lifecycle. The check then verifies transaction cleanup restored the
physical connection to `session_user=current_user=geno_v2_worker_login`.

## Governed Knowledge Pipeline

Baseline `0030_knowledge_pipeline.sql` adds the governed Knowledge boundary:
immutable source revisions and governance versions, parser/chunk/embed/fact
lineage, system-required quality definitions, and Approved Fact versions. All
project-owned references use composite project foreign keys and every table is
`FORCE RLS` protected.

Runtime may create or govern work only through reviewed `SECURITY DEFINER`
commands. A worker receives no table or sequence privilege; its execution
surface is limited to Knowledge job claim, heartbeat, frozen-input read,
begin-finalizing, complete, fail, and cancel-ack functions. Jobs freeze a
canonical input snapshot and Quality definition set before a lease is issued.
Expired leases are reclaimable and stale lease tokens are fenced.

An approved Fact remains readable only while its producing job, exact source
revision artifacts, current governance, consent, rights, model policy, and
requested publication channel remain eligible. Client viewers require a
customer-visible public projection and a channel; internal content operators
can consume the internal approved projection but still cannot bypass current
governance. Terminal artifact-finalization failure reconciles linked queued or
finalizing Knowledge jobs to failure.
