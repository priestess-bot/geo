#!/bin/sh
set -eu
umask 077

export MC_CONFIG_DIR="${MC_CONFIG_DIR:-/tmp/geo-minio-bootstrap-mc}"
trap 'rm -rf "$MC_CONFIG_DIR" /tmp/geo-minio-bootstrap' EXIT
mkdir -p /tmp/geo-minio-bootstrap "${MINIO_BOOTSTRAP_RECEIPT_DIR:-/receipts}"

read_secret() {
  value="$(printenv "$1" 2>/dev/null || true)"
  path="$(printenv "$2" 2>/dev/null || true)"
  if [ -n "$value" ] && [ -n "$path" ]; then
    echo "$1 and $2 cannot both be configured" >&2
    exit 1
  fi
  if [ -n "$path" ]; then
    if [ ! -r "$path" ]; then
      echo "$2 is not readable" >&2
      exit 1
    fi
    value="$(cat "$path")"
  fi
  if [ -z "$value" ]; then
    echo "$1 or $2 is required" >&2
    exit 1
  fi
  printf '%s' "$value"
}

require_safe_name() {
  case "$2" in
    ""|*[!A-Za-z0-9._-]*)
      echo "$1 contains unsupported characters" >&2
      exit 1
      ;;
  esac
}

require_safe_prefix() {
  case "$2" in
    ""|/*|*..*|*[!A-Za-z0-9._/-]*|*[!/])
      echo "$1 must be a relative, trailing-slash object prefix" >&2
      exit 1
      ;;
  esac
}

file_sha256() {
  set -- $(sha256sum "$1")
  printf '%s' "$1"
}

files_match_sha256() {
  test "$(file_sha256 "$1")" = "$(file_sha256 "$2")"
}

endpoint="${MINIO_ENDPOINT:-http://minio:9000}"
reports_bucket="${OBJECT_STORE_BUCKET:-geo-reports}"
workflow_c_bucket="${GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_BUCKET:-geo-restricted-workflow-c-artifacts}"
recommendation_bucket="${GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_BUCKET:-geo-restricted-recommendation-artifacts}"
synthetic_raw_bucket="${GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_BUCKET:-geo-synthetic-style-raw}"
synthetic_derived_bucket="${GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_BUCKET:-geo-synthetic-style-derived}"
backup_bucket="${OBJECT_STORE_BACKUP_BUCKET:-geo-backups}"
backup_prefix="${OBJECT_STORE_BACKUP_PREFIX:-production/local/}"
smoke_prefix="${OBJECT_STORE_BACKUP_SMOKE_PREFIX:-smoke/local/}"
restore_prefix="${OBJECT_STORE_RESTORE_PREFIX:-restore-smoke/local/}"
retention_prefix="${OBJECT_STORE_RETENTION_PREFIX:-retention-approved/local/}"
policy_version="${MINIO_POLICY_VERSION:-geo-object-store-policy-v1}"
receipt_dir="${MINIO_BOOTSTRAP_RECEIPT_DIR:-/receipts}"
action="${MINIO_BOOTSTRAP_ACTION:-provision}"

require_safe_name OBJECT_STORE_BUCKET "$reports_bucket"
require_safe_name GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_BUCKET "$workflow_c_bucket"
require_safe_name GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_BUCKET "$recommendation_bucket"
require_safe_name GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_BUCKET "$synthetic_raw_bucket"
require_safe_name GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_BUCKET "$synthetic_derived_bucket"
require_safe_name OBJECT_STORE_BACKUP_BUCKET "$backup_bucket"
require_safe_prefix OBJECT_STORE_BACKUP_PREFIX "$backup_prefix"
require_safe_prefix OBJECT_STORE_BACKUP_SMOKE_PREFIX "$smoke_prefix"
require_safe_prefix OBJECT_STORE_RESTORE_PREFIX "$restore_prefix"
require_safe_prefix OBJECT_STORE_RETENTION_PREFIX "$retention_prefix"
require_safe_name MINIO_POLICY_VERSION "$policy_version"
if [ "$recommendation_bucket" = "$reports_bucket" ] || \
   [ "$recommendation_bucket" = "$workflow_c_bucket" ] || \
   [ "$recommendation_bucket" = "$synthetic_raw_bucket" ] || \
   [ "$recommendation_bucket" = "$synthetic_derived_bucket" ] || \
   [ "$synthetic_raw_bucket" = "$synthetic_derived_bucket" ] || \
   [ "$synthetic_raw_bucket" = "$reports_bucket" ] || \
   [ "$synthetic_derived_bucket" = "$reports_bucket" ] || \
   [ "$synthetic_raw_bucket" = "$workflow_c_bucket" ] || \
   [ "$synthetic_derived_bucket" = "$workflow_c_bucket" ]; then
  echo "Restricted artifact buckets must be isolated from every other bucket" >&2
  exit 1
fi

root_user="$(read_secret MINIO_ROOT_USER MINIO_ROOT_USER_FILE)"
root_password="$(read_secret MINIO_ROOT_PASSWORD MINIO_ROOT_PASSWORD_FILE)"

until mc alias set root "$endpoint" "$root_user" "$root_password" >/dev/null 2>&1; do
  sleep 1
done

restore_user="$(read_secret OBJECT_STORE_RESTORE_ACCESS_KEY OBJECT_STORE_RESTORE_ACCESS_KEY_FILE)"
retention_user="$(read_secret OBJECT_STORE_RETENTION_ACCESS_KEY OBJECT_STORE_RETENTION_ACCESS_KEY_FILE)"
restore_password="$(read_secret OBJECT_STORE_RESTORE_SECRET_KEY OBJECT_STORE_RESTORE_SECRET_KEY_FILE)"
retention_password="$(read_secret OBJECT_STORE_RETENTION_SECRET_KEY OBJECT_STORE_RETENTION_SECRET_KEY_FILE)"

if [ "$action" = "cleanup-ephemeral" ]; then
  mc admin user remove root "$restore_user" >/dev/null 2>&1 || true
  mc admin user remove root "$retention_user" >/dev/null 2>&1 || true
  mc alias set revoked-restore "$endpoint" "$restore_user" "$restore_password" >/dev/null 2>&1 || true
  mc alias set revoked-retention "$endpoint" "$retention_user" "$retention_password" >/dev/null 2>&1 || true
  if mc ls "revoked-restore/$backup_bucket/$smoke_prefix" >/dev/null 2>&1; then
    echo "Revoked restore principal retained object access" >&2
    exit 1
  fi
  if mc ls "revoked-retention/$reports_bucket/$retention_prefix" >/dev/null 2>&1; then
    echo "Revoked retention principal retained object access" >&2
    exit 1
  fi
  verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat > "$receipt_dir/ephemeral-cleanup.json" <<EOF
{"schema_version":"production-object-store-ephemeral-cleanup-v1","restore_principal_revoked":true,"retention_principal_revoked":true,"verified_at":"$verified_at"}
EOF
  echo "MinIO ephemeral restore/retention principals revoked: receipt=$receipt_dir/ephemeral-cleanup.json"
  exit 0
fi
if [ "$action" != "provision" ]; then
  echo "Unsupported MINIO_BOOTSTRAP_ACTION" >&2
  exit 1
fi

application_user="$(read_secret OBJECT_STORE_ACCESS_KEY OBJECT_STORE_ACCESS_KEY_FILE)"
application_password="$(read_secret OBJECT_STORE_SECRET_KEY OBJECT_STORE_SECRET_KEY_FILE)"
backup_user="$(read_secret OBJECT_STORE_BACKUP_ACCESS_KEY OBJECT_STORE_BACKUP_ACCESS_KEY_FILE)"
backup_password="$(read_secret OBJECT_STORE_BACKUP_SECRET_KEY OBJECT_STORE_BACKUP_SECRET_KEY_FILE)"
workflow_c_writer="$(read_secret GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_ACCESS_KEY GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_ACCESS_KEY_FILE)"
workflow_c_writer_password="$(read_secret GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_SECRET_KEY GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_SECRET_KEY_FILE)"
workflow_c_reader="$(read_secret GEO_WORKFLOW_C_ARTIFACT_READER_ACCESS_KEY GEO_WORKFLOW_C_ARTIFACT_READER_ACCESS_KEY_FILE)"
workflow_c_reader_password="$(read_secret GEO_WORKFLOW_C_ARTIFACT_READER_SECRET_KEY GEO_WORKFLOW_C_ARTIFACT_READER_SECRET_KEY_FILE)"
workflow_c_deleter="$(read_secret GEO_WORKFLOW_C_ARTIFACT_DELETER_ACCESS_KEY GEO_WORKFLOW_C_ARTIFACT_DELETER_ACCESS_KEY_FILE)"
workflow_c_deleter_password="$(read_secret GEO_WORKFLOW_C_ARTIFACT_DELETER_SECRET_KEY GEO_WORKFLOW_C_ARTIFACT_DELETER_SECRET_KEY_FILE)"
recommendation_writer="$(read_secret GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_ACCESS_KEY GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_ACCESS_KEY_FILE)"
recommendation_writer_password="$(read_secret GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_SECRET_KEY GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_SECRET_KEY_FILE)"
recommendation_deleter="$(read_secret GEO_RECOMMENDATION_ARTIFACT_DELETER_ACCESS_KEY GEO_RECOMMENDATION_ARTIFACT_DELETER_ACCESS_KEY_FILE)"
recommendation_deleter_password="$(read_secret GEO_RECOMMENDATION_ARTIFACT_DELETER_SECRET_KEY GEO_RECOMMENDATION_ARTIFACT_DELETER_SECRET_KEY_FILE)"
synthetic_style_writer="$(read_secret GEO_SYNTHETIC_STYLE_ARTIFACT_WRITER_ACCESS_KEY GEO_SYNTHETIC_STYLE_ARTIFACT_WRITER_ACCESS_KEY_FILE)"
synthetic_style_writer_password="$(read_secret GEO_SYNTHETIC_STYLE_ARTIFACT_WRITER_SECRET_KEY GEO_SYNTHETIC_STYLE_ARTIFACT_WRITER_SECRET_KEY_FILE)"
synthetic_deleter="$(read_secret GEO_SYNTHETIC_ARTIFACT_DELETER_ACCESS_KEY GEO_SYNTHETIC_ARTIFACT_DELETER_ACCESS_KEY_FILE)"
synthetic_deleter_password="$(read_secret GEO_SYNTHETIC_ARTIFACT_DELETER_SECRET_KEY GEO_SYNTHETIC_ARTIFACT_DELETER_SECRET_KEY_FILE)"
for identity in "$root_user" "$application_user" "$backup_user" "$restore_user" "$retention_user" "$workflow_c_writer" "$workflow_c_reader" "$workflow_c_deleter" "$recommendation_writer" "$recommendation_deleter" "$synthetic_style_writer" "$synthetic_deleter"; do
  require_safe_name object_store_identity "$identity"
done
if [ -n "$(printf '%s\n' "$root_user" "$application_user" "$backup_user" "$restore_user" "$retention_user" "$workflow_c_writer" "$workflow_c_reader" "$workflow_c_deleter" "$recommendation_writer" "$recommendation_deleter" "$synthetic_style_writer" "$synthetic_deleter" | LC_ALL=C sort | uniq -d)" ]; then
  echo "MinIO identities must be distinct" >&2
  exit 1
fi

mc mb --ignore-existing "root/$reports_bucket" >/dev/null
mc mb --ignore-existing "root/$backup_bucket" >/dev/null
mc mb --ignore-existing "root/$workflow_c_bucket" >/dev/null
mc mb --ignore-existing "root/$recommendation_bucket" >/dev/null
mc mb --ignore-existing "root/$synthetic_raw_bucket" >/dev/null
mc mb --ignore-existing "root/$synthetic_derived_bucket" >/dev/null
mc version enable "root/$reports_bucket" >/dev/null
mc version enable "root/$backup_bucket" >/dev/null
mc version enable "root/$workflow_c_bucket" >/dev/null
mc version enable "root/$recommendation_bucket" >/dev/null
mc version enable "root/$synthetic_raw_bucket" >/dev/null
mc version enable "root/$synthetic_derived_bucket" >/dev/null
mc ilm rule import "root/$reports_bucket" < /bootstrap/reports-lifecycle.json >/dev/null
mc ilm rule import "root/$backup_bucket" < /bootstrap/backups-lifecycle.json >/dev/null

cat > /tmp/geo-minio-bootstrap/application-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation","s3:ListBucket"],"Resource":["arn:aws:s3:::$reports_bucket"]},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion","s3:PutObject"],"Resource":["arn:aws:s3:::$reports_bucket/*"]}]}
EOF
cat > /tmp/geo-minio-bootstrap/backup-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$reports_bucket","arn:aws:s3:::$workflow_c_bucket","arn:aws:s3:::$recommendation_bucket","arn:aws:s3:::$synthetic_raw_bucket","arn:aws:s3:::$synthetic_derived_bucket","arn:aws:s3:::$backup_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$reports_bucket","arn:aws:s3:::$workflow_c_bucket","arn:aws:s3:::$recommendation_bucket","arn:aws:s3:::$synthetic_raw_bucket","arn:aws:s3:::$synthetic_derived_bucket"],"Condition":{"StringLike":{"s3:prefix":["*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion"],"Resource":["arn:aws:s3:::$reports_bucket/*","arn:aws:s3:::$workflow_c_bucket/*","arn:aws:s3:::$recommendation_bucket/*","arn:aws:s3:::$synthetic_raw_bucket/*","arn:aws:s3:::$synthetic_derived_bucket/*"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$backup_bucket"],"Condition":{"StringLike":{"s3:prefix":["$backup_prefix*","$smoke_prefix*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion","s3:PutObject"],"Resource":["arn:aws:s3:::$backup_bucket/$backup_prefix*","arn:aws:s3:::$backup_bucket/$smoke_prefix*"]},{"Effect":"Allow","Action":["s3:DeleteObject","s3:DeleteObjectVersion"],"Resource":["arn:aws:s3:::$backup_bucket/$smoke_prefix*"]}]}
EOF
cat > /tmp/geo-minio-bootstrap/workflow-c-writer-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$workflow_c_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$workflow_c_bucket"],"Condition":{"StringLike":{"s3:prefix":["workflow-c/manual-evidence/*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion","s3:PutObject"],"Resource":["arn:aws:s3:::$workflow_c_bucket/workflow-c/manual-evidence/*"]}]}
EOF
cat > /tmp/geo-minio-bootstrap/workflow-c-reader-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$workflow_c_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$workflow_c_bucket"],"Condition":{"StringLike":{"s3:prefix":["workflow-c/manual-evidence/*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion"],"Resource":["arn:aws:s3:::$workflow_c_bucket/workflow-c/manual-evidence/*"]}]}
EOF
cat > /tmp/geo-minio-bootstrap/workflow-c-deleter-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$workflow_c_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$workflow_c_bucket"],"Condition":{"StringLike":{"s3:prefix":["workflow-c/manual-evidence/*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion","s3:DeleteObject","s3:DeleteObjectVersion"],"Resource":["arn:aws:s3:::$workflow_c_bucket/workflow-c/manual-evidence/*"]}]}
EOF
cat > /tmp/geo-minio-bootstrap/recommendation-writer-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$recommendation_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$recommendation_bucket"],"Condition":{"StringLike":{"s3:prefix":["recommendations/model-tasks/*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion","s3:PutObject","s3:DeleteObject","s3:DeleteObjectVersion"],"Resource":["arn:aws:s3:::$recommendation_bucket/recommendations/model-tasks/*"]}]}
EOF
cat > /tmp/geo-minio-bootstrap/recommendation-deleter-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$recommendation_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$recommendation_bucket"],"Condition":{"StringLike":{"s3:prefix":["recommendations/model-tasks/*"]}}},{"Effect":"Allow","Action":["s3:DeleteObject","s3:DeleteObjectVersion"],"Resource":["arn:aws:s3:::$recommendation_bucket/recommendations/model-tasks/*"]}]}
EOF
cat > /tmp/geo-minio-bootstrap/synthetic-style-writer-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$synthetic_raw_bucket","arn:aws:s3:::$synthetic_derived_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$synthetic_raw_bucket","arn:aws:s3:::$synthetic_derived_bucket"],"Condition":{"StringLike":{"s3:prefix":["synthetic-raw/*"]}}},{"Effect":"Allow","Action":["s3:PutObject","s3:DeleteObject","s3:DeleteObjectVersion"],"Resource":["arn:aws:s3:::$synthetic_raw_bucket/synthetic-raw/*","arn:aws:s3:::$synthetic_derived_bucket/synthetic-raw/*"]}]}
EOF
cat > /tmp/geo-minio-bootstrap/synthetic-artifact-deleter-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$synthetic_raw_bucket","arn:aws:s3:::$synthetic_derived_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$synthetic_raw_bucket","arn:aws:s3:::$synthetic_derived_bucket"],"Condition":{"StringLike":{"s3:prefix":["synthetic-raw/*"]}}},{"Effect":"Allow","Action":["s3:DeleteObject","s3:DeleteObjectVersion"],"Resource":["arn:aws:s3:::$synthetic_raw_bucket/synthetic-raw/*","arn:aws:s3:::$synthetic_derived_bucket/synthetic-raw/*"]}]}
EOF
cat > /tmp/geo-minio-bootstrap/restore-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$backup_bucket","arn:aws:s3:::$reports_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$backup_bucket"],"Condition":{"StringLike":{"s3:prefix":["$backup_prefix*","$smoke_prefix*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion"],"Resource":["arn:aws:s3:::$backup_bucket/$backup_prefix*","arn:aws:s3:::$backup_bucket/$smoke_prefix*"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$reports_bucket"],"Condition":{"StringLike":{"s3:prefix":["$restore_prefix*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":["arn:aws:s3:::$reports_bucket/$restore_prefix*"]}]}
EOF
cat > /tmp/geo-minio-bootstrap/retention-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$reports_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$reports_bucket"],"Condition":{"StringLike":{"s3:prefix":["$retention_prefix*"]}}},{"Effect":"Allow","Action":["s3:DeleteObject","s3:DeleteObjectVersion"],"Resource":["arn:aws:s3:::$reports_bucket/$retention_prefix*"]}]}
EOF

application_policy="geo-application-v1"
backup_policy="geo-backup-v1"
restore_policy="geo-restore-v1"
retention_policy="geo-retention-v1"
workflow_c_writer_policy="geo-workflow-c-writer-v1"
workflow_c_reader_policy="geo-workflow-c-reader-v1"
workflow_c_deleter_policy="geo-workflow-c-deleter-v1"
recommendation_writer_policy="geo-recommendation-writer-v1"
recommendation_deleter_policy="geo-recommendation-deleter-v1"
synthetic_style_writer_policy="geo-synthetic-style-writer-v1"
synthetic_deleter_policy="geo-synthetic-artifact-deleter-v1"
mc admin policy create root "$application_policy" /tmp/geo-minio-bootstrap/application-policy.json >/dev/null
mc admin policy create root "$backup_policy" /tmp/geo-minio-bootstrap/backup-policy.json >/dev/null
mc admin policy create root "$restore_policy" /tmp/geo-minio-bootstrap/restore-policy.json >/dev/null
mc admin policy create root "$retention_policy" /tmp/geo-minio-bootstrap/retention-policy.json >/dev/null
mc admin policy create root "$workflow_c_writer_policy" /tmp/geo-minio-bootstrap/workflow-c-writer-policy.json >/dev/null
mc admin policy create root "$workflow_c_reader_policy" /tmp/geo-minio-bootstrap/workflow-c-reader-policy.json >/dev/null
mc admin policy create root "$workflow_c_deleter_policy" /tmp/geo-minio-bootstrap/workflow-c-deleter-policy.json >/dev/null
mc admin policy create root "$recommendation_writer_policy" /tmp/geo-minio-bootstrap/recommendation-writer-policy.json >/dev/null
mc admin policy create root "$recommendation_deleter_policy" /tmp/geo-minio-bootstrap/recommendation-deleter-policy.json >/dev/null
mc admin policy create root "$synthetic_style_writer_policy" /tmp/geo-minio-bootstrap/synthetic-style-writer-policy.json >/dev/null
mc admin policy create root "$synthetic_deleter_policy" /tmp/geo-minio-bootstrap/synthetic-artifact-deleter-policy.json >/dev/null

mc admin user add root "$application_user" "$application_password" >/dev/null
mc admin policy attach root "$application_policy" --user "$application_user" >/dev/null
mc admin user add root "$backup_user" "$backup_password" >/dev/null
mc admin policy attach root "$backup_policy" --user "$backup_user" >/dev/null
mc admin user add root "$workflow_c_writer" "$workflow_c_writer_password" >/dev/null
mc admin policy attach root "$workflow_c_writer_policy" --user "$workflow_c_writer" >/dev/null
mc admin user add root "$workflow_c_reader" "$workflow_c_reader_password" >/dev/null
mc admin policy attach root "$workflow_c_reader_policy" --user "$workflow_c_reader" >/dev/null
mc admin user add root "$workflow_c_deleter" "$workflow_c_deleter_password" >/dev/null
mc admin policy attach root "$workflow_c_deleter_policy" --user "$workflow_c_deleter" >/dev/null
mc admin user add root "$recommendation_writer" "$recommendation_writer_password" >/dev/null
mc admin policy attach root "$recommendation_writer_policy" --user "$recommendation_writer" >/dev/null
mc admin user add root "$recommendation_deleter" "$recommendation_deleter_password" >/dev/null
mc admin policy attach root "$recommendation_deleter_policy" --user "$recommendation_deleter" >/dev/null
mc admin user add root "$synthetic_style_writer" "$synthetic_style_writer_password" >/dev/null
mc admin policy attach root "$synthetic_style_writer_policy" --user "$synthetic_style_writer" >/dev/null
mc admin user add root "$synthetic_deleter" "$synthetic_deleter_password" >/dev/null
mc admin policy attach root "$synthetic_deleter_policy" --user "$synthetic_deleter" >/dev/null

if [ "${MINIO_BOOTSTRAP_ENABLE_EPHEMERAL:-0}" = "1" ]; then
  mc admin user add root "$restore_user" "$restore_password" >/dev/null
  mc admin policy attach root "$restore_policy" --user "$restore_user" >/dev/null
  mc admin user add root "$retention_user" "$retention_password" >/dev/null
  mc admin policy attach root "$retention_policy" --user "$retention_user" >/dev/null
fi

mc alias set application "$endpoint" "$application_user" "$application_password" >/dev/null
readiness_key="bootstrap-readiness/object-store-ready.txt"
printf 'geo production object store readiness\n' > /tmp/geo-minio-bootstrap/readiness.txt
mc cp /tmp/geo-minio-bootstrap/readiness.txt "application/$reports_bucket/$readiness_key" >/dev/null
mc stat "application/$reports_bucket/$readiness_key" >/dev/null
mc cp "application/$reports_bucket/$readiness_key" /tmp/geo-minio-bootstrap/readiness-restored.txt >/dev/null
source_hash="$(file_sha256 /tmp/geo-minio-bootstrap/readiness.txt)"
restored_hash="$(file_sha256 /tmp/geo-minio-bootstrap/readiness-restored.txt)"
test "$source_hash" = "$restored_hash"
if mc rm "application/$reports_bucket/$readiness_key" >/dev/null 2>&1; then
  echo "Application principal unexpectedly deleted a business object" >&2
  exit 1
fi
if mc mb "application/geo-forbidden-$reports_bucket" >/dev/null 2>&1; then
  echo "Application principal unexpectedly created a bucket" >&2
  exit 1
fi
if mc ls "application/$backup_bucket" >/dev/null 2>&1; then
  echo "Application principal unexpectedly accessed the backup bucket" >&2
  exit 1
fi
if mc ls "application/$workflow_c_bucket" >/dev/null 2>&1; then
  echo "Application principal unexpectedly accessed the Workflow C bucket" >&2
  exit 1
fi
if mc ls "application/$recommendation_bucket" >/dev/null 2>&1; then
  echo "Application principal unexpectedly accessed the Recommendation artifact bucket" >&2
  exit 1
fi
if mc ls "application/$synthetic_raw_bucket" >/dev/null 2>&1 || \
   mc ls "application/$synthetic_derived_bucket" >/dev/null 2>&1; then
  echo "Application principal unexpectedly accessed a Synthetic Style artifact bucket" >&2
  exit 1
fi
if mc admin info application >/dev/null 2>&1; then
  echo "Application principal unexpectedly used an admin API" >&2
  exit 1
fi

workflow_c_readiness_key="workflow-c/manual-evidence/bootstrap/readiness.txt"
printf 'geo Workflow C restricted object readiness\n' > /tmp/geo-minio-bootstrap/workflow-c-readiness.txt
mc alias set workflow-c-writer "$endpoint" "$workflow_c_writer" "$workflow_c_writer_password" >/dev/null
mc alias set workflow-c-reader "$endpoint" "$workflow_c_reader" "$workflow_c_reader_password" >/dev/null
mc alias set workflow-c-deleter "$endpoint" "$workflow_c_deleter" "$workflow_c_deleter_password" >/dev/null
mc cp /tmp/geo-minio-bootstrap/workflow-c-readiness.txt \
  "workflow-c-writer/$workflow_c_bucket/$workflow_c_readiness_key" >/dev/null
mc cp "workflow-c-reader/$workflow_c_bucket/$workflow_c_readiness_key" \
  /tmp/geo-minio-bootstrap/workflow-c-readiness-restored.txt >/dev/null
if ! files_match_sha256 /tmp/geo-minio-bootstrap/workflow-c-readiness.txt \
  /tmp/geo-minio-bootstrap/workflow-c-readiness-restored.txt; then
  echo "Workflow C reader roundtrip failed" >&2
  exit 1
fi
if mc cp /tmp/geo-minio-bootstrap/workflow-c-readiness.txt \
  "workflow-c-reader/$workflow_c_bucket/$workflow_c_readiness_key-reader-write" \
  >/dev/null 2>&1; then
  echo "Workflow C reader unexpectedly wrote an object" >&2
  exit 1
fi
if mc rm "workflow-c-reader/$workflow_c_bucket/$workflow_c_readiness_key" >/dev/null 2>&1; then
  echo "Workflow C reader unexpectedly deleted an object" >&2
  exit 1
fi
if mc rm "workflow-c-writer/$workflow_c_bucket/$workflow_c_readiness_key" >/dev/null 2>&1; then
  echo "Workflow C writer unexpectedly deleted an object" >&2
  exit 1
fi
if mc cp /tmp/geo-minio-bootstrap/workflow-c-readiness.txt \
  "workflow-c-deleter/$workflow_c_bucket/$workflow_c_readiness_key-deleter-write" \
  >/dev/null 2>&1; then
  echo "Workflow C deleter unexpectedly wrote an object" >&2
  exit 1
fi
if mc cp /tmp/geo-minio-bootstrap/workflow-c-readiness.txt \
  "workflow-c-writer/$reports_bucket/workflow-c-must-be-denied.txt" \
  >/dev/null 2>&1; then
  echo "Workflow C writer unexpectedly accessed the application bucket" >&2
  exit 1
fi
if mc rm "workflow-c-deleter/$reports_bucket/$readiness_key" >/dev/null 2>&1; then
  echo "Workflow C deleter unexpectedly accessed the application bucket" >&2
  exit 1
fi
mc rm "workflow-c-deleter/$workflow_c_bucket/$workflow_c_readiness_key" >/dev/null

recommendation_readiness_key="recommendations/model-tasks/bootstrap/readiness.txt"
printf 'geo Recommendation restricted object readiness\n' > /tmp/geo-minio-bootstrap/recommendation-readiness.txt
mc alias set recommendation-writer "$endpoint" "$recommendation_writer" "$recommendation_writer_password" >/dev/null
mc alias set recommendation-deleter "$endpoint" "$recommendation_deleter" "$recommendation_deleter_password" >/dev/null
mc cp /tmp/geo-minio-bootstrap/recommendation-readiness.txt \
  "recommendation-writer/$recommendation_bucket/$recommendation_readiness_key" >/dev/null
mc cp "recommendation-writer/$recommendation_bucket/$recommendation_readiness_key" \
  /tmp/geo-minio-bootstrap/recommendation-readiness-restored.txt >/dev/null
if ! files_match_sha256 /tmp/geo-minio-bootstrap/recommendation-readiness.txt \
  /tmp/geo-minio-bootstrap/recommendation-readiness-restored.txt; then
  echo "Recommendation artifact writer roundtrip failed" >&2
  exit 1
fi
if mc cp /tmp/geo-minio-bootstrap/recommendation-readiness.txt \
  "recommendation-deleter/$recommendation_bucket/$recommendation_readiness_key-deleter-write" \
  >/dev/null 2>&1; then
  echo "Recommendation artifact deleter unexpectedly wrote an object" >&2
  exit 1
fi
if mc cp "recommendation-deleter/$recommendation_bucket/$recommendation_readiness_key" \
  /tmp/geo-minio-bootstrap/recommendation-deleter-read.txt >/dev/null 2>&1; then
  echo "Recommendation artifact deleter unexpectedly read an object" >&2
  exit 1
fi
if mc cp /tmp/geo-minio-bootstrap/recommendation-readiness.txt \
  "recommendation-writer/$reports_bucket/recommendation-must-be-denied.txt" \
  >/dev/null 2>&1; then
  echo "Recommendation artifact writer unexpectedly accessed the application bucket" >&2
  exit 1
fi
if mc rm "recommendation-deleter/$reports_bucket/$readiness_key" >/dev/null 2>&1; then
  echo "Recommendation artifact deleter unexpectedly accessed the application bucket" >&2
  exit 1
fi
# `mc rm` on a single versioned object performs a read probe.  The deleter
# intentionally has no GetObject permission, so remove only the dedicated
# bootstrap prefix via the list-and-delete code path instead.
mc rm --recursive --force --versions \
  "recommendation-deleter/$recommendation_bucket/recommendations/model-tasks/bootstrap/" \
  >/dev/null

synthetic_raw_readiness_key="synthetic-raw/bootstrap/raw-readiness.txt"
synthetic_derived_readiness_key="synthetic-raw/bootstrap/derived-readiness.txt"
printf 'geo Synthetic Style raw object isolation\n' > /tmp/geo-minio-bootstrap/synthetic-style-readiness.txt
mc alias set synthetic-style-writer "$endpoint" "$synthetic_style_writer" "$synthetic_style_writer_password" >/dev/null
mc alias set synthetic-artifact-deleter "$endpoint" "$synthetic_deleter" "$synthetic_deleter_password" >/dev/null
mc cp /tmp/geo-minio-bootstrap/synthetic-style-readiness.txt \
  "synthetic-style-writer/$synthetic_raw_bucket/$synthetic_raw_readiness_key" >/dev/null
mc cp /tmp/geo-minio-bootstrap/synthetic-style-readiness.txt \
  "synthetic-style-writer/$synthetic_derived_bucket/$synthetic_derived_readiness_key" >/dev/null
if mc cp "synthetic-style-writer/$synthetic_raw_bucket/$synthetic_raw_readiness_key" \
  /tmp/geo-minio-bootstrap/synthetic-style-raw-read.txt >/dev/null 2>&1; then
  echo "Synthetic Style writer unexpectedly read a raw object" >&2
  exit 1
fi
if mc cp /tmp/geo-minio-bootstrap/synthetic-style-readiness.txt \
  "application/$synthetic_raw_bucket/application-must-be-denied.txt" >/dev/null 2>&1; then
  echo "Application principal unexpectedly wrote a Synthetic Style raw object" >&2
  exit 1
fi
if mc cp /tmp/geo-minio-bootstrap/synthetic-style-readiness.txt \
  "synthetic-artifact-deleter/$synthetic_raw_bucket/deleter-must-not-write.txt" >/dev/null 2>&1; then
  echo "Synthetic artifact deleter unexpectedly wrote a raw object" >&2
  exit 1
fi
if mc cp "synthetic-artifact-deleter/$synthetic_raw_bucket/$synthetic_raw_readiness_key" \
  /tmp/geo-minio-bootstrap/synthetic-style-deleter-read.txt >/dev/null 2>&1; then
  echo "Synthetic artifact deleter unexpectedly read a raw object" >&2
  exit 1
fi
if mc cp /tmp/geo-minio-bootstrap/synthetic-style-readiness.txt \
  "synthetic-style-writer/$reports_bucket/synthetic-style-must-be-denied.txt" >/dev/null 2>&1; then
  echo "Synthetic Style writer unexpectedly accessed the application bucket" >&2
  exit 1
fi
# See the Recommendation bootstrap cleanup above.  Keep the deleter
# read-free while proving it can remove every version under its test prefix.
mc rm --recursive --force --versions \
  "synthetic-artifact-deleter/$synthetic_raw_bucket/synthetic-raw/bootstrap/" \
  >/dev/null
mc rm --recursive --force --versions \
  "synthetic-artifact-deleter/$synthetic_derived_bucket/synthetic-raw/bootstrap/" \
  >/dev/null

application_hash="$(file_sha256 /tmp/geo-minio-bootstrap/application-policy.json)"
backup_hash="$(file_sha256 /tmp/geo-minio-bootstrap/backup-policy.json)"
restore_hash="$(file_sha256 /tmp/geo-minio-bootstrap/restore-policy.json)"
retention_hash="$(file_sha256 /tmp/geo-minio-bootstrap/retention-policy.json)"
workflow_c_writer_hash="$(file_sha256 /tmp/geo-minio-bootstrap/workflow-c-writer-policy.json)"
workflow_c_reader_hash="$(file_sha256 /tmp/geo-minio-bootstrap/workflow-c-reader-policy.json)"
workflow_c_deleter_hash="$(file_sha256 /tmp/geo-minio-bootstrap/workflow-c-deleter-policy.json)"
recommendation_writer_hash="$(file_sha256 /tmp/geo-minio-bootstrap/recommendation-writer-policy.json)"
recommendation_deleter_hash="$(file_sha256 /tmp/geo-minio-bootstrap/recommendation-deleter-policy.json)"
synthetic_style_writer_hash="$(file_sha256 /tmp/geo-minio-bootstrap/synthetic-style-writer-policy.json)"
synthetic_deleter_hash="$(file_sha256 /tmp/geo-minio-bootstrap/synthetic-artifact-deleter-policy.json)"
verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "$receipt_dir/bootstrap.json" <<EOF
{"schema_version":"production-object-store-bootstrap-v5","policy_version":"$policy_version","reports_bucket":"$reports_bucket","workflow_c_bucket":"$workflow_c_bucket","recommendation_bucket":"$recommendation_bucket","synthetic_raw_bucket":"$synthetic_raw_bucket","synthetic_derived_bucket":"$synthetic_derived_bucket","backup_bucket":"$backup_bucket","backup_prefix":"$backup_prefix","backup_smoke_prefix":"$smoke_prefix","restore_prefix":"$restore_prefix","retention_prefix":"$retention_prefix","versioning":{"$reports_bucket":"enabled","$workflow_c_bucket":"enabled","$recommendation_bucket":"enabled","$synthetic_raw_bucket":"enabled","$synthetic_derived_bucket":"enabled","$backup_bucket":"enabled"},"lifecycle":{"$reports_bucket":"geo-reports-lifecycle-v1","$backup_bucket":"geo-backups-lifecycle-v1"},"policy_hashes":{"application":"$application_hash","backup":"$backup_hash","restore":"$restore_hash","retention":"$retention_hash","workflow_c_writer":"$workflow_c_writer_hash","workflow_c_reader":"$workflow_c_reader_hash","workflow_c_deleter":"$workflow_c_deleter_hash","recommendation_writer":"$recommendation_writer_hash","recommendation_deleter":"$recommendation_deleter_hash","synthetic_style_writer":"$synthetic_style_writer_hash","synthetic_deleter":"$synthetic_deleter_hash"},"application_readiness_sha256":"$source_hash","application_delete_denied":true,"application_create_bucket_denied":true,"application_cross_bucket_denied":true,"application_workflow_c_access_denied":true,"application_recommendation_access_denied":true,"application_synthetic_style_access_denied":true,"application_admin_denied":true,"workflow_c_writer_roundtrip":true,"workflow_c_writer_delete_denied":true,"workflow_c_reader_read_verified":true,"workflow_c_reader_write_denied":true,"workflow_c_reader_delete_denied":true,"workflow_c_deleter_delete_verified":true,"workflow_c_deleter_put_denied":true,"workflow_c_deleter_cross_bucket_denied":true,"workflow_c_writer_cross_bucket_denied":true,"recommendation_writer_roundtrip":true,"recommendation_deleter_delete_verified":true,"recommendation_deleter_read_denied":true,"recommendation_deleter_put_denied":true,"recommendation_deleter_cross_bucket_denied":true,"recommendation_writer_cross_bucket_denied":true,"synthetic_style_writer_write_verified":true,"synthetic_style_writer_raw_read_denied":true,"synthetic_style_writer_cross_bucket_denied":true,"synthetic_artifact_deleter_delete_verified":true,"synthetic_artifact_deleter_read_denied":true,"synthetic_artifact_deleter_put_denied":true,"ephemeral_principals_enabled":${MINIO_BOOTSTRAP_ENABLE_EPHEMERAL:-0},"verified_at":"$verified_at"}
EOF
echo "MinIO production bootstrap completed: receipt=$receipt_dir/bootstrap.json"
