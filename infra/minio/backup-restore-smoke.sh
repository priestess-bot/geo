#!/bin/sh
set -eu

export MC_CONFIG_DIR="${MC_CONFIG_DIR:-/tmp/geo-object-store-smoke-mc}"
trap 'rm -rf "$MC_CONFIG_DIR" /tmp/geo-object-store-smoke' EXIT
mkdir -p /tmp/geo-object-store-smoke "${OBJECT_STORE_RECEIPT_DIR:-/receipts}"

read_secret() {
  value="$(printenv "$1" 2>/dev/null || true)"
  path="$(printenv "$2" 2>/dev/null || true)"
  if [ -n "$value" ] && [ -n "$path" ]; then
    echo "$1 and $2 cannot both be configured" >&2
    exit 1
  fi
  if [ -n "$path" ]; then
    test -r "$path" || { echo "$2 is not readable" >&2; exit 1; }
    value="$(cat "$path")"
  fi
  test -n "$value" || { echo "$1 or $2 is required" >&2; exit 1; }
  printf '%s' "$value"
}

file_sha256() {
  set -- $(sha256sum "$1")
  printf '%s' "$1"
}

endpoint="${OBJECT_STORE_ENDPOINT:-http://minio:9000}"
source_bucket="${OBJECT_STORE_BUCKET:-geo-reports}"
backup_bucket="${OBJECT_STORE_BACKUP_BUCKET:-geo-backups}"
backup_prefix="${OBJECT_STORE_BACKUP_PREFIX:-production/local/}"
smoke_prefix="${OBJECT_STORE_BACKUP_SMOKE_PREFIX:-smoke/local/}"
restore_prefix="${OBJECT_STORE_RESTORE_PREFIX:-restore-smoke/local/}"
source_key="${OBJECT_STORE_BACKUP_SMOKE_SOURCE_KEY:-bootstrap-readiness/object-store-ready.txt}"
backup_key="${smoke_prefix}object-store-ready.txt"
formal_key="${backup_prefix}delete-must-be-denied.txt"
cross_run_key="smoke/cross-run-delete-must-be-denied/object.txt"
restored_key="${restore_prefix}object-store-ready.txt"
cross_run_restore_key="restore-smoke/cross-run-write-must-be-denied/object.txt"

backup_user="$(read_secret OBJECT_STORE_BACKUP_ACCESS_KEY OBJECT_STORE_BACKUP_ACCESS_KEY_FILE)"
backup_password="$(read_secret OBJECT_STORE_BACKUP_SECRET_KEY OBJECT_STORE_BACKUP_SECRET_KEY_FILE)"
restore_user="$(read_secret OBJECT_STORE_RESTORE_ACCESS_KEY OBJECT_STORE_RESTORE_ACCESS_KEY_FILE)"
restore_password="$(read_secret OBJECT_STORE_RESTORE_SECRET_KEY OBJECT_STORE_RESTORE_SECRET_KEY_FILE)"

until mc alias set backup "$endpoint" "$backup_user" "$backup_password" >/dev/null 2>&1; do
  sleep 1
done
mc alias set restore "$endpoint" "$restore_user" "$restore_password" >/dev/null

mc cp "backup/$source_bucket/$source_key" /tmp/geo-object-store-smoke/source.txt >/dev/null
mc cp /tmp/geo-object-store-smoke/source.txt "backup/$backup_bucket/$backup_key" >/dev/null
mc ls "backup/$backup_bucket/$smoke_prefix" >/dev/null
mc stat "backup/$backup_bucket/$backup_key" >/dev/null
mc cp "backup/$backup_bucket/$backup_key" /tmp/geo-object-store-smoke/backed-up.txt >/dev/null
mc cp /tmp/geo-object-store-smoke/source.txt "backup/$backup_bucket/$formal_key" >/dev/null
mc ls "backup/$backup_bucket/$backup_prefix" >/dev/null
mc stat "backup/$backup_bucket/$formal_key" >/dev/null
mc cp "backup/$backup_bucket/$formal_key" /tmp/geo-object-store-smoke/formal-backup.txt >/dev/null

if mc mb "backup/geo-forbidden-backup-smoke" >/dev/null 2>&1; then
  echo "Backup principal unexpectedly created a bucket" >&2
  exit 1
fi
if mc cp /tmp/geo-object-store-smoke/source.txt "backup/$source_bucket/backup-write-must-be-denied.txt" >/dev/null 2>&1; then
  echo "Backup principal unexpectedly wrote the source bucket" >&2
  exit 1
fi
if mc rm "backup/$backup_bucket/$formal_key" >/dev/null 2>&1; then
  echo "Backup principal unexpectedly deleted a formal backup object" >&2
  exit 1
fi
if mc rm "backup/$backup_bucket/$cross_run_key" >/dev/null 2>&1; then
  echo "Backup principal unexpectedly deleted a cross-run smoke object" >&2
  exit 1
fi
if mc cp /tmp/geo-object-store-smoke/source.txt "restore/$source_bucket/$cross_run_restore_key" >/dev/null 2>&1; then
  echo "Restore principal unexpectedly wrote a cross-run prefix" >&2
  exit 1
fi

mc cp "restore/$backup_bucket/$backup_key" /tmp/geo-object-store-smoke/restore-input.txt >/dev/null
mc cp /tmp/geo-object-store-smoke/restore-input.txt "restore/$source_bucket/$restored_key" >/dev/null
mc stat "restore/$source_bucket/$restored_key" >/dev/null
mc cp "restore/$source_bucket/$restored_key" /tmp/geo-object-store-smoke/restored.txt >/dev/null

source_hash="$(file_sha256 /tmp/geo-object-store-smoke/source.txt)"
backup_hash="$(file_sha256 /tmp/geo-object-store-smoke/backed-up.txt)"
formal_hash="$(file_sha256 /tmp/geo-object-store-smoke/formal-backup.txt)"
restored_hash="$(file_sha256 /tmp/geo-object-store-smoke/restored.txt)"
test "$source_hash" = "$backup_hash"
test "$source_hash" = "$formal_hash"
test "$source_hash" = "$restored_hash"

mc rm "backup/$backup_bucket/$backup_key" >/dev/null
mc rm "restore/$source_bucket/$restored_key" >/dev/null
verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "${OBJECT_STORE_RECEIPT_DIR:-/receipts}/backup-restore.json" <<EOF
{"schema_version":"production-object-store-backup-restore-v1","source_bucket":"$source_bucket","source_key":"$source_key","backup_bucket":"$backup_bucket","backup_key":"$backup_key","formal_backup_key":"$formal_key","restored_key":"$restored_key","source_sha256":"$source_hash","backup_sha256":"$backup_hash","formal_backup_sha256":"$formal_hash","restored_sha256":"$restored_hash","formal_backup_put_list_get":true,"negative_checks":{"create_bucket_denied":true,"source_write_denied":true,"formal_backup_delete_denied":true,"cross_run_delete_denied":true,"restore_cross_run_write_denied":true},"source_object_deleted":false,"smoke_cleanup_completed":true,"verified_at":"$verified_at"}
EOF
echo "Object backup/restore smoke passed: sha256=$restored_hash"
