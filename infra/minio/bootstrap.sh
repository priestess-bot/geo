#!/bin/sh
set -eu

export MC_CONFIG_DIR="${MC_CONFIG_DIR:-/tmp/geno-minio-bootstrap-mc}"
trap 'rm -rf "$MC_CONFIG_DIR" /tmp/geno-minio-bootstrap' EXIT
mkdir -p /tmp/geno-minio-bootstrap "${MINIO_BOOTSTRAP_RECEIPT_DIR:-/receipts}"

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

endpoint="${MINIO_ENDPOINT:-http://minio:9000}"
reports_bucket="${OBJECT_STORE_BUCKET:-geno-reports}"
backup_bucket="${OBJECT_STORE_BACKUP_BUCKET:-geno-backups}"
backup_prefix="${OBJECT_STORE_BACKUP_PREFIX:-production/local/}"
smoke_prefix="${OBJECT_STORE_BACKUP_SMOKE_PREFIX:-smoke/local/}"
restore_prefix="${OBJECT_STORE_RESTORE_PREFIX:-restore-smoke/local/}"
retention_prefix="${OBJECT_STORE_RETENTION_PREFIX:-retention-approved/local/}"
policy_version="${MINIO_POLICY_VERSION:-geno-object-store-policy-v1}"
receipt_dir="${MINIO_BOOTSTRAP_RECEIPT_DIR:-/receipts}"
action="${MINIO_BOOTSTRAP_ACTION:-provision}"

require_safe_name OBJECT_STORE_BUCKET "$reports_bucket"
require_safe_name OBJECT_STORE_BACKUP_BUCKET "$backup_bucket"
require_safe_prefix OBJECT_STORE_BACKUP_PREFIX "$backup_prefix"
require_safe_prefix OBJECT_STORE_BACKUP_SMOKE_PREFIX "$smoke_prefix"
require_safe_prefix OBJECT_STORE_RESTORE_PREFIX "$restore_prefix"
require_safe_prefix OBJECT_STORE_RETENTION_PREFIX "$retention_prefix"
require_safe_name MINIO_POLICY_VERSION "$policy_version"

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
for identity in "$root_user" "$application_user" "$backup_user" "$restore_user" "$retention_user"; do
  require_safe_name object_store_identity "$identity"
done
if [ "$root_user" = "$application_user" ] || [ "$root_user" = "$backup_user" ] || \
   [ "$root_user" = "$restore_user" ] || [ "$root_user" = "$retention_user" ] || \
   [ "$application_user" = "$backup_user" ] || [ "$restore_user" = "$application_user" ] || \
   [ "$restore_user" = "$backup_user" ] || [ "$retention_user" = "$application_user" ] || \
   [ "$retention_user" = "$backup_user" ] || [ "$restore_user" = "$retention_user" ]; then
  echo "MinIO root/application/backup/restore/retention identities must be distinct" >&2
  exit 1
fi

mc mb --ignore-existing "root/$reports_bucket" >/dev/null
mc mb --ignore-existing "root/$backup_bucket" >/dev/null
mc version enable "root/$reports_bucket" >/dev/null
mc version enable "root/$backup_bucket" >/dev/null
mc ilm rule import "root/$reports_bucket" < /bootstrap/reports-lifecycle.json >/dev/null
mc ilm rule import "root/$backup_bucket" < /bootstrap/backups-lifecycle.json >/dev/null

cat > /tmp/geno-minio-bootstrap/application-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation","s3:ListBucket"],"Resource":["arn:aws:s3:::$reports_bucket"]},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion","s3:PutObject"],"Resource":["arn:aws:s3:::$reports_bucket/*"]}]}
EOF
cat > /tmp/geno-minio-bootstrap/backup-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$reports_bucket","arn:aws:s3:::$backup_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$reports_bucket"],"Condition":{"StringLike":{"s3:prefix":["*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion"],"Resource":["arn:aws:s3:::$reports_bucket/*"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$backup_bucket"],"Condition":{"StringLike":{"s3:prefix":["$backup_prefix*","$smoke_prefix*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion","s3:PutObject"],"Resource":["arn:aws:s3:::$backup_bucket/$backup_prefix*","arn:aws:s3:::$backup_bucket/$smoke_prefix*"]},{"Effect":"Allow","Action":["s3:DeleteObject","s3:DeleteObjectVersion"],"Resource":["arn:aws:s3:::$backup_bucket/$smoke_prefix*"]}]}
EOF
cat > /tmp/geno-minio-bootstrap/restore-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$backup_bucket","arn:aws:s3:::$reports_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$backup_bucket"],"Condition":{"StringLike":{"s3:prefix":["$backup_prefix*","$smoke_prefix*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion"],"Resource":["arn:aws:s3:::$backup_bucket/$backup_prefix*","arn:aws:s3:::$backup_bucket/$smoke_prefix*"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$reports_bucket"],"Condition":{"StringLike":{"s3:prefix":["$restore_prefix*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":["arn:aws:s3:::$reports_bucket/$restore_prefix*"]}]}
EOF
cat > /tmp/geno-minio-bootstrap/retention-policy.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$reports_bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$reports_bucket"],"Condition":{"StringLike":{"s3:prefix":["$retention_prefix*"]}}},{"Effect":"Allow","Action":["s3:DeleteObject","s3:DeleteObjectVersion"],"Resource":["arn:aws:s3:::$reports_bucket/$retention_prefix*"]}]}
EOF

application_policy="geno-application-v1"
backup_policy="geno-backup-v1"
restore_policy="geno-restore-v1"
retention_policy="geno-retention-v1"
mc admin policy create root "$application_policy" /tmp/geno-minio-bootstrap/application-policy.json >/dev/null
mc admin policy create root "$backup_policy" /tmp/geno-minio-bootstrap/backup-policy.json >/dev/null
mc admin policy create root "$restore_policy" /tmp/geno-minio-bootstrap/restore-policy.json >/dev/null
mc admin policy create root "$retention_policy" /tmp/geno-minio-bootstrap/retention-policy.json >/dev/null

mc admin user add root "$application_user" "$application_password" >/dev/null
mc admin policy attach root "$application_policy" --user "$application_user" >/dev/null
mc admin user add root "$backup_user" "$backup_password" >/dev/null
mc admin policy attach root "$backup_policy" --user "$backup_user" >/dev/null

if [ "${MINIO_BOOTSTRAP_ENABLE_EPHEMERAL:-0}" = "1" ]; then
  mc admin user add root "$restore_user" "$restore_password" >/dev/null
  mc admin policy attach root "$restore_policy" --user "$restore_user" >/dev/null
  mc admin user add root "$retention_user" "$retention_password" >/dev/null
  mc admin policy attach root "$retention_policy" --user "$retention_user" >/dev/null
fi

mc alias set application "$endpoint" "$application_user" "$application_password" >/dev/null
readiness_key="bootstrap-readiness/object-store-ready.txt"
printf 'geno production object store readiness\n' > /tmp/geno-minio-bootstrap/readiness.txt
mc cp /tmp/geno-minio-bootstrap/readiness.txt "application/$reports_bucket/$readiness_key" >/dev/null
mc stat "application/$reports_bucket/$readiness_key" >/dev/null
mc cp "application/$reports_bucket/$readiness_key" /tmp/geno-minio-bootstrap/readiness-restored.txt >/dev/null
source_hash="$(file_sha256 /tmp/geno-minio-bootstrap/readiness.txt)"
restored_hash="$(file_sha256 /tmp/geno-minio-bootstrap/readiness-restored.txt)"
test "$source_hash" = "$restored_hash"
if mc rm "application/$reports_bucket/$readiness_key" >/dev/null 2>&1; then
  echo "Application principal unexpectedly deleted a business object" >&2
  exit 1
fi
if mc mb "application/geno-forbidden-$reports_bucket" >/dev/null 2>&1; then
  echo "Application principal unexpectedly created a bucket" >&2
  exit 1
fi
if mc ls "application/$backup_bucket" >/dev/null 2>&1; then
  echo "Application principal unexpectedly accessed the backup bucket" >&2
  exit 1
fi
if mc admin info application >/dev/null 2>&1; then
  echo "Application principal unexpectedly used an admin API" >&2
  exit 1
fi

application_hash="$(file_sha256 /tmp/geno-minio-bootstrap/application-policy.json)"
backup_hash="$(file_sha256 /tmp/geno-minio-bootstrap/backup-policy.json)"
restore_hash="$(file_sha256 /tmp/geno-minio-bootstrap/restore-policy.json)"
retention_hash="$(file_sha256 /tmp/geno-minio-bootstrap/retention-policy.json)"
verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "$receipt_dir/bootstrap.json" <<EOF
{"schema_version":"production-object-store-bootstrap-v1","policy_version":"$policy_version","reports_bucket":"$reports_bucket","backup_bucket":"$backup_bucket","backup_prefix":"$backup_prefix","backup_smoke_prefix":"$smoke_prefix","restore_prefix":"$restore_prefix","retention_prefix":"$retention_prefix","versioning":{"$reports_bucket":"enabled","$backup_bucket":"enabled"},"lifecycle":{"$reports_bucket":"geno-reports-lifecycle-v1","$backup_bucket":"geno-backups-lifecycle-v1"},"policy_hashes":{"application":"$application_hash","backup":"$backup_hash","restore":"$restore_hash","retention":"$retention_hash"},"application_readiness_sha256":"$source_hash","application_delete_denied":true,"application_create_bucket_denied":true,"application_cross_bucket_denied":true,"application_admin_denied":true,"ephemeral_principals_enabled":${MINIO_BOOTSTRAP_ENABLE_EPHEMERAL:-0},"verified_at":"$verified_at"}
EOF
echo "MinIO production bootstrap completed: receipt=$receipt_dir/bootstrap.json"
