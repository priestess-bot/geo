#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$repo_root"
compose_project="${GEO_DEVELOPMENT_RESTORE_COMPOSE_PROJECT:-}"
if [[ -n "$compose_project" ]]; then
  if [[ ! "$compose_project" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]]; then
    echo "development backup error: restore Compose project name is invalid" >&2
    exit 2
  fi
  compose=(
    docker compose --project-name "$compose_project"
    -f "$repo_root/infra/docker-compose.yml"
  )
else
  compose=(docker compose -f "$repo_root/infra/docker-compose.yml")
fi
output_root="${1:-$repo_root/artifacts/backup-restore-smoke}"
source_database="${GEO_DEVELOPMENT_BACKUP_SOURCE_DATABASE:-}"
source_bucket="${GEO_DEVELOPMENT_BACKUP_SOURCE_BUCKET:-}"
recommendation_source_bucket="${GEO_DEVELOPMENT_RECOMMENDATION_BACKUP_SOURCE_BUCKET:-}"
workflow_c_source_bucket="${GEO_DEVELOPMENT_WORKFLOW_C_BACKUP_SOURCE_BUCKET:-}"
synthetic_raw_source_bucket="${GEO_DEVELOPMENT_SYNTHETIC_RAW_BACKUP_SOURCE_BUCKET:-}"
synthetic_derived_source_bucket="${GEO_DEVELOPMENT_SYNTHETIC_DERIVED_BACKUP_SOURCE_BUCKET:-}"
secret_store_keyring_input="${GEO_DEVELOPMENT_SECRET_STORE_MASTER_KEYRING_FILE:-}"
secret_store_request_hash_key_input="${GEO_DEVELOPMENT_SECRET_STORE_REQUEST_HASH_KEY_FILE:-}"
restore_secret_service_identity_id="${GEO_DEVELOPMENT_RESTORE_SECRET_SERVICE_IDENTITY_ID:-}"
restore_secret_reference_id="${GEO_DEVELOPMENT_RESTORE_SECRET_REFERENCE_ID:-}"
restore_secret_project_id="${GEO_DEVELOPMENT_RESTORE_SECRET_PROJECT_ID:-}"
restore_secret_purpose="${GEO_DEVELOPMENT_RESTORE_SECRET_PURPOSE:-}"
restore_secret_version="${GEO_DEVELOPMENT_RESTORE_SECRET_VERSION:-}"
restore_secret_idempotency_key="${GEO_DEVELOPMENT_RESTORE_SECRET_IDEMPOTENCY_KEY:-}"
provider_artifact_keyring_input="${GEO_DEVELOPMENT_PROVIDER_ARTIFACT_KEYRING_FILE:-}"
synthetic_artifact_keyring_input="${GEO_DEVELOPMENT_SYNTHETIC_ARTIFACT_KEYRING_FILE:-}"
recommendation_artifact_keyring_input="${GEO_DEVELOPMENT_RECOMMENDATION_ARTIFACT_KEYRING_FILE:-}"
workflow_c_artifact_keyring_input="${GEO_DEVELOPMENT_WORKFLOW_C_ARTIFACT_KEYRING_FILE:-}"
if [[ ! "$source_database" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ \
  || ! "$source_bucket" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ \
  || ! "$recommendation_source_bucket" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ \
  || ! "$workflow_c_source_bucket" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ \
  || ! "$synthetic_raw_source_bucket" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ \
  || ! "$synthetic_derived_source_bucket" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ \
  || -z "$secret_store_keyring_input" || ! -f "$secret_store_keyring_input" \
  || -L "$secret_store_keyring_input" \
  || -z "$secret_store_request_hash_key_input" || ! -f "$secret_store_request_hash_key_input" \
  || -L "$secret_store_request_hash_key_input" \
  || -z "$provider_artifact_keyring_input" || ! -f "$provider_artifact_keyring_input" \
  || -L "$provider_artifact_keyring_input" \
  || -z "$synthetic_artifact_keyring_input" || ! -f "$synthetic_artifact_keyring_input" \
  || -L "$synthetic_artifact_keyring_input" \
  || -z "$recommendation_artifact_keyring_input" || ! -f "$recommendation_artifact_keyring_input" \
  || -L "$recommendation_artifact_keyring_input" \
  || -z "$workflow_c_artifact_keyring_input" || ! -f "$workflow_c_artifact_keyring_input" \
  || -L "$workflow_c_artifact_keyring_input" \
  || ! "$restore_secret_service_identity_id" =~ ^[0-9a-fA-F-]{36}$ \
  || ! "$restore_secret_reference_id" =~ ^[0-9a-fA-F-]{36}$ \
  || ! "$restore_secret_project_id" =~ ^[0-9a-fA-F-]{36}$ \
  || ! "$restore_secret_purpose" =~ ^[a-z][a-z0-9_.-]{0,127}$ \
  || ! "$restore_secret_version" =~ ^[1-9][0-9]*$ \
  || ! "$restore_secret_idempotency_key" =~ ^[^[:space:]]{8,256}$ ]]; then
  echo "development backup error: isolated source, Secret Store HMAC, and frozen resolve canary are required" >&2
  exit 2
fi
if [[ "$source_bucket" != "geo-artifacts" \
  || "$recommendation_source_bucket" != "geo-restricted-recommendation-artifacts" \
  || "$workflow_c_source_bucket" != "geo-restricted-workflow-c-artifacts" ]]; then
  echo "development backup error: isolated source bucket identities are invalid" >&2
  exit 2
fi
if [[ "$synthetic_raw_source_bucket" != "geo-synthetic-style-raw" \
  || "$synthetic_derived_source_bucket" != "geo-synthetic-style-derived" ]]; then
  echo "development backup error: isolated Synthetic source bucket identities are invalid" >&2
  exit 2
fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
bucket_stamp="$(printf '%s' "$stamp" | tr '[:upper:]' '[:lower:]')"
output="$output_root/$stamp"
bundle="$output/bundle"
restore_database="geo_restore_smoke_${bucket_stamp//[^[:alnum:]_]/_}"
restore_bucket="geo-restore-smoke-$bucket_stamp"
restore_recommendation_bucket="geo-restore-recommendation-$bucket_stamp"
restore_workflow_c_bucket="geo-restore-workflow-c-$bucket_stamp"
restore_synthetic_raw_bucket="geo-restore-synthetic-raw-$bucket_stamp"
restore_synthetic_derived_bucket="geo-restore-synthetic-derived-$bucket_stamp"
development_tmpfs_root="${GEO_DEVELOPMENT_RESTORE_TMPFS_ROOT:-/dev/shm}"
if [[ ! -d "$development_tmpfs_root" || -L "$development_tmpfs_root" \
  || "$(stat -f -c '%T' -- "$development_tmpfs_root")" != "tmpfs" ]]; then
  echo "development backup error: temporary key and plaintext root must be tmpfs" >&2
  exit 2
fi
secret_root="$(mktemp -d "$development_tmpfs_root/geo-dev-backup-key.XXXXXXXX")"
plaintext_root="$(mktemp -d "$development_tmpfs_root/geo-dev-restore.XXXXXXXX")"
keyring="$secret_root/backup-keyring.json"
secret_store_keyring="$secret_root/secret-store-keyring.json"
secret_store_request_hash_key="$secret_root/secret-store-request-hash-key"
provider_artifact_keyring="$secret_root/provider-artifact-keyring.json"
synthetic_artifact_keyring="$secret_root/synthetic-artifact-keyring.json"
recommendation_artifact_keyring="$secret_root/recommendation-artifact-keyring.json"
workflow_c_artifact_keyring="$secret_root/workflow-c-artifact-keyring.json"
wrong_secret_store_keyring="$secret_root/wrong-secret-store-keyring.json"
wrong_secret_store_request_hash_key="$secret_root/wrong-secret-store-request-hash-key"
wrong_provider_artifact_keyring="$secret_root/wrong-provider-artifact-keyring.json"
wrong_synthetic_artifact_keyring="$secret_root/wrong-synthetic-artifact-keyring.json"
wrong_recommendation_artifact_keyring="$secret_root/wrong-recommendation-artifact-keyring.json"
wrong_workflow_c_artifact_keyring="$secret_root/wrong-workflow-c-artifact-keyring.json"
restore_password_file="$secret_root/restore-password"
smoke_completed=0

install -d -m 0700 "$output_root" "$output" "$bundle"
chmod 0700 "$secret_root" "$plaintext_root"
install -m 0600 "$secret_store_keyring_input" "$secret_store_keyring"
install -m 0600 "$secret_store_request_hash_key_input" "$secret_store_request_hash_key"
install -m 0600 "$provider_artifact_keyring_input" "$provider_artifact_keyring"
install -m 0600 "$synthetic_artifact_keyring_input" "$synthetic_artifact_keyring"
install -m 0600 "$recommendation_artifact_keyring_input" "$recommendation_artifact_keyring"
install -m 0600 "$workflow_c_artifact_keyring_input" "$workflow_c_artifact_keyring"
printf '%s' 'geo_installer_dev' >"$restore_password_file"
chmod 0600 "$restore_password_file"
uv run python -c \
  'import base64,json,os,secrets,sys; path=sys.argv[1]; payload={"active_version":1,"format":"geo-backup-keyring-v1","keys":[{"key":base64.b64encode(secrets.token_bytes(32)).decode("ascii"),"status":"encrypt_decrypt","version":1}]}; descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(descriptor,json.dumps(payload,separators=(",",":"),sort_keys=True).encode("ascii")); os.close(descriptor)' \
  "$keyring"
uv run python - \
  "$secret_store_keyring" "$wrong_secret_store_keyring" \
  "$provider_artifact_keyring" "$wrong_provider_artifact_keyring" \
  "$synthetic_artifact_keyring" "$wrong_synthetic_artifact_keyring" \
  "$recommendation_artifact_keyring" "$wrong_recommendation_artifact_keyring" \
  "$workflow_c_artifact_keyring" "$wrong_workflow_c_artifact_keyring" <<'PY'
import base64
import json
import os
from pathlib import Path
import secrets
import sys

for source_name, destination_name in zip(sys.argv[1::2], sys.argv[2::2], strict=True):
    source = json.loads(Path(source_name).read_text(encoding="ascii"))
    source["keys"] = {
        version: base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        for version in source["keys"]
    }
    descriptor = os.open(
        destination_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(
            descriptor,
            json.dumps(source, separators=(",", ":"), sort_keys=True).encode("ascii"),
        )
    finally:
        os.close(descriptor)
PY
uv run python - "$wrong_secret_store_request_hash_key" <<'PY'
import base64
import os
import secrets
import sys

descriptor = os.open(
    sys.argv[1],
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
    0o600,
)
try:
    os.write(descriptor, base64.b64encode(secrets.token_bytes(32)))
finally:
    os.close(descriptor)
PY

drop_restore_acl_canary_roles() {
  "${compose[@]}" exec -T postgres psql -X -q -v ON_ERROR_STOP=1 \
    -U geo_installer -d postgres <<'SQL' >/dev/null 2>&1 || true
REVOKE geo_restore_canary_app, geo_restore_canary_worker, geo_restore_canary_readonly FROM geo_installer;
DROP ROLE IF EXISTS geo_restore_canary_app;
DROP ROLE IF EXISTS geo_restore_canary_worker;
DROP ROLE IF EXISTS geo_restore_canary_readonly;
SQL
}

cleanup() {
  drop_restore_acl_canary_roles
  "${compose[@]}" exec -T postgres psql -U geo_installer -d postgres \
    -c "DROP DATABASE IF EXISTS $restore_database WITH (FORCE)" >/dev/null 2>&1 || true
  "${compose[@]}" exec -T minio sh -c \
    "mc alias set smoke http://127.0.0.1:9000 geo_dev geo_dev_secret >/dev/null 2>&1; \
     for bucket in $restore_bucket $restore_recommendation_bucket $restore_workflow_c_bucket $restore_synthetic_raw_bucket $restore_synthetic_derived_bucket; do \
       mc rm --recursive --force smoke/\$bucket >/dev/null 2>&1 || true; \
       mc rb smoke/\$bucket >/dev/null 2>&1 || true; \
     done" || true
  rm -rf -- "$secret_root" "$plaintext_root"
  if [[ "$smoke_completed" != "1" ]]; then
    rm -rf -- "$output"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

compose_published_port() {
  local service="$1"
  local container_port="$2"
  local binding
  local port
  binding="$("${compose[@]}" port "$service" "$container_port" | sed -n '1p')"
  if [[ ! "$binding" =~ ^(\[[^]]+\]|[^:]+):([0-9]{1,5})$ ]]; then
    echo "development backup error: $service published port is unavailable" >&2
    exit 2
  fi
  port="${BASH_REMATCH[2]}"
  if ((port < 1 || port > 65535)); then
    echo "development backup error: $service published port is invalid" >&2
    exit 2
  fi
  printf '%s' "$port"
}

# Resolve once from Compose rather than reusing a port declaration such as
# 127.0.0.1:0.  The authenticated Gate intentionally asks Docker for random
# host ports, while ordinary development keeps returning its fixed mapping.
postgres_host_port="$(compose_published_port postgres 5432)"
minio_host_port="$(compose_published_port minio 9000)"

remove_restore_copies() {
  drop_restore_acl_canary_roles
  "${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U geo_installer -d postgres \
    -c "DROP DATABASE $restore_database WITH (FORCE)" >/dev/null
  database_remaining="$("${compose[@]}" exec -T postgres psql -X -At \
    -v ON_ERROR_STOP=1 -U geo_installer -d postgres \
    -c "SELECT count(*) FROM pg_database WHERE datname = '$restore_database'")"
  [[ "$database_remaining" == "0" ]]
  "${compose[@]}" exec -T minio sh -ceu \
    "mc alias set smoke http://127.0.0.1:9000 geo_dev geo_dev_secret >/dev/null; \
     for bucket in $restore_bucket $restore_recommendation_bucket $restore_workflow_c_bucket $restore_synthetic_raw_bucket $restore_synthetic_derived_bucket; do \
       mc rm --recursive --force smoke/\$bucket >/dev/null; \
       mc rb smoke/\$bucket >/dev/null; \
       if mc stat smoke/\$bucket >/dev/null 2>&1; then exit 70; fi; \
     done"
}

pg_scalar() {
  "${compose[@]}" exec -T postgres psql -X -At -v ON_ERROR_STOP=1 \
    -U geo_installer -d "$source_database" -c "$1"
}

development_business_consistency() {
  local database="$1"
  "${compose[@]}" exec -T postgres psql -X -qAt -v ON_ERROR_STOP=1 \
    -U geo_installer -d "$database" \
    <"$repo_root/scripts/non_b_business_consistency.sql"
}

development_relation_hash() {
  local database="$1"
  local relation="$2"
  local sql
  local digest
  case "$relation" in
    projects|project_memberships|evidence_items|monitoring_reports) ;;
    *) echo "development backup error: unsupported relation hash" >&2; exit 2 ;;
  esac
  sql="COPY (SELECT row_json FROM (SELECT to_jsonb(relation_row)::text AS row_json FROM $relation AS relation_row) AS serialized_rows ORDER BY row_json COLLATE \"C\") TO STDOUT WITH (FORMAT text)"
  digest="$(
    "${compose[@]}" exec -T postgres psql -X -qAt -v ON_ERROR_STOP=1 \
      -U geo_installer -d "$database" -c "$sql" \
      | LC_ALL=C sha256sum
  )"
  digest="${digest%% *}"
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]]
  printf '%s' "$digest"
}

source_projects="$(pg_scalar 'SELECT count(*) FROM projects')"
source_tables="$(pg_scalar "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'")"
source_migration="$(pg_scalar 'SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1')"
source_non_b_business_consistency="$(development_business_consistency "$source_database")"
source_migration_ledger="$(
  uv run python "$repo_root/scripts/alembic_sql_ledger.py" create \
    --sql-dir "$repo_root/infra/db/alembic/sql" \
    --head-revision "$source_migration"
)"
source_relations="$(pg_scalar "SELECT json_build_object('evidence_items', (SELECT count(*) FROM evidence_items), 'monitoring_reports', (SELECT count(*) FROM monitoring_reports), 'project_memberships', (SELECT count(*) FROM project_memberships))::text")"
source_projects_hash="$(development_relation_hash "$source_database" projects)"
source_project_memberships_hash="$(development_relation_hash "$source_database" project_memberships)"
source_evidence_items_hash="$(development_relation_hash "$source_database" evidence_items)"
source_monitoring_reports_hash="$(development_relation_hash "$source_database" monitoring_reports)"
source_relation_hashes="$(printf \
  '{"evidence_items":"%s","monitoring_reports":"%s","project_memberships":"%s","projects":"%s"}' \
  "$source_evidence_items_hash" "$source_monitoring_reports_hash" \
  "$source_project_memberships_hash" "$source_projects_hash")"
secret_key_versions="$(pg_scalar "SELECT count(*) FROM secret_master_key_versions WHERE status <> 'retired'")"
secret_versions="$(pg_scalar 'SELECT count(*) FROM secret_versions')"
probe_target="$(pg_scalar 'SELECT count(DISTINCT master_key_version) FROM secret_versions')"
provider_artifact_key_versions="$(pg_scalar "SELECT count(*) FROM model_gateway_artifact_master_key_versions WHERE status <> 'retired'")"
provider_active_deks="$(pg_scalar "SELECT count(*) FROM model_gateway_artifact_deks WHERE status = 'active'")"
provider_recoverable_artifacts="$(pg_scalar "SELECT count(*) FROM model_gateway_artifacts AS artifact JOIN model_gateway_artifact_deks AS dek ON dek.key_ref = artifact.key_ref AND dek.project_id = artifact.project_id AND dek.artifact_id = artifact.artifact_id JOIN model_gateway_artifact_bundles AS bundle ON bundle.id = artifact.bundle_id AND bundle.project_id = artifact.project_id WHERE dek.status = 'active' AND bundle.status = 'committed'")"
provider_probe_target=0
if [[ "$provider_recoverable_artifacts" != "0" ]]; then
  provider_probe_target=1
fi
synthetic_artifact_key_versions="$(pg_scalar "SELECT count(*) FROM synthetic_lab_artifact_master_key_versions WHERE status <> 'retired'")"
synthetic_active_deks="$(pg_scalar "SELECT count(*) FROM synthetic_lab_artifact_deks WHERE status = 'active'")"
synthetic_nondeleted_artifacts="$(pg_scalar "SELECT count(*) FROM synthetic_lab_raw_artifacts WHERE lifecycle_state <> 'deleted'")"
synthetic_tier_key_artifacts="$(pg_scalar "SELECT count(*) FROM synthetic_lab_raw_artifacts WHERE lifecycle_state <> 'deleted' AND storage_tier <> 'restricted_independent_dek'")"
artifact_source_probe="$(
  GEO_DATABASE_URL="postgresql://geo_installer:geo_installer_dev@127.0.0.1:${postgres_host_port}/$source_database" \
  GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE="$synthetic_artifact_keyring" \
  GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE="$recommendation_artifact_keyring" \
  GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE="$workflow_c_artifact_keyring" \
  OBJECT_STORE_ENDPOINT="http://127.0.0.1:${minio_host_port}" \
  OBJECT_STORE_BUCKET="$source_bucket" \
  OBJECT_STORE_ACCESS_KEY=geo_dev \
  OBJECT_STORE_SECRET_KEY=geo_dev_secret \
  OBJECT_STORE_AUTO_CREATE_BUCKET=0 \
  GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_ENDPOINT="http://127.0.0.1:${minio_host_port}" \
  GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_BUCKET="$recommendation_source_bucket" \
  GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_ACCESS_KEY=geo_dev \
  GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_SECRET_KEY=geo_dev_secret \
  GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_AUTO_CREATE_BUCKET=0 \
  GEO_WORKFLOW_C_ARTIFACT_READER_ENDPOINT="http://127.0.0.1:${minio_host_port}" \
  GEO_WORKFLOW_C_ARTIFACT_READER_BUCKET="$workflow_c_source_bucket" \
  GEO_WORKFLOW_C_ARTIFACT_READER_ACCESS_KEY=geo_dev \
  GEO_WORKFLOW_C_ARTIFACT_READER_SECRET_KEY=geo_dev_secret \
  GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_ENDPOINT="http://127.0.0.1:${minio_host_port}" \
  GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_BUCKET="$synthetic_raw_source_bucket" \
  GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_ACCESS_KEY=geo_dev \
  GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_SECRET_KEY=geo_dev_secret \
  GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_AUTO_CREATE_BUCKET=0 \
  GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_ENDPOINT="http://127.0.0.1:${minio_host_port}" \
  GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_BUCKET="$synthetic_derived_source_bucket" \
  GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_ACCESS_KEY=geo_dev \
  GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_SECRET_KEY=geo_dev_secret \
  GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_AUTO_CREATE_BUCKET=0 \
  PYTHONPATH="$repo_root/apps/api:$repo_root/packages/geo_core" \
    uv run python -m geo_worker.artifact_backup_source_probe \
      --isolated-development-source
)"
artifact_probe_value() {
  uv run python -c \
    'import json,sys; value=json.loads(sys.argv[1]); [None for key in sys.argv[2].split(".") if not (value := value[key]) is None]; print(value)' \
    "$artifact_source_probe" "$1"
}
[[ "$(artifact_probe_value schema_version)" == "geo-non-b-artifact-backup-source-v1" ]]
recommendation_artifact_key_versions="$(artifact_probe_value recommendation_artifacts.master_key_version_count)"
recommendation_artifact_lineage_count="$(artifact_probe_value recommendation_artifacts.artifact_lineage_count)"
recommendation_probe_target="$(artifact_probe_value recommendation_artifacts.representative_probe_target_count)"
recommendation_source_receipt_hash="$(artifact_probe_value recommendation_artifacts.source_verification_receipt_hash)"
workflow_c_artifact_key_versions="$(artifact_probe_value workflow_c_artifacts.master_key_version_count)"
workflow_c_active_deks="$(artifact_probe_value workflow_c_artifacts.active_dek_count)"
workflow_c_recoverable_artifacts="$(artifact_probe_value workflow_c_artifacts.recoverable_artifact_count)"
workflow_c_probe_target="$(artifact_probe_value workflow_c_artifacts.representative_probe_target_count)"
workflow_c_source_receipt_hash="$(artifact_probe_value workflow_c_artifacts.source_verification_receipt_hash)"
synthetic_restricted_probe_target=0
if [[ "$synthetic_active_deks" != "0" ]]; then
  synthetic_restricted_probe_target=1
fi
synthetic_tier_probe_target=0
if [[ "$synthetic_tier_key_artifacts" != "0" ]]; then
  synthetic_tier_probe_target=1
fi

"${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U geo_installer -d "$source_database" \
  <"$repo_root/scripts/check_postgres_fk_integrity.sql" >/dev/null
"${compose[@]}" exec -T postgres pg_dump -U geo_installer -d "$source_database" \
  --clean --if-exists --no-owner \
  | gzip -9 \
  | uv run python "$repo_root/scripts/backup_envelope.py" encrypt \
      --keyring "$keyring" --backup-id "$stamp" --artifact postgres \
      --output "$bundle/postgres.sql.gz.enc" >/dev/null

mkdir -m 0700 "$plaintext_root/minio-source" "$plaintext_root/minio-source/buckets"
mkdir -m 0700 \
  "$plaintext_root/minio-source/buckets/$source_bucket" \
  "$plaintext_root/minio-source/buckets/$recommendation_source_bucket" \
  "$plaintext_root/minio-source/buckets/$workflow_c_source_bucket" \
  "$plaintext_root/minio-source/buckets/$synthetic_raw_source_bucket" \
  "$plaintext_root/minio-source/buckets/$synthetic_derived_source_bucket"
"${compose[@]}" run --rm -T --no-deps \
  --user "$(id -u):$(id -g)" \
  -e "MC_CONFIG_DIR=/tmp/mc-config" \
  -e "SOURCE_BUCKET=$source_bucket" \
  -e "RECOMMENDATION_SOURCE_BUCKET=$recommendation_source_bucket" \
  -e "WORKFLOW_C_SOURCE_BUCKET=$workflow_c_source_bucket" \
  -e "SYNTHETIC_RAW_SOURCE_BUCKET=$synthetic_raw_source_bucket" \
  -e "SYNTHETIC_DERIVED_SOURCE_BUCKET=$synthetic_derived_source_bucket" \
  -v "$plaintext_root/minio-source/buckets:/plaintext-staging" \
  --entrypoint /bin/sh minio -ceu \
  'mc alias set smoke http://minio:9000 geo_dev geo_dev_secret >/dev/null; \
   mc mirror "smoke/$SOURCE_BUCKET" "/plaintext-staging/$SOURCE_BUCKET" >/dev/null; \
   mc mirror "smoke/$RECOMMENDATION_SOURCE_BUCKET" "/plaintext-staging/$RECOMMENDATION_SOURCE_BUCKET" >/dev/null; \
   mc mirror "smoke/$WORKFLOW_C_SOURCE_BUCKET" "/plaintext-staging/$WORKFLOW_C_SOURCE_BUCKET" >/dev/null; \
   mc mirror "smoke/$SYNTHETIC_RAW_SOURCE_BUCKET" "/plaintext-staging/$SYNTHETIC_RAW_SOURCE_BUCKET" >/dev/null; \
   mc mirror "smoke/$SYNTHETIC_DERIVED_SOURCE_BUCKET" "/plaintext-staging/$SYNTHETIC_DERIVED_SOURCE_BUCKET" >/dev/null'
(cd "$plaintext_root/minio-source" && find buckets -type f -exec sha256sum {} \; | LC_ALL=C sort >objects.sha256)
source_primary_objects="$(find "$plaintext_root/minio-source/buckets/$source_bucket" -type f | wc -l | tr -d ' ')"
source_recommendation_objects="$(find "$plaintext_root/minio-source/buckets/$recommendation_source_bucket" -type f | wc -l | tr -d ' ')"
source_workflow_c_objects="$(find "$plaintext_root/minio-source/buckets/$workflow_c_source_bucket" -type f | wc -l | tr -d ' ')"
source_synthetic_raw_objects="$(find "$plaintext_root/minio-source/buckets/$synthetic_raw_source_bucket" -type f | wc -l | tr -d ' ')"
source_synthetic_derived_objects="$(find "$plaintext_root/minio-source/buckets/$synthetic_derived_source_bucket" -type f | wc -l | tr -d ' ')"
source_objects="$((source_primary_objects + source_recommendation_objects + source_workflow_c_objects + source_synthetic_raw_objects + source_synthetic_derived_objects))"
source_bucket_object_counts="$(printf \
  '{"geo-artifacts":%s,"geo-restricted-recommendation-artifacts":%s,"geo-restricted-workflow-c-artifacts":%s,"geo-synthetic-style-raw":%s,"geo-synthetic-style-derived":%s}' \
  "$source_primary_objects" "$source_recommendation_objects" \
  "$source_workflow_c_objects" "$source_synthetic_raw_objects" \
  "$source_synthetic_derived_objects")"
tar -C "$plaintext_root/minio-source" -cf - buckets objects.sha256 \
  | uv run python "$repo_root/scripts/backup_envelope.py" encrypt \
      --keyring "$keyring" --backup-id "$stamp" --artifact minio \
      --output "$bundle/minio.tar.enc" >/dev/null
rm -rf -- "$plaintext_root/minio-source"
source_migration_ledger_after_backup="$(
  uv run python "$repo_root/scripts/alembic_sql_ledger.py" create \
    --sql-dir "$repo_root/infra/db/alembic/sql" \
    --head-revision "$source_migration"
)"
if [[ "$source_migration_ledger_after_backup" != "$source_migration_ledger" ]]; then
  echo "development backup error: Alembic SQL changed during backup" >&2
  exit 2
fi

uv run python "$repo_root/scripts/backup_manifest.py" create \
  --keyring "$keyring" --backup-dir "$bundle" --backup-id "$stamp" \
  --created-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --migration-revision "$source_migration" \
  --alembic-sql-checksum-ledger-json "$source_migration_ledger" \
  --postgres-project-count "$source_projects" --postgres-table-count "$source_tables" \
  --critical-relation-counts-json "$source_relations" \
  --critical-relation-hashes-json "$source_relation_hashes" \
  --non-b-business-consistency-json "$source_non_b_business_consistency" \
  --minio-object-count "$source_objects" \
  --minio-bucket-object-counts-json "$source_bucket_object_counts" \
  --secret-key-version-count "$secret_key_versions" \
  --secret-version-count "$secret_versions" \
  --representative-probe-target-count "$probe_target" \
  --provider-artifact-key-version-count "$provider_artifact_key_versions" \
  --provider-active-dek-count "$provider_active_deks" \
  --provider-recoverable-artifact-count "$provider_recoverable_artifacts" \
  --provider-representative-probe-target-count "$provider_probe_target" \
  --synthetic-artifact-key-version-count "$synthetic_artifact_key_versions" \
  --synthetic-active-dek-count "$synthetic_active_deks" \
  --synthetic-nondeleted-artifact-count "$synthetic_nondeleted_artifacts" \
  --synthetic-tier-key-artifact-count "$synthetic_tier_key_artifacts" \
  --synthetic-restricted-probe-target-count "$synthetic_restricted_probe_target" \
  --synthetic-tier-probe-target-count "$synthetic_tier_probe_target" \
  --recommendation-artifact-key-version-count "$recommendation_artifact_key_versions" \
  --recommendation-artifact-lineage-count "$recommendation_artifact_lineage_count" \
  --recommendation-representative-probe-target-count "$recommendation_probe_target" \
  --recommendation-source-verification-receipt-hash "$recommendation_source_receipt_hash" \
  --workflow-c-artifact-key-version-count "$workflow_c_artifact_key_versions" \
  --workflow-c-active-dek-count "$workflow_c_active_deks" \
  --workflow-c-recoverable-artifact-count "$workflow_c_recoverable_artifacts" \
  --workflow-c-representative-probe-target-count "$workflow_c_probe_target" \
  --workflow-c-source-verification-receipt-hash "$workflow_c_source_receipt_hash" \
  >/dev/null
uv run python "$repo_root/scripts/backup_manifest.py" verify \
  --keyring "$keyring" --backup-dir "$bundle" >/dev/null

"${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U geo_installer -d postgres \
  -c "CREATE DATABASE $restore_database" >/dev/null
uv run python "$repo_root/scripts/backup_manifest.py" decrypt \
  --keyring "$keyring" --backup-dir "$bundle" --artifact postgres \
  --staging-dir "$plaintext_root" \
  | gzip -dc \
  | "${compose[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 \
      -U geo_installer -d "$restore_database" >/dev/null

restore_scalar() {
  "${compose[@]}" exec -T postgres psql -X -At -v ON_ERROR_STOP=1 \
    -U geo_installer -d "$restore_database" -c "$1"
}
restored_projects="$(restore_scalar 'SELECT count(*) FROM projects')"
restored_tables="$(restore_scalar "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'")"
restored_migration="$(restore_scalar 'SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1')"
restored_non_b_business_consistency="$(development_business_consistency "$restore_database")"
restored_migration_ledger="$(
  uv run python "$repo_root/scripts/alembic_sql_ledger.py" verify \
    --sql-dir "$repo_root/infra/db/alembic/sql" \
    --ledger-json "$source_migration_ledger"
)"
restored_relations="$(restore_scalar "SELECT json_build_object('evidence_items', (SELECT count(*) FROM evidence_items), 'monitoring_reports', (SELECT count(*) FROM monitoring_reports), 'project_memberships', (SELECT count(*) FROM project_memberships))::text")"
restored_projects_hash="$(development_relation_hash "$restore_database" projects)"
restored_project_memberships_hash="$(development_relation_hash "$restore_database" project_memberships)"
restored_evidence_items_hash="$(development_relation_hash "$restore_database" evidence_items)"
restored_monitoring_reports_hash="$(development_relation_hash "$restore_database" monitoring_reports)"
restored_relation_hashes="$(printf \
  '{"evidence_items":"%s","monitoring_reports":"%s","project_memberships":"%s","projects":"%s"}' \
  "$restored_evidence_items_hash" "$restored_monitoring_reports_hash" \
  "$restored_project_memberships_hash" "$restored_projects_hash")"
[[ "$source_projects" == "$restored_projects" ]]
[[ "$source_tables" == "$restored_tables" ]]
[[ "$source_migration" == "$restored_migration" ]]
uv run python -c 'import json,sys; raise SystemExit(0 if json.loads(sys.argv[1]) == json.loads(sys.argv[2]) else 2)' "$source_relations" "$restored_relations"
uv run python -c 'import json,sys; raise SystemExit(0 if json.loads(sys.argv[1]) == json.loads(sys.argv[2]) else 2)' "$source_relation_hashes" "$restored_relation_hashes"
"${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U geo_installer \
  -d "$restore_database" <"$repo_root/scripts/check_postgres_fk_integrity.sql" >/dev/null

restore_project_id="$(restore_scalar 'SELECT id FROM projects ORDER BY id LIMIT 1')"
if [[ ! "$restore_project_id" =~ ^[0-9a-fA-F-]{36}$ ]]; then
  echo "development backup error: a restored Project is required for ACL/RLS verification" >&2
  exit 2
fi
"${compose[@]}" exec -T postgres psql -X -q -v ON_ERROR_STOP=1 \
  -U geo_installer -d "$restore_database" <<'SQL'
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
        EXECUTE format('GRANT %I TO geo_installer', role_name);
    END LOOP;
END;
$$;
SQL
acl_rls_evidence="$plaintext_root/acl-rls-canary.txt"
for role_group in \
  'geo_restore_canary_app:geo_app' \
  'geo_restore_canary_worker:geo_worker' \
  'geo_restore_canary_readonly:geo_readonly'; do
  IFS=: read -r canary_role canary_group <<<"$role_group"
  "${compose[@]}" exec -T postgres psql -X -qAt -F "|" -v ON_ERROR_STOP=1 \
    -U geo_installer -d "$restore_database" <<SQL >>"$acl_rls_evidence"
BEGIN;
SET LOCAL ROLE $canary_role;
SET LOCAL geo.project_ids = '["$restore_project_id"]';
-- The canary remains NOINHERIT.  Verify its restricted attributes first, then
-- explicitly activate the restored least-privilege group to test its grants.
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
acl_rls_receipt="$plaintext_root/acl-rls-canary.json"
uv run python "$repo_root/scripts/write_restore_acl_rls_canary.py" \
  --project-id "$restore_project_id" \
  --evidence "$acl_rls_evidence" \
  --output "$acl_rls_receipt" >/dev/null

uv run python "$repo_root/scripts/backup_manifest.py" decrypt \
  --keyring "$keyring" --backup-dir "$bundle" --artifact minio \
  --staging-dir "$plaintext_root" >"$plaintext_root/minio.tar"
chmod 0600 "$plaintext_root/minio.tar"
mkdir -m 0700 "$plaintext_root/minio-restored"
uv run python "$repo_root/scripts/verify_minio_backup.py" \
  --archive "$plaintext_root/minio.tar" --destination "$plaintext_root/minio-restored" \
  --expected-object-count "$source_objects" \
  --expected-bucket-object-counts-json "$source_bucket_object_counts" \
  >"$plaintext_root/minio-verification.json"
chmod 0600 "$plaintext_root/minio-verification.json"

run_application_key_probe() {
  local secret_keyring="$1"
  local request_hash_key="$2"
  local provider_keyring="$3"
  local synthetic_keyring="$4"
  local recommendation_keyring="$5"
  local workflow_c_keyring="$6"
  PYTHONPATH="$repo_root/apps/api:$repo_root/packages/geo_core" \
    uv run python -m geo_worker.backup_restore_probe \
      --database-password-file "$restore_password_file" \
      --database-host 127.0.0.1 \
      --database-port "$postgres_host_port" \
      --database-user geo_installer \
      --database-name "$restore_database" \
      --secret-store-keyring "$secret_keyring" \
      --secret-store-request-hash-key "$request_hash_key" \
      --secret-store-service-identity-id "$restore_secret_service_identity_id" \
      --secret-store-frozen-reference-id "$restore_secret_reference_id" \
      --secret-store-frozen-project-id "$restore_secret_project_id" \
      --secret-store-frozen-purpose "$restore_secret_purpose" \
      --secret-store-frozen-version "$restore_secret_version" \
      --secret-store-resolve-idempotency-key "$restore_secret_idempotency_key" \
      --provider-artifact-keyring "$provider_keyring" \
      --synthetic-artifact-keyring "$synthetic_keyring" \
      --recommendation-artifact-keyring "$recommendation_keyring" \
      --workflow-c-artifact-keyring "$workflow_c_keyring" \
      --object-root "$plaintext_root/minio-restored/buckets/geo-artifacts" \
      --object-bucket "$source_bucket" \
      --recommendation-object-root "$plaintext_root/minio-restored/buckets/geo-restricted-recommendation-artifacts" \
      --recommendation-object-bucket "$recommendation_source_bucket" \
      --workflow-c-object-root "$plaintext_root/minio-restored/buckets/geo-restricted-workflow-c-artifacts" \
      --workflow-c-object-bucket "$workflow_c_source_bucket" \
      --synthetic-raw-object-root "$plaintext_root/minio-restored/buckets/geo-synthetic-style-raw" \
      --synthetic-raw-object-bucket "$synthetic_raw_source_bucket" \
      --synthetic-derived-object-root "$plaintext_root/minio-restored/buckets/geo-synthetic-style-derived" \
      --synthetic-derived-object-bucket "$synthetic_derived_source_bucket"
}

run_application_key_probe \
  "$secret_store_keyring" "$secret_store_request_hash_key" "$provider_artifact_keyring" \
  "$synthetic_artifact_keyring" "$recommendation_artifact_keyring" \
  "$workflow_c_artifact_keyring" >"$plaintext_root/application-key-probe.json"
chmod 0600 "$plaintext_root/application-key-probe.json"

assert_probe_rejected() {
  local label="$1"
  shift
  set +e
  run_application_key_probe "$@" >/dev/null 2>&1
  local status=$?
  set -e
  if [[ "$status" != "2" ]]; then
    echo "development backup error: $label rejection is inconclusive" >&2
    exit 2
  fi
}

assert_probe_rejected "wrong Secret Store key" \
  "$wrong_secret_store_keyring" "$secret_store_request_hash_key" "$provider_artifact_keyring" \
  "$synthetic_artifact_keyring" "$recommendation_artifact_keyring" \
  "$workflow_c_artifact_keyring"
assert_probe_rejected "wrong Provider artifact key" \
  "$secret_store_keyring" "$secret_store_request_hash_key" "$wrong_provider_artifact_keyring" \
  "$synthetic_artifact_keyring" "$recommendation_artifact_keyring" \
  "$workflow_c_artifact_keyring"
assert_probe_rejected "wrong Synthetic artifact key" \
  "$secret_store_keyring" "$secret_store_request_hash_key" "$provider_artifact_keyring" \
  "$wrong_synthetic_artifact_keyring" "$recommendation_artifact_keyring" \
  "$workflow_c_artifact_keyring"
assert_probe_rejected "missing Provider artifact keyring" \
  "$secret_store_keyring" "$secret_store_request_hash_key" "$secret_root/missing-provider-keyring.json" \
  "$synthetic_artifact_keyring" "$recommendation_artifact_keyring" \
  "$workflow_c_artifact_keyring"
assert_probe_rejected "wrong Recommendation artifact key" \
  "$secret_store_keyring" "$secret_store_request_hash_key" "$provider_artifact_keyring" \
  "$synthetic_artifact_keyring" "$wrong_recommendation_artifact_keyring" \
  "$workflow_c_artifact_keyring"
assert_probe_rejected "missing Recommendation artifact keyring" \
  "$secret_store_keyring" "$secret_store_request_hash_key" "$provider_artifact_keyring" \
  "$synthetic_artifact_keyring" "$secret_root/missing-recommendation-keyring.json" \
  "$workflow_c_artifact_keyring"
assert_probe_rejected "wrong Workflow C artifact key" \
  "$secret_store_keyring" "$secret_store_request_hash_key" "$provider_artifact_keyring" \
  "$synthetic_artifact_keyring" "$recommendation_artifact_keyring" \
  "$wrong_workflow_c_artifact_keyring"
assert_probe_rejected "missing Workflow C artifact keyring" \
  "$secret_store_keyring" "$secret_store_request_hash_key" "$provider_artifact_keyring" \
  "$synthetic_artifact_keyring" "$recommendation_artifact_keyring" \
  "$secret_root/missing-workflow-c-keyring.json"
assert_probe_rejected "wrong Secret Store request HMAC" \
  "$secret_store_keyring" "$wrong_secret_store_request_hash_key" "$provider_artifact_keyring" \
  "$synthetic_artifact_keyring" "$recommendation_artifact_keyring" \
  "$workflow_c_artifact_keyring"
assert_probe_rejected "missing Secret Store request HMAC" \
  "$secret_store_keyring" "$secret_root/missing-request-hash-key" "$provider_artifact_keyring" \
  "$synthetic_artifact_keyring" "$recommendation_artifact_keyring" \
  "$workflow_c_artifact_keyring"

"${compose[@]}" run --rm -T --no-deps \
  --user "$(id -u):$(id -g)" \
  -e "MC_CONFIG_DIR=/tmp/mc-config" \
  -e "RESTORE_BUCKET=$restore_bucket" \
  -e "RESTORE_RECOMMENDATION_BUCKET=$restore_recommendation_bucket" \
  -e "RESTORE_WORKFLOW_C_BUCKET=$restore_workflow_c_bucket" \
  -e "RESTORE_SYNTHETIC_RAW_BUCKET=$restore_synthetic_raw_bucket" \
  -e "RESTORE_SYNTHETIC_DERIVED_BUCKET=$restore_synthetic_derived_bucket" \
  -v "$plaintext_root/minio-restored/buckets/geo-artifacts:/primary:ro" \
  -v "$plaintext_root/minio-restored/buckets/geo-restricted-recommendation-artifacts:/recommendation:ro" \
  -v "$plaintext_root/minio-restored/buckets/geo-restricted-workflow-c-artifacts:/workflow-c:ro" \
  -v "$plaintext_root/minio-restored/buckets/geo-synthetic-style-raw:/synthetic-raw:ro" \
  -v "$plaintext_root/minio-restored/buckets/geo-synthetic-style-derived:/synthetic-derived:ro" \
  --entrypoint /bin/sh minio -ceu \
  'mc alias set smoke http://minio:9000 geo_dev geo_dev_secret >/dev/null; \
   mc mb "smoke/$RESTORE_BUCKET" >/dev/null; \
   mc mb "smoke/$RESTORE_RECOMMENDATION_BUCKET" >/dev/null; \
   mc mb "smoke/$RESTORE_WORKFLOW_C_BUCKET" >/dev/null; \
   mc mb "smoke/$RESTORE_SYNTHETIC_RAW_BUCKET" >/dev/null; \
   mc mb "smoke/$RESTORE_SYNTHETIC_DERIVED_BUCKET" >/dev/null; \
   mc mirror /primary "smoke/$RESTORE_BUCKET" >/dev/null; \
   mc mirror /recommendation "smoke/$RESTORE_RECOMMENDATION_BUCKET" >/dev/null; \
   mc mirror /workflow-c "smoke/$RESTORE_WORKFLOW_C_BUCKET" >/dev/null; \
   mc mirror /synthetic-raw "smoke/$RESTORE_SYNTHETIC_RAW_BUCKET" >/dev/null; \
   mc mirror /synthetic-derived "smoke/$RESTORE_SYNTHETIC_DERIVED_BUCKET" >/dev/null'
mkdir -m 0700 "$plaintext_root/minio-roundtrip" "$plaintext_root/minio-roundtrip/buckets"
mkdir -m 0700 \
  "$plaintext_root/minio-roundtrip/buckets/geo-artifacts" \
  "$plaintext_root/minio-roundtrip/buckets/geo-restricted-recommendation-artifacts" \
  "$plaintext_root/minio-roundtrip/buckets/geo-restricted-workflow-c-artifacts" \
  "$plaintext_root/minio-roundtrip/buckets/geo-synthetic-style-raw" \
  "$plaintext_root/minio-roundtrip/buckets/geo-synthetic-style-derived"
"${compose[@]}" run --rm -T --no-deps \
  --user "$(id -u):$(id -g)" \
  -e "MC_CONFIG_DIR=/tmp/mc-config" \
  -e "RESTORE_BUCKET=$restore_bucket" \
  -e "RESTORE_RECOMMENDATION_BUCKET=$restore_recommendation_bucket" \
  -e "RESTORE_WORKFLOW_C_BUCKET=$restore_workflow_c_bucket" \
  -e "RESTORE_SYNTHETIC_RAW_BUCKET=$restore_synthetic_raw_bucket" \
  -e "RESTORE_SYNTHETIC_DERIVED_BUCKET=$restore_synthetic_derived_bucket" \
  -v "$plaintext_root/minio-roundtrip/buckets:/plaintext-staging" \
  --entrypoint /bin/sh minio -ceu \
  'mc alias set smoke http://minio:9000 geo_dev geo_dev_secret >/dev/null; \
   mc mirror "smoke/$RESTORE_BUCKET" /plaintext-staging/geo-artifacts >/dev/null; \
   mc mirror "smoke/$RESTORE_RECOMMENDATION_BUCKET" /plaintext-staging/geo-restricted-recommendation-artifacts >/dev/null; \
   mc mirror "smoke/$RESTORE_WORKFLOW_C_BUCKET" /plaintext-staging/geo-restricted-workflow-c-artifacts >/dev/null; \
   mc mirror "smoke/$RESTORE_SYNTHETIC_RAW_BUCKET" /plaintext-staging/geo-synthetic-style-raw >/dev/null; \
   mc mirror "smoke/$RESTORE_SYNTHETIC_DERIVED_BUCKET" /plaintext-staging/geo-synthetic-style-derived >/dev/null'
(cd "$plaintext_root/minio-restored/buckets" && find . -type f -exec sha256sum {} \; | sort) >"$plaintext_root/source.sha256"
(cd "$plaintext_root/minio-roundtrip/buckets" && find . -type f -exec sha256sum {} \; | sort) >"$plaintext_root/restored.sha256"
diff -u "$plaintext_root/source.sha256" "$plaintext_root/restored.sha256"
restored_objects="$(find "$plaintext_root/minio-roundtrip/buckets" -type f | wc -l | tr -d ' ')"
[[ "$source_objects" == "$restored_objects" ]]

remove_restore_copies
receipt_candidate="$plaintext_root/production-receipt.json"
uv run python "$repo_root/scripts/write_backup_restore_receipt.py" \
  --verified-manifest "$bundle/manifest.json" \
  --application-key-probe "$plaintext_root/application-key-probe.json" \
  --acl-rls-canary "$acl_rls_receipt" \
  --minio-verification "$plaintext_root/minio-verification.json" \
  --output "$receipt_candidate" \
  --restored-project-count "$restored_projects" \
  --restored-table-count "$restored_tables" \
  --restored-migration-revision "$restored_migration" \
  --restored-alembic-sql-checksum-ledger-json "$restored_migration_ledger" \
  --restored-critical-relation-counts-json "$restored_relations" \
  --restored-critical-relation-hashes-json "$restored_relation_hashes" \
  --restored-non-b-business-consistency-json "$restored_non_b_business_consistency" \
  >/dev/null
production_receipt_payload="$(<"$receipt_candidate")"
rm -rf -- "$plaintext_root" "$secret_root"
[[ ! -e "$plaintext_root" && ! -e "$secret_root" ]]
uv run python - "$output/receipt.json" "$stamp" "$production_receipt_payload" <<'PY'
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

from scripts.backup_envelope import atomic_write, canonical_json

output, backup_id, production_receipt = sys.argv[1:]
receipt = {
    "backup_id": backup_id,
    "encrypted_bundle": True,
    "ephemeral_backup_key_destroyed": True,
    "negative_key_tests": {
        "missing_provider_keyring_rejected": True,
        "missing_recommendation_keyring_rejected": True,
        "missing_workflow_c_keyring_rejected": True,
        "wrong_provider_key_rejected": True,
        "wrong_secret_store_key_rejected": True,
        "wrong_secret_store_request_hmac_rejected": True,
        "missing_secret_store_request_hmac_rejected": True,
        "wrong_synthetic_key_rejected": True,
        "wrong_recommendation_key_rejected": True,
        "wrong_workflow_c_key_rejected": True,
    },
    "production_equivalent_restore_receipt": json.loads(production_receipt),
    "restore_copy_removed": True,
    "schema_version": "geo-development-backup-restore-smoke-v6",
    "verified_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
}
atomic_write(Path(output), canonical_json(receipt) + b"\n")
PY
smoke_completed=1

echo "development authenticated backup/restore smoke passed: $output"
