# GEO Dify runtime

This directory contains only GEO-owned deployment overlays and importable
Workflow DSL files. Dify source and persistent data stay under ignored
`.runtime/`; the repository does not vendor or fork Dify.

## Runtime boundary

- Dify is pinned to tag `1.16.0`, commit
  `5c6372d2f76d240265b92fd27c16bc772ffcb107`.
- Compose project name: `geo-dify`.
- Console/API ingress defaults to `http://127.0.0.1:15000`. Set
  `GEO_DIFY_BIND_HOST=0.0.0.0` only on a private operator network when the
  Admin site and Dify console need to be opened from another machine.
- GEO and Dify share only the external Docker network `geo-dify-runtime`.
- Dify has no PostgreSQL or MinIO credentials for GEO.
- The four migrated workflows own their Prompt, model and workflow variables in
  Dify. GEO sends task-scoped structured context, hashes and the output contract;
  it does not send a second editable Prompt copy.
- Before every business execution GEO reads the current published graph, stores
  an immutable snapshot and binds its hash to the execution Attempt. Dify being
  unavailable is a visible failure and never triggers a native fallback.

## Start and stop

```bash
./scripts/bootstrap_dify_runtime.sh up
./scripts/bootstrap_dify_runtime.sh status
./scripts/bootstrap_dify_runtime.sh down
```

The first command clones the exact upstream tag, creates local random service
secrets, builds the GEO-owned Web overlay from the pinned commit and checked-in
patch, and starts Dify without publishing its database, Redis, plugin daemon,
or sandbox ports. The build keeps a Docker-backed pnpm cache so a transient
registry failure can be retried without downloading every dependency again.
`down` preserves all volumes.

## Open the console from Admin

The Admin `Dify 工作流` page displays exactly the four migrated workflows and
their current published Prompt, model and input variables. It is read-only and
opens the configured Dify Workflow for editing. Refreshing the page adopts the
latest published graph without a second GEO approval.
For a remote operator, start Dify with a private-network bind, for example:

```bash
GEO_DIFY_BIND_HOST=0.0.0.0 GEO_DIFY_HOST_PORT=15000 \
  ./scripts/bootstrap_dify_runtime.sh up
```

Then open Admin normally and use that action. Dify presents its own sign-in
page; the generated local administrator record remains in the private
`.runtime/geo-dify-state.json` file and is never copied into GEO or Git.

## Test Run inputs

The four GEO-managed workflows are detected by their five Start variables:
`geo_context_json`, `geo_context_hash`, `geo_input_hash`,
`geo_output_schema_json`, and `geo_purpose`. Opening **Test Run** queries Dify's
own successful `app-run` history, fetches run details, and keeps only service
API runs whose end-user session starts with `geo-job:`. Canary, debug, failed,
malformed and unrelated runs are excluded.

The newest compatible business run is selected automatically. Operators can
select up to 20 compatible runs from the latest 100 successful records. Only
the five `geo_*` values are copied into the draft run; Dify `sys.*` values are
never copied. Technical inputs stay collapsed and read-only until the operator
explicitly chooses Edit. If history is empty or temporarily unavailable, the
normal input form remains available and the visible loading/error state can be
retried by reopening Test Run; no GEO database or API is involved.

This behavior is a small Web overlay, not a Dify fork. The reproducible input is
`infra/dify/patches/dify-1.16.0-geo-run-input-picker.patch`; `.runtime` source
changes are never the deployment artifact. Build it directly with:

```bash
GEO_DIFY_BUILD_NETWORK=host ./scripts/build_dify_web_overlay.sh
```

Omit the network override in restricted environments. The image label
`io.geo.dify.web-overlay-sha` must match the patch SHA-256 before bootstrap will
reuse it.

Set `GEO_DIFY_STATE_HOST_FILE` to the absolute path of the private `0600` state
file. To attach a GEO development or staging API and Worker, add the overlay after
the existing Compose files:

```bash
docker compose \
  --project-name geo-advinsys-staging \
  --env-file artifacts/advinsys-staging.env \
  --env-file artifacts/advinsys-staging-runtime.env \
  -f infra/docker-compose.yml \
  -f infra/compose.staging-operator.yml \
  -f infra/dify/compose.geo-runtime.yml \
  up -d internal-api task-worker
```

Removing the last overlay and recreating those two services is the explicit
rollback to the native GEO runtime. A configured active Dify release never
silently falls through to native execution after an error.

The state file and Dify volumes are required server-migration inputs. A GEO
PostgreSQL backup alone cannot recreate the Dify administrator, application
keys, published graphs or edit history. Restore the pinned Dify volumes and the
same private state file, then verify that all four cards report `current` and run
one live canary per workflow before accepting the new server.

## Configure and enrol

Regenerate or verify the four checked-in Workflow files first:

```bash
uv run python scripts/render_dify_workflow_dsls.py
uv run python scripts/render_dify_workflow_dsls.py --check
```

Configure the one local workspace, validate the official DeepSeek credential,
import and publish all four Workflows, and create their application keys with:

```bash
uv run python scripts/configure_dify_runtime.py \
  --deepseek-api-key-file /run/secrets/deepseek-api-key
```

The generated administrator password and application keys stay in ignored
`.runtime/geo-dify-state.json` with mode `0600`; the command is idempotent and
never prints them. Enrol those keys into GEO Secret Store and register immutable
releases only after all four GEO Prompt bindings are frozen:

```bash
GEO_DATABASE_URL='postgresql://geo_app:...@127.0.0.1:55433/geo' \
uv run python scripts/enroll_dify_workflows.py \
  --project-id <project-uuid> \
  --tenant-id <tenant-uuid> \
  --prepared-by <admin-uuid> \
  --approved-by <owner-uuid> \
  --master-keyring-file /run/secrets/secret-store-keyring.json \
  --request-hash-key-file /run/secrets/secret-request-hash-key
```

Never place an application key in a Compose environment, Job payload, log, DSL,
or Git. Re-running both commands must reuse the existing Dify apps, Secret
versions and GEO releases. After initial import, Prompt edits happen only in
Dify; checked-in DSL files are bootstrap/recovery seeds, not a second live
editing surface.

## Current scope and backlog

- Migrated now: question generation, RAG grounding, placement generation and
  placement simulation.
- Not migrated now: the other ten Prompt program types. They remain a visible
  engineering backlog but are hidden from the normal Admin Dify board.
- Future: workflow templates, project-level template selection and country/
  locale variants. The short-term runtime deliberately shares one workflow set
  across all projects.
- GEO Fact/Evidence and knowledge ingestion remain in GEO. Dify Knowledge Base
  migration is not part of this change.

## Canary and activation

Run `scripts/manage_dify_workflows.py canary` once per registered release with a
`geo_worker` database URL. A release cannot be activated until its real provider
call also passes the purpose-specific business validator. Then activate it with
an application database URL:

```bash
uv run python scripts/manage_dify_workflows.py activate \
  --project-id <project-uuid> \
  --release-id <release-uuid> \
  --activated-by <owner-uuid> \
  --reason 'live canary passed'
```

`GET /v1/projects/{project_id}/dify-workflows` must report
`runtime_backend=dify` and four `active` cards. A successful canary is not a
business acceptance substitute: execute one real Durable Job for each purpose
and verify its Dify run ID plus final GEO result.

## Failure and rollback

- Network, credential, provider and output-contract failures are recorded on the
  Dify attempt and returned as actionable retryable or terminal Job failures.
- Restarting Dify and retrying the same Durable Job creates a new fenced attempt;
  it does not overwrite the failed attempt.
- To roll back explicitly, remove `infra/dify/compose.geo-runtime.yml` from the
  GEO Compose command and recreate `internal-api` and `task-worker`. This removes
  the runtime selector; an active Dify error never triggers an implicit native
  fallback.
- `./scripts/bootstrap_dify_runtime.sh down` preserves Dify data. Include the
  ignored Dify volumes and `.runtime/geo-dify-state.json` in a server migration;
  GEO database backup alone cannot recreate Dify application keys.
- To roll back only the Test Run Web overlay while preserving Dify API, Worker
  and data, run:

  ```bash
  GEO_DIFY_WEB_IMAGE=langgenius/dify-web:1.16.0 \
    ./scripts/bootstrap_dify_runtime.sh up
  ```

  Remove that environment override and run `up` again to restore the matching
  GEO overlay image.
