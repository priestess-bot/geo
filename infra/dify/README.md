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
- The ten GEO workflows own their Prompt, model and workflow variables in
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

The Admin `Dify 工作流` page displays the ten GEO workflows and
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

The GEO-managed workflows are detected by their five Start variables:
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
same private state file, then verify that all ten cards report `current` and run
one live canary per workflow before accepting the new server.

## Configure and enrol

Regenerate or verify the ten checked-in Workflow files first:

```bash
uv run python scripts/render_dify_workflow_dsls.py
uv run python scripts/render_dify_workflow_dsls.py --check
```

### Fresh GEO database: publish the Prompt bindings

The following commands assume that the fresh Internal API and Worker are
running, the project has been provisioned, and `jq` is installed. Use absolute
host paths for every key file. Development/staging authentication uses the
stored identity UUID, not an arbitrary actor label:

```bash
set -euo pipefail
export GEO_API_URL=http://127.0.0.1:18000
export PROJECT_ID='replace-with-project-uuid'
export TENANT_ID='replace-with-tenant-uuid'
export PREPARER_ID='replace-with-initial-owner-identity-uuid'
export APP_DATABASE_URL='postgresql://geo_app:...@127.0.0.1:55433/geo'
export WORKER_DATABASE_URL='postgresql://geo_worker:...@127.0.0.1:55433/geo'
export SECRET_KEYRING_FILE=/absolute/path/to/secret-store-keyring.json
export REQUEST_HASH_KEY_FILE=/absolute/path/to/secret-request-hash-key
export DEEPSEEK_KEY_FILE=/absolute/path/to/deepseek-api-key
export DIFY_STATE_FILE=/absolute/path/to/.runtime/geo-dify-state.json
export WORKER_ACTOR_ID='replace-with-stored-worker-service-identity-uuid'
AUTH=(-H "X-GEO-Actor-ID: $PREPARER_ID" -H "X-GEO-Tenant-ID: $TENANT_ID")
```

The Secret Store and provider bootstrap require two distinct active human
members. If the project has only its initial owner, create the second admin once
through the real member API; otherwise set `APPROVER_ID` to the existing second
admin identity and skip this call:

```bash
export APPROVER_ISSUER=https://identity.example.com/
export APPROVER_SUBJECT=geo-staging-approver
export APPROVER_EMAIL=geo-staging-approver@example.com
APPROVER_RESPONSE="$({
  jq -n \
    --arg issuer "$APPROVER_ISSUER" \
    --arg subject "$APPROVER_SUBJECT" \
    --arg email "$APPROVER_EMAIL" \
    '{issuer:$issuer,subject:$subject,email:$email,
      display_name:"GEO staging approver",role:"admin"}' |
  curl --fail-with-body --silent --show-error \
    -X POST "$GEO_API_URL/v1/projects/$PROJECT_ID/members" \
    "${AUTH[@]}" -H 'Content-Type: application/json' \
    -H 'Idempotency-Key: dify-staging-second-admin-v1' --data-binary @-
})"
export APPROVER_ID="$(jq -er '.member.identity_id' <<<"$APPROVER_RESPONSE")"
```

Bootstrap the real DeepSeek Model Gateway option used by Prompt suites before
creating a Dify release. This is a host command, so the database URL and file
paths must be reachable from the host. The bootstrap persists encrypted test
evidence in the primary object store, so its host-visible endpoint and
credentials are required as well; container-only `http://minio:9000` will not
work from the host:

```bash
GEO_DATABASE_URL="$APP_DATABASE_URL" \
OBJECT_STORE_ENDPOINT="$HOST_OBJECT_STORE_ENDPOINT" \
OBJECT_STORE_BUCKET="${OBJECT_STORE_BUCKET:-geo-artifacts}" \
OBJECT_STORE_ACCESS_KEY="$OBJECT_STORE_ACCESS_KEY" \
OBJECT_STORE_SECRET_KEY="$OBJECT_STORE_SECRET_KEY" \
OBJECT_STORE_AUTO_CREATE_BUCKET=0 \
uv run python scripts/bootstrap_deepseek_prompt_runtime.py \
  --project-id "$PROJECT_ID" \
  --tenant-id "$TENANT_ID" \
  --prepared-by "$PREPARER_ID" \
  --approved-by "$APPROVER_ID" \
  --api-key-file "$DEEPSEEK_KEY_FILE" \
  --master-keyring-file "$SECRET_KEYRING_FILE" \
  --request-hash-key-file "$REQUEST_HASH_KEY_FILE" \
  --enable-synthetic-review
```

Create or replay the 14 default Prompt drafts, select the approved DeepSeek test
runtime, then run and publish the ten purposes that Dify enrolment requires. A
suite is accepted only when its exact Job reaches `succeeded` with
`passed=true`; a failed, cancelled, dead-lettered or timed-out suite stops the
sequence instead of publishing an untested binding:

Each five-case suite freezes a budget of 15 paid calls: five cases multiplied
by at most three structured-output attempts. This lets a malformed model result
retry without starving later cases while preserving a deterministic upper
bound; lowering the runtime policy below 15 makes selection fail before enqueue.

```bash
BOOTSTRAP="$(curl --fail-with-body --silent --show-error \
  "$GEO_API_URL/v1/projects/$PROJECT_ID/prompt-bootstrap" "${AUTH[@]}")"
CATALOG_HASH="$(jq -er '.catalog_hash' <<<"$BOOTSTRAP")"

DRAFT_BATCH="$({
  jq -n --arg catalog_hash "$CATALOG_HASH" '{catalog_hash:$catalog_hash}' |
  curl --fail-with-body --silent --show-error \
    -X POST "$GEO_API_URL/v1/projects/$PROJECT_ID/prompt-bootstrap/drafts" \
    "${AUTH[@]}" -H 'Content-Type: application/json' \
    -H 'Idempotency-Key: dify-prompt-bootstrap-v1' --data-binary @-
})"
jq -e '.completion_status == "completed" and .failed_count == 0' \
  <<<"$DRAFT_BATCH" >/dev/null

RUNTIMES="$(curl --fail-with-body --silent --show-error \
  "$GEO_API_URL/v1/projects/$PROJECT_ID/prompt-program-test-options" "${AUTH[@]}")"
RUNTIME_SELECTION_ID="$(jq -er \
  '[.items[] | select(.provider == "deepseek")][0].runtime_selection_id' \
  <<<"$RUNTIMES")"

DIFY_PURPOSES=(
  knowledge.question_generation knowledge.rag_grounding
  placements.generation placements.simulation
  synthetic_lab.generation synthetic_lab.claim_extraction
  synthetic_lab.conflict_check synthetic_lab.revision
  synthetic_lab.style_profile recommendations.recommendation
)

for purpose in "${DIFY_PURPOSES[@]}"; do
  FLOWS="$(curl --fail-with-body --silent --show-error \
    "$GEO_API_URL/v1/projects/$PROJECT_ID/prompt-flows" "${AUTH[@]}")"
  FLOW="$(jq -cer --arg purpose "$purpose" \
    '.items[] | select(.purpose == $purpose and .program != null and .draft != null)' \
    <<<"$FLOWS")"
  PROGRAM_ID="$(jq -er '.program.id' <<<"$FLOW")"
  REVISION="$(jq -er '.draft.revision' <<<"$FLOW")"
  SUITE="$({
    jq -n --arg runtime "$RUNTIME_SELECTION_ID" --argjson revision "$REVISION" \
      '{runtime_selection_id:$runtime,expected_revision:$revision}' |
    curl --fail-with-body --silent --show-error \
      -X POST "$GEO_API_URL/v1/projects/$PROJECT_ID/prompt-programs/$PROGRAM_ID/suite-runs" \
      "${AUTH[@]}" -H 'Content-Type: application/json' \
      -H "Idempotency-Key: dify-suite-$purpose-v1" --data-binary @-
  })"
  JOB_ID="$(jq -er '.job.job_id' <<<"$SUITE")"

  passed=false
  for _ in $(seq 1 180); do
    RUNS="$(curl --fail-with-body --silent --show-error \
      "$GEO_API_URL/v1/projects/$PROJECT_ID/prompt-programs/$PROGRAM_ID/test-runs?limit=100" \
      "${AUTH[@]}")"
    RUN="$(jq -cer --arg job "$JOB_ID" \
      '.items[] | select((.job_id | tostring) == $job)' <<<"$RUNS")"
    STATUS="$(jq -er '.status' <<<"$RUN")"
    if [[ "$STATUS" == succeeded ]]; then
      jq -e '.passed == true' <<<"$RUN" >/dev/null
      passed=true
      break
    fi
    if [[ "$STATUS" =~ ^(failed|dead_lettered|cancelled)$ ]]; then
      jq -r '"Prompt suite failed: status=\(.status) error=\(.error_code // "none")"' \
        <<<"$RUN" >&2
      exit 1
    fi
    sleep 2
  done
  [[ "$passed" == true ]] || { echo "Prompt suite timed out: $purpose" >&2; exit 1; }

  jq -n --argjson revision "$REVISION" '{expected_revision:$revision}' |
  curl --fail-with-body --silent --show-error \
    -X POST "$GEO_API_URL/v1/projects/$PROJECT_ID/prompt-programs/$PROGRAM_ID/publish" \
    "${AUTH[@]}" -H 'Content-Type: application/json' \
    -H "Idempotency-Key: dify-publish-$purpose-v1" --data-binary @- |
  jq -e --arg purpose "$purpose" \
    '.release.state.status == "frozen" and .binding.purpose == $purpose' >/dev/null
done
```

Configure the one local workspace, validate the official DeepSeek credential,
import and publish all ten Workflows, and create their application keys with:

```bash
uv run python scripts/configure_dify_runtime.py \
  --base-url http://127.0.0.1:15000 \
  --state-file "$DIFY_STATE_FILE" \
  --deepseek-api-key-file "$DEEPSEEK_KEY_FILE"
```

The generated administrator password and application keys stay in ignored
`.runtime/geo-dify-state.json` with mode `0600`; the command is idempotent and
never prints them. Enrol those keys into GEO Secret Store and register immutable
releases only after the matching GEO Prompt bindings are frozen:

```bash
mkdir -p .runtime
GEO_DATABASE_URL="$APP_DATABASE_URL" \
uv run python scripts/enroll_dify_workflows.py \
  --project-id "$PROJECT_ID" \
  --tenant-id "$TENANT_ID" \
  --prepared-by "$PREPARER_ID" \
  --approved-by "$APPROVER_ID" \
  --state-file "$DIFY_STATE_FILE" \
  --master-keyring-file "$SECRET_KEYRING_FILE" \
  --request-hash-key-file "$REQUEST_HASH_KEY_FILE" \
  >.runtime/dify-enrol-receipt.json
```

Both identity values must already exist as distinct, active `owner` or `admin`
memberships for this exact tenant and project. On a fresh environment, use the
initial owner as the preparer, create a second `admin` through
`POST /v1/projects/{project_id}/members`, and use the returned `identity_id` as
the approver. The CLIs read these memberships from PostgreSQL before touching a
Secret; an arbitrary UUID, an analyst, a revoked member, or the Model Gateway
Worker service identity is rejected.

The Worker service identity only resolves the active provider Secret while a
Job runs. It is never a preparer or approver.

Never place an application key in a Compose environment, Job payload, log, DSL,
or Git. Re-running both commands must reuse the existing Dify apps, Secret
versions and GEO releases. After initial import, Prompt edits happen only in
Dify; checked-in DSL files are bootstrap/recovery seeds, not a second live
editing surface.

## Current scope and backlog

- Managed by Dify in this release: question generation, RAG grounding, placement
  generation, placement simulation, synthetic generation, claim extraction,
  conflict check, revision, style profile and recommendation. At Alembic `0101`,
  all ten have a frozen published snapshot, a successful real DeepSeek canary
  and an `active/current` fresh-staging card. Style profile and recommendation
  still require real approved-input business Job receipts before their business
  capabilities can be accepted; a technical canary is not that receipt.
- Intentionally native in GEO: style judge, arbiter, metric judge and offline
  answer. Admin labels these as `GEO 内置评审`; they are not a Dify migration
  backlog. `reference_translation` remains reserved and non-executable.
- Future: workflow templates, project-level template selection and country/
  locale variants. The short-term runtime deliberately shares one workflow set
  across all projects.
- GEO Fact/Evidence and knowledge ingestion remain in GEO. Dify Knowledge Base
  migration is not part of this change.

## Canary and activation

Run one real canary per item returned by enrolment with the Worker database URL.
The loop explicitly uses the host-visible Dify ingress; the CLI default
`http://dify-api:5001` is only resolvable inside the Compose network. A release
cannot be activated until its provider call passes the purpose-specific
validator. Activation is a separate operation using the application database
URL:

```bash
while IFS=$'\t' read -r purpose release_id; do
  GEO_DATABASE_URL="$WORKER_DATABASE_URL" \
  uv run python scripts/manage_dify_workflows.py canary \
    --project-id "$PROJECT_ID" \
    --release-id "$release_id" \
    --worker-actor-id "$WORKER_ACTOR_ID" \
    --master-keyring-file "$SECRET_KEYRING_FILE" \
    --request-hash-key-file "$REQUEST_HASH_KEY_FILE" \
    --dify-api-url http://127.0.0.1:15000 \
    --dify-console-url http://127.0.0.1:15000 \
    --dify-state-file "$DIFY_STATE_FILE"

  GEO_DATABASE_URL="$APP_DATABASE_URL" \
  uv run python scripts/manage_dify_workflows.py activate \
    --project-id "$PROJECT_ID" \
    --release-id "$release_id" \
    --activated-by "$PREPARER_ID" \
    --reason "real provider canary passed for $purpose"
done < <(jq -er '.items[] | [.purpose, .release_id] | @tsv' \
  .runtime/dify-enrol-receipt.json)
```

### 0097 runtime cutover

`0097_dify_snapshot_fencing` is intentionally not compatible with an old GEO
Worker: it revokes direct attempt/result writes and replaces them with lease-
fenced RPCs. Do not apply it as a rolling migration. Pause Dify-backed admission,
drain or cancel non-terminal Dify work, then stop every old Dify writer before
the migration. For staging, stop at least `task-worker`, `internal-api`, and
`outbox-relay` using the same Compose files and env files used to run them:

```bash
docker compose \
  --project-name geo-advinsys-staging \
  --env-file artifacts/advinsys-staging.env \
  --env-file artifacts/advinsys-staging-runtime.env \
  -f infra/docker-compose.yml \
  -f infra/compose.staging-operator.yml \
  -f infra/dify/compose.geo-runtime.yml \
  stop task-worker internal-api outbox-relay

uv run alembic upgrade head

docker compose \
  --project-name geo-advinsys-staging \
  --env-file artifacts/advinsys-staging.env \
  --env-file artifacts/advinsys-staging-runtime.env \
  -f infra/docker-compose.yml \
  -f infra/compose.staging-operator.yml \
  -f infra/dify/compose.geo-runtime.yml \
  up -d --force-recreate task-worker internal-api outbox-relay
```

Resume admission only after the new containers are healthy and one canary has
successfully pinned its published snapshot. If migration fails because an
active release lacks a successful-canary snapshot, keep writers stopped, repair
that evidence on the prior schema, and retry the maintenance window; do not
override the check or restart an old image against `0097`.

### Style Profile cutover

Import, enrol, register and run the real `synthetic_lab.style_profile` canary
before pausing traffic. The canary does not change the active binding. For the
binding cutover, first block new
`POST /v1/projects/{project_id}/synthetic-lab/jobs/profile-build` requests at the
operator ingress. If route-scoped maintenance is unavailable, stop every
Internal API replica; the staging command is:

```bash
docker compose \
  --project-name geo-advinsys-staging \
  --env-file artifacts/advinsys-staging.env \
  --env-file artifacts/advinsys-staging-runtime.env \
  -f infra/docker-compose.yml \
  -f infra/compose.staging-operator.yml \
  -f infra/dify/compose.geo-runtime.yml \
  stop internal-api
```

With `GEO_DATABASE_URL` set to the project-scoped Worker connection, run the
following check. Both counts must remain zero before activation; the actual
parent Job kind is `style.profile.build`.

```bash
psql "$GEO_DATABASE_URL" --set=project_id='<project-uuid>' <<'SQL'
BEGIN;
SELECT set_config('geo.project_id', :'project_id', true),
       set_config('geo.project_ids', json_build_array(:'project_id')::text, true);
WITH nonterminal AS (
    SELECT id, project_id, kind
    FROM durable_jobs
    WHERE project_id = :'project_id'::uuid
      AND status IN ('queued', 'running', 'retry_wait', 'finalizing')
)
SELECT count(*) FILTER (WHERE job.kind = 'style.profile.build')
           AS profile_build_nonterminal,
       count(*) FILTER (WHERE child.child_job_id IS NOT NULL)
           AS style_profile_child_nonterminal
FROM nonterminal job
LEFT JOIN synthetic_lab_model_call_children child
  ON child.project_id = job.project_id
 AND child.child_job_id = job.id
 AND child.prompt_program_kind = 'style_profile';
COMMIT;
SQL
```

Only after the zero-count check, run the `activate` command above for the Style
Profile release. Migration `0096` rejects binding or rebinding while either
count is non-zero. Migration `0098` additionally freezes the selected backend
and exact Workflow Release on every new Synthetic child; it refuses an upgrade
while a non-terminal legacy child cannot be proved against the active pinned
release. Historical terminal children reconstructed from 0097 attempts expose
an explicit `migration_backfill_*` lineage source, while newly admitted children
are labelled `runtime_admission`. Restore the ingress rule or start
`internal-api`, then confirm the card is `active/current`. Finally enqueue one
real approved-sample Profile build and one evidence-backed Recommendation Job
and verify their Dify run lineage and saved business results. Canary success
alone is not business acceptance.

`GET /v1/projects/{project_id}/dify-workflows` must report
`runtime_backend=dify` and ten `active` cards after this migration cutover. A
successful canary is not a business acceptance substitute: execute one real
Durable Job for each purpose and verify its Dify run ID plus final GEO result.

The 2026-07-28 fresh-staging cutover at `0101_dify_published_identity` reports
all ten cards as `active/current` with successful real DeepSeek canaries. The
Style Profile Release is `1bd26fe3-65ea-4edc-9701-be63d052a8bf`; the
Recommendation Release is `f1bbe32d-8657-460b-a788-604167f66219`. These IDs are
technical activation evidence only. A real Profile build remains blocked on
the approved sample corpus, and a real Recommendation Job remains blocked on
the selected Observation/Statistic/Fact/Rule evidence set.

The synthetic activation was verified at Alembic `0095` with four active Dify
bindings and four frozen Prompt bindings. Review Job
`4426834e-3e3b-5227-adcc-5b475c89031b` completed and retained exactly nine Dify
results across a Worker restart. Negative-path Job
`9e3e79d3-32bc-5dc2-87ff-ab52f5fa26ba` executed two Dify revisions and one
regeneration, then correctly failed closed when a later conflict-check output
violated its frozen contract.

## Failure and rollback

- Network, credential, provider and output-contract failures are recorded on the
  Dify attempt and returned as actionable retryable or terminal Job failures.
- A connection failure known to occur before request transmission may retry the
  same Durable Job and creates a new fenced attempt. A read/write failure or
  provider 5xx after submission is an unknown outcome and the old Job must never
  call Dify again.
- For an unknown outcome, an owner/admin must verify Dify run history and run
  `manage_dify_workflows.py reconcile-new-parent` with the run outcome and an
  evidence reference. The command only authorizes submission of a new parent
  Job with a new replay identity; it never reopens the old Job.
- A successful business result is stored atomically with its Attempt. If the
  Worker stops after that commit, retry replays the verified result without a
  second Dify provider call.
- Before rolling back the Style Profile Worker/image or binding, pause the
  profile-build route and repeat the two-count drain check above. Use the normal
  Job cancellation endpoint for work that cannot finish, wait for terminal
  state, and only then deploy the previous image or binding. Never switch a
  non-terminal parent or child Job between native and Dify execution.
- Alembic `0098 -> 0097` is a pre-activation rollback only. It accepts terminal
  `migration_backfill_*` children whose original 0097 attempts still preserve
  the same release, but refuses to erase any `runtime_admission` Dify child.
  After the first new Dify business child, an application-image rollback must
  leave the 0098 schema and its frozen lineage in place; do not rewrite the
  lineage source to force a database downgrade.
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
