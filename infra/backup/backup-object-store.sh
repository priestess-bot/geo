#!/bin/sh
set -eu

read_secret() {
  value="$(cat "$1")"
  if [ -z "$value" ]; then
    echo "backup error: empty secret file" >&2
    exit 2
  fi
  printf '%s' "$value"
}

access_key="$(read_secret "$OBJECT_STORE_BACKUP_ACCESS_KEY_FILE")"
secret_key="$(read_secret "$OBJECT_STORE_BACKUP_SECRET_KEY_FILE")"
target="/backup-data/daily/$BACKUP_STAMP/minio"

mkdir -p "$target"
mc alias set geo "$MINIO_ENDPOINT" "$access_key" "$secret_key" >/dev/null
mc mirror --overwrite --remove geo/geo-artifacts "$target/geo-artifacts"
mc mirror --overwrite --remove geo/geo-backups "$target/geo-backups"
