#!/bin/sh
set -eu

export MC_CONFIG_DIR="${MC_CONFIG_DIR:-/tmp/geno-application-roundtrip-mc}"
trap 'rm -rf "$MC_CONFIG_DIR" /tmp/geno-application-roundtrip' EXIT
mkdir -p /tmp/geno-application-roundtrip "${OBJECT_STORE_RECEIPT_DIR:-/receipts}"

access_key="$(cat "${OBJECT_STORE_ACCESS_KEY_FILE:-/run/secrets/object_store_application_access_key}")"
secret_key="$(cat "${OBJECT_STORE_SECRET_KEY_FILE:-/run/secrets/object_store_application_secret_key}")"
endpoint="${OBJECT_STORE_ENDPOINT:-http://minio:9000}"
bucket="${OBJECT_STORE_BUCKET:-geno-reports}"
run_id="${OBJECT_STORE_SMOKE_RUN_ID:?set OBJECT_STORE_SMOKE_RUN_ID}"

until mc alias set application "$endpoint" "$access_key" "$secret_key" >/dev/null 2>&1; do
  sleep 1
done

fingerprint_file=/tmp/geno-application-roundtrip/access-key
printf '%s' "$access_key" > "$fingerprint_file"
set -- $(sha256sum "$fingerprint_file")
credential_fingerprint="$1"
receipt="${OBJECT_STORE_RECEIPT_DIR:-/receipts}/consumer-roundtrip.json"
printf '{"schema_version":"production-object-store-consumer-roundtrip-v1","credential_fingerprint":"%s","consumer_roundtrips":{' "$credential_fingerprint" > "$receipt"

separator=""
for consumer in \
  api \
  browser-fidelity-scheduler \
  collector-worker \
  collector-worker-litellm \
  knowledge-worker \
  report-export-worker \
  runtime-e2e \
  task-worker-knowledge \
  task-worker-runtime
do
  payload="/tmp/geno-application-roundtrip/$consumer.txt"
  restored="/tmp/geno-application-roundtrip/$consumer-restored.txt"
  key="production-readiness/$run_id/$consumer.txt"
  printf 'geno object-store consumer=%s run=%s\n' "$consumer" "$run_id" > "$payload"
  set -- $(sha256sum "$payload")
  source_hash="$1"
  mc cp "$payload" "application/$bucket/$key" >/dev/null
  mc stat "application/$bucket/$key" >/dev/null
  mc cp "application/$bucket/$key" "$restored" >/dev/null
  set -- $(sha256sum "$restored")
  restored_hash="$1"
  test "$source_hash" = "$restored_hash"
  printf '%s"%s":{"status":"pass","sha256":"%s","execution_path":"minio-mc-file-secret"}' "$separator" "$consumer" "$restored_hash" >> "$receipt"
  separator=,
done

verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '},"verified_at":"%s"}\n' "$verified_at" >> "$receipt"
echo "Application consumer roundtrips passed: receipt=$receipt"
