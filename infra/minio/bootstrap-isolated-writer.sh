#!/bin/sh
set -eu
umask 077

export MC_CONFIG_DIR="${MC_CONFIG_DIR:-/tmp/geo-isolated-minio-mc}"
work_dir="/tmp/geo-isolated-minio-bootstrap"
trap 'rm -rf "$MC_CONFIG_DIR" "$work_dir"' EXIT
mkdir -p "$work_dir" "${ISOLATED_RECEIPT_DIR:-/receipts}"

read_secret() {
  path="$(printenv "$1" 2>/dev/null || true)"
  if [ -z "$path" ] || [ ! -r "$path" ]; then
    echo "$1 must reference a readable secret file" >&2
    exit 1
  fi
  value="$(cat "$path")"
  if [ -z "$value" ]; then
    echo "$1 cannot be empty" >&2
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

endpoint="${MINIO_ENDPOINT:-http://minio:9000}"
bucket="${ISOLATED_BUCKET:?set ISOLATED_BUCKET}"
prefix="${ISOLATED_PREFIX:?set ISOLATED_PREFIX}"
policy="${ISOLATED_POLICY_NAME:?set ISOLATED_POLICY_NAME}"
receipt="${ISOLATED_RECEIPT_NAME:?set ISOLATED_RECEIPT_NAME}"
retention_days="${ISOLATED_RETENTION_DAYS:?set ISOLATED_RETENTION_DAYS}"
require_safe_name ISOLATED_BUCKET "$bucket"
require_safe_prefix ISOLATED_PREFIX "$prefix"
require_safe_name ISOLATED_POLICY_NAME "$policy"
require_safe_name ISOLATED_RECEIPT_NAME "$receipt"
case "$retention_days" in
  ''|*[!0-9]*) echo "ISOLATED_RETENTION_DAYS must be a positive integer" >&2; exit 1 ;;
esac
if [ "$retention_days" -lt 1 ] || [ "$retention_days" -gt 3650 ]; then
  echo "ISOLATED_RETENTION_DAYS must be between 1 and 3650" >&2
  exit 1
fi

root_user="$(read_secret MINIO_ROOT_USER_FILE)"
root_password="$(read_secret MINIO_ROOT_PASSWORD_FILE)"
writer_user="$(read_secret ISOLATED_WRITER_ACCESS_KEY_FILE)"
writer_password="$(read_secret ISOLATED_WRITER_SECRET_KEY_FILE)"
require_safe_name ISOLATED_WRITER_ACCESS_KEY "$writer_user"
if [ "$writer_user" = "$root_user" ]; then
  echo "Isolated writer identity must differ from MinIO root" >&2
  exit 1
fi

until mc alias set root "$endpoint" "$root_user" "$root_password" >/dev/null 2>&1; do
  sleep 1
done

mc mb --ignore-existing "root/$bucket" >/dev/null
mc version enable "root/$bucket" >/dev/null
cat > "$work_dir/lifecycle.json" <<EOF
{"Rules":[{"Expiration":{"Days":$retention_days},"ID":"$policy-retention","Filter":{"Prefix":"$prefix"},"NoncurrentVersionExpiration":{"NoncurrentDays":1},"Status":"Enabled"}]}
EOF
mc ilm import "root/$bucket" < "$work_dir/lifecycle.json" >/dev/null
cat > "$work_dir/policy.json" <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["s3:GetBucketLocation"],"Resource":["arn:aws:s3:::$bucket"]},{"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::$bucket"],"Condition":{"StringLike":{"s3:prefix":["$prefix*"]}}},{"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion","s3:PutObject"],"Resource":["arn:aws:s3:::$bucket/$prefix*"]}]}
EOF
mc admin policy create root "$policy" "$work_dir/policy.json" >/dev/null
mc admin user add root "$writer_user" "$writer_password" >/dev/null
mc admin policy attach root "$policy" --user "$writer_user" >/dev/null

mc alias set isolated "$endpoint" "$writer_user" "$writer_password" >/dev/null
readiness_key="${prefix}bootstrap/readiness.txt"
printf 'geo isolated artifact writer readiness\n' > "$work_dir/readiness.txt"
mc cp "$work_dir/readiness.txt" "isolated/$bucket/$readiness_key" >/dev/null
mc stat "isolated/$bucket/$readiness_key" >/dev/null
mc cp "isolated/$bucket/$readiness_key" "$work_dir/restored.txt" >/dev/null
test "$(sha256sum "$work_dir/readiness.txt" | cut -d ' ' -f 1)" = \
  "$(sha256sum "$work_dir/restored.txt" | cut -d ' ' -f 1)"
if mc rm "isolated/$bucket/$readiness_key" >/dev/null 2>&1; then
  echo "Isolated writer unexpectedly deleted an object" >&2
  exit 1
fi
if mc cp "$work_dir/readiness.txt" "isolated/$bucket/forbidden/readiness.txt" >/dev/null 2>&1; then
  echo "Isolated writer unexpectedly wrote outside its prefix" >&2
  exit 1
fi
if mc mb "isolated/geo-forbidden-$bucket" >/dev/null 2>&1; then
  echo "Isolated writer unexpectedly created a bucket" >&2
  exit 1
fi
if mc admin info isolated >/dev/null 2>&1; then
  echo "Isolated writer unexpectedly used an admin API" >&2
  exit 1
fi

policy_hash="$(sha256sum "$work_dir/policy.json" | cut -d ' ' -f 1)"
verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "${ISOLATED_RECEIPT_DIR:-/receipts}/$receipt.json" <<EOF
{"schema_version":"geo-isolated-artifact-bootstrap-v2","bucket":"$bucket","prefix":"$prefix","policy":"$policy","policy_sha256":"$policy_hash","versioning":true,"retention_days":$retention_days,"orphan_cleanup":"bucket_lifecycle","writer_delete_denied":true,"writer_outside_prefix_denied":true,"writer_create_bucket_denied":true,"writer_admin_denied":true,"verified_at":"$verified_at"}
EOF

echo "Isolated artifact bucket ready: bucket=$bucket prefix=$prefix receipt=$receipt.json"
