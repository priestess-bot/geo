#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
env_file="${1:-$repo_root/infra/production.env}"
backup_input="${2:-${BACKUP_DIR:-${BACKUP_FILE:-}}}"
compose_file="$repo_root/infra/compose.prod.yml"
cd "$repo_root"

if [[ ! -f "$env_file" ]]; then
  echo "restore smoke error: production env file is unavailable" >&2
  exit 2
fi
if [[ "${EUID:-$(id -u)}" != "0" ]]; then
  echo "restore smoke error: controlled root execution is required" >&2
  exit 2
fi
if [[ -z "$backup_input" || ! -d "$backup_input" || -L "$backup_input" ]]; then
  echo "usage: $0 [production.env] ENCRYPTED_BACKUP_DIRECTORY" >&2
  exit 2
fi
uv run python "$repo_root/scripts/production_preflight.py" --env-file "$env_file" >/dev/null

config_value() {
  uv run python -c \
    'import sys; from pathlib import Path; from scripts.production_preflight import parse_env_file; values, issues = parse_env_file(Path(sys.argv[1])); field = sys.argv[2]; raise SystemExit(2) if issues or not values.get(field, "").strip() else print(values[field].strip())' \
    "$env_file" "$1"
}

backup_root="$(config_value GEO_BACKUP_ROOT)"
backup_keyring="$(config_value GEO_BACKUP_KEYRING_FILE)"
restore_tmpfs_root="$(config_value GEO_RESTORE_TMPFS_ROOT)"
backup_root="$(realpath -e -- "$backup_root")"
exec {backup_lock_fd}>>"$backup_root/.backup.lock"
chmod 0600 "$backup_root/.backup.lock"
if ! flock -n "$backup_lock_fd"; then
  echo "restore smoke error: backup maintenance is active" >&2
  exit 2
fi
backup_lexical="$(uv run python -c 'import sys; from pathlib import Path; print(Path(sys.argv[1]).absolute())' "$backup_input")"
resolved_backup="$(realpath -e -- "$backup_input")"
case "$resolved_backup" in
  "$backup_root"/daily/*|"$backup_root"/weekly/*) ;;
  *) echo "restore smoke error: backup directory is outside the configured root" >&2; exit 2 ;;
esac
backup_dir="$backup_lexical"

restore_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ "$(stat -f -c '%T' -- "$restore_tmpfs_root")" != "tmpfs" ]]; then
  echo "restore smoke error: authenticated plaintext staging is not tmpfs" >&2
  exit 2
fi
restore_staging="$(mktemp -d "$restore_tmpfs_root/geo-restore.XXXXXXXX")"
chmod 0700 "$restore_staging"
if [[ "$(stat -f -c '%T' -- "$restore_staging")" != "tmpfs" ]]; then
  rm -rf -- "$restore_staging"
  echo "restore smoke error: authenticated plaintext staging is not tmpfs" >&2
  exit 2
fi
receipts_root="$backup_root/restore-receipts"
install -d -m 0700 "$receipts_root"
compose=(
  docker compose --env-file "$env_file"
  -f "$compose_file" -f "$repo_root/infra/compose.style-collection.yml"
)
restore_removed=0

bootstrap_restore_acl_roles() {
  "${compose[@]}" exec -T restore-smoke-postgres sh -ceu \
    'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" exec psql -X -v ON_ERROR_STOP=1 -U geo_restore -d geo_restore_smoke' \
    <<'SQL'
DO $$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['geo_app', 'geo_worker', 'geo_readonly'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
                role_name
            );
        ELSIF EXISTS (
            SELECT 1
            FROM pg_roles
            WHERE rolname = role_name
              AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolcanlogin
                   OR rolinherit OR rolbypassrls)
        ) THEN
            RAISE EXCEPTION 'restore group role % has unsafe attributes', role_name
                USING ERRCODE = '42501';
        END IF;
    END LOOP;
END;
$$;
SQL
}

drop_restore_acl_canary_roles() {
  "${compose[@]}" exec -T restore-smoke-postgres sh -ceu \
    'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" exec psql -X -q -v ON_ERROR_STOP=1 -U geo_restore -d geo_restore_smoke' \
    <<'SQL' >/dev/null 2>&1 || true
REVOKE geo_restore_canary_app, geo_restore_canary_worker, geo_restore_canary_readonly FROM geo_restore;
DROP ROLE IF EXISTS geo_restore_canary_app;
DROP ROLE IF EXISTS geo_restore_canary_worker;
DROP ROLE IF EXISTS geo_restore_canary_readonly;
SQL
}

remove_restore_copy() {
  "${compose[@]}" --profile restore-smoke rm -sf \
    restore-smoke-application-key-probe restore-smoke-postgres >/dev/null
  remaining_restore_containers="$("${compose[@]}" --profile restore-smoke ps -q \
    restore-smoke-application-key-probe restore-smoke-postgres)"
  [[ -z "$remaining_restore_containers" ]]
  restore_removed=1
}

cleanup() {
  drop_restore_acl_canary_roles
  "${compose[@]}" --profile restore-smoke rm -sf \
    restore-smoke-application-key-probe restore-smoke-postgres >/dev/null 2>&1 || true
  if [[ -n "$restore_staging" ]]; then
    rm -rf -- "$restore_staging"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

uv run python "$repo_root/scripts/backup_manifest.py" verify \
  --keyring "$backup_keyring" --backup-dir "$backup_dir" \
  >"$restore_staging/verified-manifest.json"
chmod 0600 "$restore_staging/verified-manifest.json"

manifest_value() {
  uv run python -c \
    'import json,sys; value=json.load(open(sys.argv[1], encoding="ascii")); [None for key in sys.argv[2].split(".") if not (value := value[key]) is None]; print(value)' \
    "$restore_staging/verified-manifest.json" "$1"
}

source_projects="$(manifest_value source.postgres.project_count)"
source_tables="$(manifest_value source.postgres.table_count)"
source_migration="$(manifest_value source.postgres.migration_revision)"
source_migration_ledger="$(
  uv run python -c \
    'import json,sys; from scripts.backup_envelope import canonical_json; value=json.load(open(sys.argv[1], encoding="ascii"))["source"]["postgres"]["alembic_sql_checksum_ledger"]; print(canonical_json(value).decode("ascii"))' \
    "$restore_staging/verified-manifest.json"
)"
source_objects="$(manifest_value source.minio.object_count)"
source_bucket_object_counts="$(
  uv run python -c \
    'import json,sys; from scripts.backup_envelope import canonical_json; value=json.load(open(sys.argv[1], encoding="ascii"))["source"]["minio"]["bucket_object_counts"]; print(canonical_json(value).decode("ascii"))' \
    "$restore_staging/verified-manifest.json"
)"
backup_id="$(manifest_value backup_id)"

"${compose[@]}" --profile restore-smoke up -d --wait restore-smoke-postgres
bootstrap_restore_acl_roles
uv run python "$repo_root/scripts/backup_manifest.py" decrypt \
  --keyring "$backup_keyring" \
  --backup-dir "$backup_dir" \
  --artifact postgres \
  --staging-dir "$restore_staging" \
  | gzip -dc \
  | "${compose[@]}" exec -T restore-smoke-postgres sh -ceu \
      'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" psql -X -v ON_ERROR_STOP=1 -U geo_restore -d geo_restore_smoke'

restore_scalar() {
  local sql="$1"
  "${compose[@]}" exec -T restore-smoke-postgres sh -ceu \
    'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" psql -X -At -v ON_ERROR_STOP=1 -U geo_restore -d geo_restore_smoke -c "$1"' \
    sh "$sql"
}

restore_business_consistency() {
  "${compose[@]}" exec -T restore-smoke-postgres sh -ceu \
    'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" exec psql -X -qAt -v ON_ERROR_STOP=1 -U geo_restore -d geo_restore_smoke' \
    <"$repo_root/scripts/non_b_business_consistency.sql"
}

restore_relation_hash() {
  local relation="$1"
  local sql
  local digest
  case "$relation" in
    projects|project_memberships|evidence_items|monitoring_reports) ;;
    *) echo "restore smoke error: unsupported relation hash" >&2; exit 2 ;;
  esac
  sql="COPY (SELECT row_json FROM (SELECT to_jsonb(restored_row)::text AS row_json FROM $relation AS restored_row) AS serialized_rows ORDER BY row_json COLLATE \"C\") TO STDOUT WITH (FORMAT text)"
  digest="$(
    "${compose[@]}" exec -T restore-smoke-postgres sh -ceu \
      'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" psql -X -qAt -v ON_ERROR_STOP=1 -U geo_restore -d geo_restore_smoke -c "$1"' \
      sh "$sql" \
      | LC_ALL=C sha256sum
  )"
  digest="${digest%% *}"
  if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
    echo "restore smoke error: invalid relation hash" >&2
    exit 2
  fi
  printf '%s' "$digest"
}

restored_projects="$(restore_scalar 'SELECT count(*) FROM projects')"
restored_tables="$(restore_scalar "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'")"
restored_migration="$(restore_scalar 'SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1')"
restored_database_checksum_ledger_rows="$(restore_scalar "SELECT coalesce(json_agg(json_build_object('revision', revision, 'upgrade_sha256', upgrade_sha256, 'downgrade_sha256', downgrade_sha256) ORDER BY revision), '[]'::json)::text FROM alembic_sql_checksum_ledger")"
restored_non_b_business_consistency="$(restore_business_consistency)"
restored_migration_ledger="$(
  uv run python "$repo_root/scripts/alembic_sql_ledger.py" verify \
    --sql-dir "$repo_root/infra/db/alembic/sql" \
    --ledger-json "$source_migration_ledger"
)"
restored_critical_relation_counts="$(restore_scalar "SELECT json_build_object('evidence_items', (SELECT count(*) FROM evidence_items), 'monitoring_reports', (SELECT count(*) FROM monitoring_reports), 'project_memberships', (SELECT count(*) FROM project_memberships))::text")"
restored_projects_hash="$(restore_relation_hash projects)"
restored_project_memberships_hash="$(restore_relation_hash project_memberships)"
restored_evidence_items_hash="$(restore_relation_hash evidence_items)"
restored_monitoring_reports_hash="$(restore_relation_hash monitoring_reports)"
restored_critical_relation_hashes="$(printf \
  '{"evidence_items":"%s","monitoring_reports":"%s","project_memberships":"%s","projects":"%s"}' \
  "$restored_evidence_items_hash" "$restored_monitoring_reports_hash" \
  "$restored_project_memberships_hash" "$restored_projects_hash")"
[[ "$restored_projects" == "$source_projects" ]]
[[ "$restored_tables" == "$source_tables" ]]
[[ "$restored_migration" == "$source_migration" ]]
"${compose[@]}" exec -T restore-smoke-postgres sh -ceu \
  'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" psql -X -v ON_ERROR_STOP=1 -U geo_restore -d geo_restore_smoke' \
  <"$repo_root/scripts/check_postgres_fk_integrity.sql" >/dev/null

restore_project_id="$(restore_scalar 'SELECT id FROM projects ORDER BY id LIMIT 1')"
if [[ ! "$restore_project_id" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "restore smoke error: a restored project is required for ACL/RLS verification" >&2
  exit 2
fi
"${compose[@]}" exec -T restore-smoke-postgres sh -ceu \
  'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" exec psql -X -q -v ON_ERROR_STOP=1 -U geo_restore -d geo_restore_smoke' \
  <<'SQL'
DO $$
DECLARE
    role_name text;
    group_name text;
BEGIN
    FOR role_name, group_name IN
        SELECT * FROM (VALUES
            ('geo_restore_canary_app', 'geo_app'),
            ('geo_restore_canary_worker', 'geo_worker'),
            ('geo_restore_canary_readonly', 'geo_readonly')
        ) AS roles(role_name, group_name)
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('DROP ROLE %I', role_name);
        END IF;
        EXECUTE format(
            'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
            role_name
        );
        EXECUTE format('GRANT %I TO %I', group_name, role_name);
        EXECUTE format('GRANT %I TO geo_restore', role_name);
    END LOOP;
END;
$$;
SQL
acl_rls_evidence="$restore_staging/acl-rls-canary.txt"
for role_group in \
  'geo_restore_canary_app:geo_app' \
  'geo_restore_canary_worker:geo_worker' \
  'geo_restore_canary_readonly:geo_readonly'; do
  IFS=: read -r canary_role canary_group <<<"$role_group"
  "${compose[@]}" exec -T restore-smoke-postgres sh -ceu \
    'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" exec psql -X -qAt -F "|" -v ON_ERROR_STOP=1 -U geo_restore -d geo_restore_smoke' \
    <<SQL >>"$acl_rls_evidence"
BEGIN;
SET LOCAL ROLE $canary_role;
SET LOCAL geo.project_ids = '["$restore_project_id"]';
-- Keep the canary NOINHERIT and explicitly assume the restored group when
-- exercising its RLS-scoped table and function privileges.
SET LOCAL ROLE $canary_group;
SELECT '$canary_role',
       (SELECT rolcanlogin FROM pg_roles WHERE rolname = '$canary_role'),
       (SELECT rolcreaterole FROM pg_roles WHERE rolname = '$canary_role'),
       (SELECT rolsuper FROM pg_roles WHERE rolname = '$canary_role'),
       (SELECT rolbypassrls FROM pg_roles WHERE rolname = '$canary_role'),
       (SELECT rolinherit FROM pg_roles WHERE rolname = '$canary_role'),
       pg_has_role('$canary_role', '$canary_group', 'member'),
       EXISTS (SELECT 1 FROM projects WHERE id = '$restore_project_id'::uuid),
       (SELECT set_config('geo.project_ids', '[]', true)) IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM projects WHERE id = '$restore_project_id'::uuid),
       has_function_privilege(
           current_user,
           'geo_worker_claim_broker_outbox(text,integer,integer)',
           'EXECUTE'
       );
ROLLBACK;
SQL
done
chmod 0600 "$acl_rls_evidence"
acl_rls_receipt="$restore_staging/acl-rls-canary.json"
uv run python "$repo_root/scripts/write_restore_acl_rls_canary.py" \
  --project-id "$restore_project_id" \
  --evidence "$acl_rls_evidence" \
  --output "$acl_rls_receipt" >/dev/null

uv run python "$repo_root/scripts/backup_manifest.py" decrypt \
  --keyring "$backup_keyring" \
  --backup-dir "$backup_dir" \
  --artifact minio \
  --staging-dir "$restore_staging" \
  >"$restore_staging/minio.tar"
chmod 0600 "$restore_staging/minio.tar"
mkdir -m 0700 "$restore_staging/minio-restored"
uv run python "$repo_root/scripts/verify_minio_backup.py" \
  --archive "$restore_staging/minio.tar" \
  --destination "$restore_staging/minio-restored" \
  --expected-object-count "$source_objects" \
  --expected-bucket-object-counts-json "$source_bucket_object_counts" \
  >"$restore_staging/minio-verification.json"
chmod 0600 "$restore_staging/minio-verification.json"
chown -R 10001:10001 "$restore_staging/minio-restored"
"${compose[@]}" --profile restore-smoke run --rm -T --no-deps \
  -v "$restore_staging/minio-restored/buckets/geo-artifacts:/restore-objects:ro" \
  -v "$restore_staging/minio-restored/buckets/geo-restricted-recommendation-artifacts:/restore-recommendation-objects:ro" \
  -v "$restore_staging/minio-restored/buckets/geo-restricted-workflow-c-artifacts:/restore-workflow-c-objects:ro" \
  -v "$restore_staging/minio-restored/buckets/geo-synthetic-style-raw:/restore-synthetic-style-raw-objects:ro" \
  -v "$restore_staging/minio-restored/buckets/geo-synthetic-style-derived:/restore-synthetic-style-derived-objects:ro" \
  restore-smoke-application-key-probe \
  >"$restore_staging/application-key-probe.json"
chmod 0600 "$restore_staging/application-key-probe.json"
rm -rf -- "$restore_staging/minio.tar" "$restore_staging/minio-restored"

remove_restore_copy
[[ "$restore_removed" == "1" ]]
receipt="$receipts_root/$backup_id-$restore_stamp.json"
receipt_candidate="$restore_staging/receipt.json"
uv run python "$repo_root/scripts/write_backup_restore_receipt.py" \
  --verified-manifest "$restore_staging/verified-manifest.json" \
  --application-key-probe "$restore_staging/application-key-probe.json" \
  --acl-rls-canary "$acl_rls_receipt" \
  --minio-verification "$restore_staging/minio-verification.json" \
  --output "$receipt_candidate" \
  --restored-project-count "$restored_projects" \
  --restored-table-count "$restored_tables" \
  --restored-migration-revision "$restored_migration" \
  --restored-alembic-sql-checksum-ledger-json "$restored_migration_ledger" \
  --restored-database-checksum-ledger-rows-json "$restored_database_checksum_ledger_rows" \
  --restored-critical-relation-counts-json "$restored_critical_relation_counts" \
  --restored-critical-relation-hashes-json "$restored_critical_relation_hashes" \
  --restored-non-b-business-consistency-json "$restored_non_b_business_consistency" \
  >/dev/null
receipt_payload="$(<"$receipt_candidate")"
rm -rf -- "$restore_staging"
[[ ! -e "$restore_staging" ]]
restore_staging=""
printf '%s\n' "$receipt_payload" \
  | uv run python -c \
      'import sys; from pathlib import Path; from scripts.backup_envelope import atomic_write; atomic_write(Path(sys.argv[1]), sys.stdin.buffer.read())' \
      "$receipt"

echo "restore smoke passed: receipt=$receipt"
