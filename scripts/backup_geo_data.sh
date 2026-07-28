#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
env_file="${1:-$repo_root/infra/production.env}"
source_environment="${2:-}"
compose_file="$repo_root/infra/compose.prod.yml"
cd "$repo_root"

if [[ ! -f "$env_file" ]]; then
  echo "backup error: production env file is unavailable" >&2
  exit 2
fi
if [[ ! "$source_environment" =~ ^(production|staging)$ ]]; then
  echo "backup error: explicit source environment must be production or staging" >&2
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
verification_tmpfs_root="$(config_value GEO_RESTORE_TMPFS_ROOT)"
secret_store_request_hash_key="$(config_value GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE)"
restore_probe_service_identity_id="$(config_value GEO_RESTORE_PROBE_SERVICE_IDENTITY_ID)"
restore_secret_reference_id="$(config_value GEO_RESTORE_SECRET_REFERENCE_ID)"
restore_secret_project_id="$(config_value GEO_RESTORE_SECRET_PROJECT_ID)"
restore_secret_purpose="$(config_value GEO_RESTORE_SECRET_PURPOSE)"
restore_secret_version="$(config_value GEO_RESTORE_SECRET_VERSION)"
restore_secret_idempotency_key="$(config_value GEO_RESTORE_SECRET_IDEMPOTENCY_KEY)"
if [[ ! -d "$verification_tmpfs_root" \
  || "$(stat -f -c '%T' "$verification_tmpfs_root")" != "tmpfs" \
  || "$(stat -c '%a' "$verification_tmpfs_root")" != "700" ]]; then
  echo "backup error: verification staging must be a 0700 tmpfs directory" >&2
  exit 2
fi
exec {backup_lock_fd}>>"$backup_root/.backup.lock"
chmod 0600 "$backup_root/.backup.lock"
if ! flock -n "$backup_lock_fd"; then
  echo "backup error: another backup or restore operation is active" >&2
  exit 2
fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
daily_root="$backup_root/daily"
weekly_root="$backup_root/weekly"
staging_root="$backup_root/staging"
staging="$staging_root/.$stamp.$$.pending"
final="$daily_root/$stamp"
weekly_staging=""
compose=(docker compose --env-file "$env_file" -f "$compose_file")
snapshot_id=""
snapshot_pid=""
snapshot_read_fd=""
snapshot_write_fd=""
verification_staging=""

install -d -m 0700 "$daily_root" "$weekly_root" "$staging_root"
if [[ -e "$final" || -L "$final" ]]; then
  echo "backup error: backup identifier already exists" >&2
  exit 2
fi
mkdir -m 0700 "$staging"

cleanup() {
  if [[ -n "$snapshot_pid" ]]; then
    if [[ -n "$snapshot_write_fd" ]]; then
      printf 'ROLLBACK;\n\\q\n' >&"$snapshot_write_fd" 2>/dev/null || true
      exec {snapshot_write_fd}>&- 2>/dev/null || true
    fi
    wait "$snapshot_pid" 2>/dev/null || true
    if [[ -n "$snapshot_read_fd" ]]; then
      exec {snapshot_read_fd}<&- 2>/dev/null || true
    fi
  fi
  rm -rf -- "$staging"
  if [[ -n "$weekly_staging" ]]; then
    rm -rf -- "$weekly_staging"
  fi
  if [[ -n "$verification_staging" ]]; then
    rm -rf -- "$verification_staging"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

pg_scalar() {
  local sql="$1"
  "${compose[@]}" exec -T postgres sh -ceu \
    'PGPASSWORD="$(cat /run/secrets/postgres_installer_password)" psql -X -qAt -v ON_ERROR_STOP=1 -U geo_installer -d geo -c "$1"' \
    sh "$sql"
}

start_consistent_snapshot() {
  coproc SNAPSHOT_EXPORTER {
    "${compose[@]}" exec -T postgres sh -ceu \
      'PGPASSWORD="$(cat /run/secrets/postgres_installer_password)" exec psql -X -qAt -v ON_ERROR_STOP=1 -U geo_installer -d geo' \
      sh
  }
  snapshot_pid="$SNAPSHOT_EXPORTER_PID"
  exec {snapshot_read_fd}<&"${SNAPSHOT_EXPORTER[0]}"
  exec {snapshot_write_fd}>&"${SNAPSHOT_EXPORTER[1]}"
  printf '%s\n' \
    'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();' \
    >&"$snapshot_write_fd"
  if ! IFS= read -r snapshot_id <&"$snapshot_read_fd" \
    || [[ ! "$snapshot_id" =~ ^[0-9A-Fa-f-]+$ ]]; then
    echo "backup error: consistent database snapshot is unavailable" >&2
    exit 2
  fi
}

close_consistent_snapshot() {
  printf 'COMMIT;\n\\q\n' >&"$snapshot_write_fd"
  exec {snapshot_write_fd}>&-
  wait "$snapshot_pid"
  exec {snapshot_read_fd}<&-
  snapshot_id=""
  snapshot_pid=""
  snapshot_read_fd=""
  snapshot_write_fd=""
}

pg_scalar_at_snapshot() {
  local sql="$1"
  pg_scalar "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '$snapshot_id'; $sql; COMMIT;"
}

business_consistency_at_snapshot() {
  {
    printf "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '%s';\n" \
      "$snapshot_id"
    cat "$repo_root/scripts/non_b_business_consistency.sql"
    printf '\nCOMMIT;\n'
  } | "${compose[@]}" exec -T postgres sh -ceu \
    'PGPASSWORD="$(cat /run/secrets/postgres_installer_password)" exec psql -X -qAt -v ON_ERROR_STOP=1 -U geo_installer -d geo'
}

relation_hash_at_snapshot() {
  local relation="$1"
  local sql
  local digest
  case "$relation" in
    projects|project_memberships|evidence_items|monitoring_reports) ;;
    *) echo "backup error: unsupported relation hash" >&2; exit 2 ;;
  esac
  sql="BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '$snapshot_id'; COPY (SELECT row_json FROM (SELECT to_jsonb(source_row)::text AS row_json FROM $relation AS source_row) AS serialized_rows ORDER BY row_json COLLATE \"C\") TO STDOUT WITH (FORMAT text); COMMIT;"
  digest="$(
    "${compose[@]}" exec -T postgres sh -ceu \
      'PGPASSWORD="$(cat /run/secrets/postgres_installer_password)" psql -X -qAt -v ON_ERROR_STOP=1 -U geo_installer -d geo -c "$1"' \
      sh "$sql" \
      | LC_ALL=C sha256sum
  )"
  digest="${digest%% *}"
  if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
    echo "backup error: invalid relation hash" >&2
    exit 2
  fi
  printf '%s' "$digest"
}

require_count() {
  local value="$1"
  local label="$2"
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    echo "backup error: invalid $label count" >&2
    exit 2
  fi
}

start_consistent_snapshot
pg_scalar_at_snapshot "$(<"$repo_root/scripts/check_postgres_fk_integrity.sql")" >/dev/null
restore_secret_idempotency_hash="$(
  uv run python - "$secret_store_request_hash_key" "$restore_secret_idempotency_key" <<'PY'
import base64
import sys
from pathlib import Path

from geo_core.secrets import SecretRequestHasher

encoded = Path(sys.argv[1]).read_text(encoding="ascii").strip()
key = base64.b64decode(encoded, validate=True)
print(SecretRequestHasher(key).idempotency_key_hash(sys.argv[2]))
PY
)"
if [[ ! "$restore_secret_idempotency_hash" =~ ^[0-9a-f]{64}$ ]]; then
  echo "backup error: restore Secret Store request canary is invalid" >&2
  exit 2
fi
restore_secret_canary_ready="$(pg_scalar_at_snapshot "
SELECT (
    geo_require_active_service_identity(
        '$restore_probe_service_identity_id'::uuid,
        'restore_probe'
    )
    AND EXISTS (
        SELECT 1
        FROM secret_versions
        WHERE reference_id = '$restore_secret_reference_id'::uuid
          AND project_id = '$restore_secret_project_id'::uuid
          AND purpose = '$restore_secret_purpose'
          AND version = $restore_secret_version
          AND status = 'active'
    )
    AND (SELECT count(*) FROM secret_command_receipts
         WHERE project_id = '$restore_secret_project_id'::uuid
           AND idempotency_key_hash = '$restore_secret_idempotency_hash'
           AND operation = 'resolve'
           AND reference_id = '$restore_secret_reference_id'::uuid
           AND purpose = '$restore_secret_purpose'
           AND version = $restore_secret_version) = 1
    AND (SELECT count(*) FROM secret_audit_events
         WHERE project_id = '$restore_secret_project_id'::uuid
           AND reference_id = '$restore_secret_reference_id'::uuid
           AND purpose = '$restore_secret_purpose'
           AND version = $restore_secret_version
           AND actor_id = '$restore_probe_service_identity_id'::uuid
           AND action = 'version_resolved') = 1
)::text")"
if [[ "$restore_secret_canary_ready" != "true" ]]; then
  echo "backup error: frozen Secret Store restore canary is unavailable" >&2
  exit 2
fi
project_count="$(pg_scalar_at_snapshot 'SELECT count(*) FROM projects')"
project_ids="$(pg_scalar_at_snapshot "SELECT coalesce(json_agg(id::text ORDER BY id), '[]'::json)::text FROM projects")"
table_count="$(pg_scalar_at_snapshot "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'")"
migration_revision="$(pg_scalar_at_snapshot 'SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1')"
source_database_name="$(pg_scalar_at_snapshot 'SELECT current_database()')"
source_database_user="$(pg_scalar_at_snapshot 'SELECT current_user')"
source_system_identifier="$(pg_scalar_at_snapshot 'SELECT system_identifier::text FROM pg_control_system()')"
database_checksum_ledger_rows="$(pg_scalar_at_snapshot "SELECT coalesce(json_agg(json_build_object('revision', revision, 'upgrade_sha256', upgrade_sha256, 'downgrade_sha256', downgrade_sha256) ORDER BY revision), '[]'::json)::text FROM alembic_sql_checksum_ledger")"
non_b_business_consistency="$(business_consistency_at_snapshot)"
alembic_sql_checksum_ledger="$(
  uv run python "$repo_root/scripts/alembic_sql_ledger.py" create \
    --sql-dir "$repo_root/infra/db/alembic/sql" \
    --head-revision "$migration_revision"
)"
critical_relation_counts="$(pg_scalar_at_snapshot "SELECT json_build_object('evidence_items', (SELECT count(*) FROM evidence_items), 'monitoring_reports', (SELECT count(*) FROM monitoring_reports), 'project_memberships', (SELECT count(*) FROM project_memberships))::text")"
projects_hash="$(relation_hash_at_snapshot projects)"
project_memberships_hash="$(relation_hash_at_snapshot project_memberships)"
evidence_items_hash="$(relation_hash_at_snapshot evidence_items)"
monitoring_reports_hash="$(relation_hash_at_snapshot monitoring_reports)"
critical_relation_hashes="$(printf \
  '{"evidence_items":"%s","monitoring_reports":"%s","project_memberships":"%s","projects":"%s"}' \
  "$evidence_items_hash" "$monitoring_reports_hash" \
  "$project_memberships_hash" "$projects_hash")"
secret_key_version_count="$(pg_scalar_at_snapshot "SELECT count(*) FROM secret_master_key_versions WHERE status <> 'retired'")"
secret_version_count="$(pg_scalar_at_snapshot 'SELECT count(*) FROM secret_versions')"
representative_probe_target_count="$(pg_scalar_at_snapshot 'SELECT count(DISTINCT master_key_version) FROM secret_versions')"
provider_artifact_key_version_count="$(pg_scalar_at_snapshot "SELECT count(*) FROM model_gateway_artifact_master_key_versions WHERE status <> 'retired'")"
provider_active_dek_count="$(pg_scalar_at_snapshot "SELECT count(*) FROM model_gateway_artifact_deks WHERE status = 'active'")"
provider_recoverable_artifact_count="$(pg_scalar_at_snapshot "SELECT count(*) FROM model_gateway_artifacts AS artifact JOIN model_gateway_artifact_deks AS dek ON dek.key_ref = artifact.key_ref AND dek.project_id = artifact.project_id AND dek.artifact_id = artifact.artifact_id JOIN model_gateway_artifact_bundles AS bundle ON bundle.id = artifact.bundle_id AND bundle.project_id = artifact.project_id WHERE dek.status = 'active' AND bundle.status = 'committed'")"
synthetic_artifact_key_version_count="$(pg_scalar_at_snapshot "SELECT count(*) FROM synthetic_lab_artifact_master_key_versions WHERE status <> 'retired'")"
synthetic_active_dek_count="$(pg_scalar_at_snapshot "SELECT count(*) FROM synthetic_lab_artifact_deks WHERE status = 'active'")"
synthetic_nondeleted_artifact_count="$(pg_scalar_at_snapshot "SELECT count(*) FROM synthetic_lab_raw_artifacts WHERE lifecycle_state <> 'deleted'")"
synthetic_tier_key_artifact_count="$(pg_scalar_at_snapshot "SELECT count(*) FROM synthetic_lab_raw_artifacts WHERE lifecycle_state <> 'deleted' AND storage_tier <> 'restricted_independent_dek'")"
probe_value() {
  uv run python -c \
    'import json,sys; value=json.loads(sys.argv[1]); [None for key in sys.argv[2].split(".") if not (value := value[key]) is None]; print(value)' \
    "$artifact_source_probe" "$1"
}
require_count "$project_count" "project"
require_count "$table_count" "table"
require_count "$secret_key_version_count" "Secret Store key version"
require_count "$secret_version_count" "Secret Store version"
require_count "$representative_probe_target_count" "Secret Store representative probe target"
require_count "$provider_artifact_key_version_count" "Provider artifact key version"
require_count "$provider_active_dek_count" "Provider active DEK"
require_count "$provider_recoverable_artifact_count" "Provider recoverable artifact"
require_count "$synthetic_artifact_key_version_count" "Synthetic artifact key version"
require_count "$synthetic_active_dek_count" "Synthetic active DEK"
require_count "$synthetic_nondeleted_artifact_count" "Synthetic nondeleted artifact"
require_count "$synthetic_tier_key_artifact_count" "Synthetic tier-key artifact"
if [[ "$project_count" == "0" || "$table_count" == "0" || "$secret_key_version_count" == "0" ]]; then
  echo "backup error: a project-scoped schema and Secret Store key canary are required" >&2
  exit 2
fi
provider_representative_probe_target_count=0
if [[ "$provider_recoverable_artifact_count" != "0" ]]; then
  provider_representative_probe_target_count=1
fi
synthetic_restricted_probe_target_count=0
if [[ "$synthetic_active_dek_count" != "0" ]]; then
  synthetic_restricted_probe_target_count=1
fi
synthetic_tier_probe_target_count=0
if [[ "$synthetic_tier_key_artifact_count" != "0" ]]; then
  synthetic_tier_probe_target_count=1
fi
"${compose[@]}" exec -T postgres sh -ceu \
  'PGPASSWORD="$(cat /run/secrets/postgres_installer_password)" exec pg_dump -U geo_installer -d geo --clean --if-exists --no-owner --snapshot="$1"' \
  sh "$snapshot_id" \
  | gzip -9 \
  | uv run python "$repo_root/scripts/backup_envelope.py" encrypt \
      --keyring "$backup_keyring" \
      --backup-id "$stamp" \
      --artifact postgres \
      --output "$staging/postgres.sql.gz.enc" \
      >/dev/null

container_control="/backup-data/staging/$(basename "$staging")/minio-object-counts.json"
verification_staging="$(mktemp -d "$verification_tmpfs_root/geo-backup-verify.XXXXXX")"
chmod 0700 "$verification_staging"
BACKUP_STAMP="$stamp" "${compose[@]}" --profile backup run --rm -T \
  -e "BACKUP_CONTROL_PATH=$container_control" backup-object-store \
  | tee "$verification_staging/minio.tar" \
  | uv run python "$repo_root/scripts/backup_envelope.py" encrypt \
      --keyring "$backup_keyring" \
      --backup-id "$stamp" \
      --artifact minio \
      --output "$staging/minio.tar.enc" \
      >/dev/null

bucket_object_counts="$(<"$staging/minio-object-counts.json")"
rm -f -- "$staging/minio-object-counts.json"
object_count="$(uv run python -c 'import json,sys; value=json.loads(sys.argv[1]); expected={"geo-artifacts","geo-restricted-recommendation-artifacts","geo-restricted-workflow-c-artifacts","geo-synthetic-style-derived","geo-synthetic-style-raw"}; raise SystemExit(2) if set(value) != expected or any(type(item) is not int or item < 0 for item in value.values()) else print(sum(value.values()))' "$bucket_object_counts")"
require_count "$object_count" "MinIO object"
chmod 0600 "$verification_staging/minio.tar"
mkdir -m 0700 "$verification_staging/minio-restored"
uv run python "$repo_root/scripts/verify_minio_backup.py" \
  --archive "$verification_staging/minio.tar" \
  --destination "$verification_staging/minio-restored" \
  --expected-object-count "$object_count" \
  --expected-bucket-object-counts-json "$bucket_object_counts" \
  >"$verification_staging/minio-verification.json"
chmod 0600 "$verification_staging/minio-verification.json"
chown -R 10001:10001 "$verification_staging/minio-restored"
artifact_source_probe="$(
  "${compose[@]}" run --rm -T --no-deps \
    -v "$verification_staging/minio-restored/buckets/geo-artifacts:/backup-source-objects:ro" \
    -v "$verification_staging/minio-restored/buckets/geo-restricted-recommendation-artifacts:/backup-source-recommendation-objects:ro" \
    -v "$verification_staging/minio-restored/buckets/geo-restricted-workflow-c-artifacts:/backup-source-workflow-c-objects:ro" \
    -v "$verification_staging/minio-restored/buckets/geo-synthetic-style-raw:/backup-source-synthetic-style-raw-objects:ro" \
    -v "$verification_staging/minio-restored/buckets/geo-synthetic-style-derived:/backup-source-synthetic-style-derived-objects:ro" \
    task-worker python -m geo_worker.artifact_backup_source_probe \
      --snapshot "$snapshot_id" \
      --object-root /backup-source-objects \
      --recommendation-object-root /backup-source-recommendation-objects \
      --workflow-c-object-root /backup-source-workflow-c-objects \
      --synthetic-raw-object-root /backup-source-synthetic-style-raw-objects \
      --synthetic-derived-object-root /backup-source-synthetic-style-derived-objects
)"
if [[ "$(probe_value schema_version)" != "geo-non-b-artifact-backup-source-v1" ]]; then
  echo "backup error: non-B artifact source probe is invalid" >&2
  exit 2
fi
recommendation_artifact_key_version_count="$(probe_value recommendation_artifacts.master_key_version_count)"
recommendation_artifact_lineage_count="$(probe_value recommendation_artifacts.artifact_lineage_count)"
recommendation_representative_probe_target_count="$(probe_value recommendation_artifacts.representative_probe_target_count)"
recommendation_source_verification_receipt_hash="$(probe_value recommendation_artifacts.source_verification_receipt_hash)"
workflow_c_artifact_key_version_count="$(probe_value workflow_c_artifacts.master_key_version_count)"
workflow_c_active_dek_count="$(probe_value workflow_c_artifacts.active_dek_count)"
workflow_c_recoverable_artifact_count="$(probe_value workflow_c_artifacts.recoverable_artifact_count)"
workflow_c_representative_probe_target_count="$(probe_value workflow_c_artifacts.representative_probe_target_count)"
workflow_c_source_verification_receipt_hash="$(probe_value workflow_c_artifacts.source_verification_receipt_hash)"
require_count "$recommendation_artifact_key_version_count" "Recommendation artifact key version"
require_count "$recommendation_artifact_lineage_count" "Recommendation artifact lineage"
require_count "$recommendation_representative_probe_target_count" "Recommendation representative probe target"
require_count "$workflow_c_artifact_key_version_count" "Workflow C artifact key version"
require_count "$workflow_c_active_dek_count" "Workflow C active DEK"
require_count "$workflow_c_recoverable_artifact_count" "Workflow C recoverable artifact"
require_count "$workflow_c_representative_probe_target_count" "Workflow C representative probe target"
rm -rf -- "$verification_staging"
verification_staging=""
close_consistent_snapshot
alembic_sql_checksum_ledger_after_backup="$(
  uv run python "$repo_root/scripts/alembic_sql_ledger.py" create \
    --sql-dir "$repo_root/infra/db/alembic/sql" \
    --head-revision "$migration_revision"
)"
if [[ "$alembic_sql_checksum_ledger_after_backup" != "$alembic_sql_checksum_ledger" ]]; then
  echo "backup error: Alembic SQL changed during backup" >&2
  exit 2
fi

uv run python "$repo_root/scripts/backup_manifest.py" create \
  --keyring "$backup_keyring" \
  --backup-dir "$staging" \
  --backup-id "$stamp" \
  --created-at "$created_at" \
  --migration-revision "$migration_revision" \
  --alembic-sql-checksum-ledger-json "$alembic_sql_checksum_ledger" \
  --database-checksum-ledger-rows-json "$database_checksum_ledger_rows" \
  --source-database-name "$source_database_name" \
  --source-database-user "$source_database_user" \
  --source-environment "$source_environment" \
  --source-system-identifier "$source_system_identifier" \
  --source-project-ids-json "$project_ids" \
  --postgres-project-count "$project_count" \
  --postgres-table-count "$table_count" \
  --critical-relation-counts-json "$critical_relation_counts" \
  --critical-relation-hashes-json "$critical_relation_hashes" \
  --non-b-business-consistency-json "$non_b_business_consistency" \
  --minio-object-count "$object_count" \
  --minio-bucket-object-counts-json "$bucket_object_counts" \
  --secret-key-version-count "$secret_key_version_count" \
  --secret-version-count "$secret_version_count" \
  --representative-probe-target-count "$representative_probe_target_count" \
  --provider-artifact-key-version-count "$provider_artifact_key_version_count" \
  --provider-active-dek-count "$provider_active_dek_count" \
  --provider-recoverable-artifact-count "$provider_recoverable_artifact_count" \
  --provider-representative-probe-target-count "$provider_representative_probe_target_count" \
  --synthetic-artifact-key-version-count "$synthetic_artifact_key_version_count" \
  --synthetic-active-dek-count "$synthetic_active_dek_count" \
  --synthetic-nondeleted-artifact-count "$synthetic_nondeleted_artifact_count" \
  --synthetic-tier-key-artifact-count "$synthetic_tier_key_artifact_count" \
  --synthetic-restricted-probe-target-count "$synthetic_restricted_probe_target_count" \
  --synthetic-tier-probe-target-count "$synthetic_tier_probe_target_count" \
  --recommendation-artifact-key-version-count "$recommendation_artifact_key_version_count" \
  --recommendation-artifact-lineage-count "$recommendation_artifact_lineage_count" \
  --recommendation-representative-probe-target-count "$recommendation_representative_probe_target_count" \
  --recommendation-source-verification-receipt-hash "$recommendation_source_verification_receipt_hash" \
  --workflow-c-artifact-key-version-count "$workflow_c_artifact_key_version_count" \
  --workflow-c-active-dek-count "$workflow_c_active_dek_count" \
  --workflow-c-recoverable-artifact-count "$workflow_c_recoverable_artifact_count" \
  --workflow-c-representative-probe-target-count "$workflow_c_representative_probe_target_count" \
  --workflow-c-source-verification-receipt-hash "$workflow_c_source_verification_receipt_hash" \
  >/dev/null
uv run python "$repo_root/scripts/backup_manifest.py" verify \
  --keyring "$backup_keyring" --backup-dir "$staging" >/dev/null

find "$staging" -type d -exec chmod 0700 {} +
find "$staging" -type f -exec chmod 0600 {} +
mv -T -- "$staging" "$final"

if [[ "$(date -u +%u)" == "7" ]]; then
  weekly_staging="$staging_root/.weekly.$stamp.$$.pending"
  mkdir -m 0700 "$weekly_staging"
  cp -a "$final/." "$weekly_staging/"
  find "$weekly_staging" -type d -exec chmod 0700 {} +
  find "$weekly_staging" -type f -exec chmod 0600 {} +
  mv -T -- "$weekly_staging" "$weekly_root/$stamp"
  weekly_staging=""
fi
trap - EXIT INT TERM

find "$daily_root" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf -- {} +
find "$weekly_root" -mindepth 1 -maxdepth 1 -type d -mtime +28 -exec rm -rf -- {} +

echo "backup complete: $final"
