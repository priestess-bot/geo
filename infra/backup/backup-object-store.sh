#!/bin/sh
set -eu
set -o pipefail
umask 077

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
control_path="${BACKUP_CONTROL_PATH:?set BACKUP_CONTROL_PATH}"
case "$control_path" in
  /backup-data/staging/*/minio-object-counts.json) ;;
  *) echo "backup error: invalid control path" >&2; exit 2 ;;
esac

export MC_CONFIG_DIR=/plaintext-staging/mc-config
source_root=/plaintext-staging/source
reports_bucket="${OBJECT_STORE_BUCKET:-geo-artifacts}"
recommendation_bucket="${GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_BUCKET:-geo-restricted-recommendation-artifacts}"
workflow_c_bucket="${GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_BUCKET:-geo-restricted-workflow-c-artifacts}"
synthetic_raw_bucket="${GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_BUCKET:-geo-synthetic-style-raw}"
synthetic_derived_bucket="${GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_BUCKET:-geo-synthetic-style-derived}"
if [ "$reports_bucket" != "geo-artifacts" ] || \
   [ "$recommendation_bucket" != "geo-restricted-recommendation-artifacts" ] || \
   [ "$workflow_c_bucket" != "geo-restricted-workflow-c-artifacts" ] || \
   [ "$synthetic_raw_bucket" != "geo-synthetic-style-raw" ] || \
   [ "$synthetic_derived_bucket" != "geo-synthetic-style-derived" ]; then
  echo "backup error: unexpected source bucket identity" >&2
  exit 2
fi
cleanup() {
  rm -rf /plaintext-staging/*
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$MC_CONFIG_DIR" \
  "$source_root/buckets/$reports_bucket" \
  "$source_root/buckets/$recommendation_bucket" \
  "$source_root/buckets/$workflow_c_bucket" \
  "$source_root/buckets/$synthetic_raw_bucket" \
  "$source_root/buckets/$synthetic_derived_bucket"
mc alias set geo "$MINIO_ENDPOINT" "$access_key" "$secret_key" >/dev/null
mc mirror --overwrite --remove "geo/$reports_bucket" \
  "$source_root/buckets/$reports_bucket" >/dev/null
mc mirror --overwrite --remove "geo/$recommendation_bucket" \
  "$source_root/buckets/$recommendation_bucket" >/dev/null
mc mirror --overwrite --remove "geo/$workflow_c_bucket" \
  "$source_root/buckets/$workflow_c_bucket" >/dev/null
mc mirror --overwrite --remove "geo/$synthetic_raw_bucket" \
  "$source_root/buckets/$synthetic_raw_bucket" >/dev/null
mc mirror --overwrite --remove "geo/$synthetic_derived_bucket" \
  "$source_root/buckets/$synthetic_derived_bucket" >/dev/null
(
  cd "$source_root"
  find buckets -type f -exec sha256sum {} \; | LC_ALL=C sort >objects.sha256
)
reports_count="$(find "$source_root/buckets/$reports_bucket" -type f | wc -l | tr -d ' ')"
recommendation_count="$(find "$source_root/buckets/$recommendation_bucket" -type f | wc -l | tr -d ' ')"
workflow_c_count="$(find "$source_root/buckets/$workflow_c_bucket" -type f | wc -l | tr -d ' ')"
synthetic_raw_count="$(find "$source_root/buckets/$synthetic_raw_bucket" -type f | wc -l | tr -d ' ')"
synthetic_derived_count="$(find "$source_root/buckets/$synthetic_derived_bucket" -type f | wc -l | tr -d ' ')"
case "$reports_count:$recommendation_count:$workflow_c_count:$synthetic_raw_count:$synthetic_derived_count" in
  *[!0-9:]*) echo "backup error: invalid object count" >&2; exit 2 ;;
esac
control_tmp="$control_path.tmp"
printf '{"geo-artifacts":%s,"geo-restricted-recommendation-artifacts":%s,"geo-restricted-workflow-c-artifacts":%s,"geo-synthetic-style-derived":%s,"geo-synthetic-style-raw":%s}\n' \
  "$reports_count" "$recommendation_count" "$workflow_c_count" "$synthetic_derived_count" "$synthetic_raw_count" >"$control_tmp"
chmod 0600 "$control_tmp"
mv "$control_tmp" "$control_path"
tar -C "$source_root" -cf - buckets objects.sha256
